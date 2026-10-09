"""Trusted metadata-only adoption; SSH guest identity must match Proxmox QGA."""
import json
from .device_power_ssh import SSHPowerAdapter
from .device_provisioning import ProvisionError,fingerprint
from .proxmox_devices import REMOTE

GUEST = r'''
import fcntl,hashlib,json,os,pwd,sys
from pathlib import Path
p=json.load(sys.stdin)
def fail():raise ValueError('adoption_guest_unconfirmed')
def private(path,uid=None):
 path=Path(path)
 if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077 or (uid is not None and path.stat().st_uid!=uid):fail()
 return json.loads(path.read_text())
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
try:
 assert os.geteuid()==0
 u=pwd.getpwnam(p['account']);home=Path(u.pw_dir);spec=p['spec'];owner=p['owner']
 assert u.pw_uid!=0 and home==Path('/home')/p['account'] and u.pw_shell=='/usr/sbin/nologin'
 assert p['account']==('pajio-desktop' if spec['kind']=='linux' else 'pajio-phone')
 c=private(home/'.pajio-connector/connector.json',u.pw_uid)
 assert c['resources'][0]['kind']==('computer' if spec['kind']=='linux' else 'android')
 assert c['tenant_id']==spec['tenant_id'] and c['identity_id']==spec['identity_id'] and len(c['resources'])==1 and c['resources'][0]['resource_id']==spec['resource_id']
 native=private(home/'.pajio/runtime/native-driver.json',u.pw_uid)
 assert native['version']==1 and native['python']=='/opt/pajio-native/venv/bin/python'
 machine=Path('/etc/machine-id').read_text().strip();assert len(machine)==32
 sha=hashlib.sha256(machine.encode()).hexdigest()
 path=Path('/etc/pajio-native/device-owner.json');current=private(path,0) if path.exists() else None
 assert current in (None,owner)
 if p['action']=='adopt':
  assert sha==p['before']['machine_sha256'] and c['connector_id']==p['before']['connector_id']
  path.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
  assert not path.parent.is_symlink() and path.parent.stat().st_uid==0 and not path.parent.stat().st_mode&0o022
  fd=os.open('/run/lock/pajio-native-adoption.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if path.exists():assert private(path,0)==owner
  else:
   out=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(out,'w') as f:json.dump(owner,f);f.flush();os.fsync(f.fileno())
   parent=os.open(path.parent,os.O_RDONLY);os.fsync(parent);os.close(parent)
  current=private(path,0)
 elif p['action']!='probe':fail()
 print(json.dumps({'scope_matches':True,'machine_sha256':sha,'connector_id':c['connector_id'],'owner_sha256':digest(current) if current else None}))
except Exception:
 print(json.dumps({'error':'adoption_guest_unconfirmed'}));sys.exit(1)
'''

HOST = REMOTE.split("for key in ('node','storage','vg','pool'):")[0]+r'''
from pathlib import Path
if p['action'] not in ('probe','adopt'):fail('adoption_action_not_allowed')
spec=p['spec'];expected=p['owner'];vid=spec['vmid']
fd=os.open('/run/lock/pajio-device-provision.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:fail('host_provision_inflight')
c=config(vid)
if owner(c) not in (None,expected) or c.get('template') or c.get('lock'):fail('adoption_vm_conflict')
state=call('pvesh','get',f'/nodes/{p["node"]}/qemu/{vid}/status/current','--output-format','json')['status']
if state!='running':fail('adoption_requires_live_guest')
# Read the exact machine ID through the host's authenticated QGA channel, so a
# mislabeled SSH alias cannot bind a different guest with similar metadata.
r=call('qm','guest','exec',str(vid),'--','/usr/bin/cat','/etc/machine-id')
if r.get('exitcode')!=0:fail('adoption_qga_unavailable')
machine=r.get('out-data','').strip()
if not re.fullmatch('[a-f0-9]{32}',machine):fail('adoption_qga_unavailable')
sha=hashlib.sha256(machine.encode()).hexdigest()
if p['action']=='adopt':
 before=p['before']
 if sha!=before['machine_sha256']:fail('adoption_guest_changed')
 if owner(c)==expected:
  proof=c.get('description','');proof=json.loads(proof).get('pajio_manual_adoption',{})
  if proof.get('before_config_sha256')!=before['config_sha256'] or proof.get('machine_sha256')!=sha:fail('adoption_provenance_changed')
 else:
  if digest(c)!=before['config_sha256']:fail('adoption_config_changed')
  base=Path('/var/lib/pajio/device-adoptions');base.mkdir(mode=0o700,parents=True,exist_ok=True)
  if base.is_symlink() or base.stat().st_uid!=0 or base.stat().st_mode&0o077:fail('unsafe_adoption_receipt')
  path=base/(str(vid)+'.json')
  receipt={'version':1,'provenance':'manual_adoption','owner':expected,'before':c,'machine_sha256':sha}
  if path.exists():
   if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o077 or json.loads(path.read_text())!=receipt:fail('adoption_receipt_changed')
  else:
   f=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(f,'w') as out:json.dump(receipt,out);out.flush();os.fsync(out.fileno())
  description=json.dumps({'pajio_provisioning':expected,'pajio_manual_adoption':{'before_config_sha256':before['config_sha256'],'machine_sha256':sha}},sort_keys=True,separators=(',',':'))
  run_change(['qm','set',str(vid),'--digest',c['digest'],'--description',description])
  c=config(vid)
  if owner(c)!=expected:fail('adoption_host_unconfirmed')
print(json.dumps({'vmid':vid,'config_sha256':digest(c),'machine_sha256':sha,'owner_sha256':digest(expected) if owner(c)==expected else None}))
'''


class SSHAdoptionAdapter(SSHPowerAdapter):
    def _guest(self,action,spec,owner,before=None):
        target=self.sources.devices.get(spec.resource_id)
        if not target:raise ProvisionError('native_adoption_target_missing')
        return self._remote(target.host,'/usr/bin/python3',GUEST,
                            {**target.model_dump(),'action':action,'spec':spec.model_dump(),'owner':owner.model_dump(),'before':before})

    def _host(self,action,spec,owner,before=None):
        return self._remote(self.host,'/usr/bin/python3',HOST,
                            {**self.params,'action':action,'spec':spec.model_dump(),'owner':owner.model_dump(),'before':before})

    def adoption_probe(self,spec,owner):
        host=self._host('probe',spec,owner);guest=self._guest('probe',spec,owner)
        relay=self.maintenance('ready',spec,owner,'0'*32)
        if host['machine_sha256']!=guest['machine_sha256'] or relay.get('connector_id')!=guest.get('connector_id'):
            raise ProvisionError('adoption_guest_or_pairing_changed')
        if guest.get('owner_sha256') not in (None,fingerprint(owner.model_dump())) or host.get('owner_sha256') not in (None,fingerprint(owner.model_dump())):
            raise ProvisionError('adoption_owner_changed')
        # During interrupted metadata stamping only one side may be written;
        # adopted=True is reported only when both independently match.
        return {**host,'scope_matches':guest.get('scope_matches') is True,'guest_matches_vm':True,
                'paired_ready':relay.get('ready') is True,'resource_id':spec.resource_id,
                'connector_id':guest['connector_id'],'owner_sha256':host.get('owner_sha256') if host.get('owner_sha256')==guest.get('owner_sha256') else None}

    def adopt_existing(self,spec,owner,before):
        # Both helpers recheck their exact peer identity, ownership and original
        # configuration. Interrupted same-owner metadata writes can be resumed.
        current=self.adoption_probe(spec,owner)
        if current['machine_sha256']!=before['machine_sha256'] or current['connector_id']!=before['connector_id']:
            raise ProvisionError('adoption_guest_changed')
        self._guest('adopt',spec,owner,before)
        self._host('adopt',spec,owner,before)
