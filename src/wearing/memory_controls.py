"""Explicit personal-memory edits through the pinned upstream store and file lock."""
import hashlib
import json


def revision(entries):
    return hashlib.sha256(json.dumps(entries, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def mutate_memory(store, change, scan, delimiter, *, home=None):
    """Commit via upstream; optionally journal explicit user changes under HOME.

    A pending journal record is durable before the upstream write. Only its
    successful return marks it committed; an interrupted write is never offered
    as an undoable action. No client-supplied source/path is trusted.
    """
    if home is None:
        return _mutate_memory(store, change, scan, delimiter)
    target = change.get("target")
    if target not in ("user", "memory"):
        return {"success": False, "status": 422, "error": "请选择要修改的记忆。"}
    journal = _History(home, target)
    try:
        with _settings_lock(journal.lock):
            journal.load()
            return _mutate_memory(store, change, scan, delimiter, journal=journal)
    except TimeoutError:
        return {"success": False, "status": 409, "error": "记忆正在保存，请稍后重试。"}


def _mutate_memory(store, change, scan, delimiter, *, journal=None):
    target, action = change.get('target'), change.get('action')
    if target not in ('user', 'memory') or action not in ('add', 'replace', 'remove', 'clear', 'undo'):
        return {'success': False, 'status': 422, 'error': '请选择要修改的记忆。'}
    if not store.target_enabled(target) and action in {'add', 'replace', 'undo'}:
        return {'success': False, 'status': 409, 'error': '这部分记忆已暂停，请先恢复后修改。'}
    text = change.get('content', '')
    if not isinstance(text, str) or (action not in {'remove', 'clear', 'undo'} and (not text.strip() or len(text) > 12000)):
        return {'success': False, 'status': 422, 'error': '请填写记忆内容，最多 12000 字。'}
    text = text.strip()
    if action not in {'remove', 'clear', 'undo'} and scan(text):
        return {'success': False, 'status': 422, 'error': '这段内容无法保存为记忆，请检查格式。'}
    pending = None
    def apply(entries, limit):
        nonlocal pending
        if revision(entries) != change.get('revision'):
            return {'success': False, 'status': 409, 'error': '记忆已有更新，请读取最新版后再修改。'}
        updated = entries.copy()
        if action == 'clear':
            updated = []
        elif action == 'undo':
            item = journal.undoable(change.get('history_id'), entries) if journal else None
            if item is None:
                return {'success': False, 'status': 409, 'error': '这次修改已无法撤销，请读取最新记忆后核对。'}
            updated = item['before'].copy()
            if any(scan(entry) for entry in updated):
                return {'success': False, 'status': 422, 'error': '旧内容无法重新保存为记忆，请手动核对后修改。'}
        elif action == 'add':
            if text not in updated: updated.append(text)
        else:
            index = change.get('index')
            if type(index) is not int or not 0 <= index < len(entries):
                return {'success': False, 'status': 409, 'error': '这条记忆已变化，请刷新后再选择。'}
            if action == 'remove': updated.pop(index)
            else: updated[index] = text
        if len(delimiter.join(updated)) > limit:
            return {'success': False, 'status': 422, 'error': '记忆空间不足，请精简这条内容或移除不再需要的内容。'}
        if journal:
            if action == 'clear':
                # A privacy erase has no undo record. Purge inside the same upstream
                # CAS/file lock; failure must not report a completed clear.
                journal.purge()
            elif updated != entries:
                pending = journal.stage(action, entries, updated,
                                        undo_of=change.get('history_id') if action == 'undo' else None)
        return updated, '记忆已更新。'
    # Upstream owns locking, rereading, external-drift detection and atomic persistence.
    result = store._mutate(target, apply)
    if journal and pending is not None and result.get('success'):
        journal.commit(pending)
    return result


def settings_snapshot(home):
    """Validate before Hermes' permissive config loader can fall back to defaults."""
    from pathlib import Path
    try:
        import hermes_yaml as yaml
    except ImportError:
        import yaml
    path = Path(home) / 'config.yaml'
    if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size > 512 * 1024)):
        raise ValueError('Unsafe memory settings')
    raw = path.read_text(encoding='utf-8') if path.exists() else '{}'
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as error:
        raise ValueError("Invalid memory settings") from error
    if not isinstance(data, dict) or not isinstance(data.get('memory', {}), dict):
        raise ValueError('Invalid memory settings')
    return data, hashlib.sha256(raw.encode()).hexdigest()


def set_memory_enabled(home, change):
    """CAS only the selected flag; share the host configuration mutation lock."""
    from pathlib import Path
    import os
    import tempfile
    try:
        import hermes_yaml as yaml
    except ImportError:
        import yaml
    target, enabled = change.get('target'), change.get('enabled')
    if target not in ('user', 'memory') or type(enabled) is not bool:
        return {'success': False, 'status': 422, 'error': '请选择这部分记忆是否继续使用。'}
    home = Path(home)
    path, lock = home / 'config.yaml', home / '.pajio-skills.lock'
    if home.is_symlink() or lock.is_symlink():
        raise ValueError('Unsafe memory settings lock')
    try:
        with _settings_lock(lock):
            config, current = settings_snapshot(home)
            if current != change.get('settings_revision'):
                return {'success': False, 'status': 409, 'error': '记忆设置已有更新，请核对最新版后再操作。'}
            key = 'user_profile_enabled' if target == 'user' else 'memory_enabled'
            config.setdefault('memory', {})[key] = enabled
            fd, temporary = tempfile.mkstemp(prefix='.memory-config-', dir=home)
            try:
                with os.fdopen(fd, 'w') as output:
                    yaml.safe_dump(config, output, allow_unicode=True, sort_keys=False)
                    output.flush()
                    os.fsync(output.fileno())
                if settings_snapshot(home)[1] != current:
                    return {'success': False, 'status': 409, 'error': '设置刚刚发生变化，未覆盖，请重新读取。'}
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return {'success': True}
    except TimeoutError:
        return {'success': False, 'status': 409, 'error': '设置正在保存，请稍后重试。'}


from contextlib import contextmanager


@contextmanager
def _settings_lock(path):
    """Same OS flock as host FileLock, without adding deps to pinned Hermes."""
    import errno
    import os
    import time
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    acquired = False
    try:
        started = time.monotonic()
        while not acquired:
            try:
                if os.name == 'nt':
                    import msvcrt
                    if not os.fstat(fd).st_size:
                        os.write(fd, b'0')
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() - started >= 3:
                    raise TimeoutError('Memory settings locked') from None
                time.sleep(.025)
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


_HISTORY_LIMIT = 20
_HISTORY_BYTES = 2 * 1024 * 1024


class _History:
    """Private finite change log, not another source of current memory."""

    def __init__(self, home, target):
        from pathlib import Path
        self.home = Path(home)
        self.target = target
        self.directory = self.home / '.pajio-memory-history'
        self.path = self.directory / (target + '.json')
        self.lock = self.directory / (target + '.lock')
        if (self.home.is_symlink() or self.directory.is_symlink()
                or self.path.is_symlink() or self.lock.is_symlink()):
            raise ValueError('Unsafe memory history')
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        self.directory.chmod(0o700)
        self.items = []

    def load(self):
        import os
        import stat
        try:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        except FileNotFoundError:
            self.items = []
            return
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > _HISTORY_BYTES:
                raise ValueError('Unsafe memory history')
            data = json.load(stream)
        if (not isinstance(data, dict) or data.get('schema') != 1
                or data.get('target') != self.target or not isinstance(data.get('items'), list)
                or len(data['items']) > _HISTORY_LIMIT):
            raise ValueError('Invalid memory history')
        ids = set()
        for item in data['items']:
            if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                    or len(item['id']) != 32 or any(c not in '0123456789abcdef' for c in item['id'])
                    or item['id'] in ids or item.get('source') != 'user'
                    or item.get('state') not in ('pending', 'committed')
                    or item.get('action') not in ('add', 'replace', 'remove', 'undo')
                    or not isinstance(item.get('created_at'), str)):
                raise ValueError('Invalid memory history entry')
            ids.add(item['id'])
            for field in ('before', 'after'):
                entries = item.get(field)
                if (not isinstance(entries, list) or not all(isinstance(e, str) for e in entries)
                        or sum(len(e) for e in entries) > 65536
                        or item.get(field + '_revision') != revision(entries)):
                    raise ValueError('Invalid memory history content')
            if (item['action'] == 'undo' or 'undo_of' in item) and not isinstance(item.get('undo_of'), str):
                raise ValueError('Invalid memory history undo')
        self.items = data['items']

    def _save(self):
        import os
        import tempfile
        from pathlib import Path
        def encode():
            return json.dumps({'schema': 1, 'target': self.target, 'items': self.items},
                              ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.items = self.items[-_HISTORY_LIMIT:]
        raw = encode()
        while len(raw) > _HISTORY_BYTES and len(self.items) > 1:
            self.items.pop(0)
            raw = encode()
        if len(raw) > _HISTORY_BYTES:
            raise ValueError('Memory history too large')
        fd, name = tempfile.mkstemp(prefix='.' + self.target + '-history-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, self.path)
            # Rename durability matters: pending must survive a power failure
            # before upstream is allowed to perform its own atomic replacement.
            _sync_directory(self.directory)
        finally:
            Path(name).unlink(missing_ok=True)

    def stage(self, action, before, after, *, undo_of=None):
        from datetime import datetime, timezone
        from uuid import uuid4
        item = {'id': uuid4().hex, 'state': 'pending', 'source': 'user',
                'action': action, 'created_at': datetime.now(timezone.utc).isoformat(),
                'before': before.copy(), 'after': after.copy(),
                'before_revision': revision(before), 'after_revision': revision(after)}
        if undo_of is not None:
            item['undo_of'] = undo_of
        self.items.append(item)
        self._save()
        return item['id']

    def commit(self, identifier):
        next(item for item in self.items if item['id'] == identifier)['state'] = 'committed'
        self._save()

    def undoable(self, identifier, entries):
        if not isinstance(identifier, str):
            return None
        undone = {item.get('undo_of') for item in self.items if item['state'] == 'committed'}
        return next((item for item in self.items
                     if item['id'] == identifier and item['state'] == 'committed'
                     and item['action'] != 'undo' and item['id'] not in undone
                     and item['after_revision'] == revision(entries)), None)

    def purge(self):
        # Upstream may leave a drift backup on a refused external edit. Clear
        # removes only this target's known backup format, never other targets.
        memory_dir = self.home / 'memories'
        if memory_dir.is_symlink():
            raise ValueError('Unsafe memory directory')
        name = 'USER.md' if self.target == 'user' else 'MEMORY.md'
        for path in memory_dir.glob(name + '.bak.*'):
            if path.name[len(name + '.bak.'):].isdigit():
                path.unlink()
        self.path.unlink(missing_ok=True)
        for path in self.directory.glob('.' + self.target + '-history-*'):
            path.unlink()
        self.items = []
        _sync_directory(self.directory)
        if memory_dir.is_dir():
            _sync_directory(memory_dir)


def _sync_directory(directory):
    import os
    if os.name == 'nt':
        return
    fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def memory_history(home, target, entries, *, enabled=True):
    """Expose only acknowledged user changes; pending commits remain uncertain."""
    if target not in ('user', 'memory'):
        raise ValueError('Invalid memory target')
    journal = _History(home, target)
    with _settings_lock(journal.lock):
        journal.load()
        items = []
        for record in reversed(journal.items):
            if record['state'] != 'committed':
                continue
            item = {key: value for key, value in record.items() if key != 'state'}
            item['undoable'] = bool(enabled and journal.undoable(record['id'], entries))
            items.append(item)
        return {'coverage': 'user_explicit', 'limit': _HISTORY_LIMIT, 'items': items,
                'unconfirmed_changes': any(item['state'] == 'pending' for item in journal.items)}
