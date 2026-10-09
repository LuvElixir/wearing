"""Identity-scoped document imports. Files are data, never executed or installed."""
import hashlib
import os
from pathlib import Path
import re
import stat
import secrets
import unicodedata

from fastapi import HTTPException, Request
from .store import now

MAX_IMPORT_BYTES = 20 * 1024 * 1024
KEY = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


class WorkspaceImports:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS workspace_imports (
                identity_id TEXT NOT NULL, request_key TEXT NOT NULL,
                name TEXT NOT NULL, digest TEXT NOT NULL, path TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(identity_id,request_key))""")

    def upload(self, identity, root: Path, key: str, name: str, data: bytes):
        self.store.identity(identity)
        name = unicodedata.normalize('NFC', name).strip()
        if not KEY.fullmatch(key):
            raise HTTPException(422, '导入编号无效，请重新选择文件。')
        if not name or len(name.encode('utf-8')) > 180 or name in {'.', '..'} or name.startswith('.') or any(c in name for c in '/\\') or any(ord(c)<32 for c in name):
            raise HTTPException(422, '请使用不含路径的普通文件名，最多180字节。')
        if not data or len(data) > MAX_IMPORT_BYTES:
            raise HTTPException(413, '请选择非空且不超过20 MB的文件。')
        digest = hashlib.sha256(data).hexdigest()
        relative = f'imports/{key}/{name}'
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM workspace_imports WHERE identity_id=? AND request_key=?', (identity,key)).fetchone()
            if old and (old['digest'] != digest or old['name'] != name):
                raise HTTPException(409, '这个导入编号已用于另一份文件，请重新选择。')
            root.mkdir(parents=True, exist_ok=True)
            descriptors = []
            try:
                # Directory descriptors keep every child scoped even if a concurrent
                # agent swaps a path. Symlinks are rejected at every component.
                descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                descriptors.append(descriptor)
                for component in ('imports', key):
                    try: os.mkdir(component, 0o700, dir_fd=descriptor)
                    except FileExistsError: pass
                    descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                    descriptors.append(descriptor)
                def verify_existing():
                    read_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                    with os.fdopen(read_fd, 'rb') as source:
                        info = os.fstat(source.fileno())
                        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_IMPORT_BYTES or hashlib.sha256(source.read(MAX_IMPORT_BYTES + 1)).hexdigest() != digest:
                            raise HTTPException(409, '文件位置已有不同内容，未覆盖。请重新选择文件。')
                try:
                    verify_existing()
                except FileNotFoundError:
                    temporary = '.upload-' + secrets.token_hex(16)
                    file_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
                    try:
                        with os.fdopen(file_fd, 'wb') as target:
                            target.write(data); target.flush(); os.fsync(target.fileno())
                        try:
                            # Publish only complete bytes and never replace another file.
                            os.link(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
                        except FileExistsError:
                            verify_existing()
                        os.fsync(descriptor)
                    finally:
                        os.unlink(temporary, dir_fd=descriptor)
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if not old:
                    db.execute('INSERT INTO workspace_imports VALUES(?,?,?,?,?,?)', (identity,key,name,digest,relative,now()))
            except OSError as error:
                raise HTTPException(409, '文件空间暂时无法写入，请检查连接或空间后重试。') from error
            finally:
                for descriptor in reversed(descriptors): os.close(descriptor)
        return {'file': {'path': relative, 'size': len(data), 'modified': info.st_mtime}, 'request_key': key, 'sha256': digest, 'replayed': bool(old)}


def install_workspace_import_routes(app, store, runtime_for):
    import asyncio
    imports = WorkspaceImports(store)
    @app.post('/api/workspace/import', status_code=201)
    async def import_document(request: Request, name: str, request_key: str):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_IMPORT_BYTES:
                raise HTTPException(413, '文件超过20 MB，请选择较小的文件。')
        return await asyncio.to_thread(imports.upload, request.state.identity_id, runtime_for(request.state.identity_id).workspace, request_key, name, bytes(data))
