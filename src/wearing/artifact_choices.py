"""Explicit result selections become one durable, context-bound conversation message.

Untrusted HTML has no transport bridge. Only product UI submits a published option,
after showing its complete instruction. This records a request, never a tool permit.
"""
import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field

from .artifacts import ArtifactError
from .service import ACTIVE
from .store import now


class ChoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{16,100}$")
    choice_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    artifact_revision: int = Field(ge=1)
    selection_revision: int = Field(ge=0)


class ArtifactChoices:
    def __init__(self, book):
        self.book, self.store = book, book.store
        with self.store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS artifact_selections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    identity_id TEXT NOT NULL, owner_scope TEXT NOT NULL,
                    artifact_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    choice_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    source_task_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(identity_id,owner_scope,request_key),
                    UNIQUE(identity_id,owner_scope,artifact_id,revision)
                );
            """)

    @staticmethod
    def owner(value):
        if value != "local" and (not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)):
            raise ArtifactError("请重新登录后继续处理结果。", 401)
        return value

    def _artifact(self, db, identity, artifact_id, owner_scope):
        from .task_visibility import visible, predicate
        row = db.execute("SELECT * FROM artifacts WHERE identity_id=? AND id=?", (identity, artifact_id)).fetchone()
        if not row or not visible(db, identity, row['task_id'], owner_scope):
            raise ArtifactError("当前身份中没有这个结果。", 404)
        if hashlib.sha256(bytes(row["html"])).hexdigest() != row["sha256"]:
            raise ArtifactError("结果文件校验未通过，请重新整理。")
        item = json.loads(row["metadata"])
        newer = db.execute(f"SELECT a.id FROM artifacts a WHERE a.previous_id=:artifact AND {predicate('a.task_id')}",
                           {'artifact': artifact_id, 'task_owner': owner_scope}).fetchone()
        return item, newer[0] if newer else None

    def _receipt(self, db, row):
        task = db.execute("SELECT status FROM tasks WHERE id=? AND identity_id=?", (row["task_id"], row["identity_id"])).fetchone()
        handoff = db.execute("SELECT state FROM message_handoffs WHERE task_id=?", (row["task_id"],)).fetchone()
        if not task or not handoff:
            raise ArtifactError("后续任务的回执不完整，请稍后重新读取。")
        return {key: row[key] for key in ("artifact_id", "revision", "request_key", "choice_id", "task_id", "source_task_id", "created_at")} | {
            "task_status": task[0], "queue_state": handoff[0],
        }

    def state(self, identity, artifact_id, owner_scope="local"):
        owner = self.owner(owner_scope)
        with self.store.connection() as db:
            item, newer = self._artifact(db, identity, artifact_id, owner)
            row = db.execute("""SELECT * FROM artifact_selections WHERE identity_id=? AND owner_scope=?
                AND artifact_id=? ORDER BY revision DESC LIMIT 1""", (identity, owner, artifact_id)).fetchone()
            return {"artifact_id": artifact_id, "artifact_revision": item["revision"], "revision": row["revision"] if row else 0,
                    "newer_id": newer, "choices": item.get("choices", []), "selection": self._receipt(db, row) if row else None}

    def select(self, identity, artifact_id, body: ChoiceRequest, owner_scope="local"):
        owner = self.owner(owner_scope)
        self.store.identity(identity)
        fingerprint = hashlib.sha256((artifact_id + "\n" + body.model_dump_json(exclude={"request_key"})).encode()).hexdigest()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            item, newer = self._artifact(db, identity, artifact_id, owner)
            prior = db.execute("SELECT * FROM artifact_selections WHERE identity_id=? AND owner_scope=? AND request_key=?",
                               (identity, owner, body.request_key)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise ArtifactError("这个提交编号已用于另一项选择，请先查看原回执。")
                return self._receipt(db, prior)
            if newer or body.artifact_revision != item["revision"]:
                raise ArtifactError("这份结果已有新版本，请打开新版再选择。")
            latest = db.execute("""SELECT * FROM artifact_selections WHERE identity_id=? AND owner_scope=?
                AND artifact_id=? ORDER BY revision DESC LIMIT 1""", (identity, owner, artifact_id)).fetchone()
            if body.selection_revision != (latest["revision"] if latest else 0):
                raise ArtifactError("选择状态已变化，请重新读取回执，避免重复交代。")
            if latest:
                status = db.execute("SELECT status FROM tasks WHERE id=?", (latest["task_id"],)).fetchone()
                if not status or status[0] in ACTIVE or status[0] == "draft":
                    raise ArtifactError("上一项选择还在等待或执行，请先查看对应任务。")
            source = db.execute("SELECT status FROM tasks WHERE id=? AND identity_id=?", (item["task_id"], identity)).fetchone()
            if not source or source[0] in ACTIVE or source[0] == "draft":
                raise ArtifactError("原任务还在执行或等待核对，结束后再继续这份结果。")
            choice = next((c for c in item.get("choices", []) if c["id"] == body.choice_id), None)
            if not choice:
                raise ArtifactError("这份结果没有这个选项，请重新读取。", 422)
            # Native capability permission stays tied to the authenticated account.
            # A missing owner mapping never borrows another user's phone policy.
            prompt = (f'继续处理《{item["title"]}》第 {item["revision"]} 版。\n'
                      f'原任务：{item["task_id"]}\n结果编号：{artifact_id}\n'
                      f'我选择：{choice["label"]}\n接下来：{choice["instruction"]}\n\n'
                      '请先读取这份原结果和当前状态，再继续处理。这个选择不代表付款、外发、'
                      '删除或设备操作的额外授权；仍按本次任务已有权限和必要的实际确认执行。')
            task_id = self.store.insert_message(db, prompt, identity)
            # Execution context belongs to the model prompt, not the person's
            # chat bubble or compact task title.
            display = f'关于《{item["title"]}》，我选择“{choice["label"]}”。\n{choice["instruction"]}'
            db.execute("UPDATE messages SET content=? WHERE task_id=?", (display, task_id))
            db.execute("UPDATE tasks SET title=? WHERE id=?", (f'{choice["label"]} · {item["title"]}'[:64], task_id))
            self.store.bind_task_principal(db, task_id, owner)
            stamp, revision = now(), body.selection_revision + 1
            db.execute("INSERT INTO message_handoffs VALUES(?,?,?,?,?,?,NULL,?,?)",
                       (task_id, identity, "result_" + task_id, hashlib.sha256(prompt.encode()).hexdigest(), "queued", None, stamp, stamp))
            db.execute("INSERT INTO events(task_id,kind,message,created_at) VALUES(?,?,?,?)",
                       (task_id, "artifact_choice", f'已接收结果选择：{choice["label"]}。等待继续处理。', stamp))
            db.execute("""INSERT INTO artifact_selections(identity_id,owner_scope,artifact_id,revision,request_key,
                fingerprint,choice_id,task_id,source_task_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (identity, owner, artifact_id, revision, body.request_key, fingerprint, body.choice_id, task_id, item["task_id"], stamp))
            row = db.execute("SELECT * FROM artifact_selections WHERE task_id=?", (task_id,)).fetchone()
            return self._receipt(db, row)
