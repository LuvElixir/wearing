"""Bounded data-only Inbox/Outbox I/O. No caller-supplied root or executable action."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import unicodedata

MAX_BYTES = 20 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
FILE_METHODS = ('files.send', 'files.list', 'files.fetch')


class FileChannelError(ValueError):
    pass


def name_checked(name):
    if (not isinstance(name, str) or name != unicodedata.normalize('NFC', name)
            or name in {'', '.', '..'} or name.startswith('.') or name != name.strip() or len(name.encode('utf-8')) > 180
            or '/' in name or '\\' in name or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise FileChannelError('file_name_invalid')
    return name


def id_checked(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise FileChannelError('file_id_invalid')
    return value


def source_info(name, data):
    name_checked(name)
    if not data or len(data) > MAX_BYTES:
        raise FileChannelError('file_too_large')
    digest = hashlib.sha256(data).hexdigest()
    identifier = hashlib.sha256(json.dumps([name, len(data), digest], ensure_ascii=True).encode()).hexdigest()[:32]
    return {'file_id': identifier, 'name': name, 'size': len(data), 'sha256': digest}


def source_checked(value):
    if not isinstance(value, dict) or set(value) != {'file_id', 'name', 'size', 'sha256'}:
        raise FileChannelError('file_source_invalid')
    id_checked(value['file_id']); name_checked(value['name'])
    if type(value['size']) is not int or not 1 <= value['size'] <= MAX_BYTES:
        raise FileChannelError('file_too_large')
    if not isinstance(value['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['sha256']):
        raise FileChannelError('file_hash_invalid')
    return value


def directory_fd(root, *, create=False, owner=None):
    """Open every absolute component without following symlinks."""
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts:
        raise FileChannelError('file_root_invalid')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in root.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700 if owner is None else 0o770, dir_fd=fd)
                    if owner is not None: os.chown(part, *owner, dir_fd=fd, follow_symlinks=False)
                except FileExistsError:
                    pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_regular(fd, name):
    name_checked(name)
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(handle)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise FileChannelError('file_not_regular')
        if before.st_size > MAX_BYTES: raise FileChannelError('file_too_large')
        data = bytearray()
        while len(data) <= MAX_BYTES:
            chunk = os.read(handle, min(CHUNK_BYTES, MAX_BYTES + 1 - len(data)))
            if not chunk: break
            data.extend(chunk)
        after = os.fstat(handle)
        signature = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns, v.st_nlink)
        if signature(before) != signature(after) or len(data) != before.st_size:
            raise FileChannelError('file_changed')
        if len(data) > MAX_BYTES: raise FileChannelError('file_too_large')
        return bytes(data)
    finally:
        os.close(handle)


class InboxOutbox:
    def __init__(self, root, *, owner=None):
        self.root, self.owner = Path(root), owner

    def available(self):
        for folder in ('Inbox', 'Outbox'):
            fd = directory_fd(self.root / folder)
            os.close(fd)
        return True

    def prepare(self):
        for folder in ('Inbox', 'Outbox'):
            fd = directory_fd(self.root / folder, create=True, owner=self.owner)
            os.close(fd)

    def send(self, request_id, source, data):
        id_checked(request_id); source_checked(source)
        if source_info(source['name'], data) != source:
            raise FileChannelError('file_hash_changed')
        fd = directory_fd(self.root / 'Inbox')
        name = request_id + '-' + source['name']
        # User names are bounded separately; internal names add the stable ID.
        if len(name.encode()) > 240: raise FileChannelError('file_name_invalid')
        temp = '.pending-' + secrets.token_hex(16)
        try:
            try:
                old = self._read_internal(fd, name)
            except FileNotFoundError:
                old = None
            if old is not None:
                if old != data: raise FileChannelError('file_destination_changed')
                return {'source': source, 'receipt_id': request_id, 'destination_name': name, 'replayed': True}
            out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                if self.owner is not None:
                    os.fchown(out, *self.owner); os.fchmod(out, 0o660)
                with os.fdopen(out, 'wb', closefd=False) as stream:
                    stream.write(data); stream.flush(); os.fsync(out)
            finally: os.close(out)
            try:
                os.link(temp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            except FileExistsError:
                if self._read_internal(fd, name) != data: raise FileChannelError('file_destination_changed')
            finally:
                os.unlink(temp, dir_fd=fd)
            os.fsync(fd)
            return {'source': source, 'receipt_id': request_id, 'destination_name': name, 'replayed': False}
        finally:
            try: os.unlink(temp, dir_fd=fd)
            except FileNotFoundError: pass
            os.close(fd)

    @staticmethod
    def _read_internal(fd, name):
        # Prefix removal keeps the public filename validator strict.
        id_checked(name[:32]); name_checked(name[33:])
        if name[32] != '-': raise FileChannelError('file_name_invalid')
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(handle)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES or info.st_mode & 0o111:
                raise FileChannelError('file_not_regular')
            with os.fdopen(handle, 'rb', closefd=False) as stream: data = stream.read(MAX_BYTES + 1)
            if len(data) != info.st_size: raise FileChannelError('file_changed')
            return data
        finally: os.close(handle)

    def listing(self):
        fd = directory_fd(self.root / 'Outbox')
        files, total, truncated = [], 0, False
        try:
            # Bound enumeration as well as hashing; never enumerate the rest of the phone.
            with os.scandir(fd) as entries:
                for index, entry in enumerate(entries):
                    if index >= 200 or len(files) >= 50 or total >= 100 * 1024 * 1024:
                        truncated = True; break
                    if entry.name.startswith('.'): continue
                    try:
                        data = read_regular(fd, entry.name)
                        source = source_info(entry.name, data)
                    except (OSError, FileChannelError): continue
                    files.append(source); total += len(data)
            return {'files': sorted(files, key=lambda x: x['name']), 'truncated': truncated}
        finally: os.close(fd)

    def fetch(self, source):
        source_checked(source)
        fd = directory_fd(self.root / 'Outbox')
        try: data = read_regular(fd, source['name'])
        finally: os.close(fd)
        if source_info(source['name'], data) != source:
            raise FileChannelError('file_changed')
        return data
