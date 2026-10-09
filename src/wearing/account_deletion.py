"""Operator-owned, resumable account deletion jobs; no implicit destructive adapter.

This journal lives outside tenant data. Registry ownership must be established by
an operator, never inferred from a sole active membership or client input. The
public gateway and production provisioner are intentionally not wired here.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Protocol
import uuid

from filelock import FileLock, Timeout

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
JOB_ID = re.compile(r"^[a-f0-9]{32}$")
KEY = re.compile(r"^[A-Za-z0-9_-]{16,120}$")
MODES = {"operator", "synthetic"}
CODES = {"adapter_unconfigured", "adapter_failed", "adapter_mismatch", "invalid_receipt",
         "ownership_changed", "instance_busy", "provider_unavailable", "backup_retained",
         "fixture_busy", "unsafe_storage", "incomplete_registry"}
PRIVATE_STEPS = ("freeze_tenant", "revoke_credentials", "revoke_devices", "drain_actions",
                 "stop_instance", "erase_primary", "erase_indexes", "erase_backups", "finalize_tenant")


class DeletionError(ValueError):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise DeletionError("invalid_identifier", 422)
    return value


@dataclass(frozen=True)
class Operation:
    operation_id: str
    job_id: str
    user_id: str
    plan_revision: str
    phase: str
    tenant_id: str | None
    instance_id: str | None
    mode: str
    scope: tuple[dict, ...]


@dataclass(frozen=True)
class Receipt:
    operation_id: str
    disposition: str  # done / retry / retained; only done advances the journal
    evidence: str | None = None  # opaque SHA-256 of adapter-owned evidence
    code: str | None = None
    retained_until: float | None = None


class DeletionAdapter(Protocol):
    mode: str

    def execute(self, operation: Operation) -> Receipt: ...


class DeletionJobs:
    def __init__(self, root, *, initialize=False, mode="operator", clock=time.time):
        if mode not in MODES:
            raise DeletionError("invalid_mode", 422)
        self.root, self.clock = Path(root).absolute(), clock
        if self.root.is_symlink():
            raise DeletionError("unsafe_storage")
        if self.root.exists() and (not self.root.is_dir() or os.name != "nt" and
                                   (self.root.stat().st_uid != os.getuid() or self.root.stat().st_mode & 0o077)):
            raise DeletionError("unsafe_storage")
        marker = self.root / "deletion-journal.json"
        if initialize and not marker.exists():
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if any(self.root.iterdir()):
                raise DeletionError("journal_directory_not_empty")
            with marker.open("x") as f:
                os.chmod(marker, 0o600)
                json.dump({"schema": 1, "mode": mode}, f)
        if (not marker.is_file() or marker.is_symlink() or marker.stat().st_size > 1024
                or os.name != "nt" and (marker.stat().st_uid != os.getuid() or marker.stat().st_mode & 0o077)):
            raise DeletionError("unsafe_storage")
        try:
            if json.loads(marker.read_text()) != {"schema": 1, "mode": mode}:
                raise ValueError()
        except (OSError, ValueError):
            raise DeletionError("journal_mode_mismatch") from None
        self.mode = mode
        self.path = self.root / "deletions.sqlite3"
        if self.path.is_symlink() or self.path.exists() and (not self.path.is_file() or self.path.stat().st_nlink != 1):
            raise DeletionError("unsafe_storage")
        with self.tx() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS tenants(id TEXT PRIMARY KEY, classification TEXT NOT NULL,
                owner TEXT, members TEXT NOT NULL, instance TEXT, revision INTEGER NOT NULL);
              CREATE UNIQUE INDEX IF NOT EXISTS deletion_instance_owner ON tenants(instance) WHERE instance IS NOT NULL;
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,request_key TEXT NOT NULL,
                plan TEXT NOT NULL,revision TEXT NOT NULL,state TEXT NOT NULL,code TEXT,created REAL,updated REAL,
                UNIQUE(user_id,request_key));
              CREATE TABLE IF NOT EXISTS steps(job_id TEXT NOT NULL,number INTEGER NOT NULL,phase TEXT NOT NULL,
                tenant TEXT,instance TEXT,operation_id TEXT NOT NULL UNIQUE,state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,code TEXT,evidence TEXT,retained_until REAL,updated REAL,
                PRIMARY KEY(job_id,number));
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def register(self, tenant_id, classification, member_ids, *, owner_user_id=None, instance_id=None, revision=None):
        """Trusted operator enrollment, not a browser API. Include inactive members."""
        identifier(tenant_id)
        if classification not in {"private", "shared", "unknown"}:
            raise DeletionError("invalid_classification", 422)
        if not isinstance(member_ids, (tuple, list)) or not member_ids or len(member_ids) > 1000:
            raise DeletionError("invalid_members", 422)
        members = sorted({identifier(v) for v in member_ids})
        if len(members) != len(member_ids):
            raise DeletionError("duplicate_member", 422)
        if owner_user_id is not None:
            identifier(owner_user_id)
            if owner_user_id not in members:
                raise DeletionError("owner_not_member", 422)
        if classification == "private" and owner_user_id is None:
            raise DeletionError("owner_required", 422)
        if instance_id is not None:
            identifier(instance_id)
        if revision is not None and (type(revision) is not int or revision < 1):
            raise DeletionError("invalid_registry_revision", 422)
        with self.tx() as db:
            current = db.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
            if revision != (current["revision"] if current else None):
                raise DeletionError("registry_changed")
            if instance_id is not None and db.execute("SELECT 1 FROM tenants WHERE instance=? AND id!=?", (instance_id,tenant_id)).fetchone():
                raise DeletionError("instance_already_owned")
            # Our registry cannot change underneath admitted work. The production
            # adapter must ALSO fence the live control plane before destructive work.
            for job in db.execute("SELECT plan FROM jobs WHERE state != 'completed'"):
                if any(t["tenant_id"] == tenant_id for t in json.loads(job[0])["tenants"]):
                    raise DeletionError("tenant_deletion_in_progress")
            db.execute("INSERT OR REPLACE INTO tenants VALUES(?,?,?,?,?,?)", (tenant_id, classification,
                       owner_user_id, encoded(members), instance_id, (revision or 0) + 1))
        return self.registration(tenant_id)

    def registration(self, tenant_id):
        with self.tx() as db:
            row = db.execute("SELECT * FROM tenants WHERE id=?", (identifier(tenant_id),)).fetchone()
            if row is None:
                raise DeletionError("tenant_not_registered", 404)
            return {"tenant_id": row["id"], "classification": row["classification"], "owner_user_id": row["owner"],
                    "member_ids": json.loads(row["members"]), "instance_id": row["instance"], "revision": row["revision"]}

    def _preview(self, db, user_id):
        tenants, blockers = [], []
        for row in db.execute("SELECT * FROM tenants ORDER BY id"):
            members = json.loads(row["members"])
            if user_id not in members:
                continue
            reason = None
            if row["classification"] == "unknown": reason = "ownership_unknown"
            elif row["classification"] == "private":
                if row["owner"] != user_id: reason = "not_private_owner"
                elif members != [user_id]: reason = "private_has_other_members"
                elif row["instance"] is None: reason = "instance_unregistered"
            elif row["owner"] == user_id: reason = "shared_owner_transfer_required"
            if reason: blockers.append({"tenant_id": row["id"], "code": reason})
            tenants.append({"tenant_id": row["id"], "classification": row["classification"],
                            "owner_user_id": row["owner"], "member_ids": members, "instance_id": row["instance"],
                            "registry_revision": row["revision"],
                            "action": "erase_private" if row["classification"] == "private" and reason is None else
                                      "leave_shared" if row["classification"] == "shared" and reason is None else "blocked"})
        if not tenants: blockers.append({"tenant_id": None, "code": "account_not_registered"})
        snapshot = {"schema": 1, "user_id": user_id, "mode": self.mode, "tenants": tenants, "blockers": blockers}
        return {**snapshot, "revision": digest(snapshot), "ready": not blockers}

    def preview(self, user_id):
        with self.tx() as db:
            return self._preview(db, identifier(user_id))

    def request(self, user_id, request_key, revision):
        identifier(user_id)
        if not isinstance(request_key, str) or not KEY.fullmatch(request_key):
            raise DeletionError("invalid_request_key", 422)
        with self.tx() as db:
            old = db.execute("SELECT * FROM jobs WHERE user_id=? AND request_key=?", (user_id, request_key)).fetchone()
            if old:
                if old["revision"] != revision: raise DeletionError("request_conflict")
                return self._status(db, old["id"])
            plan = self._preview(db, user_id)
            if plan["revision"] != revision: raise DeletionError("plan_changed")
            if not plan["ready"]: raise DeletionError("ownership_not_ready")
            if db.execute("SELECT 1 FROM jobs WHERE user_id=?", (user_id,)).fetchone():
                raise DeletionError("account_deletion_already_requested")
            job_id, stamp = uuid.uuid4().hex, self.clock()
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,'pending',NULL,?,?)", (job_id,user_id,request_key,encoded(plan),revision,stamp,stamp))
            sequence = [("freeze_account", None, None), ("revoke_user_devices", None, None)]
            for t in plan["tenants"]:
                sequence.extend((phase,t["tenant_id"],t["instance_id"]) for phase in
                                (PRIVATE_STEPS if t["action"] == "erase_private" else ("leave_shared",)))
            sequence.append(("finalize_account",None,None))
            for number,(phase,tenant,instance) in enumerate(sequence):
                op = digest([job_id,revision,number,phase,tenant])
                db.execute("INSERT INTO steps(job_id,number,phase,tenant,instance,operation_id,state,updated) VALUES(?,?,?,?,?,?,'pending',?)",
                           (job_id,number,phase,tenant,instance,op,stamp))
            return self._status(db,job_id)

    def _status(self, db, job_id):
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None: raise DeletionError("job_not_found",404)
        steps = [dict(s) for s in db.execute("SELECT number,phase,tenant AS tenant_id,operation_id,state,attempts,code,evidence,retained_until,updated FROM steps WHERE job_id=? ORDER BY number", (job_id,))]
        return {"id":row["id"],"user_id":row["user_id"],"mode":self.mode,"plan_revision":row["revision"],
                "state":row["state"],"code":row["code"],"created_at":row["created"],"updated_at":row["updated"],"steps":steps}

    def status(self, job_id):
        if not isinstance(job_id,str) or not JOB_ID.fullmatch(job_id): raise DeletionError("invalid_job_id",422)
        with self.tx() as db: return self._status(db,job_id)

    def _result(self, db, operation, step, result):
        valid = (isinstance(result,Receipt) and result.operation_id == operation.operation_id
                 and result.disposition in {"done","retry","retained"}
                 and (result.evidence is None or isinstance(result.evidence,str) and re.fullmatch(r"[0-9a-f]{64}",result.evidence)))
        if not valid or result.disposition == "done" and (result.evidence is None or result.code is not None or result.retained_until is not None):
            result = Receipt(operation.operation_id,"retry",code="invalid_receipt")
        if result.disposition != "done" and result.code not in CODES:
            result = Receipt(operation.operation_id,"retry",code="invalid_receipt")
        if result.disposition == "retained" and (type(result.retained_until) not in (int,float) or not self.clock() < result.retained_until < self.clock()+10*366*86400):
            result = Receipt(operation.operation_id,"retry",code="invalid_receipt")
        if result.disposition == "retry" and result.retained_until is not None:
            result = Receipt(operation.operation_id,"retry",code="invalid_receipt")
        state = "succeeded" if result.disposition == "done" else "waiting"
        stamp=self.clock()
        db.execute("UPDATE steps SET state=?,code=?,evidence=?,retained_until=?,updated=? WHERE job_id=? AND number=?",
                   (state,result.code,result.evidence,result.retained_until,stamp,operation.job_id,step["number"]))
        remains = db.execute("SELECT 1 FROM steps WHERE job_id=? AND state!='succeeded'", (operation.job_id,)).fetchone()
        jobstate = "completed" if not remains else "running" if state == "succeeded" else "waiting"
        db.execute("UPDATE jobs SET state=?,code=?,updated=? WHERE id=?", (jobstate,result.code,stamp,operation.job_id))

    def run_one(self, job_id, adapter: DeletionAdapter | None = None):
        self.status(job_id)
        try:
            with FileLock(self.root/(job_id+".lock"),timeout=0):
                with self.tx() as db:
                    job=db.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
                    step=db.execute("SELECT * FROM steps WHERE job_id=? AND state!='succeeded' ORDER BY number LIMIT 1",(job_id,)).fetchone()
                    if step is None:return self._status(db,job_id)
                    operation=Operation(step["operation_id"],job_id,job["user_id"],job["revision"],step["phase"],step["tenant"],step["instance"],self.mode,tuple(json.loads(job["plan"])["tenants"]))
                    db.execute("UPDATE steps SET state='running',attempts=attempts+1,code=NULL,updated=? WHERE job_id=? AND number=?",(self.clock(),job_id,step["number"]))
                    db.execute("UPDATE jobs SET state='running',code=NULL,updated=? WHERE id=?",(self.clock(),job_id))
                try:
                    if adapter is None: result=Receipt(operation.operation_id,"retry",code="adapter_unconfigured")
                    elif adapter.mode != self.mode: result=Receipt(operation.operation_id,"retry",code="adapter_mismatch")
                    else: result=adapter.execute(operation)
                except Exception:
                    # Never persist provider messages, paths, credential-containing URLs or stack traces.
                    result=Receipt(operation.operation_id,"retry",code="adapter_failed")
                # BaseException deliberately leaves the durable running step. On
                # restart the SAME operation_id is reconciled by the adapter.
                with self.tx() as db:
                    self._result(db,operation,step,result)
                    return self._status(db,job_id)
        except Timeout:
            raise DeletionError("job_already_running") from None

    def run(self, job_id, adapter=None, *, max_steps=50):
        if type(max_steps) is not int or not 1 <= max_steps <= 100: raise DeletionError("invalid_step_limit",422)
        current=self.status(job_id)
        for _ in range(max_steps):
            if current["state"] == "completed":break
            current=self.run_one(job_id,adapter)
            if current["state"] in {"waiting","completed"}:break
        return current
