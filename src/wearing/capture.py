"""Private originals, durable capture jobs and revision-fenced organization."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from .config import private_directory
from .life import LifeBook, LifeDraft, LifeError
from .store import now

MAX_ASSET_BYTES = 15 * 1024 * 1024
ASSET_ID = re.compile(r"^asset_[0-9a-f]{32}$")
JOB_STATES = {"queued", "extracting", "organizing", "done", "failed", "conflict", "paused", "saved"}


class CaptureDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record: LifeDraft
    asset_ids: list[str] = Field(default_factory=list, max_length=4)
    request_key: str = Field(min_length=1, max_length=120)
    organize: bool = True


class OrganizedNote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=12000)


def media_type(data, claimed):
    claimed = claimed.split(";", 1)[0].lower()
    if claimed.startswith("image/"):
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 24_000_000:
                    raise LifeError("图片过大，请选一张不超过 2400 万像素的图片。", 413)
                kind = image.format
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
            raise LifeError("这张图片无法读取，请使用 JPEG、PNG 或 WebP。", 422) from error
        types = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp")}
        if kind not in types:
            raise LifeError("当前支持 JPEG、PNG 和 WebP 图片。", 422)
        return types[kind]
    if claimed.startswith("audio/") or claimed == "video/webm":
        if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            return "audio/wav", ".wav"
        if data.startswith(b"\x1aE\xdf\xa3"):
            return "audio/webm", ".webm"
        if data.startswith(b"OggS"):
            return "audio/ogg", ".ogg"
        if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224):
            return "audio/mpeg", ".mp3"
        if data[4:8] == b"ftyp":
            return "audio/mp4", ".m4a"
    raise LifeError("文件类型无法确认，请选择图片或常用格式的录音。", 422)


class CaptureBook:
    def __init__(self, life: LifeBook):
        self.life, self.store = life, life.store
        self.root = self.store.path.parent / "media"
        if self.root.is_symlink():
            raise LifeError("原件目录不可使用符号链接。", 422)
        private_directory(self.root)
        with self.store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS life_assets (
                    id TEXT PRIMARY KEY, identity_id TEXT NOT NULL REFERENCES identities(id),
                    name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, digest TEXT NOT NULL,
                    suffix TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(identity_id,request_key));
                CREATE TABLE IF NOT EXISTS life_captures (
                    id TEXT PRIMARY KEY, identity_id TEXT NOT NULL, record_id TEXT NOT NULL UNIQUE,
                    original_text TEXT NOT NULL, asset_ids TEXT NOT NULL, expected_revision INTEGER NOT NULL,
                    state TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 1,
                    extracted TEXT NOT NULL DEFAULT '[]', proposal TEXT, error TEXT,
                    request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(identity_id,request_key));
                CREATE INDEX IF NOT EXISTS capture_queue ON life_captures(state,created_at);
                CREATE TABLE IF NOT EXISTS voice_transcripts (
                    asset_id TEXT PRIMARY KEY REFERENCES life_assets(id),
                    identity_id TEXT NOT NULL, text TEXT NOT NULL);
            """)

    def transcript(self, identity, asset_id):
        self.asset(identity, asset_id)
        with self.store.connection() as db:
            row = db.execute("SELECT text FROM voice_transcripts WHERE asset_id=? AND identity_id=?", (asset_id, identity)).fetchone()
        return row['text'] if row else None

    def save_transcript(self, identity, asset_id, text):
        self.asset(identity, asset_id)
        with self.store.connection() as db:
            db.execute("INSERT OR IGNORE INTO voice_transcripts VALUES(?,?,?)", (asset_id, identity, text))
        return self.transcript(identity, asset_id)

    def asset(self, identity, asset_id):
        if not ASSET_ID.fullmatch(asset_id):
            raise LifeError("没有找到这份原件。", 404)
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM life_assets WHERE identity_id=? AND id=?", (identity, asset_id)).fetchone()
        if row is None:
            raise LifeError("当前身份没有这份原件。", 404)
        return dict(row)

    def file(self, identity, asset_id):
        asset = self.asset(identity, asset_id)
        path = self.root / (asset_id + asset["suffix"])
        if self.root.is_symlink() or path.is_symlink() or not path.is_file():
            raise LifeError("原件暂时无法读取。", 404)
        return path, asset

    def upload(self, identity, data, name, claimed, request_key):
        self.store.identity(identity)
        if not data or len(data) > MAX_ASSET_BYTES:
            raise LifeError("文件为空或超过 15 MB，请换一份较小的原件。", 413)
        if not request_key or len(request_key) > 120:
            raise LifeError("上传标识无效，请重试。", 422)
        name = Path(name.replace("\\", "/")).name[:180] or "原件"
        name = "".join(c for c in name if ord(c) >= 32)
        mime, suffix = media_type(data, claimed)
        digest = hashlib.sha256(data).hexdigest()
        fingerprint = hashlib.sha256(json.dumps([digest, name, mime]).encode()).hexdigest()
        asset_id = "asset_" + uuid.uuid4().hex
        target = self.root / (asset_id + suffix)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM life_assets WHERE identity_id=? AND request_key=?", (identity, request_key)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise LifeError("这次上传内容已变化，请重新选择文件。")
                return self.public_asset(dict(previous))
            if self.root.is_symlink():
                raise LifeError("原件目录已变化，请检查后重试。", 422)
            fd, temporary = tempfile.mkstemp(prefix="upload-", dir=self.root)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                Path(temporary).replace(target)
                db.execute("INSERT INTO life_assets VALUES(?,?,?,?,?,?,?,?,?,?)", (asset_id, identity, name, mime, len(data), digest, suffix, request_key, fingerprint, now()))
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                target.unlink(missing_ok=True)
                raise
        return self.public_asset(self.asset(identity, asset_id))

    @staticmethod
    def public_asset(asset):
        return {k: asset[k] for k in ("id", "name", "mime", "size", "digest")}

    def create(self, identity, draft: CaptureDraft):
        self.store.identity(identity)
        if len(set(draft.asset_ids)) != len(draft.asset_ids):
            raise LifeError("同一份原件不用重复添加。", 422)
        for asset_id in draft.asset_ids:
            self.asset(identity, asset_id)
        fingerprint = hashlib.sha256(draft.model_dump_json(exclude={"request_key"}).encode()).hexdigest()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM life_captures WHERE identity_id=? AND request_key=?", (identity, draft.request_key)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise LifeError("保存内容已经变化，请重新保存。")
                return self.row(previous)
            if draft.organize and db.execute("SELECT count(*) FROM life_captures WHERE state IN ('queued','extracting','organizing')").fetchone()[0] >= 20:
                raise LifeError("正在整理的记录较多，可以取消整理先保存，或稍后再试。", 429)
            record_id, capture_id = "life_" + uuid.uuid4().hex, "capture_" + uuid.uuid4().hex
            body, stamp = draft.record.model_dump_json(), now()
            db.execute("INSERT INTO life_records VALUES(?,?,?,?,?,?,?,?,?)", (record_id, identity, 1, body, None, stamp, stamp, "capture:"+capture_id, hashlib.sha256(body.encode()).hexdigest()))
            db.execute("INSERT INTO life_captures(id,identity_id,record_id,original_text,asset_ids,expected_revision,state,request_key,fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (capture_id, identity, record_id, draft.record.content, json.dumps(draft.asset_ids), 1, "queued" if draft.organize else "saved", draft.request_key, fingerprint, stamp, stamp))
            record = self.life.unpack(db.execute("SELECT * FROM life_records WHERE id=?", (record_id,)).fetchone())
            self.life.receipt(db, record, "user")
            return self.row(db.execute("SELECT * FROM life_captures WHERE id=?", (capture_id,)).fetchone())

    @staticmethod
    def row(row):
        return {**dict(row), "asset_ids": json.loads(row["asset_ids"]), "extracted": json.loads(row["extracted"]),
                "proposal": json.loads(row["proposal"]) if row["proposal"] else None}

    def get(self, identity, capture_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM life_captures WHERE identity_id=? AND id=?", (identity, capture_id)).fetchone()
        if row is None:
            raise LifeError("当前身份没有这条随手记录。", 404)
        return self.row(row)

    def claim(self):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM life_captures WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE life_captures SET state='extracting',error=NULL,updated_at=? WHERE id=?", (now(),row["id"]))
            self._notify(db, row["record_id"])
            result = self.row(row); result["state"] = "extracting"
            return result

    def _notify(self, db, record_id):
        record = self.life.unpack(db.execute("SELECT * FROM life_records WHERE id=?", (record_id,)).fetchone())
        self.life.receipt(db, record, "agent")

    def state(self, job, state, *, extracted=None, error=None):
        assert state in JOB_STATES
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM life_captures WHERE id=?", (job["id"],)).fetchone()
            if row["generation"] != job["generation"]:
                return False
            db.execute("UPDATE life_captures SET state=?,extracted=?,error=?,updated_at=? WHERE id=?", (state, json.dumps(extracted,ensure_ascii=False) if extracted is not None else row["extracted"], error, now(),job["id"]))
            self._notify(db,row["record_id"])
        return True

    def apply(self, job, proposal: OrganizedNote):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current_job = db.execute("SELECT * FROM life_captures WHERE id=?", (job["id"],)).fetchone()
            if current_job["generation"] != job["generation"] or current_job["state"] not in {"extracting", "organizing"}:
                return False
            row = db.execute("SELECT * FROM life_records WHERE id=? AND identity_id=?", (job["record_id"],job["identity_id"])).fetchone()
            conflict = row["revision"] != job["expected_revision"] or bool(row["deleted_at"])
            if not conflict:
                record = LifeDraft.model_validate({**json.loads(row["body"]), **proposal.model_dump()})
                db.execute("UPDATE life_records SET body=?,revision=revision+1,updated_at=? WHERE id=?", (record.model_dump_json(),now(),row["id"]))
            db.execute("UPDATE life_captures SET state=?,proposal=?,error=NULL,updated_at=? WHERE id=?", ("conflict" if conflict else "done",proposal.model_dump_json(),now(),job["id"]))
            self._notify(db,row["id"])
            return not conflict

    def retry(self, identity, capture_id):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM life_captures WHERE identity_id=? AND id=?", (identity,capture_id)).fetchone()
            if row is None:
                raise LifeError("当前身份没有这条记录。",404)
            if row["state"] in {"queued","extracting","organizing"}:
                return self.row(row)
            if row["generation"] >= 3:
                raise LifeError("已经尝试三次。原件仍在，可以先手动编辑。")
            record = db.execute("SELECT * FROM life_records WHERE id=?",(row["record_id"],)).fetchone()
            if record["deleted_at"]:
                raise LifeError("记录已移除，请先恢复。")
            db.execute("UPDATE life_captures SET state='queued',generation=generation+1,expected_revision=?,error=NULL,updated_at=? WHERE id=?",(record["revision"],now(),capture_id))
            self._notify(db,row["record_id"])
            return self.row(db.execute("SELECT * FROM life_captures WHERE id=?", (capture_id,)).fetchone())

    def recover(self):
        # An interrupted paid call is never silently submitted again.
        with self.store.connection() as db:
            rows=db.execute("SELECT * FROM life_captures WHERE state IN ('extracting','organizing')").fetchall()
            for row in rows:
                db.execute("UPDATE life_captures SET state='paused',error=?,updated_at=? WHERE id=?",("整理中断了，原件已经保存。可以重新整理。",now(),row["id"]))
                self._notify(db,row["record_id"])
