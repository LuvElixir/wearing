"""Execute the exact shipped SSH script against controlled Proxmox command IO."""
import io
import json
import os
import subprocess
import sys

import pytest

from wearing.cloud.device_provisioning import DeviceSpec, Owner, Policy, Template, fingerprint
from wearing.cloud.proxmox_devices import REMOTE


@pytest.fixture
def host(tmp_path, monkeypatch, capsys):
    configs = {9000: {'template': 1, 'cores': 2, 'memory': 4096, 'sockets': 1,
                      'scsi0': 'local-lvm:base-9000-disk-0,size=32G', 'digest': 'f' * 40,
                      'ide2': 'local-lvm:vm-9000-cloudinit,media=cdrom', 'onboot': 0,
                      'net0': 'virtio=00:00:00:00:00:01,bridge=template-only',
                      'sshkeys': 'fixture-public-key', 'ciuser': 'old-template-user'}}
    states = {9000: 'stopped'}
    mutations = []
    def digest(config):
        return fingerprint({k: v for k, v in config.items() if k != 'digest'})
    item = DeviceSpec(request_id='a' * 32, tenant_id='tenant_a', identity_id='daily',
                      resource_id='computer_a', kind='linux', vmid=1200)
    limits = Policy(node='pve01', storage='local-lvm', templates={
        'linux': Template(vmid=9000, config_sha256=digest(configs[9000]), clean_review_ref='synthetic_clean_review', disk_mib=32768)})
    owner = Owner(tenant_id=item.tenant_id, identity_id=item.identity_id, resource_id=item.resource_id,
                  request_id=item.request_id, request_sha256=fingerprint(item.model_dump()), nonce='b' * 64,
                  kind=item.kind, vcpus=item.vcpus, memory_mib=item.memory_mib, disk_mib=item.disk_mib)

    def run(argv, **kwargs):
        if argv[0] == 'pvesh':
            assert argv[1] == 'get'
            path = argv[2]
            if path == '/nodes/pve01/status':
                value = {'cpuinfo': {'cores': 16, 'sockets': 1}, 'memory': {'total': 65536 << 20, 'available': 60000 << 20}}
            elif path == '/cluster/resources':
                value = [{'vmid': vmid, 'node': 'pve01', 'type': 'qemu', 'status': states[vmid]} for vmid in configs]
            elif path == '/nodes/pve01/storage/local-lvm/status':
                value = {'type': 'lvmthin', 'active': 1, 'enabled': 1, 'total': 1048576 << 20, 'avail': 900000 << 20}
            elif path == '/storage/local-lvm':
                value = {'vgname': 'pve', 'thinpool': 'data'}
            elif '/qemu/' in path and path.endswith('/config'):
                value = configs[int(path.split('/')[-2])]
            elif '/qemu/' in path and path.endswith('/status/current'):
                value = {'status': states[int(path.split('/')[-3])]}
            else:
                raise AssertionError(argv)
        elif argv[0] == 'lvs':
            value = {'report': [{'lv': [{'vg_name': 'pve', 'pool_lv': 'data', 'lv_size': str(32768 << 20)} for _ in configs]}]}
        elif argv[:2] == ['qm', 'clone']:
            mutations.append(argv)
            source, target = int(argv[2]), int(argv[3])
            assert target not in configs
            options = dict(zip(argv[4::2], argv[5::2]))
            assert options['--full'] == '1' and options['--storage'] == 'local-lvm'
            configs[target] = {**configs[source], 'description': options['--description'], 'template': 0}
            states[target] = 'stopped'
            return subprocess.CompletedProcess(argv, 0, '', '')
        elif argv[:2] == ['qm', 'set']:
            mutations.append(argv)
            target = int(argv[2]);options = dict(zip(argv[3::2], argv[4::2]))
            assert options['--digest'] == configs[target]['digest']
            for key in options.get('--delete', '').split(','):
                configs[target].pop(key, None)
            for key in ('memory', 'cores', 'sockets', 'balloon', 'onboot'):
                if '--' + key in options:
                    configs[target][key] = int(options['--' + key])
            return subprocess.CompletedProcess(argv, 0, '', '')
        else:
            raise AssertionError('unexpected native command')
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), '')

    def execute(action, **extra):
        payload = {'node': 'pve01', 'storage': 'local-lvm', 'vg': 'pve', 'pool': 'data',
                   'action': action, 'spec': item.model_dump(), 'policy': limits.model_dump(),
                   'owner': owner.model_dump(), **extra}
        fds = []
        original_open = os.open
        def open_lock(path, flags, mode=0o777):
            assert path == '/run/lock/pajio-device-provision.lock'
            fd = original_open(tmp_path / 'host.lock', flags, mode);fds.append(fd);return fd
        with monkeypatch.context() as patch:
            patch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload)))
            patch.setattr(subprocess, 'run', run)
            patch.setattr(os, 'open', open_lock)
            try:
                exec(compile(REMOTE, '<pajio-proxmox-remote>', 'exec'), {})
            except SystemExit:
                pass
            finally:
                for fd in fds:
                    os.close(fd)
        return json.loads(capsys.readouterr().out)
    return execute, configs, states, mutations, item, owner, digest


def test_remote_clone_records_owner_atomically_and_leaves_vm_stopped(host):
    execute, configs, states, mutations, item, owner, digest = host
    assert execute('clone_stopped') == {'ok': True, 'started': False}
    assert json.loads(configs[1200]['description']) == {'pajio_provisioning': owner.model_dump()}
    assert states[1200] == 'stopped'
    assert [command[1] for command in mutations] == ['clone']
    assert execute('clone_stopped')['error'] == 'vm_id_or_owner_conflict'
    assert len(mutations) == 1


def test_remote_prepare_cas_removes_template_network_and_bootstrap_credentials(host):
    execute, configs, _, mutations, _, _, digest = host
    execute('clone_stopped')
    result = execute('prepare_stopped', config_sha256=digest(configs[1200]))
    assert result['ok']
    assert not {'net0', 'ciuser', 'sshkeys'} & configs[1200].keys()
    assert configs[1200]['onboot'] == configs[1200]['balloon'] == 0
    assert configs[1200]['memory'] == 4096 and configs[1200]['cores'] == 2
    assert [command[1] for command in mutations] == ['clone', 'set']


@pytest.mark.parametrize('change', ['foreign_owner', 'running', 'locked', 'changed_config'])
def test_remote_rechecks_owner_state_and_digest_before_any_configuration(host, change):
    execute, configs, states, mutations, _, _, digest = host
    execute('clone_stopped')
    approved = digest(configs[1200])
    if change == 'foreign_owner': configs[1200]['description'] = '{}'
    elif change == 'running': states[1200] = 'running'
    elif change == 'locked': configs[1200]['lock'] = 'clone'
    else: configs[1200]['memory'] = 8192
    assert 'error' in execute('prepare_stopped', config_sha256=approved)
    assert [command[1] for command in mutations] == ['clone']


def test_remote_host_final_capacity_fence_blocks_create_without_ledger_reliance(host):
    execute, configs, states, mutations, *_ = host
    for vmid in range(1000, 1008):
        configs[vmid] = {**configs[9000], 'template': 0};states[vmid] = 'running'
    assert execute('clone_stopped')['error'] == 'host_capacity_changed'
    assert mutations == []


def test_remote_inventory_does_not_disclose_template_keys_or_vm_config(host):
    execute, _, _, mutations, *_ = host
    result = execute('inventory')
    assert 'fixture-public-key' not in json.dumps(result)
    assert result['vms'][0]['config_sha256']
    assert result['committed_storage_mib'] == 32768
    assert mutations == []


@pytest.mark.parametrize('reuse', ['tenant_kind', 'resource', 'request'])
def test_remote_host_fence_rejects_binding_reuse_from_another_ledger(host, reuse):
    execute, configs, states, mutations, item, owner, digest = host
    prior = owner.model_copy(update={'request_id': 'c' * 32, 'resource_id': 'computer_c', 'tenant_id': 'tenant_c'})
    if reuse == 'tenant_kind': prior = prior.model_copy(update={'tenant_id': item.tenant_id})
    elif reuse == 'resource': prior = prior.model_copy(update={'resource_id': item.resource_id})
    else: prior = prior.model_copy(update={'request_id': item.request_id})
    configs[1201] = {**configs[9000], 'template': 0,
                     'description': json.dumps({'pajio_provisioning': prior.model_dump()})}
    states[1201] = 'stopped'
    assert execute('clone_stopped')['error'] == 'device_binding_conflict'
    assert mutations == []


def test_exact_startup_transport_only_sets_reviewed_onboot(host, monkeypatch):
    from wearing.cloud.device_delivery_ssh import STARTUP_REMOTE
    execute, configs, states, mutations, item, owner, digest = host
    execute('clone_stopped')
    states[item.vmid] = 'running'
    before = dict(configs[item.vmid])
    monkeypatch.setattr(sys.modules[__name__], 'REMOTE', STARTUP_REMOTE)
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    plan = execute('startup_plan')
    assert plan['before_sha256'] == digest(before) and plan['onboot'] == 0
    result = execute('startup_apply', plan=plan)
    assert result['onboot'] == 1 and result['before_sha256'] == plan['after_sha256']
    assert configs[item.vmid] == {**before, 'onboot': 1}
    assert states[item.vmid] == 'running'
    assert mutations[-1] == ['qm', 'set', str(item.vmid), '--digest', before['digest'], '--onboot', '1']
    assert execute('startup_apply', plan=plan)['error'] == 'device_configuration_changed'
    assert len(mutations) == 2  # Clone plus one CAS configuration change; no repeat.


@pytest.mark.parametrize('change', ['owner', 'lock', 'digest', 'unprivileged'])
def test_startup_transport_rejects_changed_scope_before_mutation(host, monkeypatch, change):
    from wearing.cloud.device_delivery_ssh import STARTUP_REMOTE
    execute, configs, _, mutations, item, owner, digest = host
    execute('clone_stopped')
    monkeypatch.setattr(sys.modules[__name__], 'REMOTE', STARTUP_REMOTE)
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    plan = execute('startup_plan')
    if change == 'owner': configs[item.vmid]['description'] = '{}'
    elif change == 'lock': configs[item.vmid]['lock'] = 'backup'
    elif change == 'digest': configs[item.vmid]['memory'] = 8192
    else: monkeypatch.setattr(os, 'geteuid', lambda: 1000)
    assert 'error' in execute('startup_apply', plan=plan)
    assert len(mutations) == 1
