"""Wearing records task truth separately from Hermes sessions and model runs."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import private_directory

DEFAULT_IDENTITY = "daily"


class IdentityError(ValueError):
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
        for field in ("payload", "usage", "approval"):
            if item.get(field):
                item[field] = json.loads(item[field])
        return item

    def create(self, prompt, target, identity_id=DEFAULT_IDENTITY):
        self.identity(identity_id)
        task_id = uuid.uuid4().hex
        stamp = now()
        with self.connection() as db:
            db.execute("INSERT INTO tasks(id,title,prompt,target,status,session_id,created_at,updated_at,identity_id) VALUES(?,?,?,?,?,?,?,?,?)",
                       (task_id, prompt[:64], prompt, target, "draft", "wearing-" + task_id, stamp, stamp, identity_id))
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
        allowed = {"status", "output", "error", "run_id", "attempt", "session_id", "payload", "idempotency_key", "usage", "approval", "verification_note", "verified_at"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("Unsupported task update")
        current = self.get(task_id)
        if current and all(current.get(key) == value for key, value in fields.items()):
            return current
        data = {key: json.dumps(value, ensure_ascii=False) if key in {"payload", "usage", "approval"} and value is not None else value for key, value in fields.items()}
        data["updated_at"] = now()
        with self.connection() as db:
            db.execute("UPDATE tasks SET " + ",".join(f"{key}=?" for key in data) + " WHERE id=?", (*data.values(), task_id))
        return self.get(task_id)

    def reserve_start(self, task_id, payload, key, active_states):
        """Atomic admission also prevents two app workers sending the same draft."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None or task[0] != "draft":
                return False
            marks = ",".join("?" for _ in active_states)
            if db.execute(f"SELECT 1 FROM tasks WHERE status IN ({marks}) LIMIT 1", tuple(active_states)).fetchone():
                return False
            db.execute("UPDATE tasks SET status='starting',payload=?,idempotency_key=?,attempt=1,error=NULL,updated_at=? WHERE id=?",
                       (json.dumps(payload, ensure_ascii=False), key, now(), task_id))
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
            if db.execute("SELECT 1 FROM messages WHERE task_id=?", (task_id,)).fetchone():
                identity_id = db.execute("SELECT identity_id FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
                db.execute("UPDATE identity_conversations SET session_id=? WHERE identity_id=?", (session_id, identity_id))
                # Messages saved during an earlier run must resume its canonical
                # session too, rather than the pre-response local session ID.
                db.execute("UPDATE tasks SET session_id=? WHERE status='draft' AND identity_id=? AND id IN (SELECT task_id FROM messages)", (session_id, identity_id))

    def is_conversation_task(self, task_id):
        with self.connection() as db:
            return db.execute("SELECT 1 FROM messages WHERE task_id=?", (task_id,)).fetchone() is not None

    def set_setting(self, key, value):
        with self.connection() as db:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))
