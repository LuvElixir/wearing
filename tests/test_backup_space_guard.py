import importlib.util
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / 'deploy/on-prem'))
from operations_scope import config_fingerprint

spec = importlib.util.spec_from_file_location('backup_space', Path(__file__).parents[1] / 'deploy/on-prem/check-backup-space.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_full_disk_bound_ignores_only_explicit_nonbackup_disks():
    assert guard.worst_case_bytes({'scsi0': 'local-lvm:disk,size=32G',
        'ide2': 'local-lvm:cloudinit,media=cdrom,size=4M',
        'scsi1': 'local-lvm:scratch,backup=0,size=8G'}) >= 32 * 1024**3
    assert guard.worst_case_bytes({'scsi0': 'local-lvm:disk,size=32768M'}) == guard.worst_case_bytes({'scsi0': 'local-lvm:disk,size=32G'})


@pytest.mark.parametrize('config', [{}, {'scsi0': '/dev/unknown'}, {'scsi0': 'local-lvm:disk,size=unexpected'}])
def test_unknown_allocation_does_not_assume_free_space(config):
    with pytest.raises(ValueError):
        guard.worst_case_bytes(config)


def test_new_execution_guests_require_matching_provisioning_owner():
    import json
    owner = {'version': 1, 'kind': 'linux', 'tenant_id': 'synthetic', 'identity_id': 'daily',
             'resource_id': 'computer_example', 'request_id': 'a'*32, 'nonce': 'b'*64,
             'request_sha256': 'c'*64}
    config = {'description': json.dumps({'pajio_provisioning': owner})}
    scope = {'version': 1, 'guests': {'1411': {'config_sha256': config_fingerprint(config), 'services': ['nginx']}}}
    assert guard.approved_owner('1411', config, scope)
    assert guard.approved_owner('1411', {**config, 'lock': 'backup', 'digest': 'provider-token'}, scope)
    assert not guard.approved_owner('1412', config, scope)
    assert not guard.approved_owner('9999', config, scope)
    assert not guard.approved_owner('1411', {'tags': 'pajio'}, scope)
    assert not guard.approved_owner('1411', {'description': '{corrupt'}, scope)
    owner['tenant_id'] = 'different-user'
    assert not guard.approved_owner('1411', {'description': json.dumps({'pajio_provisioning': owner})}, scope)
    assert not guard.approved_owner('1411', {**config, 'lock': 'clone'}, scope)
    assert not guard.approved_owner('1411', {**config, 'scsi0': 'replacement-disk'}, scope)
