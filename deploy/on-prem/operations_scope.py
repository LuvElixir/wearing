"""Root-reviewed guest scope shared by host monitoring and backup guards."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

SCOPE = Path('/etc/pajio-operations-scope.json')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def config_fingerprint(config):
    # Proxmox may hold its backup lock when the pre-backup hook runs. Other
    # locks are never accepted. All ownership, disks and network fields bind.
    return fingerprint({k: v for k, v in config.items() if k not in ('digest', 'lock')})


def validate(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('operations_scope_invalid')
    guests = value.get('guests')
    if not isinstance(guests, dict) or not guests:
        raise ValueError('operations_scope_empty')
    for vmid, guest in guests.items():
        if (not isinstance(vmid, str) or not re.fullmatch(r'[1-9][0-9]{2,8}', vmid)
                or not isinstance(guest, dict) or not isinstance(guest.get('config_sha256'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', guest['config_sha256'])):
            raise ValueError('operations_guest_invalid')
        services = guest.get('services')
        if (not isinstance(services, list) or not services
                or any(not isinstance(x, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9@_.-]{0,100}', x)
                       for x in services) or len(services) != len(set(services))):
            raise ValueError('operations_services_invalid')
    return value


def load_scope(path=SCOPE):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('operations_scope_permissions_invalid')
        return validate(json.load(handle))


def approved(vmid, config, scope):
    entry = scope['guests'].get(str(vmid))
    return bool(entry and config.get('lock') in (None, 'backup') and not config.get('template')
                and config_fingerprint(config) == entry['config_sha256'])
