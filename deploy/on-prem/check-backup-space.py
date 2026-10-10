#!/usr/bin/python3
"""Pajio-only vzdump hook; refuse a backup before it can consume host reserve."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, '/usr/local/lib/pajio')
from operations_scope import approved, load_scope

RESERVE = 16 * 1024**3


def approved_owner(vmid, config, scope):
    return approved(vmid, config, scope)


def worst_case_bytes(config):
    total = 0
    for key, value in config.items():
        if not re.fullmatch(r'(?:ide|sata|scsi|virtio)\d+', key):
            continue
        fields = value.split(',')
        if 'media=cdrom' in fields or 'backup=0' in fields:
            continue
        size = next((v[5:] for v in fields if v.startswith('size=')), '')
        match = re.fullmatch(r'(\d+(?:\.\d+)?)([KMGT])', size)
        if not match:
            raise ValueError('backup_disk_size_unknown')
        total += int(float(match[1]) * 1024**('KMGT'.index(match[2]) + 1))
    if total <= 0:
        raise ValueError('backup_disk_scope_unknown')
    # Bound by full virtual disk size, not current compressed size/thin usage.
    return (total * 105 + 99) // 100


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('backup-start', 'backup-end'):
        return
    scope = load_scope()
    if len(sys.argv) != 4 or sys.argv[2] != 'snapshot' or sys.argv[3] not in scope['guests']:
        raise ValueError('backup_scope_not_approved')
    if os.environ.get('STOREID') != 'local':
        raise ValueError('backup_storage_not_approved')
    target = Path(os.environ.get('DUMPDIR', '/var/lib/vz/dump')).resolve()
    if target != Path('/var/lib/vz/dump'):
        raise ValueError('backup_directory_not_approved')
    if target.stat().st_uid != 0:
        raise ValueError('backup_directory_owner_invalid')
    # VM archives contain the guest's session state and private keys. Proxmox
    # writes ordinary archives 0644; protect the whole destination before start.
    target.chmod(0o700)
    if sys.argv[1] == 'backup-end':
        archive = Path(os.environ.get('TARGET', ''))
        if (archive.is_symlink() or archive.parent != target or
                not re.fullmatch('vzdump-qemu-' + sys.argv[3] + r'-[0-9_\-]+\.vma\.zst', archive.name)
                or not archive.is_file() or archive.stat().st_uid != 0):
            raise ValueError('backup_archive_scope_invalid')
        archive.chmod(0o600)
        print('Pajio backup archive privacy verified')
        return
    config = json.loads(subprocess.check_output(['pvesh', 'get',
        '/nodes/pve01/qemu/' + sys.argv[3] + '/config', '--output-format', 'json']))
    if not approved_owner(sys.argv[3], config, scope):
        raise ValueError('backup_vm_owner_not_approved')
    required = worst_case_bytes(config) + RESERVE
    if shutil.disk_usage(target).free < required:
        raise ValueError('backup_storage_reserve_insufficient')
    print('Pajio backup storage reserve verified')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error, ValueError) else 'backup_preflight_failed', file=sys.stderr)
        raise SystemExit(1)
