"""Operator-only full-bundle capacity preclaim and invite issue.

A reservation is not an account. Devices stay unowned until real invitation
redemption and the normal AccountProof-gated delivery books create them.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time

from pydantic import Field, model_validator

from .commands import Identifier, Record
from .bundle_activation import ActivationError
from .bundle_activation_pipeline import ActivationPlan
from .proxmox_devices import REMOTE
from .invitations import InvitationStore, issue_to_file
from .instance import read_private


class ReservedMember(Record):
    kind: str = Field(pattern='^(core|linux|android)$')
    vmid: int = Field(strict=True, ge=100, le=999999999)
    request_id: str = Field(pattern='^[a-f0-9]{32}$')
    vcpus: int = Field(strict=True, ge=1, le=16)
    memory_mib: int = Field(strict=True, ge=1024, le=32768)
    disk_mib: int = Field(strict=True, ge=16384, le=1048576)
    image_sha256: str = Field(pattern='^[a-f0-9]{64}$')
    core_reservation_sha256: str | None = Field(default=None, pattern='^[a-f0-9]{64}$')


class BundleReservation(Record):
    version: int = Field(default=1, strict=True, ge=1, le=1)
    reservation_id: str = Field(pattern='^[a-f0-9]{32}$')
    node: str = 'pve01'
    purpose: str = 'invitation'
    tenant_id: Identifier
    created_at: int = Field(strict=True, gt=0)
    expires_at: int = Field(strict=True, gt=0)
    members: list[ReservedMember]

    @model_validator(mode='after')
    def checked(self):
        if (self.node != 'pve01' or self.purpose != 'invitation' or self.created_at >= self.expires_at
                or len(self.members) != 3 or {m.kind for m in self.members} != {'core','linux','android'}
                or len({m.vmid for m in self.members}) != 3 or len({m.request_id for m in self.members}) != 3):
            raise ValueError('bundle_reservation_invalid')
        for m in self.members:
            if (m.kind == 'core') != (m.core_reservation_sha256 is not None):
                raise ValueError('bundle_core_reservation_required')
            if m.kind != 'core' and m.memory_mib < 2048:
                raise ValueError('bundle_memory_invalid')
        return self

    def encoded(self):
        return json.dumps(self.model_dump(), sort_keys=True, separators=(',', ':')) + '\n'


HOST = REMOTE.split("for key in ('node','storage','vg','pool'):")[0] + r'''
import stat,tempfile
from pathlib import Path
if os.geteuid()!=0 or (p['node'],p['storage'],p['vg'],p['pool'])!=('pve01','local-lvm','pve','data'):fail('bundle_host_invalid')
reservation=p['reservation'];raw=p['reservation_raw'].encode()
if json.loads(raw)!=reservation or reservation['purpose']!='invitation' or reservation['node']!='pve01':fail('bundle_reservation_invalid')
if not re.fullmatch('[a-f0-9]{32}',reservation['reservation_id']):fail('bundle_reservation_invalid')
if type(reservation['expires_at']) is not int or reservation['expires_at']<=time.time()+900:fail('bundle_reservation_expired')
rows=reservation['members']
if len(rows)!=3 or {v['kind'] for v in rows}!={'core','linux','android'} or len({v['vmid'] for v in rows})!=3:fail('bundle_members_invalid')
def private(path):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_nlink!=1 or stat.S_IMODE(st.st_mode)!=0o600 or st.st_size>131072:fail('bundle_file_unsafe')
  return os.read(fd,131073)
 finally:os.close(fd)
def directory(path):
 try:path.mkdir(mode=0o700)
 except FileExistsError:pass
 st=path.lstat()
 if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or stat.S_IMODE(st.st_mode)!=0o700:fail('bundle_directory_unsafe')
lock=os.open('/run/lock/pajio-device-provision.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:
 st=os.fstat(lock)
 if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_nlink!=1 or st.st_mode&0o077:fail('bundle_lock_unsafe')
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 inv=inventory();live={v['vmid']:v for v in inv['vms']}
 base=Path('/var/lib/pajio-resource-reservations');folder=base/reservation['reservation_id'];path=folder/'reservation.json'
 if path.exists() or path.is_symlink():
  if private(path)!=raw:fail('bundle_reservation_changed')
  totals=capacity_totals(inv)
  missing=sum(v['memory_mib'] for v in rows if v['vmid'] not in live)
  extra=totals['recovery_and_missing_disk_mib']
  if (totals['vcpus']+2>inv['physical_cores'] or totals['memory_mib']+6144>inv['memory_mib']
      or inv['available_memory_mib']<missing+6144
      or inv['committed_storage_mib']+extra>inv['storage_mib']*80//100
      or inv['available_storage_mib']<extra+inv['storage_mib']*20//100):fail('bundle_capacity_unavailable')
  print(json.dumps({'reservation_sha256':hashlib.sha256(raw).hexdigest(),'reservation':reservation,'observed_at':time.time()}));sys.exit()
 if p['action']!='reserve':fail('bundle_reservation_missing')
 if any(v['purpose']=='benchmark' for v in inv['resource_promises']):fail('benchmark_retirement_required')
 existing={v['vmid'] for v in inv['resource_promises']}
 if existing.intersection(v['vmid'] for v in rows) or any(v['tenant_id']==reservation['tenant_id'] for v in inv['resource_promises']):fail('bundle_reservation_conflict')
 totals=capacity_totals(inv)
 for member in rows:
  for key,lo,hi in [('vmid',100,999999999),('vcpus',1,16),('memory_mib',1024,32768),('disk_mib',16384,1048576)]:
   if type(member[key]) is not int or not lo<=member[key]<=hi:fail('bundle_members_invalid')
  if not re.fullmatch('[a-f0-9]{32}',member['request_id']) or not re.fullmatch('[a-f0-9]{64}',member['image_sha256']):fail('bundle_members_invalid')
  if member['kind']=='core':
   core=private(Path('/var/lib/pajio-core-provisioning')/str(member['vmid'])/'reservation.json')
   value=json.loads(core)
   if hashlib.sha256(core).hexdigest()!=member['core_reservation_sha256'] or value['tenant_id']!=reservation['tenant_id'] or value['node']!='pve01' or any(value[k]!=member[k] for k in ('vmid','request_id','vcpus','memory_mib','disk_mib','image_sha256')):fail('bundle_core_changed')
   current=live.get(member['vmid'])
   if not current or current['state']!='running' or current['locked'] or current['template'] or any(current[k]!=member[k] for k in ('vcpus','memory_mib','disk_mib')):fail('bundle_core_unavailable')
   if json.loads(config(member['vmid'])['description'])!={'pajio_core_provisioning':value}:fail('bundle_core_owner_changed')
  else:
   if member['vmid'] in live or any(v['vmid']==member['vmid'] for v in inv['core_promises']) or member['core_reservation_sha256'] is not None or member['memory_mib']<2048:fail('bundle_device_conflict')
   volumes=call('pvesh','get','/nodes/pve01/storage/local-lvm/content','--output-format','json')
   if any(v.get('vmid')==member['vmid'] for v in volumes):fail('bundle_device_volume_conflict')
   totals['vcpus']+=member['vcpus'];totals['memory_mib']+=member['memory_mib'];totals['recovery_and_missing_disk_mib']+=member['disk_mib']*2+4
 memory=sum(v['memory_mib'] for v in rows if v['kind']!='core')
 extra=totals['recovery_and_missing_disk_mib']
 if (totals['vcpus']+2>inv['physical_cores'] or totals['memory_mib']+6144>inv['memory_mib']
     or inv['available_memory_mib']<memory+6144
     or inv['committed_storage_mib']+extra>inv['storage_mib']*80//100
     or inv['available_storage_mib']<extra+inv['storage_mib']*20//100):fail('bundle_capacity_unavailable')
 directory(base);directory(folder)
 fd,temp=tempfile.mkstemp(prefix='.reservation-',dir=folder)
 try:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  os.link(temp,path);d=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(d)
  finally:os.close(d)
 finally:os.unlink(temp)
 final=inventory();matches=[v for v in final['resource_promises'] if v['reservation_id']==reservation['reservation_id']]
 if len(matches)!=3 or any(v['reservation_sha256']!=hashlib.sha256(raw).hexdigest() for v in matches):fail('bundle_reservation_unconfirmed')
 print(json.dumps({'reservation_sha256':hashlib.sha256(raw).hexdigest(),'reservation':reservation,'observed_at':time.time()}))
finally:os.close(lock)
'''


# Runs on the controller, not on the operator's laptop. No database credential
# is passed to the worker account. The actual running service and installed
# plan/artifacts must match before an invitation may be issued.
WORKER_PROBE = r'''
import hashlib,json,os,pwd,subprocess,sys,time
from pathlib import Path
from wearing.cloud.bundle_activation_pipeline import BundlePipeline
from wearing.cloud.instance import read_private
p=json.load(sys.stdin)
try:
 assert os.geteuid()==0
 assert set(p['modules'])=={'bundle_activation.py','bundle_activation_pipeline.py','bundle_activation_worker.py'}
 import wearing.cloud
 source_mtime=0
 for name,expected in p['modules'].items():
  source=Path(wearing.cloud.__file__).parent/name
  assert hashlib.sha256(source.read_bytes()).hexdigest()==expected
  source_mtime=max(source_mtime,source.stat().st_mtime)
 raw=subprocess.run(['systemctl','show','pajio-activation.service','--property=ActiveState,SubState,User,Group,MainPID,WorkingDirectory,UnitFileState'],check=True,capture_output=True,text=True,timeout=15).stdout
 service=dict(v.split('=',1) for v in raw.splitlines())
 assert service['ActiveState']=='active' and service['SubState']=='running' and service['UnitFileState']=='enabled'
 assert service['User']==service['Group']=='pajio-activation' and service['WorkingDirectory']=='/var/lib/pajio-activation'
 pid=int(service['MainPID']);assert pid>0
 assert (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')[:-1]==[b'/opt/wearing/venv/bin/python',b'-m',b'wearing.cloud.bundle_activation_worker',b'--root',b'/var/lib/pajio-activation']
 process_stat=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
 boot=int(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime ')))
 started=boot+int(process_stat[19])/os.sysconf('SC_CLK_TCK')
 assert source_mtime<=started and time.time()-started>=15
 u=pwd.getpwnam('pajio-activation');assert u.pw_uid!=0
 assert (Path('/proc')/str(pid)).stat().st_uid==u.pw_uid
 os.setgroups([]);os.setgid(u.pw_gid);os.setuid(u.pw_uid)
 pipe=BundlePipeline('/var/lib/pajio-activation')
 plan,members=pipe._plan({'bundle_id':p['bundle']['id'],'bundle':p['bundle']})
 pipe._core(plan)
 print(json.dumps({'worker_ready':True,'worker_plan_sha256':p['bundle']['worker_plan_sha256'],'bundle_id':p['bundle']['id'],'observed_at':time.time()}))
except Exception:
 print(json.dumps({'error':'bundle_worker_not_ready'}));sys.exit(1)
'''


class BundleOperator:
    def __init__(self, *, ssh_config, host, worker_host=None, runner=subprocess.run):
        if not __import__('re').fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}', host):
            raise ActivationError('bundle_host_invalid')
        self.config, self.host, self.runner = str(ssh_config), host, runner
        if worker_host is not None and not __import__('re').fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}',worker_host):
            raise ActivationError('bundle_worker_host_invalid')
        self.worker_host=worker_host

    def worker_ready(self, plan, reservation, plan_sha256):
        if not self.worker_host:
            raise ActivationError('bundle_worker_required')
        modules={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in
                 ('bundle_activation.py','bundle_activation_pipeline.py','bundle_activation_worker.py')}
        bundle={'id':plan.bundle_id,'tenant_id':plan.tenant_id,'instance_id':plan.instance_id,
                'host':plan.host,'reservation_sha256':plan.reservation_sha256,
                'worker_plan_sha256':plan_sha256,
                'members_json':{m.kind:m.model_dump(exclude={'kind'}) for m in reservation.members}}
        command=shlex.join(['sudo','-n','/opt/wearing/venv/bin/python','-I','-c',WORKER_PROBE])
        result=self.runner(['ssh','-F',self.config,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                           '-o','ConnectTimeout=10',self.worker_host,command],
                           input=json.dumps({'bundle':bundle,'modules':modules}),capture_output=True,text=True,timeout=60)
        try:
            value=json.loads(result.stdout)
            observed=value.pop('observed_at')
            import math
            valid=(not result.returncode and len(result.stdout)<=2048 and type(observed) in (int,float)
                   and math.isfinite(observed) and 0<=time.time()-observed<=60
                   and value=={'worker_ready':True,'worker_plan_sha256':plan_sha256,'bundle_id':plan.bundle_id})
        except (ValueError,TypeError,KeyError,AttributeError):
            valid=False
        if not valid:
            raise ActivationError('bundle_worker_not_ready')

    def reservation(self, value, *, create=False):
        value = BundleReservation.model_validate(value)
        result = self.runner(['ssh','-F',self.config,'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
            '-o','ConnectTimeout=10',self.host, shlex.join(['python3','-c',HOST])],
            input=json.dumps({'action':'reserve' if create else 'inspect','reservation':value.model_dump(),
                'reservation_raw':value.encoded(),'node':'pve01','storage':'local-lvm','vg':'pve','pool':'data'}),
            capture_output=True,text=True,timeout=120)
        if result.returncode or len(result.stdout)>65536:
            raise ActivationError('bundle_reservation_unconfirmed')
        observed=json.loads(result.stdout)
        if (observed.get('reservation')!=value.model_dump()
                or observed.get('reservation_sha256')!=hashlib.sha256(value.encoded().encode()).hexdigest()
                or not 0<=time.time()-observed.get('observed_at',0)<=60):
            raise ActivationError('bundle_reservation_unconfirmed')
        return observed

    def issue(self, store, *, reservation, worker_plan_path, issuer, output, lifetime=86400):
        reservation=BundleReservation.model_validate(reservation)
        raw=read_private(Path(worker_plan_path))
        plan=ActivationPlan.model_validate_json(raw)
        plan_sha256=hashlib.sha256(raw.encode()).hexdigest()
        observed=self.reservation(reservation)
        if (plan.reservation_sha256!=observed['reservation_sha256'] or plan.bundle_id!=reservation.reservation_id
                or plan.tenant_id!=reservation.tenant_id or plan.host!=self.host):
            raise ActivationError('bundle_issue_scope_changed')
        for kind,item in plan.devices.items():
            member=next(v for v in reservation.members if v.kind==kind)
            if any(getattr(item.spec,k)!=getattr(member,k) for k in ('vmid','request_id','vcpus','memory_mib','disk_mib')):
                raise ActivationError('bundle_issue_scope_changed')
        self.worker_ready(plan,reservation,plan_sha256)
        api=InvitationStore(store)
        api.bind_bundle(bundle_id=plan.bundle_id,tenant_id=plan.tenant_id,instance_id=plan.instance_id,
            host=plan.host,reservation_sha256=observed['reservation_sha256'],
            members={v.kind:v.model_dump(exclude={'kind'}) for v in reservation.members},
            reservation_expires_at=reservation.expires_at,worker_plan_path=worker_plan_path)
        # A second host read catches cleanup/capacity changes before issuing.
        self.reservation(reservation)
        self.worker_ready(plan,reservation,plan_sha256)
        return issue_to_file(store,issuer=issuer,tenant_id=plan.tenant_id,output=output,lifetime=lifetime,
                             bundle_id=plan.bundle_id,worker_plan_path=worker_plan_path)
