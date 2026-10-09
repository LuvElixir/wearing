"""Identity-bound, immutable HTML results. The model cannot choose ownership."""
import hashlib
import json
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .store import DEFAULT_IDENTITY, now
from .workspace import WorkspaceError, workspace_file
from .task_visibility import predicate

MAX_HTML_BYTES = 1024 * 1024


class ArtifactError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class ArtifactChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    label: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=1000)


class ArtifactDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    path: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=400)
    presentation: Literal["dashboard", "diagram", "interactive"] = "interactive"
    sources: list[str] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    previous_id: str | None = Field(default=None, max_length=40)
    choices: list[ArtifactChoice] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_choices(self):
        if len({choice.id for choice in self.choices}) != len(self.choices):
            raise ValueError("结果选项的 id 不能重复。")
        return self


class ArtifactBook:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    run_id TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    metadata TEXT NOT NULL, html BLOB NOT NULL, sha256 TEXT NOT NULL,
                    previous_id TEXT UNIQUE, created_at TEXT NOT NULL,
                    UNIQUE(identity_id, task_id, run_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS artifact_owner ON artifacts(identity_id, created_at);
            """)
            # Older results did not retain their original workspace path. Keep
            # those rows unknown; never infer ownership from a filename.
            db.execute("BEGIN IMMEDIATE")
            if "source_path" not in {row[1] for row in db.execute("PRAGMA table_info(artifacts)")}:
                db.execute("ALTER TABLE artifacts ADD COLUMN source_path TEXT")

    def workspace(self, identity):
        self.store.identity(identity)
        root = self.store.path.parent
        return (root if identity == DEFAULT_IDENTITY else root / "identities" / identity) / "workspace"

    @staticmethod
    def metadata(row):
        return json.loads(row["metadata"])

    def get(self, identity, artifact_id, *, content=False, owner_scope='local'):
        self.store.identity(identity)
        with self.store.connection() as db:
            row = db.execute(f"""SELECT a.* FROM artifacts a JOIN tasks t ON t.id=a.task_id AND t.identity_id=a.identity_id
              WHERE a.id=:artifact AND a.identity_id=:identity AND {predicate('t.id')}""",
              {'artifact': artifact_id, 'identity': identity, 'task_owner': owner_scope}).fetchone()
        if not row:
            raise ArtifactError("当前身份中没有这个结果。", 404)
        item = self.metadata(row)
        if content:
            raw = bytes(row["html"])
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ArtifactError("结果文件校验未通过，请让 Pajio 重新整理。")
            return item, raw
        return item

    def list(self, identity, task_id=None, *, owner_scope='local'):
        self.store.identity(identity)
        with self.store.connection() as db:
            if task_id:
                rows = db.execute(f"""SELECT a.metadata FROM artifacts a JOIN tasks t ON t.id=a.task_id AND t.identity_id=a.identity_id
                  WHERE a.identity_id=:identity AND a.task_id=:task AND {predicate('t.id')} ORDER BY a.created_at,a.id""",
                  {'identity': identity, 'task': task_id, 'task_owner': owner_scope}).fetchall()
            else:
                rows = db.execute(f"""SELECT a.metadata FROM artifacts a JOIN tasks t ON t.id=a.task_id AND t.identity_id=a.identity_id
                  WHERE a.identity_id=:identity AND {predicate('t.id')} ORDER BY a.created_at DESC,a.id DESC LIMIT 100""",
                  {'identity': identity, 'task_owner': owner_scope}).fetchall()
        return [self.metadata(row) for row in rows]

    def for_conversation(self, identity, *, owner_scope='local'):
        """One metadata-only query per poll; HTML blobs never enter the chat feed."""
        self.store.identity(identity)
        with self.store.connection() as db:
            rows = db.execute(f"""SELECT a.task_id,a.metadata FROM artifacts a JOIN tasks t ON t.id=a.task_id AND t.identity_id=a.identity_id
              WHERE a.identity_id=:identity AND {predicate('t.id')} ORDER BY a.created_at,a.id""",
              {'identity': identity, 'task_owner': owner_scope}).fetchall()
        grouped = {}
        for row in rows:
            grouped.setdefault(row["task_id"], []).append(self.metadata(row))
        return grouped

    def publish(self, identity, draft: ArtifactDraft, request_key: str):
        if not isinstance(request_key, str) or not 1 <= len(request_key.strip()) <= 120:
            raise ArtifactError("请提供稳定的 request_key，重试使用同一个值。", 422)
        if any(len(value) > 1200 for field in (draft.sources, draft.assumptions, draft.limitations) for value in field):
            raise ArtifactError("每条依据或说明请限制在 1200 字以内。", 422)
        root = self.workspace(identity)
        try:
            path = workspace_file(root, draft.path)
            if path.suffix.lower() not in {".html", ".htm"}:
                raise ArtifactError("当前结果视图支持自包含 HTML 文件。", 422)
            with path.open("rb") as stream:
                raw = stream.read(MAX_HTML_BYTES + 1)
        except (WorkspaceError, OSError) as error:
            raise ArtifactError("请先在当前身份的文件空间保存 HTML 文件，再发布结果。", 422) from error
        if not raw or len(raw) > MAX_HTML_BYTES:
            raise ArtifactError("结果文件不能为空，大小需在 1 MB 以内。", 422)
        try:
            html = raw.decode("utf-8-sig")
        except UnicodeError as error:
            raise ArtifactError("结果文件需要使用 UTF-8 编码。", 422) from error
        if "<html" not in html.lower() or "</html>" not in html.lower():
            raise ArtifactError("请生成包含 html 根元素的完整页面。", 422)
        sha = hashlib.sha256(raw).hexdigest()
        fingerprint = hashlib.sha256((draft.model_dump_json() + sha).encode()).hexdigest()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT id,run_id FROM tasks WHERE identity_id=? AND status='running' AND run_id IS NOT NULL", (identity,)).fetchall()
            if len(active) != 1:
                raise ArtifactError("没有唯一的正在执行的对话，不能把结果关联到本轮。")
            task = active[0]
            prior = db.execute("SELECT * FROM artifacts WHERE identity_id=? AND task_id=? AND run_id=? AND request_key=?", (identity, task["id"], task["run_id"], request_key)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise ArtifactError("这次发布已保存了不同内容，请为新版本使用新的 request_key。")
                return self.metadata(prior)
            count = db.execute("SELECT COUNT(*) FROM artifacts WHERE task_id=? AND run_id=?", (task["id"], task["run_id"])).fetchone()[0]
            if count >= 8:
                raise ArtifactError("本轮已有 8 份结果，请先向用户交付已有内容。")
            previous = None
            if draft.previous_id:
                principal = db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (task['id'],)).fetchone()
                row = db.execute(f"""SELECT a.* FROM artifacts a JOIN tasks t ON t.id=a.task_id AND t.identity_id=a.identity_id
                  WHERE a.id=:artifact AND a.identity_id=:identity AND {predicate('t.id')}""",
                  {'artifact': draft.previous_id, 'identity': identity, 'task_owner': principal[0] if principal else None}).fetchone()
                if not row:
                    raise ArtifactError("原结果不在当前身份中。", 404)
                if db.execute("SELECT 1 FROM artifacts WHERE previous_id=?", (draft.previous_id,)).fetchone():
                    raise ArtifactError("原结果已有更新版本，请先读取最新结果再修改。")
                previous = self.metadata(row)
            artifact_id, stamp = "art_" + uuid.uuid4().hex, now()
            item = {"id": artifact_id, "task_id": task["id"], "title": draft.title, "summary": draft.summary,
                    "presentation": draft.presentation, "sources": draft.sources, "assumptions": draft.assumptions,
                    "limitations": draft.limitations, "revision": previous["revision"] + 1 if previous else 1,
                    "previous_id": draft.previous_id, "family_id": previous["family_id"] if previous else artifact_id,
                    "created_at": stamp, "size": len(raw), "sha256": sha, "state": "generated",
                    "checks": {"file": "verified", "render": "not_verified", "content": "not_verified"},
                    "choices": [choice.model_dump() for choice in draft.choices]}
            db.execute("""INSERT INTO artifacts
                (id,identity_id,task_id,run_id,request_key,fingerprint,metadata,html,sha256,previous_id,created_at,source_path)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (artifact_id, identity, task["id"], task["run_id"], request_key, fingerprint,
                 json.dumps(item, ensure_ascii=False), raw, sha, draft.previous_id, stamp,
                 path.relative_to(root).as_posix()))
            return item
