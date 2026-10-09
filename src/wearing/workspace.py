"""Download/list surface for the dedicated file space. Agent I/O is owned by MCP."""

import os
from pathlib import Path


class WorkspaceError(Exception):
    pass


def workspace_file(root: Path, name: str):
    relative = Path(name)
    if not name or relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise WorkspaceError("文件路径不在 Pajio 文件空间内。")
    target = root / relative
    if root.is_symlink() or any(path.is_symlink() for path in (target, *target.parents) if path != root.parent):
        raise WorkspaceError("文件下载不跟随符号链接。")
    try:
        if not target.resolve(strict=True).is_relative_to(root.resolve()) or not target.is_file():
            raise WorkspaceError("文件不存在。")
    except OSError:
        raise WorkspaceError("文件不存在。") from None
    return target


def list_files(root: Path, limit=200):
    if not root.exists():
        return {"files": [], "truncated": False}
    if root.is_symlink():
        raise WorkspaceError("文件空间不能使用符号链接。")
    files = []
    visited = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            visited += 1
            if visited > 2000:
                return {"files": files, "truncated": True}
            try:
                path = workspace_file(root, str((Path(directory) / name).relative_to(root)))
                info = path.stat()
            except (OSError, WorkspaceError):
                continue
            files.append({"path": path.relative_to(root).as_posix(), "size": info.st_size, "modified": info.st_mtime})
            if len(files) >= limit:
                return {"files": files, "truncated": True}
        visited += len(dirs)
        if visited > 2000:
            return {"files": files, "truncated": True}
    return {"files": files, "truncated": False}


# Native browsing uses bounded, resumable scans. The legacy listing above stays
# available for older clients; it never pretends to cover more than its limit.
import copy
import secrets
import stat
import threading
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass


class WorkspacePageError(WorkspaceError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def _relative(value, *, empty=False):
    if not isinstance(value, str) or len(value) > 2048 or (not value and not empty) or '\\' in value or any(ord(c) < 32 for c in value):
        raise WorkspacePageError('文件夹路径不正确。', 422)
    if value and any(part in {'', '.', '..'} for part in value.split('/')):
        raise WorkspacePageError('文件夹路径不正确。', 422)
    return value


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns)


def _directory_fd(root, relative=''):
    """Every component under the configured root is opened without symlinks."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.split('/') if relative else ():
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def file_metadata(root: Path, name: str):
    """Read one exact safe file without enumerating its siblings or its content."""
    _relative(name)
    directory, _, leaf = name.rpartition('/')
    try:
        fd = _directory_fd(root, directory)
        try: info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
        finally: os.close(fd)
        if not stat.S_ISREG(info.st_mode): raise OSError('Not a regular file')
    except OSError:
        raise WorkspacePageError('文件已移动或暂时无法读取，请刷新文件夹。', 404) from None
    return {'path': name, 'size': info.st_size, 'modified': info.st_mtime}


@dataclass
class _Frame:
    path: str
    fd: int
    iterator: object
    signature: tuple

    def close(self):
        self.iterator.close()
        os.close(self.fd)


class _Scan:
    def __init__(self, root, identity, directory, query, clock):
        self.root, self.identity, self.directory, self.query = root, identity, directory, query
        self.clock, self.touched, self.id = clock, clock(), secrets.token_hex(16)
        self.cursor = secrets.token_urlsafe(32)
        self.history = OrderedDict()
        self.frames, self.watched = [], {}
        self.validation = None
        self.scanned = 0
        self.finished = False
        self.root_signature = _signature(os.stat(root, follow_symlinks=False))
        fd = _directory_fd(root, directory)
        try: self.push(directory, fd)
        except BaseException:
            os.close(fd)
            raise

    def push(self, path, fd):
        signature = _signature(os.fstat(fd))
        frame = _Frame(path, fd, os.scandir(fd), signature)
        self.frames.append(frame)
        self.watched[path] = signature

    def close(self):
        while self.frames: self.frames.pop().close()

    def validate_one(self, path, expected):
        try:
            fd = _directory_fd(self.root, path)
            try: current = _signature(os.fstat(fd))
            finally: os.close(fd)
        except OSError:
            raise WorkspacePageError('文件夹发生变化，请重新读取列表。') from None
        if current != expected: raise WorkspacePageError('文件夹发生变化，请重新读取列表。')

    def consume(self, *, limit, budget, seconds, max_frames):
        start, steps, files, walked = time.monotonic(), 0, [], False
        def room(): return steps < budget and time.monotonic() - start < seconds
        if self.validation is None: self.validation = deque(self.watched.items())
        while self.validation and room():
            self.validate_one(*self.validation.popleft())
            steps += 1
        if not self.validation:
            while self.frames and len(files) < limit and room():
                walked = True
                frame = self.frames[-1]
                if _signature(os.fstat(frame.fd)) != frame.signature:
                    raise WorkspacePageError('文件夹发生变化，请重新读取列表。')
                steps += 1
                try: entry = next(frame.iterator)
                except StopIteration:
                    self.frames.pop().close()
                    continue
                self.scanned += 1
                relative = (frame.path + '/' if frame.path else '') + entry.name
                # Unrepresentable paths cannot silently disappear into a claim
                # of completeness. The caller can narrow the selected folder.
                _relative(relative)
                try: info = entry.stat(follow_symlinks=False)
                except OSError: raise WorkspacePageError('文件夹发生变化，请重新读取列表。') from None
                if stat.S_ISLNK(info.st_mode): continue
                if stat.S_ISDIR(info.st_mode):
                    if len(self.frames) >= max_frames or len(self.watched) >= 10000:
                        raise WorkspacePageError('文件夹层级或数量较多，请打开具体文件夹后再查找。', 413)
                    try:
                        fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=frame.fd)
                        if _signature(os.fstat(fd)) != _signature(info):
                            os.close(fd)
                            raise WorkspacePageError('文件夹发生变化，请重新读取列表。')
                        try: self.push(relative, fd)
                        except BaseException:
                            os.close(fd)
                            raise
                    except OSError: raise WorkspacePageError('文件夹暂时无法读取，请刷新后重试。') from None
                elif stat.S_ISREG(info.st_mode) and (not self.query or unicodedata.normalize('NFC', self.query).casefold() in unicodedata.normalize('NFC', entry.name).casefold()):
                    # Re-open from root so a moved/replaced ancestor cannot
                    # expose entries from a directory no longer in this space.
                    metadata = file_metadata(self.root, relative)
                    files.append(metadata)
            if not self.frames and not self.finished:
                self.finished = True
                self.validation = deque(self.watched.items())
                while self.validation and room():
                    self.validate_one(*self.validation.popleft())
                    steps += 1
            elif self.frames and walked:
                self.validation = None  # Revalidate visited folders next page.
        complete = self.finished and not self.validation
        return {'files': files, 'truncated': not complete, 'complete': complete,
                'scan_id': self.id, 'directory': self.directory, 'query': self.query,
                'scanned': self.scanned, 'phase': 'complete' if complete else 'checking' if self.validation else 'scanning'}


class WorkspacePager:
    """Process-local opaque cursors, bounded I/O and memory, retryable last pages.

    A restart/eviction/expiry safely asks the client to restart its query. Cursors
    are not reusable credentials and are bound to identity AND configured root.
    Directory changes invalidate the scan; file content is never searched/read.
    This is an observed listing, not an atomic filesystem snapshot.
    """
    def __init__(self, *, ttl=300, max_scans=8, scan_budget=2000, seconds=.12, clock=time.monotonic):
        self.ttl, self.max_scans, self.scan_budget, self.seconds, self.clock = ttl, max_scans, scan_budget, seconds, clock
        self.scans, self.tokens, self.lock = OrderedDict(), {}, threading.RLock()

    def _drop(self, scan):
        scan.close()
        self.scans.pop(scan.id, None)
        for token in (*scan.history, scan.cursor): self.tokens.pop(token, None)

    def close(self):
        with self.lock:
            for scan in list(self.scans.values()): self._drop(scan)

    def page(self, root: Path, identity: str, *, directory='', query='', cursor=None, limit=200):
        directory = _relative(directory, empty=True)
        if not isinstance(query, str) or len(query) > 200 or any(ord(c) < 32 for c in query):
            raise WorkspacePageError('搜索词请控制在 200 字以内。', 422)
        query = query.strip()
        if type(limit) is not int or not 1 <= limit <= 200: raise WorkspacePageError('每页文件数量无效。', 422)
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) != 43 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_' for c in cursor)):
            raise WorkspacePageError('文件列表已过期，请重新读取。')
        root = Path(root).absolute()
        if root.is_symlink(): raise WorkspacePageError('文件空间不能使用符号链接。')
        with self.lock:
            for expired in list(self.scans.values()):
                if self.clock() - expired.touched >= self.ttl: self._drop(expired)
            if cursor:
                scan = self.scans.get(self.tokens.get(cursor))
                if not scan or (scan.identity, scan.root, scan.directory, scan.query, scan.limit) != (identity, root, directory, query, limit):
                    raise WorkspacePageError('文件列表已变化或过期，请重新读取。')
                try:
                    if _signature(os.stat(root, follow_symlinks=False)) != scan.root_signature:
                        raise WorkspacePageError('文件空间发生变化，请重新读取列表。')
                except OSError: raise WorkspacePageError('文件空间发生变化，请重新读取列表。') from None
                if cursor in scan.history:
                    scan.touched = self.clock()
                    return copy.deepcopy(scan.history[cursor])
            else:
                while len(self.scans) >= self.max_scans or sum(len(s.frames) for s in self.scans.values()) >= 32:
                    self._drop(next(iter(self.scans.values())))
                if not root.exists() and not directory:
                    return {'files': [], 'truncated': False, 'complete': True, 'scan_id': secrets.token_hex(16), 'page_cursor': secrets.token_urlsafe(32), 'directory': '', 'query': query, 'scanned': 0, 'phase': 'complete', 'next_cursor': None}
                try: scan = _Scan(root, identity, directory, query, self.clock)
                except OSError: raise WorkspacePageError('文件夹不存在或暂时无法读取。', 404) from None
                scan.limit = limit
                self.scans[scan.id] = scan
                self.tokens[scan.cursor] = scan.id
                cursor = scan.cursor
            self.scans.move_to_end(scan.id)
            scan.touched = self.clock()
            try:
                available = min(32, 48 - sum(len(s.frames) for s in self.scans.values() if s is not scan))
                result = scan.consume(limit=limit, budget=self.scan_budget, seconds=self.seconds, max_frames=available)
                result['page_cursor'] = cursor
            except BaseException:
                self._drop(scan)
                raise
            if result['complete']:
                scan.close()
                result['next_cursor'] = None
            else:
                scan.cursor = secrets.token_urlsafe(32)
                self.tokens[scan.cursor] = scan.id
                result['next_cursor'] = scan.cursor
            scan.history[cursor] = result
            # Last two pages survive network retries without advancing again.
            while len(scan.history) > 2:
                old, _ = scan.history.popitem(last=False)
                self.tokens.pop(old, None)
            return copy.deepcopy(result)
