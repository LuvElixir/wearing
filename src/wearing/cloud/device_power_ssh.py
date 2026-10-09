"""Fixed operator SSH operations for native quiescence and graceful VM power.

No force-stop fallback, command interpolation, credentials in receipts or public
API. Requires the reviewed native owner marker installed during fresh bootstrap.
"""
import json
from pathlib import Path
import re
import shlex
import subprocess

from pydantic import Field, field_validator
from .commands import Record, Identifier
from .device_admission import MetadataTarget
from .device_provisioning import ProvisionError, fingerprint
from .proxmox_devices import ProxmoxDevices, REMOTE


class NativeTarget(Record):
    host: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$')
    account: str = Field(pattern=r'^pajio-(desktop|phone)$')
    connector_unit: str = Field(pattern=r'^com\.wearing\.connector\.[a-f0-9]{16}\.service$')


class PowerSources(Record):
    tenants: dict[Identifier, MetadataTarget]
    devices: dict[Identifier, NativeTarget]


TENANT_REMOTE = r'''
import json,os,pwd,subprocess,sys,time
from pathlib import Path
from wearing.cloud.device_maintenance import DeviceMaintenance
from wearing.cloud.instance import load_instance
from wearing.cloud.relay import instance_relay
from wearing.cloud import relay,device_access,device_maintenance,desktop_approval
p=json.load(sys.stdin)
try:
 assert os.geteuid()==0
 # Refuse old live relay processes which have not loaded the new admission gate.
 r=subprocess.run(['systemctl','show','pajio-device-relay.service','--property=MainPID','--property=ActiveState'],capture_output=True,text=True,check=True)
 fields=dict(v.split('=',1) for v in r.stdout.splitlines() if '=' in v)
 assert fields['ActiveState']=='active';pid=int(fields['MainPID']);assert pid>0
 stat=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
 btime=int(next(v.split()[1] for v in Path('/proc/stat').read_text().splitlines() if v.startswith('btime ')))
 started=btime+int(stat[19])/os.sysconf('SC_CLK_TCK')
 assert started>=max(Path(m.__file__).stat().st_mtime for m in (relay,device_access,device_maintenance,desktop_approval))
 u=pwd.getpwnam(p['account']);assert u.pw_uid!=0
 os.setgroups([]);os.setgid(u.pw_gid);os.setuid(u.pw_uid)
 root=Path(p['root']);instance=load_instance(root)
 assert instance.tenant_id==p['spec']['tenant_id']
 store=instance_relay(root)
 if p['action']=='ready':
  rows=[v for v in store.inventory(p['spec']['identity_id']) if v['resource_id']==p['spec']['resource_id']]
  assert len(rows)==1 and rows[0]['online'] and not rows[0]['paused'] and not rows[0]['control_pending'] and not rows[0]['needs_review']
  with store.tx() as db:
   from wearing.cloud.device_access import owned
   c,s=owned(db,p['spec']['identity_id'],p['spec']['resource_id'])
   assert c['human_access_ready'] and json.loads(c['human_availability']).get(p['spec']['resource_id'])
  result={'ready':True,'connector_id':rows[0]['connector_id']}
 else:
  assert p['action'] in ('begin','freeze','assert_drained','status','wake','finish_wake')
  result=getattr(DeviceMaintenance(store,operator=True),p['action'])(p['spec']['identity_id'],p['spec']['resource_id'],p['operation'],p['owner_sha256'])
 print(json.dumps(result))
except Exception as e:
 from wearing.cloud.relay import RelayError
 print(json.dumps({'error':str(e) if isinstance(e,RelayError) else 'trusted_maintenance_unavailable'}));sys.exit(1)
'''


NATIVE_REMOTE = r'''
import fcntl,hashlib,json,os,pwd,sqlite3,subprocess,sys,time,urllib.request
from pathlib import Path
p=json.load(sys.stdin)
def fail(code):
 print(json.dumps({'error':code}));sys.exit(1)
def read(path):
 path=Path(path)
 if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077:fail('private_native_metadata_required')
 return json.loads(path.read_text())
def sql(path,query,args=()):
 path=Path(path)
 if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077:fail('private_native_metadata_required')
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
  db.execute('PRAGMA query_only=ON');return db.execute(query,args).fetchall()
def unit(argv):
 return subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=45)
try:
 if os.geteuid()!=0:fail('operator_required')
 spec,owner=p['spec'],p['owner'];u=pwd.getpwnam(p['account']);home=Path(u.pw_dir)
 if u.pw_uid==0 or home!=Path('/home')/p['account'] or u.pw_shell!='/usr/sbin/nologin':fail('native_account_changed')
 owner_path=Path('/etc/pajio-native/device-owner.json')
 if owner_path.stat().st_uid!=0 or read(owner_path)!=owner:fail('native_owner_changed')
 root=home/'.pajio-connector';c=read(root/'connector.json')
 if c['tenant_id']!=spec['tenant_id'] or c['identity_id']!=spec['identity_id'] or len(c['resources'])!=1 or c['resources'][0]['resource_id']!=spec['resource_id']:fail('native_pairing_changed')
 rid=spec['resource_id'];lp=home/'.wearing/phone-locks'/f'{rid}.lock'
 if not lp.parent.is_dir() or lp.parent.is_symlink():fail('native_lock_unavailable')
 fd=os.open(lp,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
 os.fchown(fd,u.pw_uid,u.pw_gid)
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:fail('native_action_inflight')
 gateway=sql(home/'.wearing/device-gateway/ownership.sqlite3','SELECT state,epoch FROM ownership WHERE resource=?',(rid,))
 if len(gateway)!=1 or gateway[0][0]!='agent_ready':fail('native_not_agent_ready')
 if sql(root/'actions.sqlite3',"SELECT COUNT(*) FROM actions WHERE state='started' OR (state IN ('unknown','device_error') AND uploaded=0)")[0][0]:fail('native_actions_unresolved')
 boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 env=['runuser','-u',p['account'],'--','env','HOME='+str(home),f'XDG_RUNTIME_DIR=/run/user/{u.pw_uid}',f'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{u.pw_uid}/bus','systemctl','--user']
 connector=env+['is-active',p['connector_unit']]
 media=['systemctl','is-active','pajio-private-media.service']
 marker=Path('/var/lib/pajio-native/power.json')
 intent={'version':1,'operation':p['operation'],'owner_sha256':p['owner_sha256'],'boot_id':boot,'gateway_epoch':gateway[0][1]}
 if p['action'] in ('health','quiesce'):
  if unit(connector).stdout.strip()!='active' or unit(media).stdout.strip()!='active':fail('native_services_not_ready')
  config=read('/etc/pajio/media-host.json')
  if len(config['resources'])!=1 or config['resources'][0]['resource_id']!=rid:fail('media_binding_changed')
  req=urllib.request.Request('http://127.0.0.1:8792/v1/status',headers={'Authorization':'Bearer '+config['token']})
  with urllib.request.urlopen(req,timeout=8) as r: status=json.loads(r.read(65537))
  if status.get('ready') is not True or rid not in status.get('resources',[]):fail('native_media_not_ready')
  if any(not v.get('closed') or not v.get('cleared') for v in status.get('sessions',{}).values()):fail('native_media_inflight')
 if p['action']=='quiesce':
  if marker.exists() and read(marker)!=intent:
   old=read(marker)
   if old.get('owner_sha256')!=intent['owner_sha256'] or old.get('boot_id')==boot:fail('native_power_intent_changed')
  marker.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  if not marker.exists() or read(marker)!=intent:
   tmp=marker.with_suffix('.new');f=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
   with os.fdopen(f,'w') as out:json.dump(intent,out);out.flush();os.fsync(out.fileno())
   os.replace(tmp,marker)
   parent=os.open(marker.parent,os.O_RDONLY);os.fsync(parent);os.close(parent)
  for argv in (env+['stop',p['connector_unit']],['systemctl','stop','pajio-private-media.service']):
   if unit(argv).returncode:fail('native_quiesce_unknown')
 if p['action'] in ('quiesce','quiesced'):
  if read(marker)!=intent:fail('native_power_intent_changed')
  if unit(connector).stdout.strip()!='inactive' or unit(media).stdout.strip()!='inactive':fail('native_quiesce_unconfirmed')
 elif p['action']!='health':fail('native_action_not_allowed')
 print(json.dumps({'boot_id':boot,'gateway_epoch':gateway[0][1],'connector_id':c['connector_id'],'ready':p['action']=='health','quiesced':p['action'] in ('quiesce','quiesced')}))
except Exception:
 fail('native_evidence_unavailable')
'''


POWER_REMOTE = REMOTE.split("for key in ('node','storage','vg','pool'):")[0] + r'''
if p['action'] not in ('shutdown','start'):fail('power_action_not_allowed')
lock=os.open('/run/lock/pajio-device-provision.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:fail('host_provision_inflight')
spec=p['spec'];c=config(spec['vmid'])
if owner(c)!=p['owner'] or c.get('template') or c.get('lock') or digest(c)!=p['config_sha256']:fail('vm_owner_or_configuration_changed')
state=call('pvesh','get',f'/nodes/{p["node"]}/qemu/{spec["vmid"]}/status/current','--output-format','json')['status']
if state!=('running' if p['action']=='shutdown' else 'stopped'):fail('power_state_changed')
if p['action']=='start':
 inv=inventory()
 reserved=[v for v in inv['vms'] if not v['template'] and (v['owner'] or v['state']!='stopped')]
 if sum(v['vcpus'] for v in reserved)+p['host_cores']>inv['physical_cores'] or sum(v['memory_mib'] for v in reserved)+p['host_memory_mib']>inv['memory_mib'] or inv['available_memory_mib']<spec['memory_mib']+p['host_memory_mib']:fail('wake_capacity_unavailable')
argv=['qm',p['action'],str(spec['vmid'])]
if p['action']=='shutdown':argv+=['--timeout','60','--forceStop','0']
run_change(argv)
print(json.dumps({'accepted':True}))
'''


class SSHPowerAdapter(ProxmoxDevices):
    def __init__(self, *, sources, host_memory_mib=6144, host_cores=2, **kwargs):
        super().__init__(**kwargs)
        self.sources = PowerSources.model_validate(sources)
        if host_memory_mib < 4096 or host_cores < 1: raise ProvisionError('invalid_host_reserve')
        self.host_memory_mib, self.host_cores = host_memory_mib, host_cores

    def _remote(self, host, python, source, body):
        if not self.allow_create: raise ProvisionError('operator_apply_required')
        if not python.startswith('/') or any(ord(c)<32 for c in python): raise ProvisionError('invalid_operator_target')
        argv = ['ssh','-F',str(self.config),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',host,
                'if [ "$(id -u)" -eq 0 ]; then set --; else set -- sudo -n; fi; exec "$@" '+shlex.quote(python)+' -c '+shlex.quote(source)]
        try:
            r = self.runner(argv,input=json.dumps(body),capture_output=True,text=True,timeout=100)
            if len(r.stdout)>65536: raise ValueError()
            value=json.loads(r.stdout)
            if r.returncode or value.get('error'):
                code=value.get('error')
                raise ProvisionError(code if isinstance(code,str) and re.fullmatch('[a-z_]{1,80}',code) else 'power_outcome_unknown')
            return value
        except (ValueError,OSError,subprocess.TimeoutExpired) as error:
            if isinstance(error,ProvisionError): raise
            raise ProvisionError('power_outcome_unknown') from None

    def maintenance(self, action, spec, owner, operation):
        target=self.sources.tenants.get(spec.tenant_id)
        if not target: raise ProvisionError('tenant_power_target_missing')
        return self._remote(target.host,target.python,TENANT_REMOTE,
                            {**target.model_dump(),'action':action,'spec':spec.model_dump(),'operation':operation,'owner_sha256':fingerprint(owner.model_dump())})

    def native(self, action, spec, owner, operation):
        target=self.sources.devices.get(spec.resource_id)
        if not target: raise ProvisionError('native_power_target_missing')
        return self._remote(target.host,'/usr/bin/python3',NATIVE_REMOTE,
                            {**target.model_dump(),'action':action,'spec':spec.model_dump(),'owner':owner.model_dump(),'operation':operation,'owner_sha256':fingerprint(owner.model_dump())})

    def assert_ready(self, spec, owner):
        relay=self.maintenance('ready',spec,owner,'0'*32)
        native=self.native('health',spec,owner,'0'*32)
        if relay.get('ready') is not True or relay.get('connector_id')!=native.get('connector_id'):
            raise ProvisionError('device_readiness_unconfirmed')

    def assert_wake_capacity(self, spec):
        inventory=self.inventory()
        if inventory.available_memory_mib < spec.memory_mib+self.host_memory_mib:
            raise ProvisionError('wake_capacity_unavailable')

    def power(self, action, spec, owner, config_sha256):
        return self._remote(self.host,'/usr/bin/python3',POWER_REMOTE,
                            {**self.params,'action':action,'spec':spec.model_dump(),'owner':owner.model_dump(),
                             'config_sha256':config_sha256,'host_memory_mib':self.host_memory_mib,'host_cores':self.host_cores})
