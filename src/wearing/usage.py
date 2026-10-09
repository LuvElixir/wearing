"""Durable trial admission. Counts attempts, never fabricates a supplier bill.

The budget belongs to one tenant runtime/data directory, not a switchable
identity. Completed/uncertain attempts remain charged after a process crash.
Only a dead owner releases concurrency; there is no time-based free retry.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


class UsageError(RuntimeError):
    def __init__(self, code, detail=None):
        self.code = code
        self.detail = detail or {
            "quota_exhausted": "试用执行额度已用完；仍可查看结果、读取原件和暂停任务。",
            "quota_busy": "已有调用正在处理，请稍后再试。",
            "quota_duplicate": "这次请求已经提交，不能重复扣减或重复调用；请查看已有结果。",
            "quota_unavailable": "暂时无法核对试用额度，已停止新调用，请稍后重试。",
            "quota_provider": "当前模型尚未接入试用限额，请切换到已支持的兼容接口模型。",
        }.get(code, "这次调用未能开始，请稍后重试。")
        super().__init__(self.detail)


@dataclass(frozen=True)
class UsagePolicy:
    model_calls: int = 200
    speech_calls: int = 100
    speech_ms: int = 3_600_000
    model_concurrency: int = 2
    speech_concurrency: int = 2

    def __post_init__(self):
        if any(type(v) is not int or v < 0 or v > 1_000_000_000 for v in asdict(self).values()):
            raise ValueError("Invalid trial limit")
        if not self.model_concurrency or not self.speech_concurrency:
            raise ValueError("Concurrency must be positive")


def _process_stamp(pid):
    try:
        import psutil
        return str(psutil.Process(pid).create_time())
    except ImportError:
        return ""
    except Exception:
        return None


def _alive(pid, stamp):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True  # Unknown is not permission to oversubscribe.
    current = _process_stamp(pid)
    return not stamp or current is None or not current or current == stamp


class UsageBook:
    def __init__(self, data_dir, policy=None, *, alive=None, enabled=None):
        self.enabled = os.environ.get("PAJIO_TRIAL_LIMITS") == "1" if enabled is None else enabled
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "usage.sqlite3"
        self.alive = alive or _alive
        self.pid = os.getpid()
        self.stamp = _process_stamp(self.pid) or ""
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS trial_policy (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trial_calls (
                  id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                  identity_id TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
                  reserved_ms INTEGER NOT NULL DEFAULT 0, measured_ms INTEGER,
                  input_tokens INTEGER, output_tokens INTEGER,
                  provider TEXT, model TEXT, owner_pid INTEGER NOT NULL, owner_stamp TEXT NOT NULL,
                  created_at REAL NOT NULL, finished_at REAL);
                CREATE INDEX IF NOT EXISTS trial_calls_kind_state ON trial_calls(kind,state);
            """)
            db.execute("INSERT OR IGNORE INTO trial_policy VALUES(1,?)", (json.dumps(asdict(policy or UsagePolicy())),))
        self.path.chmod(0o600)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=10000")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def configure(self, policy):
        """Operator-only integration point. Never exposed as a client mutation."""
        if not isinstance(policy, UsagePolicy):
            raise ValueError("Invalid trial policy")
        with self._db() as db:
            db.execute("UPDATE trial_policy SET body=? WHERE id=1", (json.dumps(asdict(policy)),))

    def _recover(self, db):
        owners = db.execute("SELECT DISTINCT owner_pid,owner_stamp FROM trial_calls WHERE state='active'").fetchall()
        for owner in owners:
            if not self.alive(owner["owner_pid"], owner["owner_stamp"]):
                db.execute("UPDATE trial_calls SET state='uncertain',finished_at=? WHERE state='active' AND owner_pid=? AND owner_stamp=?", (time.time(), owner["owner_pid"], owner["owner_stamp"]))

    def recover(self):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover(db)

    def _totals(self, db, kind):
        return dict(db.execute("""SELECT count(*) AS calls,
            coalesce(sum(state='active'),0) AS active,
            coalesce(sum(state='uncertain'),0) AS uncertain,
            coalesce(sum(CASE WHEN kind='speech' THEN coalesce(measured_ms,reserved_ms) ELSE 0 END),0) AS audio_ms
            FROM trial_calls WHERE kind=?""", (kind,)).fetchone())

    def _check(self, db, kind, reserve_ms=0):
        if not self.enabled:
            return
        policy = UsagePolicy(**json.loads(db.execute("SELECT body FROM trial_policy WHERE id=1").fetchone()[0]))
        totals = self._totals(db, kind)
        if totals["calls"] >= getattr(policy, kind + "_calls") or (kind == "speech" and totals["audio_ms"] + reserve_ms > policy.speech_ms):
            raise UsageError("quota_exhausted")
        if totals["active"] >= getattr(policy, kind + "_concurrency"):
            raise UsageError("quota_busy")

    def check(self, kind="model"):
        if kind not in ("model", "speech"):
            raise ValueError("Invalid usage kind")
        try:
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                self._recover(db)
                self._check(db, kind)
        except (OSError, sqlite3.Error):
            raise UsageError("quota_unavailable") from None

    def reserve(self, identity, kind, request_key, *, reserve_ms=0, provider=None, model=None):
        if kind not in ("model", "speech") or not isinstance(identity, str) or not identity or len(identity) > 120:
            raise ValueError("Invalid usage owner")
        if not isinstance(request_key, str) or not request_key or len(request_key) > 300 or type(reserve_ms) is not int or reserve_ms < 0 or reserve_ms > 180_000:
            raise ValueError("Invalid reservation")
        digest = hashlib.sha256((identity + "\0" + kind + "\0" + request_key).encode()).hexdigest()
        try:
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                self._recover(db)
                if db.execute("SELECT id FROM trial_calls WHERE request_key=?", (digest,)).fetchone():
                    raise UsageError("quota_duplicate")
                self._check(db, kind, reserve_ms)
                call_id = uuid.uuid4().hex
                db.execute("""INSERT INTO trial_calls(id,request_key,identity_id,kind,state,reserved_ms,provider,model,owner_pid,owner_stamp,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (call_id, digest, identity, kind, "active", reserve_ms,
                    str(provider or "")[:100] or None, str(model or "")[:160] or None, self.pid, self.stamp, time.time()))
            return call_id
        except (OSError, sqlite3.Error):
            raise UsageError("quota_unavailable") from None

    def settle(self, call_id, *, input_tokens=None, output_tokens=None, measured_ms=None, uncertain=False):
        """Terminal settlement is idempotent; missing receipt stays NULL."""
        for value in (input_tokens, output_tokens, measured_ms):
            if value is not None and (type(value) is not int or value < 0 or value > 1_000_000_000):
                raise ValueError("Invalid provider receipt")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM trial_calls WHERE id=?", (call_id,)).fetchone()
            if not row:
                raise ValueError("Unknown call")
            if row["state"] != "active":
                return
            if measured_ms is not None and measured_ms > row["reserved_ms"]:
                raise ValueError("Audio exceeded reserved budget")
            db.execute("""UPDATE trial_calls SET state=?,input_tokens=?,output_tokens=?,measured_ms=?,finished_at=? WHERE id=? AND state='active'""",
                       ("uncertain" if uncertain else "completed", input_tokens, output_tokens, measured_ms, time.time(), call_id))

    def snapshot(self, identity):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._recover(db)
            policy = json.loads(db.execute("SELECT body FROM trial_policy WHERE id=1").fetchone()[0])
            resources = {}
            for kind in ("model", "speech"):
                total = self._totals(db, kind)
                resources[kind] = {**total, "limit": policy[kind + "_calls"], "remaining": max(0, policy[kind + "_calls"] - total["calls"]), "concurrency": policy[kind + "_concurrency"]}
            resources["speech"].update(ms_limit=policy["speech_ms"], ms_remaining=max(0, policy["speech_ms"] - resources["speech"]["audio_ms"]))
            own = dict(db.execute("""SELECT count(*) AS calls,
                sum(input_tokens) AS input_tokens,sum(output_tokens) AS output_tokens,
                coalesce(sum(kind='model' AND (input_tokens IS NULL OR output_tokens IS NULL)),0) AS unreported_model_calls
                FROM trial_calls WHERE identity_id=?""", (identity,)).fetchone())
            return {"mode": "trial" if self.enabled else "not_enabled", "scope": "runtime", "reset_at": None, "resources": resources,
                    "identity_usage": own, "cost": None, "cost_status": "unavailable", "observed_at": time.time()}
