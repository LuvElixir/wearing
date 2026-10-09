"""Explicit personal-memory edits through the pinned upstream store and file lock."""
import hashlib
import json


def revision(entries):
    return hashlib.sha256(json.dumps(entries, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def mutate_memory(store, change, scan, delimiter):
    target, action = change.get('target'), change.get('action')
    if target not in {'user', 'memory'} or action not in {'add', 'replace', 'remove', 'clear'}:
        return {'success': False, 'status': 422, 'error': '请选择要修改的记忆。'}
    if not store.target_enabled(target) and action in {'add', 'replace'}:
        return {'success': False, 'status': 409, 'error': '这部分记忆已暂停，请先恢复后修改。'}
    text = change.get('content', '')
    if not isinstance(text, str) or (action not in {'remove', 'clear'} and (not text.strip() or len(text) > 12000)):
        return {'success': False, 'status': 422, 'error': '请填写记忆内容，最多 12000 字。'}
    text = text.strip()
    if action not in {'remove', 'clear'} and scan(text):
        return {'success': False, 'status': 422, 'error': '这段内容无法保存为记忆，请检查格式。'}
    def apply(entries, limit):
        if revision(entries) != change.get('revision'):
            return {'success': False, 'status': 409, 'error': '记忆已有更新，请读取最新版后再修改。'}
        updated = entries.copy()
        if action == 'clear':
            updated = []
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
        return updated, '记忆已更新。'
    # Upstream owns locking, rereading, external-drift detection and atomic persistence.
    return store._mutate(target, apply)


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
    if target not in {'user', 'memory'} or type(enabled) is not bool:
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
