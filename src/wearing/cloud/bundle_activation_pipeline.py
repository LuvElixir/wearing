"""Fixed Core/Linux/Android delivery pipeline over existing ownership books."""
from __future__ import annotations

import hashlib
import json
import ipaddress
import os
from pathlib import Path
import shlex
import subprocess
import time

from pydantic import Field, model_validator

from .bundle_activation import ActivationError, KINDS, STAGE_ORDER
from .commands import Record, Identifier
from .device_admission import AdmissionSources, TrustedSSHAdmission
from .device_bootstrap import BootstrapBook, BootstrapSpec
from .device_bootstrap_ssh import SSHBootstrapAdapter
from .device_delivery import DeviceDelivery
from .device_delivery_ssh import SSHDeliveryAdapter
from .device_enrollment import EnrollmentBook, EnrollmentSpec, EnrollmentSources, SSHEnrollmentAdapter
from .device_provisioning import DeviceSpec, Policy, ProvisionBook, ProvisionError, fingerprint
from .instance import read_private
from .proxmox_devices import ProxmoxDevices


class DevicePlan(Record):
    spec: DeviceSpec
    bootstrap: BootstrapSpec
    enrollment: EnrollmentSpec
    runtime_bundle: str
    runtime_installer: str


class ActivationPlan(Record):
    version: int = Field(default=1, ge=1, le=1, strict=True)
    bundle_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    tenant_id: Identifier
    instance_id: Identifier
    reservation_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    host: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')
    node: str = 'pve01'
    ssh_config: str
    identity_file: str
    ledger_root: str
    admission: AdmissionSources
    enrollment_sources: EnrollmentSources
    policy: Policy
    devices: dict[str, DevicePlan]
    files: dict[str, str]

    @model_validator(mode='after')
    def checked(self):
        if set(self.devices) != {'linux', 'android'} or self.node != 'pve01':
            raise ValueError('activation_device_pair_required')
        if self.policy.node != self.node:
            raise ValueError('activation_host_changed')
        if (set(self.admission.tenants) != {self.tenant_id}
                or self.enrollment_sources.tenants != self.admission.tenants
                or self.devices['linux'].spec.identity_id != self.devices['android'].spec.identity_id
                or self.devices['linux'].spec.vmid == self.devices['android'].spec.vmid):
            raise ValueError('activation_metadata_scope_changed')
        if set(self.enrollment_sources.devices) != {d.spec.resource_id for d in self.devices.values()}:
            raise ValueError('activation_device_sources_changed')
        paths = [self.ssh_config, self.identity_file, self.ledger_root]
        for kind, item in self.devices.items():
            if (item.spec.kind != kind or item.spec.tenant_id != self.tenant_id
                    or item.bootstrap.node != self.node
                    or item.enrollment.artifact_sha256 != item.bootstrap.artifact_sha256):
                raise ValueError('activation_plan_scope_changed')
            guest = str(ipaddress.ip_network(item.bootstrap.network.subnet).network_address + 2)
            if (self.enrollment_sources.devices[item.spec.resource_id].host != 'pajio-device-' + str(item.spec.vmid)
                    or item.enrollment.guest_ipv4 != guest
                    or item.enrollment.tenant_endpoint.rstrip('/') != 'https://' + item.bootstrap.network.tenant_ipv4 + ':8444'):
                raise ValueError('activation_network_scope_changed')
            paths.extend((item.runtime_bundle, item.runtime_installer))
            if item.runtime_installer not in self.files:
                raise ValueError('activation_installer_pin_required')
        if any(not Path(p).is_absolute() or any(ord(c) < 32 for c in p) for p in paths):
            raise ValueError('activation_absolute_paths_required')
        if any(not Path(p).is_absolute() or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha)
               for p, sha in self.files.items()):
            raise ValueError('activation_artifact_pin_invalid')
        return self


CORE_PROBE = r'''
import json,os,pwd,sys,urllib.request
from pathlib import Path
from urllib.parse import urlparse
from wearing.cloud.instance import load_instance,read_private
p=json.load(sys.stdin)
try:
 assert os.geteuid()==0
 account=pwd.getpwnam(p['account']);assert account.pw_uid!=0
 os.setgroups([]);os.setgid(account.pw_gid);os.setuid(account.pw_uid)
 root=Path(p['root']);instance=load_instance(root)
 assert instance.tenant_id==p['tenant_id'] and instance.instance_id==p['instance_id']
 key=read_private(root/'gateway.key').strip()
 headers={'Authorization':'Bearer '+key,'X-Wearing-Tenant':p['tenant_id'],
          'X-Wearing-Identity':p['identity_id'],'Host':urlparse(instance.public_origin).netloc}
 req=urllib.request.Request('http://127.0.0.1:8765/api/bootstrap',headers=headers)
 with urllib.request.urlopen(req,timeout=10) as response:
  assert response.status==200;raw=response.read(262145);assert len(raw)<=262144
 value=json.loads(raw)
 assert value.get('configured') is True and value.get('deployment')=='cloud'
 assert value.get('default_identity_id')==p['identity_id']
 assert any(v.get('id')==p['identity_id'] for v in value.get('identities',[]))
 with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8765/api/status',headers=headers),timeout=10) as response:
  assert response.status==200;raw=response.read(262145);assert len(raw)<=262144
 status=json.loads(raw)
 assert status.get('identity_id')==p['identity_id'] and status.get('hermes',{}).get('state')=='reachable'
 print(json.dumps({'core_ready':True,'tenant_id':p['tenant_id'],'instance_id':p['instance_id']}))
except Exception:
 print(json.dumps({'error':'core_not_ready'}));sys.exit(1)
'''


class BundlePipeline:
    def __init__(self, root, *, runner=subprocess.run, clock=time.time):
        self.root, self.runner, self.clock = Path(root), runner, clock

    def _plan(self, event):
        bundle = event['bundle']
        ident = bundle['id']
        if (not isinstance(ident, str) or len(ident) != 32
                or any(c not in '0123456789abcdef' for c in ident)):
            raise ActivationError('activation_bundle_invalid')
        raw = read_private(self.root / 'plans' / (ident + '.json'))
        if hashlib.sha256(raw.encode()).hexdigest() != bundle['worker_plan_sha256']:
            raise ActivationError('activation_plan_changed')
        plan = ActivationPlan.model_validate_json(raw)
        for name in ('tenant_id', 'instance_id', 'reservation_sha256', 'host'):
            if getattr(plan, name) != bundle[name]:
                raise ActivationError('activation_bundle_changed')
        if plan.bundle_id != ident or event['bundle_id'] != ident:
            raise ActivationError('activation_bundle_changed')
        members = bundle['members_json']
        members = json.loads(members) if isinstance(members, str) else members
        if isinstance(members, dict):
            members = [dict(v, kind=k) for k, v in members.items()]
        if len(members) != 3 or {m['kind'] for m in members} != set(KINDS):
            raise ActivationError('activation_bundle_changed')
        for kind, item in plan.devices.items():
            member = next(m for m in members if m['kind'] == kind)
            if any(member[k] != getattr(item.spec, k) for k in
                   ('vmid', 'request_id', 'vcpus', 'memory_mib', 'disk_mib')):
                raise ActivationError('activation_device_scope_changed')
        # Executable installers and runtime bytes are pinned by the operator's
        # immutable worker plan, never by a user-supplied request.
        for name, expected in plan.files.items():
            path = Path(name)
            if (path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid()
                    or path.stat().st_mode & 0o022):
                raise ActivationError('activation_artifact_unsafe')
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                    raise ActivationError('activation_artifact_changed')
        return plan, members

    def _core(self, plan):
        target = plan.admission.tenants.get(plan.tenant_id)
        if target is None:
            raise ActivationError('core_target_unregistered')
        identity = plan.devices['linux'].spec.identity_id
        command = shlex.join(['sudo', '-n', target.python, '-c', CORE_PROBE])
        result = self.runner(['ssh', '-F', plan.ssh_config, '-o', 'BatchMode=yes', '-o',
            'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', target.host, command],
            input=json.dumps({'root': target.root, 'account': target.account, 'tenant_id': plan.tenant_id,
                              'instance_id': plan.instance_id, 'identity_id': identity}),
            capture_output=True, text=True, timeout=30)
        if result.returncode or len(result.stdout) > 2048:
            raise ActivationError('core_not_ready')
        expected = {'core_ready': True, 'tenant_id': plan.tenant_id, 'instance_id': plan.instance_id}
        if json.loads(result.stdout) != expected:
            raise ActivationError('core_not_ready')
        return expected

    def advance(self, event, lease_check):
        plan, members = self._plan(event)
        trusted = TrustedSSHAdmission(ssh_config=plan.ssh_config, sources=plan.admission, runner=self.runner)
        class LeasedAdmission:
            def check(self, spec):
                lease_check()
                proof = trusted.check(spec)
                lease_check()
                return proof
        admission = LeasedAdmission()
        base = {'ssh_config': plan.ssh_config, 'host': plan.host, 'node': plan.node,
                'storage': plan.policy.storage, 'allow_create': True, 'runner': self.runner}
        provider = ProxmoxDevices(**base)
        book = ProvisionBook(plan.ledger_root, operator=True, admission=admission)
        bootstrap, delivery, enrollment = BootstrapBook(book), DeviceDelivery(book), EnrollmentBook(book)

        def guard():
            lease_check()
            for item in plan.devices.values():
                proof = admission.check(item.spec)
                if any(getattr(proof, k) != event[k] for k in
                       ('tenant_id', 'instance_id', 'ownership_revision', 'member_digest')) or proof.owner_user_id != event['user_id']:
                    raise ActivationError('activation_owner_changed')

        guard()
        inventory = provider.inventory()
        promises = [p for p in inventory.resource_promises if p.reservation_sha256 == plan.reservation_sha256]
        if len(promises) != 3:
            raise ActivationError('activation_reservation_changed')
        for member in members:
            matches = [p for p in promises if p.kind == member['kind']]
            if (len(matches) != 1 or matches[0].purpose != 'invitation'
                    or matches[0].tenant_id != plan.tenant_id
                    or any(getattr(matches[0], k) != member[k] for k in
                           ('vmid', 'request_id', 'vcpus', 'memory_mib', 'disk_mib'))):
                raise ActivationError('activation_reservation_changed')
        core = self._core(plan)
        progress = {k: {'state': 'pending'} for k in KINDS}
        progress['core'] = {'state': 'ready'}
        evidence = {'core': core}

        def result(state, step, data, kind=None, reason=None):
            guard()
            if state in STAGE_ORDER and event['state'] in STAGE_ORDER:
                state = STAGE_ORDER[max(STAGE_ORDER.index(state), STAGE_ORDER.index(event['state']))]
            if kind:
                progress[kind] = {'state': 'preparing'}
            return {'state': state, 'step': step, 'members': progress, 'reason': reason,
                    'evidence': {'bundle_id': plan.bundle_id, 'step': step, 'result': data}}

        for kind in ('linux', 'android'):
            item = plan.devices[kind]
            request = item.spec.request_id
            try:
                current = book.status(request)
            except ProvisionError as error:
                if str(error) != 'request_not_found':
                    raise
                preview = book.plan(item.spec, plan.policy, provider)
                if not preview['admitted']:
                    raise ActivationError('activation_capacity_unavailable')
                guard()
                created = book.reserve(item.spec, plan.policy, provider, plan_sha256=preview['plan_sha256'])
                return result('preparing', kind + ':reserve', created, kind)
            if current['state'] != 'staged':
                guard()
                staged = book.apply(request, provider, plan_sha256=current['plan_sha256'])
                return result('preparing', kind + ':clone', staged, kind)
            with book._tx() as db:
                network = db.execute('SELECT * FROM device_bootstrap WHERE request=?', (request,)).fetchone()
            if not network or network['state'] != 'network_staged':
                transport = SSHBootstrapAdapter(**base, sources={'tenants': {}, 'devices': {}})
                bundle = bootstrap.plan(request, item.bootstrap, transport)
                guard()
                staged = bootstrap.stage_network(request, item.bootstrap, transport, reviewed_sha256=bundle['bundle_sha256'])
                return result('preparing', kind + ':network', staged, kind)
            host_delivery = SSHDeliveryAdapter(**base, delivery_sources=plan.enrollment_sources,
                runtime_bundle=item.runtime_bundle, installer=item.runtime_installer,
                host_memory_mib=plan.policy.host_memory_mib, host_cores=plan.policy.host_cores)
            try:
                delivered = delivery.status(request)
            except ProvisionError as error:
                if str(error) != 'delivery_not_started':
                    raise
                delivered = {'state': 'new'}
            if delivered['state'] in ('new', 'boot_sent'):
                guard()
                try:
                    booted = delivery.boot(request, host_delivery, reviewed_sha256=network['bundle_sha256'])
                except ProvisionError as error:
                    if str(error) != 'fresh_os_attestation_pending':
                        raise
                    return result('installing', kind + ':boot', {'waiting_for_cloud_init': True}, kind)
                return result('installing', kind + ':boot', booted, kind)
            # This re-reads the host-authenticated QGA key before using guest SSH.
            binding = delivery.bind_ssh(request, host_delivery, identity_file=plan.identity_file, base_config=plan.ssh_config)
            guest_base = {**base, 'ssh_config': binding['ssh_config']}
            guest_delivery = SSHDeliveryAdapter(**guest_base, delivery_sources=plan.enrollment_sources,
                runtime_bundle=item.runtime_bundle, installer=item.runtime_installer,
                host_memory_mib=plan.policy.host_memory_mib, host_cores=plan.policy.host_cores)
            if delivered['state'] in ('bootstrapped', 'runtime_installing'):
                guard()
                installed = delivery.install_runtime(request, guest_delivery)
                return result('installing', kind + ':runtime', installed, kind)
            pairing = SSHEnrollmentAdapter(config=binding['ssh_config'], sources=plan.enrollment_sources,
                                           allow_apply=True, runner=self.runner)
            paired = enrollment.inspect(request, pairing)
            if paired.get('paired_scope_matches') is not True:
                planned = enrollment.plan(request, item.enrollment, pairing)
                guard()
                paired = enrollment.enroll(request, item.enrollment, pairing, reviewed_sha256=planned['plan_sha256'])
                return result('pairing', kind + ':pair', {'paired': paired.get('paired_scope_matches') is True}, kind)
            guard()
            verified = delivery.verify(request, guest_delivery, pairing)
            if verified.get('device_ready') is not True:
                return result('pairing', kind + ':verify', verified, kind)
            with book._tx() as db:
                startup = db.execute('SELECT * FROM device_startup_config WHERE request=?', (request,)).fetchone()
            if startup is None or startup['state'] != 'verified':
                # Reconcile an interrupted onboot write from its frozen plan;
                # never generate a new intent over an unknown outcome.
                startup_plan = (json.loads(startup['plan']) if startup else
                                delivery.startup_plan(request, guest_delivery))
                plan_sha = startup_plan.pop('plan_sha256', None)
                startup_plan.pop('product_ready', None)
                guard()
                autostart = delivery.finalize_startup(request, guest_delivery,
                    reviewed_sha256=plan_sha or fingerprint(startup_plan))
                return result('pairing', kind + ':startup', autostart, kind)
            observed = guest_delivery.startup_config(item.spec, delivery._bound(request)[1])
            if (observed.get('onboot') != 1
                    or observed.get('before_sha256') != json.loads(startup['plan'])['after_sha256']):
                raise ActivationError('activation_startup_changed')
            progress[kind] = {'state': 'ready'}
            evidence[kind] = {'evidence_sha256': verified['evidence_sha256'], 'verified_at': verified['verified_at']}
        # Both devices were freshly checked in this pass and the owner is still
        # identical. A stored earlier ready bit cannot complete the bundle.
        guard()
        evidence['core'] = self._core(plan)
        return {'state': 'ready', 'step': 'complete', 'members': progress,
                'reason': None, 'evidence': evidence}
