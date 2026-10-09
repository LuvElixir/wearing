"""Configure only an owned, stopped VM's unique network and cloud-init seed."""
from .proxmox_devices import REMOTE, ProxmoxDevices
from .device_power_ssh import SSHPowerAdapter


STAGE_REMOTE = REMOTE.split("for key in ('node','storage','vg','pool'):")[0] + r'''
from pathlib import Path
if os.geteuid()!=0:fail('operator_required')
spec,expected,bundle=p['spec'],p['owner'],p['bundle'];manifest=bundle['manifest'];vid=spec['vmid']
if p['bundle_sha256']!=digest(manifest):fail('bootstrap_plan_changed')
if manifest['owner_sha256']!=digest(expected) or manifest['vmid']!=vid:fail('bootstrap_owner_changed')
lock=os.open('/run/lock/pajio-device-provision.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:fail('host_provision_inflight')
c=checked_target(spec,expected)
directory=Path('/var/lib/pajio/device-bootstrap');directory.mkdir(mode=0o700,parents=True,exist_ok=True)
if directory.is_symlink() or directory.stat().st_uid!=0 or directory.stat().st_mode&0o077:fail('unsafe_bootstrap_directory')
receipt=directory/f'{vid}.json'
def write(path,content):
 path=Path(path)
 if path.is_symlink():fail('unsafe_bootstrap_path')
 if path.exists():
  if path.stat().st_uid!=0 or path.read_text()!=content:fail('bootstrap_existing_file_changed')
  return
 temp=path.with_name(path.name+'.new')
 fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:f.write(content);f.flush();os.fsync(f.fileno())
 os.replace(temp,path)
def state(phase):
 data={'version':1,'owner_sha256':manifest['owner_sha256'],'bundle_sha256':p['bundle_sha256'],'phase':phase}
 temp=receipt.with_suffix('.new');fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(data,f);f.flush();os.fsync(f.fileno())
 os.replace(temp,receipt)
old=None
if receipt.exists():
 if receipt.is_symlink() or receipt.stat().st_uid!=0 or receipt.stat().st_mode&0o077:fail('unsafe_bootstrap_receipt')
 old=json.loads(receipt.read_text())
 if old['owner_sha256']!=manifest['owner_sha256'] or old['bundle_sha256']!=p['bundle_sha256']:fail('bootstrap_owner_changed')
elif digest(c)!=p['config_sha256']:fail('vm_configuration_changed')
if set(bundle['files'])!={'user-data','meta-data','network-config','interfaces.conf','network-lease.json'}:fail('invalid_bootstrap_files')
for name,body in bundle['files'].items():
 if hashlib.sha256(body.encode()).hexdigest()!=manifest['files'][name]:fail('bootstrap_artifact_changed')
if manifest['bridge']!='pj'+str(vid):fail('bootstrap_bridge_changed')
lease=json.loads(bundle['files']['network-lease.json'])
if lease['owner']!=expected or lease['vmid']!=vid or lease['node']!=p['node']:fail('bootstrap_owner_changed')
# Import only the fixed, root-owned installed stdlib renderer, never bundle code.
import importlib.util
renderer=Path('/usr/local/libexec/pajio-render-device-network.py')
if renderer.is_symlink() or not renderer.is_file() or renderer.stat().st_uid!=0 or renderer.stat().st_mode&0o022:fail('network_renderer_required')
module=importlib.util.spec_from_file_location('pajio_network',renderer);network=importlib.util.module_from_spec(module);module.loader.exec_module(network)
leases=Path('/etc/pajio/device-network');leases.mkdir(mode=0o700,parents=True,exist_ok=True)
if leases.is_symlink() or leases.stat().st_uid!=0 or leases.stat().st_mode&0o077:fail('unsafe_network_directory')
existing=network.load(leases)
network.validate([v for v in existing if v['vmid']!=vid]+[lease])
state('preparing')
bridge=manifest['bridge'];interface=Path('/etc/network/interfaces.d')/f'pajio-device-{vid}'
# An unrelated interface with this name is never adopted.
link=subprocess.run(['ip','-j','link','show','dev',bridge],capture_output=True,text=True)
if link.returncode==0 and not interface.exists():fail('network_bridge_exists')
write(interface,bundle['files']['interfaces.conf'])
prefix=f'pajio-device-{vid}-{expected["nonce"][:12]}'
snippets=Path('/var/lib/vz/snippets')
if not snippets.is_dir() or snippets.is_symlink():fail('trusted_snippets_directory_required')
for name in ('user-data','meta-data','network-config'):write(snippets/f'{prefix}-{name}.yaml',bundle['files'][name])
cicustom=','.join(f'{kind}=local:snippets/{prefix}-{name}.yaml' for kind,name in [('user','user-data'),('meta','meta-data'),('network','network-config')])
net='virtio,bridge='+bridge
c=checked_target(spec,expected)
if c.get('cicustom')!=cicustom or 'bridge='+bridge not in c.get('net0',''):
 if old and old['phase']!='preparing':fail('bootstrap_configuration_changed')
 if digest(c)!=p['config_sha256']:fail('bootstrap_configuration_changed')
 if any(re.fullmatch(r'net\d+',k) for k in c):fail('bootstrap_existing_network')
 run_change(['qm','set',str(vid),'--digest',c['digest'],'--net0',net,'--cicustom',cicustom,'--onboot','0'])
c=checked_target(spec,expected)
if c.get('cicustom')!=cicustom or 'bridge='+bridge not in c.get('net0','') or int(c.get('onboot',0))!=0:fail('bootstrap_configuration_unconfirmed')
write(leases/f'{vid}.json',bundle['files']['network-lease.json'])
run_change(['ifup',bridge])
run_change(['/usr/local/sbin/pajio-apply-lab-network'])
addr=call('ip','-j','addr','show','dev',bridge)
if len(addr)!=1 or not any(v.get('local')==manifest['gateway_ipv4'] and v.get('prefixlen')==30 for v in addr[0]['addr_info']):fail('bootstrap_bridge_unconfirmed')
for family,table,chain in [('inet','pajio_lab_guard',f'pv{vid}_input'),('inet','pajio_lab_guard',f'pv{vid}_forward'),('ip','pajio_lab_nat','provisioned_nat')]:
 run_change(['nft','list','chain',family,table,chain])
checked_target(spec,expected);state('network_staged')
print(json.dumps({'network_staged':True,'started':False,'config_sha256':digest(c),'bundle_sha256':p['bundle_sha256']}))
'''


class SSHBootstrapAdapter(SSHPowerAdapter):
    def stage_network(self, spec, owner, config_sha256, bundle):
        return self._remote(self.host, '/usr/bin/python3', STAGE_REMOTE,
                            {**self.params,'spec':spec.model_dump(),'owner':owner.model_dump(),
                             'config_sha256':config_sha256,'bundle':bundle,'bundle_sha256':bundle['bundle_sha256']})
