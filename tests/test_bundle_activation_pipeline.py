"""Production activation orchestration with real durable device books, no SSH.

Only provider transports and the independent core health reader are synthetic.
The tests intentionally retain the real reserve/bootstrap/delivery/enrollment
books so method shapes and crash-recovery phases cannot be hidden by mocks.
"""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from wearing.cloud import bundle_activation_pipeline as pipeline
from wearing.cloud.bundle_activation import ActivationError, STAGE_ORDER
from wearing.cloud.bundle_activation_worker import LeaseLost
from wearing.cloud.device_bootstrap import BootstrapSpec
from wearing.cloud.device_enrollment import EnrollmentBook
from wearing.cloud.device_provisioning import ProvisionBook, ProvisionError, ResourcePromise, fingerprint
from wearing.mobile import resource_id
from test_device_bootstrap import KEY, settings
from test_device_enrollment import Adapter, config
from test_device_provisioning import Provider, SyntheticAdmission, policy, spec


def private(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o600)
    return path


class Transport(Provider, Adapter):
    def __init__(self):
        Provider.__init__(self)
        Adapter.__init__(self)
        self.clock = time.time()
        self.host = 'fixture-host'
        self.starts, self.installs, self.autostarts = [], [], []
        self.startup = {}
        self.after_stage = lambda stage: None
        self.cloud_ready = True
        self.native_ready = True

    def stage_network(self, item, owner, before, bundle):
        return {'network_staged': True, 'started': False,
                'bundle_sha256': bundle['bundle_sha256'],
                'config_sha256': self.inspect_vm(item.vmid).config_sha256}

    def verify_staged_network(self, *args):
        return None

    def assert_wake_capacity(self, *args):
        return None

    def power(self, action, item, owner, before):
        assert action == 'start'
        self.starts.append(item.vmid)
        old = self.inspect_vm(item.vmid)
        self.vms[self.vms.index(old)] = old.model_copy(update={'state': 'running'})

    def attest(self, item, owner, bundle):
        return {'owner_sha256': fingerprint(owner.model_dump()),
                'cloud_init_ready': self.cloud_ready,
                'machine_sha256': hashlib.sha256(str(item.vmid).encode()).hexdigest(),
                'ssh_host_key': KEY}

    def install_runtime(self, item, *args):
        self.installs.append(item.vmid)

    def runtime_status(self, item, owner, bundle, machine):
        return {'version': 1, 'owner_sha256': fingerprint(owner.model_dump()),
                'artifact_sha256': bundle['manifest']['artifact_sha256']}

    def delivery_evidence(self, *args):
        return {'network_isolated': True, 'native_ready': self.native_ready,
                'browser_ready': False, 'browser_setup_state': 'first_run_unverified'}

    def startup_config(self, item, owner):
        current = self.inspect_vm(item.vmid)
        after = hashlib.sha256(('startup:' + str(item.vmid)).encode()).hexdigest()
        return {'before_sha256': current.config_sha256, 'after_sha256': after,
                'onboot': self.startup.get(item.vmid, 0)}

    def set_autostart(self, item, owner, plan):
        self.autostarts.append(item.vmid)
        old = self.inspect_vm(item.vmid)
        self.vms[self.vms.index(old)] = old.model_copy(update={'config_sha256': plan['after_sha256']})
        self.startup[item.vmid] = 1

    def result(self, stage, item, owner, material):
        result = Adapter.result(self, stage, item, owner, material)
        if stage == 'prepare' and item.kind == 'android':
            result['inventory']['resources'][0].update(kind='android', methods=['phone.observe'])
        return result

    def apply(self, stage, *args):
        result = Adapter.apply(self, stage, *args)
        self.after_stage(stage)
        return result


@pytest.fixture
def environment(tmp_path, monkeypatch):
    key = private(tmp_path / 'operator-key', 'synthetic fixture only')
    private(Path(str(key) + '.pub'), KEY)
    ssh = private(tmp_path / 'config', 'Host fixture-host\n  HostName 127.0.0.1\n')
    installer = private(tmp_path / 'installer.py', '# fixture is never executed\n')
    tenant = {'host': 'fixture-core', 'root': '/srv/pajio-fixture'}
    specs = {'linux': spec(resource_id='computer_' + '1' * 20),
             'android': spec(request_id='b' * 32, kind='android', vmid=1201,
                             resource_id=resource_id('127.0.0.1:21201'))}
    devices = {}
    for kind, item in specs.items():
        boot = settings(network={'subnet': '10.78.1.0/30' if kind == 'linux' else '10.78.1.4/30',
                                 'tenant_ipv4': '10.77.101.2', 'turn_ipv4': '134.175.112.118'})
        devices[kind] = {'spec': item.model_dump(), 'bootstrap': boot.model_dump(),
                         'enrollment': config(guest_ipv4='10.78.1.2' if kind == 'linux' else '10.78.1.6').model_dump(),
                         'runtime_bundle': str(tmp_path / ('bundle-' + kind)), 'runtime_installer': str(installer)}
    plan = pipeline.ActivationPlan.model_validate({
        'bundle_id': 'c' * 32, 'tenant_id': 'tenant_a', 'instance_id': 'instance_fixture',
        'reservation_sha256': 'd' * 64, 'host': 'fixture-host', 'ssh_config': str(ssh),
        'identity_file': str(key), 'ledger_root': str(tmp_path / 'ledger'),
        'admission': {'control': {'host': 'fixture-control', 'root': '/srv/control'},
                      'operator_env': '/etc/operator.env', 'tenants': {'tenant_a': tenant}},
        'enrollment_sources': {'tenants': {'tenant_a': tenant}, 'devices': {
            item.resource_id: {'host': 'pajio-device-' + str(item.vmid)} for item in specs.values()}},
        'policy': policy().model_dump(), 'devices': devices,
        'files': {str(installer): hashlib.sha256(installer.read_bytes()).hexdigest()}})
    members = [{'kind': kind, **{k: getattr(item, k) for k in ('vmid', 'request_id', 'vcpus', 'memory_mib', 'disk_mib')}}
               for kind, item in specs.items()]
    members.insert(0, {'kind': 'core', 'vmid': 1101, 'request_id': 'e' * 32, 'vcpus': 1, 'memory_mib': 2048, 'disk_mib': 32768})
    raw = plan.model_dump_json()
    private(tmp_path / 'plans' / (plan.bundle_id + '.json'), raw)
    event = {'id': 'f' * 32, 'bundle_id': plan.bundle_id, 'tenant_id': plan.tenant_id,
             'instance_id': plan.instance_id, 'ownership_revision': 1, 'member_digest': '1' * 64,
             'user_id': 'user_fixture', 'state': 'reserved', 'members_json': {k: {'state': 'pending'} for k in pipeline.KINDS},
             'bundle': {'id': plan.bundle_id, 'tenant_id': plan.tenant_id, 'instance_id': plan.instance_id,
                        'reservation_sha256': plan.reservation_sha256, 'host': plan.host,
                        'worker_plan_sha256': hashlib.sha256(raw.encode()).hexdigest(), 'members_json': members}}
    transport = Transport()
    transport.extra['resource_promises'] = tuple(ResourcePromise(**m, purpose='invitation', tenant_id=plan.tenant_id,
        expires_at=int(time.time()) + 900, reservation_id='9' * 32, reservation_sha256=plan.reservation_sha256) for m in members)
    admission = SyntheticAdmission(clock=time.time)
    monkeypatch.setattr(pipeline, 'TrustedSSHAdmission', lambda **kwargs: admission)
    monkeypatch.setattr(pipeline, 'ProxmoxDevices', lambda **kwargs: transport)
    monkeypatch.setattr(pipeline, 'SSHBootstrapAdapter', lambda **kwargs: transport)
    monkeypatch.setattr(pipeline, 'SSHDeliveryAdapter', lambda **kwargs: transport)
    monkeypatch.setattr(pipeline, 'SSHEnrollmentAdapter', lambda **kwargs: transport)
    flow = pipeline.BundlePipeline(tmp_path)
    monkeypatch.setattr(flow, '_core', lambda p: {'core_ready': True, 'tenant_id': p.tenant_id, 'instance_id': p.instance_id})
    return SimpleNamespace(flow=flow, plan=plan, event=event, transport=transport, admission=admission, specs=specs)


def tick(env, guard=lambda: None):
    result = env.flow.advance(env.event, guard)
    env.event.update(state=result['state'], members_json=result['members'])
    return result


def until(env, step):
    for _ in range(30):
        result = tick(env)
        if result['step'] == step:
            return result
    raise AssertionError('requested stage not reached')


def test_actual_books_deliver_two_fresh_devices_and_recheck_before_ready(environment):
    env = environment
    results = []
    for _ in range(30):
        result = tick(env)
        results.append(result)
        if result['state'] == 'ready':
            break
    assert result['state'] == 'ready'
    assert all(v['state'] == 'ready' for v in result['members'].values())
    assert env.transport.starts == [1200, 1201]
    assert env.transport.installs == [1200, 1201]
    assert env.transport.autostarts == [1200, 1201]
    assert [STAGE_ORDER.index(r['state']) for r in results] == sorted(STAGE_ORDER.index(r['state']) for r in results)
    # A stored old ready result must not hide a current device backend failure.
    env.transport.native_ready = False
    reread = tick(env)
    assert reread['step'] == 'linux:verify'
    assert reread['members']['linux']['state'] != 'ready'
    assert env.transport.starts == [1200, 1201]


def test_pending_cloud_init_does_not_replay_start(environment):
    env = environment
    until(env, 'linux:network')
    env.transport.cloud_ready = False
    assert tick(env)['evidence']['result'] == {'waiting_for_cloud_init': True}
    assert tick(env)['evidence']['result'] == {'waiting_for_cloud_init': True}
    assert env.transport.starts == [1200]
    env.transport.cloud_ready = True
    assert tick(env)['step'] == 'linux:boot'
    assert env.transport.starts == [1200]


def test_member_scope_change_rejects_before_any_provider_change(environment):
    env = environment
    env.event['bundle']['members_json'][1]['request_id'] = '0' * 32
    with pytest.raises(ActivationError, match='activation_device_scope_changed'):
        tick(env)
    assert env.transport.calls == [] and env.transport.starts == []


def test_lost_clone_response_is_observed_without_second_clone(environment):
    env = environment
    until(env, 'linux:reserve')
    env.transport.clone_error = TimeoutError('synthetic lost response')
    with pytest.raises(ProvisionError, match='provider_outcome_unknown'):
        tick(env)
    env.transport.clone_error = None
    assert tick(env)['step'] == 'linux:clone'
    assert env.transport.calls.count('clone') == 1


def test_lease_loss_between_enrollment_stages_blocks_next_mutation(environment):
    env = environment
    until(env, 'linux:runtime')
    valid = True
    def guard():
        if not valid:
            raise LeaseLost('activation_lease_lost')
    def after(stage):
        nonlocal valid
        if stage == 'prepare':
            valid = False
    env.transport.after_stage = after
    env.transport.calls.clear()
    with pytest.raises((LeaseLost, ProvisionError)):
        tick(env, guard)
    assert [v for v in env.transport.calls if v in ('prepare', 'issue', 'configure', 'bind', 'activate')] == ['prepare']


def test_exact_core_probe_rejects_configured_but_unreachable_engine(monkeypatch, capsys):
    import os
    import pwd
    import sys
    import urllib.request
    from contextlib import contextmanager
    from wearing.cloud import instance
    calls = []
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setattr(pwd, 'getpwnam', lambda name: SimpleNamespace(pw_uid=123, pw_gid=123))
    for method in ('setgroups', 'setgid', 'setuid'):
        monkeypatch.setattr(os, method, lambda *args: None)
    monkeypatch.setattr(instance, 'load_instance', lambda root: SimpleNamespace(tenant_id='tenant_a', instance_id='instance_fixture', public_origin='https://pajio.test'))
    monkeypatch.setattr(instance, 'read_private', lambda path: 'synthetic-gateway-key')
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({'account': 'fixture', 'root': '/srv/fixture',
        'tenant_id': 'tenant_a', 'instance_id': 'instance_fixture', 'identity_id': 'daily'})))
    @contextmanager
    def request(req, **kwargs):
        calls.append(req.full_url)
        if req.full_url.endswith('/api/bootstrap'):
            body = {'configured': True, 'deployment': 'cloud', 'default_identity_id': 'daily', 'identities': [{'id': 'daily'}]}
        elif req.full_url.endswith('/api/status'):
            body = {'identity_id': 'daily', 'hermes': {'state': 'unavailable'}}
        else:
            raise AssertionError('unexpected request')
        yield SimpleNamespace(status=200, read=lambda limit: json.dumps(body).encode())
    monkeypatch.setattr(urllib.request, 'urlopen', request)
    with pytest.raises(SystemExit):
        exec(compile(pipeline.CORE_PROBE, '<actual-core-probe>', 'exec'), {})
    assert json.loads(capsys.readouterr().out) == {'error': 'core_not_ready'}
    assert any(path.endswith('/api/status') for path in calls)


@pytest.mark.parametrize('failure,expected', [
    ('QEMU guest agent is not running', 'fresh_os_attestation_pending'),
    ("VM 1200 qmp command 'guest-exec' failed - got timeout", 'fresh_os_attestation_pending'),
    ("VM 1200 qmp command 'guest-ping' failed - command timed out", 'fresh_os_attestation_pending'),
    ('timeout', 'fresh_os_attestation_pending'),
    ('QEMU guest agent is not enabled', 'proxmox_query_failed'),
    ("VM 9999 qmp command 'guest-exec' failed - got timeout", 'proxmox_query_failed'),
    ('permission denied; synthetic secret', 'proxmox_query_failed'),
    ('QEMU guest agent is not running\npermission denied', 'proxmox_query_failed'),
    ('malformed', 'proxmox_query_failed'),
])
def test_actual_host_qga_query_only_known_cold_start_condition_is_pending(monkeypatch, failure, expected):
    import re
    import subprocess
    from wearing.cloud.device_delivery_ssh import HOST
    # Execute the exact query in the host program after its owner/network
    # checks; stderr is a synthetic provider fixture, never a real log.
    query = HOST.split('source=__QGA_SOURCE__', 1)[-1] if '__QGA_SOURCE__' in HOST else HOST
    query = query[query.index('# This is a read-only observation'):query.index('v=json.loads(')]
    def run(argv, **kwargs):
        assert argv[:5] == ['qm', 'guest', 'exec', '1200', '--']
        assert kwargs['timeout'] == 45
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(argv, 45)
        if failure == 'malformed':
            return SimpleNamespace(returncode=0, stdout='not-json', stderr='')
        return SimpleNamespace(returncode=1, stdout='', stderr=failure)
    monkeypatch.setattr(subprocess, 'run', run)
    def fail(code):
        raise ProvisionError(code)
    with pytest.raises(ProvisionError, match='^' + expected + '$'):
        exec(compile(query, '<actual-host-qga-query>', 'exec'),
             {'subprocess': subprocess, 're': re, 'json': json, 'vid': 1200, 'source': 'fixture', 'fail': fail})


def test_observed_startup_config_cannot_drift_after_linux_is_delivered(environment):
    env = environment
    until(env, 'linux:startup')
    old = env.transport.inspect_vm(1200)
    env.transport.vms[env.transport.vms.index(old)] = old.model_copy(update={'vcpus': 1, 'config_sha256': '7' * 64})
    # The owner and onboot value still match, but the approved resource/config
    # image does not. Do not begin another member or publish ready from it.
    with pytest.raises((ActivationError, ProvisionError)):
        tick(env)
    assert env.transport.starts == [1200]


@pytest.mark.parametrize('write_happened', [True, False])
def test_startup_lost_response_reconciles_only_without_replaying(environment, write_happened):
    env = environment
    until(env, 'linux:pair')
    original = env.transport.set_autostart
    attempts = []
    def lost(item, owner, plan):
        attempts.append(item.vmid)
        if write_happened:
            original(item, owner, plan)
        raise TimeoutError('synthetic response lost')
    env.transport.set_autostart = lost
    with pytest.raises(TimeoutError):
        tick(env)
    env.transport.set_autostart = original
    if write_happened:
        assert tick(env)['step'] == 'linux:startup'
    else:
        with pytest.raises(ProvisionError, match='startup_outcome_unknown_no_replay'):
            tick(env)
    assert attempts == [1200]
    assert env.transport.autostarts == ([1200] if write_happened else [])
