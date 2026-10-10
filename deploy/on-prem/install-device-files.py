#!/usr/bin/env python3
"""Operator-only enablement on an existing, bound dedicated execution VM.

Requires the new Python modules already installed. Does not grant relay access,
restart connector/core/media, install an APK, or change a container.
"""
import json
import os
from pathlib import Path
import pwd
import secrets
import stat
import subprocess

from wearing.device_files_io import InboxOutbox, directory_fd


METADATA_LIMIT = 131072


def _read_metadata(directory, name, uid, *, private=True, mode=None, gid=None):
    """Read the pinned inode only; do not follow a replaced leaf or parent."""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != uid or private and before.st_mode & 0o077
                or before.st_mode & 0o022 or before.st_size > METADATA_LIMIT
                or mode is not None and stat.S_IMODE(before.st_mode) != mode
                or gid is not None and before.st_gid != gid):
            raise ValueError('file_install_metadata_unsafe')
        data = bytearray()
        while len(data) <= METADATA_LIMIT:
            chunk = os.read(fd, min(65536, METADATA_LIMIT + 1 - len(data)))
            if not chunk: break
            data.extend(chunk)
        after = os.fstat(fd)
        signature = lambda v: (v.st_dev, v.st_ino, v.st_mode, v.st_uid, v.st_gid,
                               v.st_size, v.st_mtime_ns, v.st_ctime_ns, v.st_nlink)
        if signature(before) != signature(after) or len(data) != before.st_size or len(data) > METADATA_LIMIT:
            raise ValueError('file_install_metadata_changed')
        return bytes(data).decode('utf-8')
    finally:
        os.close(fd)


def read(path, uid=0, *, private=True):
    path = Path(path)
    directory = directory_fd(path.parent)
    try:
        return _read_metadata(directory, path.name, uid, private=private)
    finally:
        os.close(directory)


def write_exact(path, content, *, uid=0, gid=0, mode=0o600):
    """Install complete metadata once, without an enrollment-module dependency.

    No overwrite, including on a racing creator. An interrupted temporary write
    is never published; retry can install the same bytes after inspection.
    """
    if (type(uid) is not int or uid < 0 or type(gid) is not int or gid < 0
            or mode not in (0o600, 0o644) or not isinstance(content, str)):
        raise ValueError('file_install_metadata_unsafe')
    data = content.encode('utf-8')
    if len(data) > METADATA_LIMIT: raise ValueError('file_install_metadata_unsafe')
    path = Path(path)
    directory = directory_fd(path.parent, create=True)
    temporary = None
    try:
        def verify_existing():
            value = _read_metadata(directory, path.name, uid, private=mode == 0o600, mode=mode, gid=gid)
            if value != content: raise ValueError('file_install_existing_changed')
        try:
            verify_existing()
            return
        except FileNotFoundError:
            pass
        temporary = '.pajio-file-install-' + secrets.token_hex(16)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
            remaining = memoryview(data)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0: raise OSError('file_install_write_failed')
                remaining = remaining[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            verify_existing()
        os.unlink(temporary, dir_fd=directory); temporary = None
        os.fsync(directory)
    finally:
        if temporary is not None:
            try: os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError: pass
        os.close(directory)


def install():
    if os.geteuid() != 0: raise SystemExit('operator_root_required')
    owner = json.loads(read('/etc/pajio-native/device-owner.json'))
    kind = owner['kind']
    user = 'pajio-desktop' if kind == 'linux' else 'pajio-phone' if kind == 'android' else None
    if not user: raise SystemExit('unsupported_device_kind')
    account = pwd.getpwnam(user)
    if account.pw_uid == 0 or account.pw_dir != '/home/' + user or account.pw_shell != '/usr/sbin/nologin':
        raise SystemExit('native_account_changed')
    # Confirm the actual locally paired resource before introducing any service.
    connector = json.loads(read(Path(account.pw_dir) / '.pajio-connector/connector.json', account.pw_uid))
    if (connector['tenant_id'] != owner['tenant_id'] or connector['identity_id'] != owner['identity_id']
            or len(connector['resources']) != 1 or connector['resources'][0]['resource_id'] != owner['resource_id']):
        raise SystemExit('paired_owner_changed')
    root = account.pw_dir + '/Pajio' if kind == 'linux' else '/var/lib/pajio-phone/data/media/0/Download/Pajio'
    config = {'version': 1, 'kind': 'computer' if kind == 'linux' else 'android',
              'resource_id': owner['resource_id'], 'user': user, 'root': root}
    # Root-managed readable metadata only; contains no credential.
    write_exact('/etc/pajio-device-files.json', json.dumps(config, sort_keys=True), mode=0o644)
    if kind == 'linux':
        InboxOutbox(root, owner=(account.pw_uid, account.pw_gid)).prepare()
    else:
        fd = directory_fd(Path(root).parent.parent); os.close(fd)
        unit = '''[Unit]
Description=Pajio bounded Android Inbox and Outbox
After=pajio-phone-adb.service
Requires=pajio-phone-adb.service
[Service]
Type=simple
User=root
Group=pajio-phone
RuntimeDirectory=pajio-device-files
RuntimeDirectoryMode=0750
ExecStart=/opt/pajio-native/venv/bin/python -I -m wearing.device_files_broker
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/pajio-phone/data/media/0 /run/pajio-device-files
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
'''
        write_exact('/etc/systemd/system/pajio-device-files.service', unit, mode=0o644)
        subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], check=True)
        subprocess.run(['/usr/bin/systemctl', 'enable', '--now', 'pajio-device-files.service'], check=True)
    print(json.dumps({'installed': True, 'resource_id': owner['resource_id'], 'kind': kind,
                      'relay_permission_granted': False, 'inbox': 'Pajio/Inbox', 'outbox': 'Pajio/Outbox'}))


if __name__ == '__main__': install()
