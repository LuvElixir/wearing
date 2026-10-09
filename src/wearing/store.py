"""Wearing records task truth separately from Hermes sessions and model runs."""

import json
import hashlib
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import private_directory

DEFAULT_IDENTITY = "daily"


class IdentityError(ValueError):
    pass


class MessageConflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        private_directory(path.parent)
        self.path = path
        if path.exists():
            with self.connection() as db:
                columns = {r[1] for r in db.execute("PRAGMA table_info(tasks)")}
                backup = path.with_suffix(".before-identities.sqlite3")
                if columns and "identity_id" not in columns and not backup.exists():
                    with sqlite3.connect(backup) as copy:
                        db.backup(copy)
                    backup.chmod(0o600)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL,
                    target TEXT NOT NULL, status TEXT NOT NULL, output TEXT NOT NULL DEFAULT '',
                    error TEXT, run_id TEXT, attempt INTEGER NOT NULL DEFAULT 0,
                    session_id TEXT NOT NULL, payload TEXT, idempotency_key TEXT,
                    usage TEXT, approval TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    verification_note TEXT, verified_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                    kind TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversation (
                    id INTEGER PRIMARY KEY CHECK(id=1), session_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
                    task_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
                );
            """)
            db.execute("INSERT OR IGNORE INTO conversation(id,session_id) VALUES(1,?)", ("wearing-personal-" + uuid.uuid4().hex,))
        self._migrate_identities()
        with self.connection() as db:
            if "research" not in {r[1] for r in db.execute("PRAGMA table_info(tasks)")}:
                db.execute("ALTER TABLE tasks ADD COLUMN research TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS message_handoffs (
                task_id TEXT PRIMARY KEY REFERENCES tasks(id), identity_id TEXT NOT NULL,
                request_id TEXT, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
                blocked_reason TEXT, next_retry TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(identity_id,request_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_principals (
                task_id TEXT PRIMARY KEY REFERENCES tasks(id), owner_scope TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS owner_conversations (
                identity_id TEXT NOT NULL REFERENCES identities(id), owner_scope TEXT NOT NULL,
                session_id TEXT NOT NULL, PRIMARY KEY(identity_id,owner_scope))""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_conversation_sessions (
                task_id TEXT PRIMARY KEY REFERENCES tasks(id), identity_id TEXT NOT NULL,
                owner_scope TEXT NOT NULL, session_id TEXT NOT NULL)""")

    def _migrate_identities(self):
        # The legacy singleton is retained for rollback; its session is copied once.
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS identities (
                id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '', region TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            stamp = now()
            db.execute("INSERT OR IGNORE INTO identities VALUES(?,?,?,?,?,?)",
                       (DEFAULT_IDENTITY, "日常", "日常生活与身边的事情", "CN", stamp, stamp))
            db.execute("""CREATE TABLE IF NOT EXISTS identity_conversations (
                identity_id TEXT PRIMARY KEY REFERENCES identities(id), session_id TEXT NOT NULL)""")
            db.execute("INSERT OR IGNORE INTO identity_conversations SELECT ?,session_id FROM conversation WHERE id=1", (DEFAULT_IDENTITY,))
            if "identity_id" not in {r[1] for r in db.execute("PRAGMA table_info(tasks)")}:
                db.execute("ALTER TABLE tasks ADD COLUMN identity_id TEXT NOT NULL DEFAULT 'daily' REFERENCES identities(id)")
            db.execute("CREATE INDEX IF NOT EXISTS tasks_identity ON tasks(identity_id,created_at)")

    def identity(self, identity_id=DEFAULT_IDENTITY):
        with self.connection() as db:
            row = db.execute("SELECT * FROM identities WHERE id=?", (identity_id,)).fetchone()
            if row is None:
                raise IdentityError("这个身份不存在，请重新选择。")
            return dict(row)

    def identities(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM identities ORDER BY created_at,id")]

    def save_identity(self, name, description="", region="CN", identity_id=None):
        name, description = name.strip(), description.strip()
        if not 1 <= len(name) <= 24 or any(ord(c) < 32 for c in name) or len(description) > 240:
            raise IdentityError("身份名称请填写 1–24 个字，用途不超过 240 个字。")
        if region not in {"CN", "international", "custom"}:
            raise IdentityError("请选择身份的使用范围。")
        if identity_id is not None:
            self.identity(identity_id)
        new = identity_id is None
        identity_id = identity_id or "id_" + uuid.uuid4().hex
        stamp = now()
        try:
            with self.connection() as db:
                if new:
                    db.execute("INSERT INTO identities VALUES(?,?,?,?,?,?)", (identity_id, name, description, region, stamp, stamp))
                    db.execute("INSERT INTO identity_conversations VALUES(?,?)", (identity_id, "wearing-personal-" + uuid.uuid4().hex))
                else:
                    db.execute("UPDATE identities SET name=?,description=?,region=?,updated_at=? WHERE id=?", (name, description, region, stamp, identity_id))
        except sqlite3.IntegrityError as error:
            raise IdentityError("已经有一个同名身份，换个容易区分的名字吧。") from error
        return self.identity(identity_id)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _decode(self, row):
        if row is None:
            return None
        item = dict(row)
        for field in ("payload", "usage", "approval", "research"):
            if item.get(field):
                item[field] = json.loads(item[field])
        return item

    def create(self, prompt, target, identity_id=DEFAULT_IDENTITY, *, owner_scope=None):
        self.identity(identity_id)
        task_id = uuid.uuid4().hex
        stamp = now()
        with self.connection() as db:
            db.execute("INSERT INTO tasks(id,title,prompt,target,status,session_id,created_at,updated_at,identity_id) VALUES(?,?,?,?,?,?,?,?,?)",
                       (task_id, prompt[:64], prompt, target, "draft", "wearing-" + task_id, stamp, stamp, identity_id))
            if owner_scope is not None:
                self.bind_task_principal(db, task_id, owner_scope)
            db.execute("INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)", (task_id, "created", "事情已记下，等待开始。", stamp))
        return self.get(task_id)

    def get(self, task_id):
        with self.connection() as db:
            return self._decode(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def list(self, identity_id=None):
        with self.connection() as db:
            query = "SELECT * FROM tasks" + (" WHERE identity_id=?" if identity_id is not None else "") + " ORDER BY created_at DESC"
            return [self._decode(row) for row in db.execute(query, (identity_id,) if identity_id is not None else ())]

    def update(self, task_id, **fields):
        allowed = {"status", "output", "error", "run_id", "attempt", "session_id", "payload", "idempotency_key", "usage", "approval", "verification_note", "verified_at", "research"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("Unsupported task update")
        current = self.get(task_id)
        if current and all(current.get(key) == value for key, value in fields.items()):
            return current
        data = {key: json.dumps(value, ensure_ascii=False) if key in {"payload", "usage", "approval", "research"} and value is not None else value for key, value in fields.items()}
        data["updated_at"] = now()
        with self.connection() as db:
            db.execute("UPDATE tasks SET " + ",".join(f"{key}=?" for key in data) + " WHERE id=?", (*data.values(), task_id))
        return self.get(task_id)

    def reserve_start(self, task_id, payload, key, active_states, *, source_generation=None):
        """Atomic admission also prevents two app workers sending the same draft."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None or task[0] != "draft":
                return False
            marks = ",".join("?" for _ in active_states)
            if db.execute(f"SELECT 1 FROM tasks WHERE status IN ({marks}) LIMIT 1", tuple(active_states)).fetchone():
                return False
            principal = db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (task_id,)).fetchone()
            if source_generation is not None:
                from .conversation_sources import generation
                identity = db.execute('SELECT identity_id FROM tasks WHERE id=?', (task_id,)).fetchone()[0]
                if generation(db, identity, principal[0] if principal else 'local') != source_generation:
                    return False  # Context assembled before a source boundary must be rebuilt.
            if principal and db.execute('SELECT 1 FROM messages WHERE task_id=?', (task_id,)).fetchone():
                identity = db.execute('SELECT identity_id FROM tasks WHERE id=?', (task_id,)).fetchone()[0]
                session = self._owner_session(db, identity, principal[0])
                # Admission rebinds old queued rows too. Never resume a legacy
                # shared engine session merely because the task has a principal.
                payload['session_id'] = session
                db.execute('UPDATE tasks SET session_id=? WHERE id=?', (session, task_id))
                db.execute('INSERT INTO task_conversation_sessions VALUES(?,?,?,?)', (task_id, identity, principal[0], session))
            from .conversation_sources import generation, stamp_admission
            identity = db.execute('SELECT identity_id FROM tasks WHERE id=?', (task_id,)).fetchone()[0]
            source_owner = principal[0] if principal else 'local'
            source_revision = generation(db, identity, source_owner)
            if source_revision and principal is None:
                return False  # Never adopt an unowned legacy context after a source boundary.
            if source_revision and not db.execute('SELECT 1 FROM messages WHERE task_id=?', (task_id,)).fetchone():
                # Goals may reuse a session across rounds. After a source boundary
                # every standalone task starts fresh; saved reports remain explicit.
                payload['session_id'] = f'wearing-task-{task_id}-g{source_revision}'
                db.execute('UPDATE tasks SET session_id=? WHERE id=?', (payload['session_id'], task_id))
            stamp_admission(db, task_id, identity, source_owner, payload.get('session_id'))
            db.execute("UPDATE tasks SET status='starting',payload=?,idempotency_key=?,attempt=1,error=NULL,updated_at=? WHERE id=?",
                       (json.dumps(payload, ensure_ascii=False), key, now(), task_id))
            db.execute("UPDATE message_handoffs SET state='dispatched',blocked_reason=NULL,next_retry=NULL,updated_at=? WHERE task_id=?", (now(), task_id))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='goal_messages'").fetchone():
                db.execute("UPDATE goal_messages SET queued=0,next_retry=NULL WHERE task_id=?", (task_id,))
        return True

    def event(self, task_id, kind, message):
        with self.connection() as db:
            db.execute("INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)", (task_id, kind, message, now()))

    def events(self, task_id):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,))]

    def setting(self, key, default=None):
        with self.connection() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def conversation(self, identity_id=DEFAULT_IDENTITY):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT m.* FROM messages m JOIN tasks t ON t.id=m.task_id WHERE t.identity_id=? ORDER BY m.id", (identity_id,))]

    def create_message(self, content, identity_id=DEFAULT_IDENTITY):
        self.identity(identity_id)
        with self.connection() as db:
            task_id = self.insert_message(db, content, identity_id)
        return self.get(task_id)

    @staticmethod
    def bind_task_principal(db, task_id, owner_scope):
        """Trusted admission only; call inside the transaction creating the task."""
        if owner_scope != "local" and (not isinstance(owner_scope, str) or not re.fullmatch(r"[a-f0-9]{64}", owner_scope)):
            raise MessageConflict("这次任务的账户授权无法核对。")
        if not db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
            raise MessageConflict("这次任务尚未创建。")
        prior = db.execute("SELECT owner_scope FROM task_principals WHERE task_id=?", (task_id,)).fetchone()
        if prior and prior[0] != owner_scope:
            raise MessageConflict("这次任务已经属于另一账户，不能更换授权。")
        db.execute("INSERT OR IGNORE INTO task_principals(task_id,owner_scope) VALUES(?,?)", (task_id, owner_scope))
        if db.execute('SELECT 1 FROM messages WHERE task_id=?', (task_id,)).fetchone():
            identity = db.execute('SELECT identity_id FROM tasks WHERE id=?', (task_id,)).fetchone()[0]
            session = Store._owner_session(db, identity, owner_scope)
            db.execute("UPDATE tasks SET session_id=? WHERE id=? AND status='draft'", (session, task_id))

    @staticmethod
    def _owner_session(db, identity, owner_scope):
        db.execute('INSERT OR IGNORE INTO owner_conversations VALUES(?,?,?)',
                   (identity, owner_scope, 'wearing-personal-' + uuid.uuid4().hex))
        return db.execute('SELECT session_id FROM owner_conversations WHERE identity_id=? AND owner_scope=?',
                          (identity, owner_scope)).fetchone()[0]

    def accept_message(self, content, identity_id, request_id, active_states, owner_scope=None):
        """Only a fresh user submission may acquire a durable queue receipt.

        Old draft rows are deliberately not migrated into this table. Reserving
        the request and creating its message is one transaction, even across
        server processes; a retry can only retrieve the original task.
        """
        self.identity(identity_id)
        if owner_scope is not None and owner_scope != "local" and (not isinstance(owner_scope, str) or not re.fullmatch(r"[a-f0-9]{64}", owner_scope)):
            raise MessageConflict("这次消息的账户授权无法核对，请重新登录。")
        fingerprint = hashlib.sha256(content.encode()).hexdigest()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT task_id,fingerprint FROM message_handoffs WHERE identity_id=? AND request_id=?",
                               (identity_id, request_id)).fetchone() if request_id else None
            if prior:
                principal = db.execute("SELECT owner_scope FROM task_principals WHERE task_id=?", (prior["task_id"],)).fetchone()
                if (principal[0] if principal else None) != owner_scope:
                    raise MessageConflict("这次提交标识不属于当前账户，请重新提交新的消息。")
                if prior["fingerprint"] != fingerprint:
                    raise MessageConflict("这次提交标识已用于另一段内容，请重新提交新的消息。")
                task_id, created = prior["task_id"], False
            else:
                marks = ",".join("?" for _ in active_states)
                busy = bool(db.execute(f"SELECT 1 FROM tasks WHERE status IN ({marks}) LIMIT 1", tuple(active_states)).fetchone())
                queued = busy or bool(self._queued_messages(db))
                task_id, created = self.insert_message(db, content, identity_id), True
                if owner_scope is not None:
                    self.bind_task_principal(db, task_id, owner_scope)
                stamp = now()
                db.execute("INSERT INTO message_handoffs VALUES(?,?,?,?,?,?,NULL,?,?)",
                           (task_id, identity_id, request_id, fingerprint, "queued" if queued else "saved",
                            "等待前面的运行结束或完成核对。" if queued else None, stamp, stamp))
                if queued:
                    db.execute("INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)",
                               (task_id, "message_queued", "已接收排队，尚未开始执行；可以在交接前撤回。", stamp))
        return self.get(task_id), created

    @staticmethod
    def _queued_messages(db):
        rows = [dict(row) for row in db.execute("""SELECT m.id,m.task_id,t.identity_id,h.next_retry
            FROM messages m JOIN tasks t ON t.id=m.task_id JOIN message_handoffs h ON h.task_id=t.id
            WHERE t.status='draft' AND h.state IN ('queued','blocked')""")]
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='goal_messages'").fetchone():
            rows += [dict(row) for row in db.execute("""SELECT m.id,m.task_id,t.identity_id,g.next_retry
                FROM messages m JOIN tasks t ON t.id=m.task_id JOIN goal_messages g ON g.task_id=t.id
                WHERE t.status='draft' AND g.queued=1 AND NOT EXISTS
                    (SELECT 1 FROM message_handoffs h WHERE h.task_id=t.id)""")]
        return sorted(rows, key=lambda row: row["id"])

    def queued_messages(self):
        with self.connection() as db:
            return self._queued_messages(db)

    def next_queued_message(self):
        # Preserve order within each identity; an offline identity does not keep
        # another identity's accepted work behind its retry delay.
        visited = set()
        for row in self.queued_messages():
            if row["identity_id"] in visited:
                continue
            visited.add(row["identity_id"])
            if not row["next_retry"] or row["next_retry"] <= now():
                return row
        return None

    def message_receipt(self, task_id):
        with self.connection() as db:
            return self._message_receipt(db, task_id)

    @staticmethod
    def _message_receipt(db, task_id):
        task = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        handoff = db.execute("SELECT * FROM message_handoffs WHERE task_id=?", (task_id,)).fetchone()
        if handoff:
            queued = bool(task and task[0] == "draft" and handoff["state"] in {"queued", "blocked"})
            state = handoff["state"] if handoff["state"] != "saved" else None
            return {"queued": queued, "queue_state": state, "blocked_reason": handoff["blocked_reason"] if task and task[0] == 'draft' else None}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='goal_messages'").fetchone():
            linked = db.execute("SELECT queued FROM goal_messages WHERE task_id=?", (task_id,)).fetchone()
            if task and task[0] == "draft" and linked and linked[0]:
                return {"queued": True, "queue_state": "queued", "blocked_reason": "等待前面的运行结束或完成核对。"}
        return {"queued": False, "queue_state": None, "blocked_reason": None}

    def queue_if_busy(self, task_id, active_states):
        """Close admission races without admitting a legacy or replayed draft."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            marks = ",".join("?" for _ in active_states)
            busy = db.execute(f"SELECT 1 FROM tasks WHERE status IN ({marks}) LIMIT 1", tuple(active_states)).fetchone()
            if busy:
                db.execute("""UPDATE message_handoffs SET state='queued',blocked_reason=?,updated_at=?
                    WHERE task_id=? AND state='saved' AND EXISTS(SELECT 1 FROM tasks WHERE id=? AND status='draft')""",
                           ("等待前面的运行结束或完成核对。", now(), task_id, task_id))

    def retain_message_rejection(self, task_id, reason):
        """Remember why a saved message did not start; never enroll it in a queue."""
        with self.connection() as db:
            db.execute("""UPDATE message_handoffs SET blocked_reason=?,updated_at=?
              WHERE task_id=? AND state='saved' AND EXISTS(SELECT 1 FROM tasks
                WHERE id=? AND status='draft' AND run_id IS NULL AND payload IS NULL AND idempotency_key IS NULL)""",
                       (str(reason)[:400], now(), task_id, task_id))

    def defer_message(self, task_id, reason, retry_at):
        with self.connection() as db:
            db.execute("""UPDATE message_handoffs SET state='blocked',blocked_reason=?,next_retry=?,updated_at=?
                WHERE task_id=? AND state IN ('queued','blocked') AND EXISTS(SELECT 1 FROM tasks WHERE id=? AND status='draft')""",
                       (str(reason)[:400], retry_at, now(), task_id, task_id))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='goal_messages'").fetchone():
                db.execute("UPDATE goal_messages SET next_retry=? WHERE task_id=? AND queued=1", (retry_at, task_id))

    def insert_message(self, db, content, identity_id):
        """Participate in a caller's transaction when a message changes a goal."""
        task_id, stamp = uuid.uuid4().hex, now()
        session_id = db.execute("SELECT session_id FROM identity_conversations WHERE identity_id=?", (identity_id,)).fetchone()[0]
        db.execute("INSERT INTO tasks(id,title,prompt,target,status,session_id,created_at,updated_at,identity_id) VALUES(?,?,?,?,?,?,?,?,?)",
                   (task_id, content[:64], content, "computer", "draft", session_id, stamp, stamp, identity_id))
        db.execute("INSERT INTO messages(content,task_id,created_at) VALUES(?,?,?)", (content, task_id, stamp))
        db.execute("INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)", (task_id, "created", "这条消息已保存。", stamp))
        return task_id

    def sync_conversation_session(self, task_id, session_id):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM messages WHERE task_id=?", (task_id,)).fetchone():
                identity_id = db.execute("SELECT identity_id FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
                principal = db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (task_id,)).fetchone()
                if principal:
                    from .conversation_sources import current_generation
                    if not current_generation(db, task_id, identity_id, principal[0]):
                        return  # A source-control boundary invalidates late run receipts.
                    admitted = db.execute('SELECT * FROM task_conversation_sessions WHERE task_id=?', (task_id,)).fetchone()
                    canonical = self._owner_session(db, identity_id, principal[0])
                    if (not admitted or admitted['identity_id'] != identity_id or admitted['owner_scope'] != principal[0]
                            or admitted['session_id'] != canonical):
                        return  # Pre-upgrade/foreign history is never adopted.
                    db.execute('UPDATE owner_conversations SET session_id=? WHERE identity_id=? AND owner_scope=?', (session_id, identity_id, principal[0]))
                    db.execute('UPDATE task_conversation_sessions SET session_id=? WHERE task_id=?', (session_id, task_id))
                    db.execute("""UPDATE tasks SET session_id=? WHERE status='draft' AND identity_id=?
                        AND id IN (SELECT task_id FROM messages) AND id IN
                        (SELECT task_id FROM task_principals WHERE owner_scope=?)""", (session_id, identity_id, principal[0]))
                else:
                    db.execute("UPDATE identity_conversations SET session_id=? WHERE identity_id=?", (session_id, identity_id))
                    db.execute("""UPDATE tasks SET session_id=? WHERE status='draft' AND identity_id=?
                        AND id IN (SELECT task_id FROM messages) AND id NOT IN (SELECT task_id FROM task_principals)""", (session_id, identity_id))

    def is_conversation_task(self, task_id):
        with self.connection() as db:
            return db.execute("SELECT 1 FROM messages WHERE task_id=?", (task_id,)).fetchone() is not None

    def set_setting(self, key, value):
        with self.connection() as db:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))
