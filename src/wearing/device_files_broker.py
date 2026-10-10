"""Root-owned Android data bridge. Unix credentials and a fixed filesystem root only."""
import os
import pwd
import socket
import struct
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path
from .device_files_native import configuration, SOCKET, receive, transmit, dispatch, require_peer_uid
from .device_files_io import InboxOutbox, directory_fd


@contextmanager
def agent_fence(home, uid, resource, epoch):
    """Read-only ownership check; no creation/reset of gateway state by root."""
    import fcntl
    if type(epoch) is not int or epoch < 0: raise ValueError('file_epoch_required')
    base = Path(home) / '.wearing'
    dirs = []
    lock = None
    try:
        for name in ('phone-locks', 'device-gateway'): dirs.append(directory_fd(base / name))
        lock = os.open(resource + '.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirs[0])
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
            raise ValueError('file_lock_binding_changed')
        # The root broker holds an independent OS lock; caller timeout cannot release it.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def validate():
            info = os.stat('ownership.sqlite3', dir_fd=dirs[1], follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
                raise ValueError('file_gateway_binding_changed')
            # /proc/self/fd pins the already no-follow opened parent directory.
            db = sqlite3.connect(f'file:/proc/self/fd/{dirs[1]}/ownership.sqlite3?mode=ro', uri=True, timeout=5)
            try: row = db.execute('SELECT epoch,state FROM ownership WHERE resource=?', (resource,)).fetchone()
            finally: db.close()
            if row != (epoch, 'agent_ready'): raise ValueError('file_private_or_epoch_changed')
        validate()
        yield
        validate()
    finally:
        if lock is not None: os.close(lock)
        for fd in dirs: os.close(fd)


def serve():
    if os.geteuid() != 0: raise SystemExit('file_broker_root_required')
    config = configuration()
    if config['kind'] != 'android': raise SystemExit('file_broker_android_only')
    account = pwd.getpwnam(config['user'])
    if account.pw_uid == 0 or account.pw_dir != '/home/pajio-phone' or account.pw_shell != '/usr/sbin/nologin':
        raise SystemExit('file_broker_user_changed')
    # Android must already have provisioned /data/media/0. Never fabricate an
    # unbooted/missing data mount that merely looks like a phone filesystem.
    fd = directory_fd(Path(config['root']).parent.parent); os.close(fd)
    io = InboxOutbox(config['root'], owner=(1023, 1023))
    io.prepare()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        # systemd RuntimeDirectory owns the parent. Never unlink somebody else's node.
        if os.path.lexists(SOCKET):
            info = os.lstat(SOCKET)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0: raise SystemExit('file_broker_socket_unsafe')
            os.unlink(SOCKET)
        listener.bind(SOCKET); os.chown(SOCKET, 0, account.pw_gid); os.chmod(SOCKET, 0o660)
        listener.listen(4)
        while True:
            peer, _ = listener.accept()
            with peer:
                peer.settimeout(15)
                try: require_peer_uid(peer, account.pw_uid)
                except ValueError: continue
                try:
                    request = receive(peer)
                    if (not isinstance(request, dict) or set(request) != {'resource_id', 'action', 'params', 'permit_epoch'}
                            or request['resource_id'] != config['resource_id']): raise ValueError()
                    if request['action'] == 'available':
                        value = dispatch(io, request['action'], request['params'])
                    else:
                        with agent_fence(account.pw_dir, account.pw_uid, config['resource_id'], request['permit_epoch']):
                            value = dispatch(io, request['action'], request['params'])
                    transmit(peer, value)
                except Exception:
                    try: transmit(peer, {'error': 'file_broker_rejected'})
                    except OSError: pass


if __name__ == '__main__': serve()
