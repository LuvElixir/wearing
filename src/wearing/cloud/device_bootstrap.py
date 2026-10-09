"""Deterministic per-device bootstrap artifacts; credentials never enter templates.

Rendering is offline. Applying requires an already reserved/stopped owned VM and
an operator-reviewed artifact digest. Network rules are unique to the VM bridge.
"""
import base64
import ipaddress
import json
from pathlib import Path
import re

from pydantic import Field, model_validator
from .commands import Record
from .device_provisioning import DeviceSpec, Owner, Policy, ProvisionError, encoded, fingerprint


class BootstrapNetwork(Record):
    subnet: str
    tenant_ipv4: str
    turn_ipv4: str
    uplink: str = Field(default='vmbr0', pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,14}$')

    @model_validator(mode='after')
    def checked(self):
        network = ipaddress.ip_network(self.subnet, strict=True)
        tenant, turn = ipaddress.ip_address(self.tenant_ipv4), ipaddress.ip_address(self.turn_ipv4)
        if (network.version != 4 or network.prefixlen != 30 or not network.subnet_of(ipaddress.ip_network('10.78.0.0/16'))
                or tenant.version != 4 or not tenant.is_private or tenant in network
                or turn.version != 4 or not turn.is_global):
            raise ValueError('invalid_bootstrap_network')
        return self


class BootstrapSpec(Record):
    node: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,14}$')
    network: BootstrapNetwork
    operator_ssh_public_key: str = Field(max_length=1024)
    artifact_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def public_key(self):
        # Public key only; no PEM/private key, command= options or extra lines.
        if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}(?: [A-Za-z0-9_.@-]{1,80})?', self.operator_ssh_public_key):
            raise ValueError('ed25519_public_key_required')
        blob = base64.b64decode(self.operator_ssh_public_key.split()[1], validate=True)
        if len(blob) != 51 or blob[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
            raise ValueError('ed25519_public_key_required')
        return self


LINUX_PACKAGES = ('xvfb','xfce4-session','xfwm4','xfce4-panel','xfdesktop4','dbus-x11','imagemagick',
    'xauth','xdotool','x11-utils','python3-gi','python3-pyatspi','gir1.2-gtk-3.0',
    'at-spi2-core','fonts-noto-cjk','locales','python3-venv','qemu-guest-agent','nginx','curl','ca-certificates','gnupg')
ANDROID_PACKAGES = ('docker.io','adb','python3-venv','libatomic1',
    'qemu-guest-agent','nginx','curl','ca-certificates','gnupg')


def render(spec, owner, bootstrap):
    if (owner.request_sha256 != fingerprint(spec.model_dump()) or owner.tenant_id != spec.tenant_id
            or owner.resource_id != spec.resource_id or owner.identity_id != spec.identity_id or owner.kind != spec.kind):
        raise ProvisionError('bootstrap_owner_mismatch')
    if spec.kind == 'android':
        from ..mobile import resource_id
        if spec.vmid > 45535 or spec.resource_id != resource_id('127.0.0.1:' + str(20000 + spec.vmid)):
            raise ProvisionError('android_unique_transport_binding_required')
    network = ipaddress.ip_network(bootstrap.network.subnet)
    gateway, guest = str(network.network_address + 1), str(network.network_address + 2)
    bridge = 'pj' + str(spec.vmid)
    if len(bridge) > 15: raise ProvisionError('bootstrap_bridge_invalid')
    instance_id = 'pajio-' + fingerprint(owner.model_dump())[:32]
    # cloud-init JSON is valid YAML and contains no account/model/pairing secrets.
    user = {'users':[{'name':'pajio-admin','lock_passwd':True,'shell':'/bin/bash',
                     'sudo':['ALL=(ALL) NOPASSWD:ALL'],'ssh_authorized_keys':[bootstrap.operator_ssh_public_key]}],
            'disable_root':True,'ssh_pwauth':False,'ssh_deletekeys':True,'ssh_genkeytypes':['ed25519'],
            'package_update':True,'packages':list(LINUX_PACKAGES if spec.kind=='linux' else ANDROID_PACKAGES),
            'write_files':[{'path':'/etc/pajio-native/device-owner.json','owner':'root:root','permissions':'0600',
                            'content':encoded(owner.model_dump())},
                           {'path':'/etc/pajio-native/bootstrap-expected.json','owner':'root:root','permissions':'0600',
                            'content':encoded({'version':1,'owner_sha256':fingerprint(owner.model_dump()),
                                               'artifact_sha256':bootstrap.artifact_sha256})}],
            'runcmd':[['systemctl','enable','--now','qemu-guest-agent']],
            'final_message':'Pajio base OS ready. Device delivery verification is still required.'}
    metadata = {'instance-id': instance_id, 'local-hostname': 'pajio-' + str(spec.vmid)}
    net = {'version':2,'ethernets':{'device0':{'match':{'name':'en*'},'dhcp4':False,'dhcp6':False,
            'accept-ra':False,'addresses':[guest+'/30'],'routes':[{'to':'default','via':gateway}],
            'nameservers':{'addresses':['223.5.5.5','1.1.1.1']}}}}
    interfaces = f'auto {bridge}\niface {bridge} inet static\n  address {gateway}/30\n  bridge-ports none\n  bridge-stp off\n  bridge-fd 0\n'
    # The shared host renderer composes these structured leases into the parent
    # firewall chains. A standalone table cannot override a later parent drop.
    lease={'version':1,'vmid':spec.vmid,'node':bootstrap.node,'owner':owner.model_dump(),
           **bootstrap.network.model_dump()}
    files = {'user-data':'#cloud-config\n'+encoded(user)+'\n', 'meta-data':encoded(metadata)+'\n',
             'network-config':encoded(net)+'\n','interfaces.conf':interfaces,'network-lease.json':encoded(lease)+'\n'}
    manifest = {'version':1,'vmid':spec.vmid,'owner_sha256':fingerprint(owner.model_dump()),
                'bridge':bridge,'guest_ipv4':guest,'gateway_ipv4':gateway,'subnet':str(network),
                'instance_id':instance_id,'artifact_sha256':bootstrap.artifact_sha256,
                'files':{name:__import__('hashlib').sha256(body.encode()).hexdigest() for name,body in files.items()}}
    return {'manifest':manifest,'files':files,'bundle_sha256':fingerprint(manifest),'product_ready':False}


def write_bundle(path, bundle):
    from ..config import private_directory, write_private_json
    path=Path(path)
    if path.is_symlink() or (path.exists() and any(path.iterdir())):
        raise ProvisionError('bootstrap_output_must_be_empty')
    private_directory(path)
    for name,body in bundle['files'].items():
        p=path/name
        with p.open('x') as f:f.write(body)
        p.chmod(0o600)
    write_private_json(path/'manifest.json',bundle['manifest'])


def validate_delivery(owner, evidence):
    """Accept evidence gathered by trusted operator adapters, never client JSON.

    Missing/unknown checks are distinct pending phases; a pure classifier cannot
    itself establish truth. The SSH delivery reader supplies this evidence.
    """
    required = ('network_isolated','owner_matches','bootstrap_matches','unique_os_identity',
                'native_ready','paired_scope_matches','agent_online','human_online','mtls_verified')
    if evidence.get('owner_sha256') != fingerprint(owner.model_dump()):
        raise ProvisionError('delivery_owner_changed')
    pending=[key for key in required if evidence.get(key) is not True]
    return {'state':'ready' if not pending else 'awaiting_verification','pending':pending,
            'device_ready':not pending,'product_ready':False,'evidence_sha256':fingerprint(evidence),
            'browser_ready':evidence.get('browser_ready'),
            'browser_setup_state':evidence.get('browser_setup_state','not_applicable')}


class BootstrapBook:
    """Network stage uses the same reservation, lock, account proof and owner."""
    def __init__(self, book):
        self.book=book
        with book._tx() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS device_bootstrap(
              request TEXT PRIMARY KEY, bundle_sha256 TEXT NOT NULL, bundle TEXT NOT NULL,
              before_config_sha256 TEXT NOT NULL, state TEXT NOT NULL, code TEXT NOT NULL,
              updated REAL NOT NULL)''')

    def _bound(self, request):
        with self.book._tx() as db:
            row=db.execute('SELECT * FROM devices WHERE request=?',(request,)).fetchone()
            account=db.execute('SELECT scope FROM device_accounts WHERE request=?',(request,)).fetchone()
        if not row or row['state']!='staged' or not account:
            raise ProvisionError('staged_device_required')
        spec,owner=DeviceSpec.model_validate_json(row['spec']),Owner.model_validate_json(row['owner'])
        self.book._account(spec,json.loads(account['scope']))
        return spec,owner,Policy.model_validate_json(row['policy'])

    def plan(self, request, bootstrap, adapter):
        with self.book._guard():
            spec,owner,policy=self._bound(request)
            if bootstrap.node!=policy.node:raise ProvisionError('bootstrap_host_changed')
            vm=adapter.inspect_vm(spec.vmid)
            if not vm or vm.owner!=owner or vm.state!='stopped' or vm.template or vm.locked:
                raise ProvisionError('vm_owner_or_state_conflict')
            return render(spec,owner,bootstrap)

    def stage_network(self, request, bootstrap, adapter, *, reviewed_sha256):
        with self.book._guard():
            bundle=self.plan(request,bootstrap,adapter)
            if bundle['bundle_sha256']!=reviewed_sha256:raise ProvisionError('bootstrap_plan_changed')
            spec,owner,_=self._bound(request)
            vm=adapter.inspect_vm(spec.vmid)
            if not vm or vm.owner!=owner or vm.state!='stopped' or vm.locked or vm.template:
                raise ProvisionError('vm_owner_or_state_conflict')
            with self.book._tx() as db:
                old=db.execute('SELECT * FROM device_bootstrap WHERE request=?',(request,)).fetchone()
                if old and old['bundle_sha256']!=reviewed_sha256:raise ProvisionError('bootstrap_plan_changed')
                if not old:
                    db.execute('INSERT INTO device_bootstrap VALUES (?,?,?,?,?,?,?)',
                               (request,reviewed_sha256,encoded(bundle),vm.config_sha256,'network_pending','',self.book.clock()))
            try:
                self._bound(request)
                result=adapter.stage_network(spec,owner,old['before_config_sha256'] if old else vm.config_sha256,bundle)
                self._bound(request)
                current=adapter.inspect_vm(spec.vmid)
                if (result.get('network_staged') is not True or result.get('started') is not False
                        or result.get('bundle_sha256')!=reviewed_sha256 or not current
                        or current.owner!=owner or current.state!='stopped' or current.locked
                        or current.config_sha256!=result.get('config_sha256')):
                    raise ProvisionError('bootstrap_network_unconfirmed')
                with self.book._tx() as db:
                    db.execute("UPDATE device_bootstrap SET state='network_staged',code='',updated=? WHERE request=?",(self.book.clock(),request))
                return {'request_id':request,'state':'network_staged','bundle_sha256':reviewed_sha256,
                        'product_ready':False,'started':False}
            except Exception as error:
                code=str(error) if isinstance(error,ProvisionError) else 'bootstrap_outcome_unknown'
                with self.book._tx() as db:
                    db.execute('UPDATE device_bootstrap SET code=?,updated=? WHERE request=?',(code,self.book.clock(),request))
                raise ProvisionError(code) from None
