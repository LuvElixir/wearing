"""Fixed SSH/QGA transport for first boot and verified per-clone runtime install."""
import importlib.util
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from .device_power_ssh import SSHPowerAdapter
from .device_enrollment import EnrollmentSources
from .device_provisioning import ProvisionError,fingerprint
from .proxmox_devices import REMOTE

from .device_bootstrap_repair import REPAIR_VALIDATION_SOURCE

UPLOAD_CHECK = r'''
import hashlib,json,os,pathlib,sys
try:
 p=pathlib.Path(sys.argv[1]);expected=json.load(sys.stdin)
 assert not p.is_symlink() and p.is_dir() and p.stat().st_uid==os.getuid()
 assert {v.name for v in p.iterdir()}==set(expected)
 for name,sha in expected.items():
  assert pathlib.Path(name).name==name
  v=p/name
  assert not v.is_symlink() and v.is_file() and v.stat().st_uid==os.getuid()
  with v.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==sha
except Exception:sys.exit(1)
'''

QGA_SOURCE=REPAIR_VALIDATION_SOURCE + r'''
import hashlib,json,pathlib,subprocess
p=pathlib.Path
owner=json.loads(p('/etc/pajio-native/device-owner.json').read_text())
sha=lambda value:hashlib.sha256(value.encode()).hexdigest()
machine=p('/etc/machine-id').read_text().strip()
cloud=subprocess.run(['cloud-init','status','--format','json'],capture_output=True,text=True,timeout=10)
state=json.loads(cloud.stdout)
expected=json.loads(p('/etc/pajio-native/bootstrap-expected.json').read_text())
cloud_ready=state.get('status')=='done' and not state.get('errors') and cloud.returncode==0
repaired=not cloud_ready and verify_bootstrap_repair(owner,expected,sha(machine),state)
ips=json.loads(subprocess.check_output(['ip','-j','addr'],text=True))
print(json.dumps({'owner_sha256':sha(json.dumps(owner,sort_keys=True,separators=(',',':'))),'machine_sha256':sha(machine),
'ssh_host_key':p('/etc/ssh/ssh_host_ed25519_key.pub').read_text().strip(),'cloud_init_ready':cloud_ready,'raw_cloud_init_status':state.get('status'),'bootstrap_repair_verified':repaired,
'interfaces':[{'mac':v.get('address','').lower(),'addresses':[a['local'] for a in v.get('addr_info',[]) if a.get('scope')=='global' and a.get('family')=='inet']} for v in ips]}))
'''

HOST = REMOTE.split("for key in ('node','storage','vg','pool'):")[0]+r'''
from pathlib import Path
import importlib.util
if os.geteuid()!=0:fail('operator_required')
spec,expected,bundle=p['spec'],p['owner'],p['bundle'];vid=spec['vmid'];c=config(vid);manifest=bundle['manifest']
if owner(c)!=expected or c.get('template') or c.get('lock'):fail('device_owner_changed')
renderer=Path('/usr/local/libexec/pajio-render-device-network.py')
if renderer.is_symlink() or renderer.stat().st_uid!=0 or renderer.stat().st_mode&0o022:fail('network_renderer_required')
s=importlib.util.spec_from_file_location('pajio_network',renderer);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
leases=m.load();target=[v for v in leases if v['vmid']==vid]
if target!=[json.loads(bundle['files']['network-lease.json'])]:fail('device_network_scope_changed')
for family,table,chain in [('inet','pajio_lab_guard',f'pv{vid}_input'),('inet','pajio_lab_guard',f'pv{vid}_forward'),('ip','pajio_lab_nat','provisioned_nat')]:
 call('nft','-j','list','chain',family,table,chain)
if p['action']=='network':print(json.dumps({'staged_network':True}));sys.exit()
if p['action']!='attest':fail('invalid_delivery_action')
source=__QGA_SOURCE__
# This is a read-only observation after a durably recorded start. A fresh
# guest often has no QGA yet; only that known condition or this bounded query's
# timeout is retryable. Never turn an arbitrary host/configuration error into
# a healthy boot, and never expose provider stderr in the receipt.
try:
 qga=subprocess.run(['qm','guest','exec',str(vid),'--','/usr/bin/python3','-c',source],capture_output=True,text=True,timeout=45)
except subprocess.TimeoutExpired:
 fail('fresh_os_attestation_pending')
if qga.returncode:
 message=qga.stderr.strip()
 if (message=='QEMU guest agent is not running'
     or re.fullmatch(r"VM "+str(vid)+r" qmp command 'guest-(?:exec|ping)' failed - (?:got timeout|command timed out)",message)):
  fail('fresh_os_attestation_pending')
 fail('proxmox_query_failed')
try:r=json.loads(qga.stdout)
except (ValueError,TypeError):fail('proxmox_query_failed')
if not isinstance(r,dict):fail('proxmox_query_failed')
if r.get('exitcode')!=0:fail('fresh_os_attestation_pending')
v=json.loads(r.get('out-data','{}'))
def management_matches(net0,interfaces,address):
 parts=dict(item.split('=',1) for item in net0.split(',') if '=' in item)
 mac=parts.get('virtio','').lower()
 if not re.fullmatch(r'(?:[a-f0-9]{2}:){5}[a-f0-9]{2}',mac):return False
 matching=[item for item in interfaces if item.get('mac')==mac]
 return len(matching)==1 and matching[0].get('addresses')==[address]
if v.get('owner_sha256')!=digest(expected) or not management_matches(c.get('net0',''),v.get('interfaces',[]),manifest['guest_ipv4']) or not re.fullmatch('[a-f0-9]{64}',v.get('machine_sha256','')):fail('fresh_os_attestation_changed')
if not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}(?: [^\r\n]*)?',v.get('ssh_host_key','')):fail('fresh_os_host_key_missing')
print(json.dumps(v))
'''

HOST=HOST.replace('__QGA_SOURCE__',repr(QGA_SOURCE))

GUEST = r'''
import hashlib,json,os,pwd,socket,subprocess,sys,urllib.request
from pathlib import Path
p=json.load(sys.stdin)
def read(path,uid=0):
 path=Path(path)
 assert path.is_file() and not path.is_symlink() and path.stat().st_uid==uid and not path.stat().st_mode&0o077
 return json.loads(path.read_text())
try:
 assert os.geteuid()==0
 owner=read('/etc/pajio-native/device-owner.json');assert owner==p['owner']
 machine=hashlib.sha256(Path('/etc/machine-id').read_text().strip().encode()).hexdigest();assert machine==p['machine_sha256']
 installed=read('/etc/pajio-native/bootstrap-installed.json')
 expected={'version':1,'owner_sha256':p['owner_sha256'],'artifact_sha256':p['artifact_sha256']};assert installed==expected
 if p['action']=='runtime_status':print(json.dumps(installed));sys.exit()
 assert p['action']=='evidence'
 def connected(address,port):
  try:
   with socket.create_connection((address,port),timeout=2):return True
  except TimeoutError:return False
  except OSError:return None
 blocked=[(p['gateway_ipv4'],22),(p['gateway_ipv4'],8006),('192.168.1.1',80),('10.77.100.2',22),('10.77.103.2',9443),('10.77.104.2',9443),(p['tenant_ipv4'],22)]
 network=all(connected(ip,port) is False for ip,port in blocked) and connected(p['tenant_ipv4'],8444) is True
 service=pwd.getpwnam('pajio-desktop' if p['spec']['kind']=='linux' else 'pajio-phone')
 assert service.pw_uid!=0 and service.pw_dir=='/home/'+service.pw_name and service.pw_shell=='/usr/sbin/nologin'
 config=read('/etc/pajio/media-host.json',service.pw_uid);req=urllib.request.Request('http://127.0.0.1:8792/v1/status',headers={'Authorization':'Bearer '+config['token']})
 with urllib.request.urlopen(req,timeout=5) as r:status=json.loads(r.read(65537))
 rid=p['spec']['resource_id']
 native=status.get('ready') is True and status.get('resources')==[rid]
 uid=str(service.pw_uid)
 environment=['HOME='+service.pw_dir,'XDG_RUNTIME_DIR=/run/user/'+uid,'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+uid+'/bus']
 if p['spec']['kind']=='linux':
  # Media capture can work while the Agent's AT-SPI/screenshot backend lacks
  # dependencies. Probe that exact backend under the dedicated user's session.
  probe='import json;from wearing.linux_computer import linux_computer_status;v=linux_computer_status();print(json.dumps({"ready":v.get("ready") is True and v.get("installed") is True}))'
  environment+=['DISPLAY=:10',
   'XAUTHORITY=/run/user/'+uid+'/pajio-x11/Xauthority','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/'+uid+'/pajio-desktop-bus',
   'XDG_SESSION_TYPE=x11']
 else:
  # ADB heartbeat and video do not exercise the Agent's phone MCP resolver.
  # Run one read-only tool through the same NativeAdapter and ownership gate.
  probe='import asyncio,json,re\nfrom pathlib import Path\nfrom types import SimpleNamespace\nfrom wearing.connectors.remote.adapter import NativeAdapter\nasync def main():\n async with NativeAdapter(Path.home()/".pajio") as native:\n  value=await native.execute(SimpleNamespace(resource_id='+repr(rid)+',method="phone.mobile_get_screen_size",params={}))\n  sizes=[re.fullmatch(r"Screen size is ([1-9][0-9]*)x([1-9][0-9]*) pixels",v.get("text","")) for v in value.get("content",[]) if v.get("type")=="text"]\n  ready=value.get("isError") is False and any(m and int(m[1])<=16384 and int(m[2])<=16384 for m in sizes)\n  print(json.dumps({"ready":bool(ready)}))\nasyncio.run(main())'
 result=subprocess.run(['runuser','-u',service.pw_name,'--','env',*environment,'/opt/pajio-native/venv/bin/python','-c',probe],
  stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=30)
 backend=result.returncode==0 and len(result.stdout)<65536 and json.loads(result.stdout).get('ready') is True
 native=native and backend
 # Base-device readiness is separate from a specific application's first run.
 # Android AOSP has no blanket acceptance dialog. Firefox starts only when the
 # user elects to launch it; absence of an app-specific proof is an honest
 # browser limitation, never a reason to invent a system-wide consent gate.
 browser=None;browser_state='not_applicable'
 if p['spec']['kind']=='linux':
  browser=False;browser_state='first_run_unverified'
  record=Path('/etc/pajio-native/browser-ready.json')
  if record.exists():
   value=read(record)
   browser=value.get('owner_sha256')==p['owner_sha256'] and value.get('application')=='firefox' and value.get('first_run_verified') is True and bool(value.get('evidence_ref'))
   if browser:browser_state='ready'
 print(json.dumps({'network_isolated':network,'native_ready':native,'native_backend_ready':backend,'browser_ready':browser,'browser_setup_state':browser_state}))
except SystemExit:raise
except Exception:
 print(json.dumps({'error':'delivery_evidence_unavailable'}));sys.exit(1)
'''

STARTUP_REMOTE = REMOTE.split("for key in ('node','storage','vg','pool'):")[0]+r'''
if os.geteuid()!=0:fail('operator_required')
for key in ('node','storage','vg','pool'):
 if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}',p.get(key,'')):fail('invalid_operator_target')
spec,expected=p['spec'],p['owner'];c=config(spec['vmid'])
if owner(c)!=expected or c.get('template') or c.get('lock'):fail('device_owner_changed')
def result(c):
 updated=dict(c);updated['onboot']=1
 return {'before_sha256':digest(c),'after_sha256':digest(updated),'onboot':int(c.get('onboot',0))}
if p['action']=='startup_plan':print(json.dumps(result(c)));sys.exit()
if p['action']!='startup_apply':fail('invalid_delivery_action')
lock=os.open('/run/lock/pajio-device-provision.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:fail('host_provision_inflight')
c=config(spec['vmid']);plan=p['plan']
if owner(c)!=expected or c.get('template') or c.get('lock') or digest(c)!=plan['before_sha256'] or result(c)['after_sha256']!=plan['after_sha256']:fail('device_configuration_changed')
run_change(['qm','set',str(spec['vmid']),'--digest',c['digest'],'--onboot','1'])
c=config(spec['vmid'])
if owner(c)!=expected or digest(c)!=plan['after_sha256'] or int(c.get('onboot',0))!=1:fail('startup_outcome_unknown_no_replay')
print(json.dumps(result(c)))
'''

def upload_digests(directory):
    # Runtime images can exceed the worker's memory limit; only the fixed-size
    # file_digest buffer is live while hashing each reviewed public artifact.
    values={}
    for path in Path(directory).iterdir():
        with path.open('rb') as stream:
            values[path.name]=hashlib.file_digest(stream,'sha256').hexdigest()
    return values


class SSHDeliveryAdapter(SSHPowerAdapter):
    def __init__(self,*,delivery_sources,runtime_bundle=None,installer=None,**kwargs):
        super().__init__(sources={'tenants':{},'devices':{}},**kwargs)
        self.guest_sources=EnrollmentSources.model_validate(delivery_sources)
        self.runtime_bundle=Path(runtime_bundle).absolute() if runtime_bundle else None
        self.installer=Path(installer).absolute() if installer else None

    def startup_config(self,spec,owner):
        return self._remote(self.host,'/usr/bin/python3',STARTUP_REMOTE,{**self.params,'action':'startup_plan','spec':spec.model_dump(),'owner':owner.model_dump()})

    def set_autostart(self,spec,owner,plan):
        return self._remote(self.host,'/usr/bin/python3',STARTUP_REMOTE,{**self.params,'action':'startup_apply','spec':spec.model_dump(),'owner':owner.model_dump(),'plan':plan})

    def _host_check(self,action,spec,owner,bundle):
        return self._remote(self.host,'/usr/bin/python3',HOST,{**self.params,'action':action,'spec':spec.model_dump(),'owner':owner.model_dump(),'bundle':bundle})

    def verify_staged_network(self,spec,owner,bundle):
        if self._host_check('network',spec,owner,bundle).get('staged_network') is not True:raise ProvisionError('device_network_unconfirmed')

    def attest(self,spec,owner,bundle):return self._host_check('attest',spec,owner,bundle)

    def _guest(self,action,spec,owner,bundle,machine):
        target=self.guest_sources.devices.get(spec.resource_id)
        if not target:raise ProvisionError('trusted_guest_ssh_target_required')
        lease=json.loads(bundle['files']['network-lease.json'])
        return self._remote(target.host,'/usr/bin/python3',GUEST,{'action':action,'spec':spec.model_dump(),'owner':owner.model_dump(),
            'owner_sha256':fingerprint(owner.model_dump()),'machine_sha256':machine,'artifact_sha256':bundle['manifest']['artifact_sha256'],
            'gateway_ipv4':bundle['manifest']['gateway_ipv4'],'tenant_ipv4':lease['tenant_ipv4']})

    def runtime_status(self,*args):return self._guest('runtime_status',*args)
    def delivery_evidence(self,*args):return self._guest('evidence',*args)

    def install_runtime(self,spec,owner,bundle,machine):
        if not self.allow_create or not self.runtime_bundle or not self.installer:raise ProvisionError('reviewed_runtime_bundle_required')
        target=self.guest_sources.devices.get(spec.resource_id)
        if not target:raise ProvisionError('trusted_guest_ssh_target_required')
        # The local installer is an operator-installed program; only its pure
        # verifier is called before any transfer. Uploaded bytes are reverified.
        definition=importlib.util.spec_from_file_location('pajio_runtime_installer',self.installer)
        verifier=importlib.util.module_from_spec(definition);definition.loader.exec_module(verifier)
        artifact=bundle['manifest']['artifact_sha256'];verifier.verify_bundle(self.runtime_bundle,artifact)
        if self.attest(spec,owner,bundle).get('machine_sha256')!=machine:raise ProvisionError('device_os_identity_changed')
        remote='/tmp/pajio-runtime-'+artifact
        ssh=['ssh','-F',str(self.config),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',target.host]
        prepare="import os,pathlib,sys;p=pathlib.Path(sys.argv[1]);p.mkdir(mode=0o700,exist_ok=True);assert not p.is_symlink() and p.is_dir() and p.stat().st_uid==os.getuid() and not p.stat().st_mode&0o077"
        mkdir='/usr/bin/python3 -c '+shlex.quote(prepare)+' '+shlex.quote(remote)
        try:
            self.runner(ssh+[mkdir],check=True,capture_output=True,text=True,timeout=30)
            expected=upload_digests(self.runtime_bundle)
            command='/usr/bin/python3 -c '+shlex.quote(UPLOAD_CHECK)+' '+shlex.quote(remote+'/'+self.runtime_bundle.name)
            reusable=self.runner(ssh+[command],input=json.dumps(expected),capture_output=True,text=True,timeout=60).returncode==0
            # Reuse only byte-identical public artifacts; always send the current
            # operator installer. The root installer independently verifies all
            # bytes again before using its immutable, owner-bound stage.
            sources=([str(self.runtime_bundle)] if not reusable else [])+[str(self.installer)]
            copy=['scp','-q','-r','-F',str(self.config),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',*sources,target.host+':'+remote+'/']
            self.runner(copy,check=True,capture_output=True,text=True,timeout=600)
            command='sudo -n /usr/bin/python3 '+shlex.quote(remote+'/'+self.installer.name)+' --bundle '+shlex.quote(remote+'/'+self.runtime_bundle.name)+' --artifact-sha256 '+artifact+' --vmid '+str(spec.vmid)+' --machine-sha256 '+machine
            result=self.runner(ssh+[command],capture_output=True,text=True,timeout=2100)
            if result.returncode:raise ProvisionError('runtime_install_incomplete')
            installed=json.loads(result.stdout)
            if installed.get('installed') is not True:raise ProvisionError('runtime_install_unconfirmed')
        except (OSError,ValueError,subprocess.SubprocessError) as error:
            if isinstance(error,ProvisionError):raise
            raise ProvisionError('runtime_install_outcome_unknown') from None
