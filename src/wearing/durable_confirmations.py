"""Durable proposals and read-only recovery. Old decisions never grant new actions.

This is not an execution replay queue. A recovery gets its own guarded task and
must observe a revisioned resource and obtain a new, exact-operation decision.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from .store import now
from .task_visibility import INTERNAL, predicate, visible

MARKER = "PAJIO_CONFIRMATION_V2\n"
LIVE = {"starting", "running", "waiting_for_approval", "stopping", "connection_lost", "ambiguous"}
TERMINAL = {"completed_unverified", "verified", "stopped", "failed", "closed_by_user"}
PREFIX = "mcp__wearing_life__"
# Only contracts whose actual mutation checks the observed revision atomically.
RESOURCE_TOOLS = {
    PREFIX + "life_change": ("life_records", "record_id", PREFIX + "life_records"),
    PREFIX + "goal_change": ("personal_goals", "goal_id", PREFIX + "goal_list"),
    PREFIX + "schedule_change": ("personal_schedules", "schedule_id", PREFIX + "schedule_list"),
}


class ConfirmationError(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def deadline(seconds=300):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class DurableConfirmations:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS durable_confirmations (
              id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, task_id TEXT NOT NULL,
              run_id TEXT NOT NULL, card TEXT NOT NULL, state TEXT NOT NULL,
              revision INTEGER NOT NULL DEFAULT 1, request_id TEXT, parent_id TEXT,
              recovery_task_id TEXT, expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS durable_confirmations_identity ON durable_confirmations(identity_id,created_at);
            CREATE TABLE IF NOT EXISTS confirmation_recovery_tasks (
              task_id TEXT PRIMARY KEY, source_id TEXT NOT NULL UNIQUE,
              permit_id TEXT, consumed_at TEXT, result_state TEXT);
            CREATE TABLE IF NOT EXISTS confirmation_resume_requests (
              identity_id TEXT NOT NULL, request_key TEXT NOT NULL,
              action_id TEXT NOT NULL, revision INTEGER NOT NULL, task_id TEXT NOT NULL,
              PRIMARY KEY(identity_id,request_key));
            CREATE TABLE IF NOT EXISTS confirmation_observations (
              task_id TEXT NOT NULL, tool TEXT NOT NULL, resource_id TEXT NOT NULL,
              revision INTEGER NOT NULL, observed_at TEXT NOT NULL,
              PRIMARY KEY(task_id,tool,resource_id));
            """)

    def _expire(self, db):
        db.execute("""UPDATE durable_confirmations SET state='needs_recheck',revision=revision+1,updated_at=?
                    WHERE state='pending' AND expires_at<=?""", (now(), now()))

    def _reconcile_recoveries(self, db):
        # A previous process may have committed task cancellation without
        # observing the durable proposal. Repair only authoritative terminal
        # tasks, never infer termination from a stale connection or a stop request.
        marks = ','.join('?' for _ in TERMINAL)
        tasks = db.execute(f"""SELECT t.* FROM tasks t
            JOIN confirmation_recovery_tasks r ON r.task_id=t.id
            JOIN durable_confirmations d ON d.id=r.source_id
            WHERE d.state='recovering' AND t.status IN ({marks})""", tuple(TERMINAL)).fetchall()
        for task in tasks:
            self.observe_task_in(db, task)

    @staticmethod
    def _decode(row):
        if not row:
            return None
        item = dict(row)
        item["card"] = json.loads(item["card"])
        return item

    def get(self, identity, action_id, *, owner_scope=INTERNAL):
        with self.store.connection() as db:
            self._expire(db)
            self._reconcile_recoveries(db)
            clause = '' if owner_scope is INTERNAL else ' AND ' + predicate('d.task_id')
            row = db.execute('SELECT d.* FROM durable_confirmations d WHERE id=:action AND identity_id=:identity' + clause,
                {'action': action_id, 'identity': identity, 'task_owner': None if owner_scope is INTERNAL else owner_scope}).fetchone()
        if not row:
            raise ConfirmationError("当前身份没有这项确认。")
        return self._decode(row)

    def list(self, identity, *, owner_scope=INTERNAL):
        self.store.identity(identity)
        with self.store.connection() as db:
            self._expire(db)
            self._reconcile_recoveries(db)
            clause = '' if owner_scope is INTERNAL else ' AND ' + predicate('d.task_id')
            rows = db.execute("""SELECT d.*,t.status AS task_status,r.status AS recovery_task_status
                FROM durable_confirmations d JOIN tasks t ON t.id=d.task_id
                LEFT JOIN tasks r ON r.id=d.recovery_task_id WHERE d.identity_id=:identity""" + clause + ' ORDER BY d.created_at DESC,d.id',
                {'identity': identity, 'task_owner': None if owner_scope is INTERNAL else owner_scope}).fetchall()
        return [dict(self._decode(r), can_resume=r["state"] == "needs_recheck" and r["task_status"] in TERMINAL,
                     resume_label="重新核对并继续") for r in rows]

    def active_task(self, identity):
        with self.store.connection() as db:
            rows = db.execute("""SELECT * FROM tasks WHERE identity_id=?
                AND status IN ('starting','running','waiting_for_approval')""", (identity,)).fetchall()
        if len(rows) != 1 or not rows[0]["run_id"]:
            raise ConfirmationError("当前运行尚未绑定，未创建确认卡。请稍后重新读取运行状态。")
        return dict(rows[0])

    def create(self, identity, card):
        task = self.active_task(identity)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            recovery = db.execute("SELECT * FROM confirmation_recovery_tasks WHERE task_id=?", (task["id"],)).fetchone()
            if db.execute("""SELECT 1 FROM durable_confirmations WHERE task_id=?
                AND state IN ('pending','sending','unknown','needs_recheck')""", (task["id"],)).fetchone():
                raise ConfirmationError("本轮已有待处理的确认，不能重建卡片或重试旧动作。")
            if recovery:
                if recovery["permit_id"] or recovery["consumed_at"]:
                    raise ConfirmationError("本次恢复的操作已处理；请返回真实结果，不重复发起。")
                self._validate_operation(db, task, card.get("operation"), observed=True)
            action_id, stamp = "decision_" + uuid.uuid4().hex, now()
            db.execute("""INSERT INTO durable_confirmations
                (id,identity_id,task_id,run_id,card,state,parent_id,expires_at,created_at,updated_at)
                VALUES(?,?,?,?,?,'pending',?,?,?,?)""",
                (action_id, identity, task["id"], task["run_id"], encoded(card),
                 recovery["source_id"] if recovery else None, deadline(), stamp, stamp))
            if recovery:
                db.execute("UPDATE durable_confirmations SET state='superseded',revision=revision+1,updated_at=? WHERE id=? AND state='recovering'", (stamp, recovery["source_id"]))
        return self.get(identity, action_id)

    def bind(self, task, action_id, card, request_id):
        """Validate the model-visible envelope against the trusted MCP receipt."""
        with self.store.connection() as db:
            self._expire(db)
            row = db.execute("SELECT * FROM durable_confirmations WHERE id=?", (action_id,)).fetchone()
            if not row or row["task_id"] != task["id"] or row["identity_id"] != task["identity_id"] or row["run_id"] != task["run_id"] or row["card"] != encoded(card):
                raise ConfirmationError("这张确认卡与当前运行不一致。")
            if row["request_id"] not in {None, request_id}:
                raise ConfirmationError("确认请求已变化，旧卡不能继续使用。")
            db.execute("UPDATE durable_confirmations SET request_id=? WHERE id=?", (request_id, action_id))
            return row["state"]

    def claim(self, task, action_id, request_id, *, approving=True):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._expire(db)
            row = db.execute("SELECT * FROM durable_confirmations WHERE id=?", (action_id,)).fetchone()
            if not row or row["task_id"] != task["id"] or row["run_id"] != task["run_id"] or row["request_id"] != request_id or row["state"] != "pending":
                return False
            if row["parent_id"] and approving:
                try:
                    self._validate_operation(db, task, json.loads(row["card"]).get("operation"), observed=True)
                except ConfirmationError:
                    db.execute("UPDATE durable_confirmations SET state='needs_recheck',revision=revision+1,updated_at=? WHERE id=?", (now(), action_id))
                    return False
            db.execute("UPDATE durable_confirmations SET state='sending',updated_at=? WHERE id=?", (now(), action_id))
            return True

    def delivery(self, action_id, state):
        # An elicit accept/decline is a stronger receipt than a lost HTTP response.
        with self.store.connection() as db:
            db.execute("UPDATE durable_confirmations SET state=?,updated_at=? WHERE id=? AND state='sending'",
                       (state, now(), action_id))

    def finish_wait(self, action_id, accepted=None):
        """Only called by the bound MCP waiter, never by a stale UI decision."""
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM durable_confirmations WHERE id=?", (action_id,)).fetchone()
            if not row or row["state"] not in {"pending", "sending", "unknown"}:
                return False
            if accepted is True and row["expires_at"] > now():
                state = "approved"
            elif accepted is False:
                state = "denied"
            else:
                state = "needs_recheck"
            db.execute("UPDATE durable_confirmations SET state=?,revision=revision+1,updated_at=? WHERE id=?", (state, now(), action_id))
            if state == "approved" and row["parent_id"]:
                db.execute("UPDATE confirmation_recovery_tasks SET permit_id=? WHERE task_id=? AND permit_id IS NULL AND consumed_at IS NULL", (action_id, row["task_id"]))
            return state == "approved"

    def observe_task(self, task, action_id=None, *, stopped=False):
        with self.store.connection() as db:
            self._expire(db)
            self.observe_task_in(db, task, action_id, stopped=stopped)

    def observe_task_in(self, db, task, action_id=None, *, stopped=False):
        """Reconcile with a trusted task row in its caller's write transaction."""
        if not stopped and task["status"] not in TERMINAL:
            return
        # An authoritative terminal run has no actionable waiter. A lost
        # approval response never became a permit unless finish_wait first
        # persisted approved; unknown/sending are therefore safe to recheck.
        db.execute("""UPDATE durable_confirmations SET state=?,revision=revision+1,updated_at=?
            WHERE task_id=? AND state IN ('pending','sending','unknown') AND id IS NOT ?""",
            ("denied" if stopped else "needs_recheck", now(), task["id"], action_id))
        # An unused machine permit is provably unexecuted. A consumed one
        # with no returned receipt is ambiguous and MUST NOT be replayed.
        db.execute("""UPDATE durable_confirmations SET state=?,revision=revision+1,updated_at=?
            WHERE state='approved' AND id=(SELECT permit_id FROM confirmation_recovery_tasks
            WHERE task_id=? AND consumed_at IS NULL)""", ("denied" if stopped else "needs_recheck", now(), task["id"]))
        db.execute("""UPDATE durable_confirmations SET state='execution_unknown',revision=revision+1,updated_at=?
            WHERE state='executing' AND id=(SELECT permit_id FROM confirmation_recovery_tasks
            WHERE task_id=? AND consumed_at IS NOT NULL)""", (now(), task["id"]))
        recovery = db.execute("SELECT * FROM confirmation_recovery_tasks WHERE task_id=?", (task["id"],)).fetchone()
        if recovery and not recovery["permit_id"] and not recovery["consumed_at"] and not db.execute("SELECT 1 FROM durable_confirmations WHERE task_id=?", (task["id"],)).fetchone():
            if task['status'] not in TERMINAL:
                return  # Stop was requested; completion still needs proof.
            source = db.execute("SELECT * FROM durable_confirmations WHERE id=?", (recovery["source_id"],)).fetchone()
            if task["status"] in {'failed', 'stopped', 'closed_by_user'}:
                # No proposal/permit existed, therefore this interrupted read-only
                # attempt cannot have performed the pending operation. A new
                # durable entry permits an explicit new observation attempt;
                # replay of the original request key still returns old task.
                stamp = now()
                db.execute("""INSERT INTO durable_confirmations
                    (id,identity_id,task_id,run_id,card,state,parent_id,expires_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,'needs_recheck',?,?,?,?)""",
                    ("decision_" + uuid.uuid4().hex, task["identity_id"], task["id"], task["run_id"] or "",
                     source["card"], source["id"], stamp, stamp, stamp))
                state = "superseded"
            else:
                state = "denied" if stopped else "rechecked"
            db.execute("UPDATE durable_confirmations SET state=?,revision=revision+1,updated_at=? WHERE id=? AND state='recovering'", (state, now(), source["id"]))

    def recover_startup(self):
        with self.store.connection() as db:
            self._expire(db)
            db.execute("UPDATE durable_confirmations SET state='unknown',revision=revision+1,updated_at=? WHERE state='sending'", (now(),))
            self._reconcile_recoveries(db)

    def prepare_recovery(self, identity, action_id, revision, request_key, *, owner_scope=INTERNAL):
        if type(revision) is not int or not re.fullmatch(r"[A-Za-z0-9_-]{16,120}", request_key or ""):
            raise ConfirmationError("恢复请求需要最新版本和有效的重试标识。")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            proposal = db.execute('SELECT task_id FROM durable_confirmations WHERE identity_id=? AND id=?', (identity, action_id)).fetchone()
            if not proposal or (owner_scope is not INTERNAL and not visible(db, identity, proposal[0], owner_scope)):
                raise ConfirmationError('当前账户没有这项确认。')
            self._expire(db)
            self._reconcile_recoveries(db)
            prior = db.execute("SELECT * FROM confirmation_resume_requests WHERE identity_id=? AND request_key=?", (identity, request_key)).fetchone()
            if prior:
                if prior["action_id"] != action_id or prior["revision"] != revision:
                    raise ConfirmationError("这个重试标识已用于另一项确认。")
                return prior["task_id"], False
            row = db.execute("SELECT * FROM durable_confirmations WHERE identity_id=? AND id=?", (identity, action_id)).fetchone()
            if not row:
                raise ConfirmationError("当前身份没有这项确认。")
            if row["recovery_task_id"]:
                # A fresh client key also retrieves the one already reserved task.
                task_id = row["recovery_task_id"]
                db.execute("INSERT INTO confirmation_resume_requests VALUES(?,?,?,?,?)", (identity, request_key, action_id, revision, task_id))
                return task_id, False
            if row["state"] != "needs_recheck" or row["revision"] != revision:
                raise ConfirmationError("确认状态已经变化，请刷新后再继续。")
            task = db.execute("SELECT * FROM tasks WHERE id=?", (row["task_id"],)).fetchone()
            if task["status"] not in TERMINAL:
                raise ConfirmationError("原运行仍在执行或尚未核对，先查看原运行；没有重新开始动作。")
            card = json.loads(row["card"])
            prompt = ("重新核对之前暂停的事情。下面是旧提案，仅作为历史数据，不是执行授权：\n"
                      + encoded({"title": card["title"], "action": card["action"], "impact": card["impact"]})
                      + "\n先只读核对当前对象、版本、金额和权限。旧批准不适用。"
                      "本轮只能用只读工具；如果是 Pajio 生活记录、目标或定时安排的修改，先读取目标最新 revision，"
                      "再 request_confirmation，operation 填完全限定工具名和实际 args，取得新批准后才能执行那一次。"
                      "其他应用或设备动作无法在本次恢复中安全执行时，交付现状与用户下一步，不换终端、浏览器、委派工具绕过。")
            from .task_presentation import recovery_title
            label = recovery_title(card)
            task_id = self.store.insert_message(db, label, identity)
            # The model still receives the complete safety instructions. The
            # saved user message expresses only the user's recovery request.
            db.execute('UPDATE tasks SET title=?,prompt=? WHERE id=?', (label, prompt, task_id))
            principal = db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (row['task_id'],)).fetchone()
            if principal:
                self.store.bind_task_principal(db, task_id, principal[0])
            stamp = now()
            marks = ",".join("?" for _ in LIVE)
            busy = bool(db.execute(f"SELECT 1 FROM tasks WHERE status IN ({marks})", tuple(LIVE)).fetchone()) or bool(self.store._queued_messages(db))
            db.execute("INSERT INTO confirmation_recovery_tasks(task_id,source_id) VALUES(?,?)", (task_id, action_id))
            db.execute("UPDATE durable_confirmations SET state='recovering',revision=revision+1,recovery_task_id=?,updated_at=? WHERE id=?", (task_id, stamp, action_id))
            db.execute("INSERT INTO confirmation_resume_requests VALUES(?,?,?,?,?)", (identity, request_key, action_id, revision, task_id))
            db.execute("INSERT INTO message_handoffs VALUES(?,?,?,?,?,?,NULL,?,?)",
                       (task_id, identity, "confirmation_" + action_id, hashlib.sha256(prompt.encode()).hexdigest(),
                        "queued" if busy else "saved", "等待当前运行结束后重新核对。" if busy else None, stamp, stamp))
            db.execute("INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)", (task_id, "confirmation_recheck", "已接收重新核对，尚未授权旧动作。", stamp))
        return task_id, True

    def _validate_operation(self, db, task, operation, *, observed):
        if not isinstance(operation, dict) or set(operation) != {"tool", "args"} or operation["tool"] not in RESOURCE_TOOLS:
            raise ConfirmationError("恢复只接受有版本核对的生活记录、目标或安排修改；其他动作请交付现状供用户接管。")
        args = operation["args"]
        table, id_key, read_tool = RESOURCE_TOOLS[operation["tool"]]
        if not isinstance(args, dict) or type(args.get("revision")) is not int or not isinstance(args.get(id_key), str):
            raise ConfirmationError("需要准确对象和刚读取的 revision。")
        # Identifiers here come only from the fixed table above, never model text.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            raise ConfirmationError("目标资源暂不可用。")
        resource = db.execute(f"SELECT revision FROM {table} WHERE id=? AND identity_id=?", (args[id_key], task["identity_id"])).fetchone()
        if not resource or resource["revision"] != args["revision"]:
            raise ConfirmationError("对象已经变化，请重新读取，旧确认不能覆盖新版本。")
        if observed:
            receipt = db.execute("""SELECT * FROM confirmation_observations WHERE task_id=? AND tool=? AND resource_id=? AND revision=?""",
                                 (task["id"], read_tool, args[id_key], args["revision"])).fetchone()
            if not receipt or receipt["observed_at"] < (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat():
                raise ConfirmationError("本轮尚未实际读取这个对象的最新版本。")
        return True

    def read_snapshot(self, task, tool, args):
        """Snapshot before real read; persisting only on successful return is conservative."""
        specs = {spec[2]: spec[:2] for spec in RESOURCE_TOOLS.values()}
        if tool not in specs:
            return []
        table, id_key = specs[tool]
        with self.store.connection() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                return []
            query = f"SELECT id,revision FROM {table} WHERE identity_id=?"
            params = [task["identity_id"]]
            if args.get(id_key):
                query += " AND id=?"
                params.append(args[id_key])
            elif tool.endswith("life_records") and not args.get("include_deleted"):
                query += " AND deleted_at IS NULL"
            return [dict(r) for r in db.execute(query, params)]

    def record_read(self, task, tool, snapshot):
        with self.store.connection() as db:
            db.executemany("INSERT OR REPLACE INTO confirmation_observations VALUES(?,?,?,?,?)",
                           [(task["id"], tool, r["id"], r["revision"], now()) for r in snapshot])

    def consume(self, task, tool, args):
        """Commit intent BEFORE calling a mutator. Unknown/failed calls are never replayed."""
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current_task = db.execute("SELECT status,run_id,identity_id FROM tasks WHERE id=?", (task["id"],)).fetchone()
            if not current_task or current_task["status"] not in LIVE - {"stopping"} or current_task["run_id"] != task["run_id"] or current_task["identity_id"] != task["identity_id"]:
                return False
            recovery = db.execute("SELECT * FROM confirmation_recovery_tasks WHERE task_id=?", (task["id"],)).fetchone()
            if not recovery or not recovery["permit_id"] or recovery["consumed_at"]:
                return False
            proposal = db.execute("SELECT * FROM durable_confirmations WHERE id=?", (recovery["permit_id"],)).fetchone()
            if not proposal or proposal["state"] != "approved" or proposal["expires_at"] <= now():
                return False
            operation = json.loads(proposal["card"]).get("operation")
            if encoded(operation) != encoded({"tool": tool, "args": args}):
                return False
            try:
                self._validate_operation(db, task, operation, observed=True)
            except ConfirmationError:
                return False
            db.execute("UPDATE confirmation_recovery_tasks SET consumed_at=?,result_state='unknown' WHERE task_id=? AND consumed_at IS NULL", (now(), task["id"]))
            db.execute("UPDATE durable_confirmations SET state='executing',revision=revision+1,updated_at=? WHERE id=?", (now(), proposal["id"]))
            return True

    def execution_result(self, task_id, successful):
        with self.store.connection() as db:
            db.execute("UPDATE confirmation_recovery_tasks SET result_state=? WHERE task_id=? AND consumed_at IS NOT NULL", ("returned" if successful else "unknown", task_id))
            db.execute("""UPDATE durable_confirmations SET state=?,revision=revision+1,updated_at=?
                WHERE id=(SELECT permit_id FROM confirmation_recovery_tasks WHERE task_id=?) AND state='executing'""",
                ("executed_unverified" if successful else "execution_unknown", now(), task_id))
