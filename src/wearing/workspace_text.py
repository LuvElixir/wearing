"""Bounded user-document editing with durable recovery and identity-scoped receipts.

Imported originals are immutable: edits create documents/<request>/<filename>.
Recovery bytes are private SQLite versions, never exposed through file listings.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .service import ACTIVE
from .store import now
from .workspace import _directory_fd, _relative, WorkspacePageError

MAX_TEXT_BYTES = 64 * 1024
RESERVED = {'skills', 'skill', 'scripts', 'bin', 'node_modules', 'config', 'credentials', 'secrets', 'keys', 'hermes', 'runtime'}
ENGINE_NAMES = {'agents.md', 'agent.md', 'skill.md', 'soul.md', 'user.md', 'memory.md', 'identity.md', 'credentials.txt', 'secrets.txt', 'passwords.txt', 'tokens.txt'}


class TextEditError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def document_path(value):
    try: _relative(value)
    except WorkspacePageError as error: raise TextEditError('文档路径不正确。', 422) from error
    parts = value.split('/')
    if any(part.startswith('.') or part.casefold() in RESERVED for part in parts) or parts[-1].casefold() in ENGINE_NAMES or Path(value).suffix.lower() not in {'.md', '.markdown', '.txt'}:
        raise TextEditError('这里仅编辑普通 Markdown 和文本文档；系统、技能和凭据文件不开放编辑。', 403)
    return value


def text_bytes(text):
    try: raw = text.encode('utf-8')
    except UnicodeError as error: raise TextEditError('文档需要有效的 UTF-8 文字。', 422) from error
    if len(raw) > MAX_TEXT_BYTES: raise TextEditError('直接编辑支持不超过 64 KB 的文本文档。', 413)
    if any(ord(c) < 32 and c not in '\n\r\t' for c in text) or re.search(r'-----BEGIN (?:[A-Z ]* )?PRIVATE KEY-----', text):
        raise TextEditError('这份内容不是可编辑的普通文本文档。', 422)
    return raw


class TextSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=2048)
    text: str = Field(max_length=MAX_TEXT_BYTES)
    base_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    base_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,80}$')

    @field_validator('path')
    @classmethod
    def valid_path(cls, value): return document_path(value)

    @field_validator('text')
    @classmethod
    def valid_text(cls, value): text_bytes(value); return value


def signature(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def snapshot(path, raw, info):
    digest = hashlib.sha256(raw).hexdigest()
    revision = hashlib.sha256((json.dumps(signature(info)) + digest).encode()).hexdigest()
    try: text = raw.decode('utf-8')
    except UnicodeError as error: raise TextEditError('文档不是 UTF-8 编码，请先转换为 UTF-8。', 422) from error
    text_bytes(text)
    return {'path': path, 'text': text, 'size': len(raw), 'sha256': digest, 'revision': revision, 'modified': info.st_mtime}


@contextmanager
def parent_fd(root, path, *, create=False):
    document_path(path)
    parent, _, name = path.rpartition('/')
    # The workspace itself and its configured ancestors may not be symlinks.
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise TextEditError('文档路径不能经过符号链接。', 403)
    descriptors = []
    try:
        fd = _directory_fd(root)
        descriptors.append(fd)
        for part in parent.split('/') if parent else ():
            if create:
                try: os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError: pass
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
        yield fd, name
    finally:
        for fd in reversed(descriptors): os.close(fd)


def read_at(fd, name, path):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(handle, 'rb') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise TextEditError('只支持未链接的普通文本文档。', 403)
        if info.st_size > MAX_TEXT_BYTES: raise TextEditError('直接编辑支持不超过 64 KB 的文本文档。', 413)
        raw = file.read(MAX_TEXT_BYTES + 1)
        if signature(os.fstat(file.fileno())) != signature(info): raise TextEditError('文档正在变化，请重新读取。')
    return snapshot(path, raw, info), raw


def read_file(root, path):
    try:
        with parent_fd(root, path) as (fd, name): return read_at(fd, name, path)
    except FileNotFoundError as error: raise TextEditError('文档已移动或不存在，请刷新文件夹。', 404) from error
    except OSError as error: raise TextEditError('文档暂时无法读取，未修改文件。', 409) from error


class WorkspaceText:
    def __init__(self, store, runtime_for):
        self.store, self.runtime_for = store, runtime_for
        with store.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS workspace_text_versions (
                identity_id TEXT NOT NULL, request_key TEXT NOT NULL, spec TEXT NOT NULL,
                source_path TEXT NOT NULL, target_path TEXT NOT NULL, base_revision TEXT NOT NULL,
                old_bytes BLOB NOT NULL, new_bytes BLOB NOT NULL, created_at TEXT NOT NULL,
                receipt TEXT, PRIMARY KEY(identity_id,request_key))''')

    def root(self, identity):
        self.store.identity(identity)
        return Path(self.runtime_for(identity).workspace)

    @staticmethod
    def active(db, identity):
        return bool(db.execute('SELECT 1 FROM tasks WHERE identity_id=? AND status IN (' + ','.join('?' for _ in ACTIVE) + ') LIMIT 1', (identity, *ACTIVE)).fetchone())

    def read(self, identity, path):
        value, _ = read_file(self.root(identity), document_path(path))
        with self.store.connection() as db:
            active = self.active(db, identity)
            versions = db.execute('SELECT request_key,created_at FROM workspace_text_versions WHERE identity_id=? AND target_path=? AND receipt IS NOT NULL ORDER BY created_at DESC LIMIT 20', (identity, path)).fetchall()
        return {**value, 'identity_id': identity, 'save_mode': 'copy' if path.split('/')[0] == 'imports' else 'replace',
                'editable': not active, 'blocked_reason': '当前身份的任务仍在执行，完成或停止后再保存。' if active else None,
                'history': [{'id': row['request_key'], 'created_at': row['created_at']} for row in versions]}

    def recovery(self, identity, path, identifier):
        self.root(identity)
        document_path(path)
        with self.store.connection() as db:
            row = db.execute('SELECT old_bytes,created_at FROM workspace_text_versions WHERE identity_id=? AND target_path=? AND request_key=? AND receipt IS NOT NULL', (identity, path, identifier)).fetchone()
        if not row: raise TextEditError('当前身份没有这份恢复版本。', 404)
        raw = bytes(row['old_bytes'])
        return {'identity_id': identity, 'path': path, 'id': identifier, 'created_at': row['created_at'], 'text': raw.decode('utf-8'), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}

    def save(self, identity, body):
        root = self.root(identity)
        raw = text_bytes(body.text)
        spec = hashlib.sha256(body.model_dump_json(exclude={'request_key'}).encode()).hexdigest()
        target = f'documents/{body.request_key}/{Path(body.path).name}' if body.path.split('/')[0] == 'imports' else body.path
        # Commit original bytes BEFORE replacing a file, so a crash or failed final
        # receipt commit cannot erase the recovery copy or invent a second write.
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM workspace_text_versions WHERE identity_id=? AND request_key=?', (identity, body.request_key)).fetchone()
            if prior:
                if prior['spec'] != spec: raise TextEditError('这次保存编号已用于其他修改，请取回原回执。')
                if prior['receipt']: return json.loads(prior['receipt'])
            else:
                if self.active(db, identity): raise TextEditError('当前身份的任务仍在执行，完成或停止后再保存。', 423)
                current, original = read_file(root, body.path)
                if (current['revision'], current['sha256']) != (body.base_revision, body.base_sha256): raise TextEditError('文档已有更新，草稿已保留。请读取最新版并比较。')
                db.execute('INSERT INTO workspace_text_versions VALUES(?,?,?,?,?,?,?,?,?,NULL)', (identity, body.request_key, spec, body.path, target, body.base_revision, original, raw, now()))
        with self.store.connection() as db:
            # TaskService reserves starts through this same write lock.
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM workspace_text_versions WHERE identity_id=? AND request_key=?', (identity, body.request_key)).fetchone()
            if prior['receipt']: return json.loads(prior['receipt'])
            try: current, current_raw = read_file(root, target)
            except TextEditError as error:
                if target != body.path and error.status == 404: current, current_raw = None, None
                else: raise
            # A previous atomic publication may have outlived its DB reply. Adopt
            # only identical bytes; never write again to recover an old receipt.
            if current_raw != raw:
                if self.active(db, identity): raise TextEditError('当前身份的任务仍在执行，草稿保留，稍后再保存。', 423)
                source, _ = read_file(root, body.path)
                if (source['revision'], source['sha256']) != (body.base_revision, body.base_sha256) or target != body.path and current is not None:
                    raise TextEditError('文档已有更新，未覆盖。请读取最新版并比较。')
                current = self._publish(root, body.path, target, raw, body.base_revision)
            receipt = {key: value for key, value in current.items() if key != 'text'} | {'identity_id': identity, 'source_path': body.path, 'request_key': body.request_key, 'recovery_id': body.request_key, 'saved_at': now(), 'save_mode': 'copy' if target != body.path else 'replace'}
            db.execute('UPDATE workspace_text_versions SET receipt=? WHERE identity_id=? AND request_key=?', (json.dumps(receipt), identity, body.request_key))
        return receipt

    def _publish(self, root, source, target, raw, base_revision):
        try:
            with parent_fd(root, target, create=target != source) as (fd, name):
                temporary = '.edit-' + secrets.token_hex(16)
                handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                try:
                    with os.fdopen(handle, 'wb') as file:
                        file.write(raw); file.flush(); os.fsync(file.fileno())
                    # Reopen the live path and reject a swapped/moved parent.
                    with parent_fd(root, target) as (live, _):
                        if (os.fstat(live).st_dev, os.fstat(live).st_ino) != (os.fstat(fd).st_dev, os.fstat(fd).st_ino): raise TextEditError('文件夹已变化，请重新读取。')
                    if read_file(root, source)[0]['revision'] != base_revision: raise TextEditError('文档刚刚更新，未覆盖，请重新比较。')
                    if target == source: os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
                    else: os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                    if target != source: os.unlink(temporary, dir_fd=fd)
                    os.fsync(fd)
                    return read_at(fd, name, target)[0]
                finally:
                    try: os.unlink(temporary, dir_fd=fd)
                    except FileNotFoundError: pass
        except OSError as error: raise TextEditError('保存结果尚未确认，请取回同一次保存回执。', 503) from error


def install_workspace_text_routes(app, store, runtime_for):
    import asyncio
    from fastapi import Request
    from fastapi.responses import JSONResponse
    editor = WorkspaceText(store, runtime_for)
    app.state.workspace_text = editor

    @app.exception_handler(TextEditError)
    async def error(_request, exc): return JSONResponse({'detail': str(exc)}, status_code=exc.status)

    @app.get('/api/workspace/text')
    async def read(request: Request, path: str): return await asyncio.to_thread(editor.read, request.state.identity_id, path)

    @app.get('/api/workspace/text/recovery')
    async def recovery(request: Request, path: str, version: str): return await asyncio.to_thread(editor.recovery, request.state.identity_id, path, version)

    @app.post('/api/workspace/text')
    async def save(request: Request, body: TextSave): return await asyncio.to_thread(editor.save, request.state.identity_id, body)
    return editor
