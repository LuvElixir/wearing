"""Trusted ownership, immutable user requests and operator freeze; never erases data.

The public role can insert/read its own request, but cannot administer membership,
ownership or routes. A durable request itself immediately fences account access.
"""
import json
import re
import time
import uuid

from sqlalchemy import delete, insert, select, update

from ..account_deletion import DeletionError, digest as plan_digest
from .control import deletion_requests, digest, members, ownership, routes, sessions, tenants, users


class AccountDeletionControl:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock

    def _operator(self):
        if not self.store.operator:
            raise DeletionError("operator_required", 403)

    def register(self, tenant_id, classification, *, owner_user_id=None, expected_revision=None):
        """Operator-only explicit enrollment, including every inactive membership."""
        self._operator()
        if classification not in {"private", "shared", "unknown"} or classification != "unknown" and owner_user_id is None:
            raise DeletionError("invalid_ownership", 422)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise DeletionError("invalid_registry_revision", 422)
        with self.store.transaction(mutating=True) as db:
            if not self.store.tenant_editable(db, tenant_id):
                raise DeletionError("tenant_unavailable")
            people = sorted((r.user_id, r.active) for r in db.execute(select(members).where(members.c.tenant_id == tenant_id)))
            if not people or owner_user_id is not None and owner_user_id not in {p[0] for p in people}:
                raise DeletionError("owner_not_member", 422)
            if any(not self.store.user_available(db, p[0]) for p in people):
                raise DeletionError("account_deletion_in_progress")
            old = db.execute(select(ownership).where(ownership.c.tenant_id == tenant_id)).mappings().first()
            if expected_revision != (old["revision"] if old else None):
                raise DeletionError("registry_changed")
            values = dict(classification=classification, owner_user_id=owner_user_id,
                          member_count=len(people), member_digest=digest(json.dumps(people, separators=(",", ":"))),
                          instance_id=db.scalar(select(routes.c.instance_id).where(routes.c.tenant_id == tenant_id)),
                          revision=(old["revision"] if old else 0)+1)
            if old:
                db.execute(update(ownership).where(ownership.c.tenant_id == tenant_id).values(**values))
            else:
                db.execute(insert(ownership).values(tenant_id=tenant_id, **values))
            return {"tenant_id": tenant_id, **values}

    def _preview(self, db, user_id):
        scope, blockers = [], []
        own = list(db.scalars(select(members.c.tenant_id).where(members.c.user_id == user_id).order_by(members.c.tenant_id)))
        for tenant_id in own:
            row = db.execute(select(ownership).where(ownership.c.tenant_id == tenant_id)).mappings().first()
            reason = None
            if row is None or row["classification"] == "unknown": reason = "ownership_unknown"
            elif row["classification"] == "private":
                if row["owner_user_id"] != user_id: reason = "not_private_owner"
                elif row["member_count"] != 1: reason = "private_has_other_members"
                elif row["instance_id"] is None: reason = "instance_unregistered"
            elif row["owner_user_id"] == user_id: reason = "shared_owner_transfer_required"
            elif row["owner_user_id"] is None: reason = "ownership_unknown"
            if reason: blockers.append({"tenant_id": tenant_id, "code": reason})
            scope.append({"tenant_id": tenant_id, "classification": row["classification"] if row else "unknown",
                          "registry_revision": row["revision"] if row else None,
                          "member_digest": row["member_digest"] if row else None,
                          "instance_id": row["instance_id"] if row else None,
                          "action": "blocked" if reason else "erase_private" if row["classification"] == "private" else "leave_shared"})
        if not own: blockers.append({"tenant_id": None, "code": "account_not_registered"})
        plan = {"schema": 1, "user_id": user_id, "tenants": scope, "blockers": blockers}
        return {**plan, "revision": plan_digest(plan), "ready": not blockers}

    def preview(self, session):
        with self.store.transaction(user_id=session.user_id) as db:
            if not self.store.user_available(db, session.user_id):
                raise DeletionError("account_unavailable", 403)
            return self._preview(db, session.user_id)

    @staticmethod
    def _receipt(row):
        if row is None: return None
        plan = json.loads(row["plan_json"])
        return {"id": row["id"], "user_id": row["user_id"], "request_key": row["request_key"],
                "plan_revision": row["plan_revision"], "state": row["state"], "code": row["code"],
                "created_at": row["created_at"], "updated_at": row["updated_at"] or row["created_at"],
                "tenants": [{k: t[k] for k in ("tenant_id", "classification", "action")} for t in plan["tenants"]],
                "data_erased": row["state"] == "completed" and row["code"] == "verified"}

    def request(self, session, request_key, plan_revision):
        if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,120}", request_key):
            raise DeletionError("invalid_request_key", 422)
        if not isinstance(plan_revision, str) or not re.fullmatch(r"[a-f0-9]{64}", plan_revision):
            raise DeletionError("invalid_plan_revision", 422)
        with self.store.transaction(mutating=True, user_id=session.user_id) as db:
            old = db.execute(select(deletion_requests).where(deletion_requests.c.user_id == session.user_id)).mappings().first()
            if old:
                if old["request_key"] != request_key or old["plan_revision"] != plan_revision:
                    raise DeletionError("request_conflict")
                return self._receipt(old)
            if not self.store.user_available(db, session.user_id):
                raise DeletionError("account_unavailable", 403)
            plan = self._preview(db, session.user_id)
            if plan["revision"] != plan_revision: raise DeletionError("plan_changed")
            if not plan["ready"]: raise DeletionError("ownership_not_ready")
            job_id = uuid.uuid4().hex
            db.execute(insert(deletion_requests).values(id=job_id, user_id=session.user_id, request_key=request_key,
                        plan_revision=plan_revision, plan_json=json.dumps(plan, sort_keys=True, separators=(",", ":")), created_at=int(self.clock())))
            return self._receipt(db.execute(select(deletion_requests).where(deletion_requests.c.id == job_id)).mappings().one())

    def status(self, user_id, job_id=None, request_key=None):
        """Caller must authenticate the user (business session or B's signed status-only receipt)."""
        if (job_id is None) == (request_key is None): raise DeletionError("invalid_status_selector", 422)
        if job_id is not None and (not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id)):
            raise DeletionError("invalid_job_id", 422)
        if request_key is not None and (not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,120}", request_key)):
            raise DeletionError("invalid_request_key", 422)
        with self.store.transaction(user_id=user_id) as db:
            clause = deletion_requests.c.id == job_id if job_id else deletion_requests.c.request_key == request_key
            return self._receipt(db.execute(select(deletion_requests).where(deletion_requests.c.user_id == user_id, clause)).mappings().first())

    def freeze(self, job_id):
        """Operator step only. Revalidate under the enrollment lock; never deletes content."""
        self._operator()
        with self.store.transaction(mutating=True) as db:
            row = db.execute(select(deletion_requests).where(deletion_requests.c.id == job_id)).mappings().first()
            if not row: raise DeletionError("job_not_found", 404)
            if row["state"] == "frozen": return self._receipt(row)
            if row["state"] != "awaiting_operator": raise DeletionError("job_state_conflict")
            plan = self._preview(db, row["user_id"])
            if plan["revision"] != row["plan_revision"] or not plan["ready"] or plan != json.loads(row["plan_json"]):
                raise DeletionError("ownership_changed")
            db.execute(update(users).where(users.c.id == row["user_id"]).values(deletion_state="frozen"))
            for tenant in plan["tenants"]:
                if tenant["action"] == "erase_private":
                    db.execute(update(tenants).where(tenants.c.id == tenant["tenant_id"]).values(deletion_state="frozen"))
            db.execute(update(members).where(members.c.user_id == row["user_id"]).values(active=False))
            for tenant in plan["tenants"]:
                self.store.refresh_ownership(db, tenant["tenant_id"])
            db.execute(delete(sessions).where(sessions.c.user_id == row["user_id"]))
            db.execute(update(deletion_requests).where(deletion_requests.c.id == job_id).values(state="frozen", code="adapter_unconfigured", updated_at=int(self.clock())))
            return self._receipt(db.execute(select(deletion_requests).where(deletion_requests.c.id == job_id)).mappings().one())
