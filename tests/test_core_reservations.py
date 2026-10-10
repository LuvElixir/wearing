import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from wearing.cloud.core_reservations import CORE_RESERVATIONS_SOURCE


def validator(tmp_path):
    namespace = {}
    exec(CORE_RESERVATIONS_SOURCE, namespace)
    actual_lstat, actual_fstat = Path.lstat, os.fstat

    def root_stat(value):
        return SimpleNamespace(st_mode=value.st_mode, st_uid=0, st_nlink=value.st_nlink, st_size=value.st_size)

    # Tests run unprivileged; only UID is mapped, actual permissions/link counts
    # and O_NOFOLLOW behavior still come from real temporary files.
    return namespace['core_reservations'], patch.object(Path, 'lstat', lambda p: root_stat(actual_lstat(p))), patch.object(os, 'fstat', lambda fd: root_stat(actual_fstat(fd)))


def reservation(tmp_path, vmid=1401):
    tmp_path.chmod(0o700)
    directory = tmp_path / str(vmid)
    directory.mkdir(mode=0o700)
    value = dict(version=1, node='pve01', vmid=vmid, tenant_id='pajio_personal_primary',
                 request_id='a' * 32, vcpus=1, memory_mib=2048, disk_mib=32768, image_sha256='b' * 64)
    path = directory / 'reservation.json'
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return value, path


def test_absent_and_stopped_core_remain_promised(tmp_path):
    value, path = reservation(tmp_path)
    check, a, b = validator(tmp_path)
    with a, b:
        assert check([], str(tmp_path)) == [dict(vmid=1401, vcpus=1, memory_mib=2048, disk_mib=32768)]
        row = dict(vmid=1401, state='stopped', template=False, owner=None, vcpus=1, memory_mib=1024, disk_mib=32768)
        with patch.object(subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps({'description': json.dumps({'pajio_core_provisioning': value})}))):
            assert check([row], str(tmp_path))[0]['memory_mib'] == 2048


def test_existing_vm_must_match_entire_original_core_scope(tmp_path):
    value, path = reservation(tmp_path)
    check, a, b = validator(tmp_path)
    row = dict(vmid=1401, state='running', template=False, owner=None, vcpus=1, memory_mib=2048, disk_mib=32768)
    with a, b:
        for owner in ({'pajio_core_provisioning': {**value, 'tenant_id': 'qa'}}, {},
                      {'pajio_core_provisioning': {**value, 'request_id': 'c' * 32}}):
            with patch.object(subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps({'description': json.dumps(owner)}))):
                with pytest.raises(ValueError):
                    check([row], str(tmp_path))


def test_unsafe_or_interrupted_reservation_fails_closed(tmp_path):
    value, path = reservation(tmp_path)
    check, a, b = validator(tmp_path)
    with a, b:
        path.chmod(0o644)
        with pytest.raises(ValueError):
            check([], str(tmp_path))
        path.chmod(0o600)
        path.unlink()
        with pytest.raises(FileNotFoundError):
            check([], str(tmp_path))
        path.symlink_to('/tmp/nonexistent-core-reservation')
        with pytest.raises(OSError):
            check([], str(tmp_path))


def test_duplicate_tenant_and_extra_success_flag_are_not_authority(tmp_path):
    value, path = reservation(tmp_path)
    check, a, b = validator(tmp_path)
    with a, b:
        path.write_text(json.dumps({**value, 'compute_released': True}))
        with pytest.raises(ValueError):
            check([], str(tmp_path))
        path.write_text(json.dumps(value))
        second = tmp_path / '1402'
        second.mkdir(mode=0o700)
        other = second / 'reservation.json'
        other.write_text(json.dumps({**value, 'vmid': 1402, 'request_id': 'd' * 32}))
        other.chmod(0o600)
        with pytest.raises(ValueError):
            check([], str(tmp_path))
