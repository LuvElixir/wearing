"""Narrow operator repair for one known Android base-image package error.

The original cloud-init failure remains visible. No API accepts uploaded repair
success; delivery reruns the root receipt and installed-package checks via QGA.
"""
import json
from pathlib import Path
import re
import shlex
import subprocess

from .device_provisioning import ProvisionError, fingerprint


REPAIR_VALIDATION_SOURCE = r'''
import hashlib,json,os,pathlib,platform,re,subprocess
_REPAIR_ERROR = "('package_update_upgrade_install', PackageInstallerError(\"Failed to install the following packages: {'linux-modules-extra-generic'}. See associated package manager logs for more details.\"))"
_REPAIR_BASE = ('docker.io','adb','python3-venv','qemu-guest-agent','nginx','curl','ca-certificates','gnupg')
_REPAIR_WARNING = [
 "Failure when attempting to install packages: ['docker.io', 'adb', 'linux-modules-extra-generic', 'python3-venv', 'qemu-guest-agent', 'nginx', 'curl', 'ca-certificates', 'gnupg']",
 '1 failed with exceptions, re-raising the last one',
 "Running module package_update_upgrade_install (<module 'cloudinit.config.cc_package_update_upgrade_install' from '/usr/lib/python3/dist-packages/cloudinit/config/cc_package_update_upgrade_install.py'>) failed"]
def _repair_digest(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def _repair_cloud_allowed(state):
 if state.get('status')!='error' or state.get('stage') is not None or state.get('errors')!=[_REPAIR_ERROR]:return False
 for stage in ('init-local','init','modules-config'):
  if state.get(stage,{}).get('errors')!=[] or state.get(stage,{}).get('recoverable_errors')!={}:return False
 final=state.get('modules-final',{})
 return (final.get('errors')==[_REPAIR_ERROR] and final.get('recoverable_errors')=={'WARNING':_REPAIR_WARNING}
         and state.get('recoverable_errors')=={'WARNING':_REPAIR_WARNING})
def _repair_private(path):
 p=pathlib.Path(path)
 if any(x.is_symlink() for x in (p,*p.parents)) or not p.is_file():raise ValueError('unsafe_bootstrap_repair_receipt')
 s=p.stat()
 if s.st_uid!=0 or s.st_mode&0o077 or s.st_size>131072:raise ValueError('unsafe_bootstrap_repair_receipt')
 return json.loads(p.read_text())
def _repair_cmd(argv):
 r=subprocess.run(argv,capture_output=True,text=True,timeout=30)
 if r.returncode:raise ValueError('bootstrap_repair_probe_failed')
 return r.stdout.strip()
def _repair_observe(kernel):
 if kernel!=platform.release() or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-[0-9]+-generic',kernel):raise ValueError('bootstrap_repair_kernel_changed')
 names=(*_REPAIR_BASE,'linux-modules-extra-'+kernel)
 output=_repair_cmd(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${db:Status-Status}\n',*names])
 packages={}
 for line in output.splitlines():
  name,version,status=line.split('\t')
  if name not in names or status!='installed' or not re.fullmatch('[A-Za-z0-9.+:~_-]{1,200}',version):raise ValueError('bootstrap_repair_packages_unconfirmed')
  packages[name]=version
 if set(packages)!=set(names):raise ValueError('bootstrap_repair_packages_unconfirmed')
 module=pathlib.Path(_repair_cmd(['modinfo','-F','filename','binder_linux'])).resolve()
 base=pathlib.Path('/lib/modules',kernel).resolve()
 if not module.is_relative_to(base) or not module.name.startswith('binder_linux.ko') or not module.is_file():raise ValueError('bootstrap_repair_module_unconfirmed')
 s=module.stat()
 if s.st_uid!=0 or s.st_mode&0o022:raise ValueError('bootstrap_repair_module_unconfirmed')
 if not _repair_cmd(['modinfo','-F','vermagic','binder_linux']).startswith(kernel+' '):raise ValueError('bootstrap_repair_module_unconfirmed')
 with module.open('rb') as f:module_sha=hashlib.file_digest(f,'sha256').hexdigest()
 return {'packages':packages,'module_path':str(module),'module_sha256':module_sha}
def _repair_receipt_matches(receipt,owner,expected,machine_sha256,cloud_state,kernel,observed):
 required={'version','repair','owner_sha256','artifact_sha256','machine_sha256','kernel','cloud_error_sha256','packages','module_path','module_sha256'}
 return (set(receipt)==required and type(receipt['version']) is int and receipt['version']==1
   and receipt['repair']=='android_missing_exact_kernel_modules'
   and owner.get('kind')=='android' and receipt['owner_sha256']==_repair_digest(owner)
   and expected=={'version':1,'owner_sha256':_repair_digest(owner),'artifact_sha256':receipt['artifact_sha256']}
   and receipt['machine_sha256']==machine_sha256 and receipt['kernel']==kernel
   and _repair_cloud_allowed(cloud_state) and receipt['cloud_error_sha256']==_repair_digest(cloud_state)
   and all(receipt[k]==observed[k] for k in ('packages','module_path','module_sha256')))
def verify_bootstrap_repair(owner,expected,machine_sha256,cloud_state):
 try:
  receipt=_repair_private('/etc/pajio-native/bootstrap-repair.json')
  original=_repair_private('/var/lib/pajio-native/bootstrap-repair-cloud-init.json')
  # The snapshot is immutable evidence; later boots can legitimately change
  # cloud-init timestamps. Recheck the current exact error set separately.
  if _repair_digest(original)!=receipt.get('cloud_error_sha256') or not _repair_cloud_allowed(cloud_state):return False
  kernel=platform.release();observed=_repair_observe(kernel)
  return _repair_receipt_matches(receipt,owner,expected,machine_sha256,original,kernel,observed)
 except Exception:return False
'''


GUEST_REPAIR_SOURCE = REPAIR_VALIDATION_SOURCE + r'''
import fcntl,tempfile,time
def _repair_write_once(path,value):
 p=pathlib.Path(path)
 if any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('unsafe_bootstrap_repair_receipt')
 if p.exists():
  if _repair_private(p)!=value:raise ValueError('bootstrap_repair_receipt_changed')
  return
 p.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
 fd,temporary=tempfile.mkstemp(prefix='.bootstrap-repair-',dir=p.parent)
 try:
  with os.fdopen(fd,'w') as f:json.dump(value,f,sort_keys=True,allow_nan=False);f.flush();os.fsync(f.fileno())
  # A crash while serializing must never publish a partial receipt. Hard-link
  # commit is atomic and refuses to replace evidence created by another writer.
  try:os.link(temporary,p,follow_symlinks=False)
  except FileExistsError:
   if _repair_private(p)!=value:raise ValueError('bootstrap_repair_receipt_changed')
  directory=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(directory)
  finally:os.close(directory)
 finally:os.unlink(temporary)
def perform_bootstrap_repair(intent):
 if os.geteuid()!=0:raise ValueError('operator_required')
 owner=_repair_private('/etc/pajio-native/device-owner.json')
 expected=_repair_private('/etc/pajio-native/bootstrap-expected.json')
 if _repair_digest(owner)!=intent['owner_sha256'] or owner.get('kind')!='android':raise ValueError('bootstrap_repair_owner_changed')
 if expected!={'version':1,'owner_sha256':intent['owner_sha256'],'artifact_sha256':intent['artifact_sha256']}:raise ValueError('bootstrap_repair_artifact_changed')
 if pathlib.Path('/etc/pajio-native/bootstrap-installed.json').exists():raise ValueError('bootstrap_repair_only_before_runtime')
 lock=os.open('/run/lock/pajio-bootstrap-repair.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 state_result=subprocess.run(['cloud-init','status','--format','json'],capture_output=True,text=True,timeout=20)
 state=json.loads(state_result.stdout)
 if state_result.returncode!=1 or not _repair_cloud_allowed(state):raise ValueError('bootstrap_repair_error_not_allowed')
 kernel=platform.release()
 if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-[0-9]+-generic',kernel):raise ValueError('bootstrap_repair_kernel_changed')
 machine=hashlib.sha256(pathlib.Path('/etc/machine-id').read_text().strip().encode()).hexdigest()
 original='/var/lib/pajio-native/bootstrap-repair-cloud-init.json'
 _repair_write_once(original,state)
 installed=pathlib.Path('/etc/pajio-native/bootstrap-repair.json')
 if not installed.exists():
  # The exact running-kernel package is idempotent. This contains no account,
  # login, pairing or app data and never invokes cloud-init clean/reinitialise.
  env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'}
  result=subprocess.run(['apt-get','-y','install','--no-install-recommends','linux-modules-extra-'+kernel],
      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,timeout=900)
  if result.returncode:raise ValueError('bootstrap_repair_package_install_failed')
 observed=_repair_observe(kernel)
 receipt={'version':1,'repair':'android_missing_exact_kernel_modules','owner_sha256':intent['owner_sha256'],
  'artifact_sha256':intent['artifact_sha256'],'machine_sha256':machine,'kernel':kernel,
  'cloud_error_sha256':_repair_digest(state),**observed}
 _repair_write_once(installed,receipt)
 if not verify_bootstrap_repair(owner,expected,machine,state):raise ValueError('bootstrap_repair_verification_failed')
 return {'bootstrap_repair_verified':True,'raw_cloud_init_status':'error','cloud_init_ready':False,
         'owner_sha256':intent['owner_sha256'],'artifact_sha256':intent['artifact_sha256'],
         'machine_sha256':machine,'kernel':kernel,'receipt_sha256':_repair_digest(receipt),'packages':observed['packages']}
'''


HOST_REPAIR_SOURCE = r'''
import json,os,subprocess,sys
p=json.load(sys.stdin)
if os.geteuid()!=0:raise ValueError('operator_required')
spec,owner=p['spec'],p['owner']
def call(args):
 r=subprocess.run(args,capture_output=True,text=True,timeout=45)
 if r.returncode:raise ValueError('bootstrap_repair_host_probe_failed')
 return json.loads(r.stdout)
c=call(['pvesh','get',f'/nodes/{p["node"]}/qemu/{spec["vmid"]}/config','--output-format','json'])
current=call(['pvesh','get',f'/nodes/{p["node"]}/qemu/{spec["vmid"]}/status/current','--output-format','json'])
if (json.loads(c.get('description','{}')).get('pajio_provisioning')!=owner or c.get('template') or c.get('lock')
    or current.get('status')!='running'):raise ValueError('bootstrap_repair_host_owner_changed')
source=p['guest_source']+'\ntry:\n print(json.dumps(perform_bootstrap_repair('+repr(p['intent'])+')))\nexcept Exception as error:\n print(json.dumps({"error":str(error) if isinstance(error,ValueError) else "bootstrap_repair_incomplete"}));raise SystemExit(1)\n'
r=subprocess.run(['qm','guest','exec',str(spec['vmid']),'--timeout','1000','--','/usr/bin/python3','-c',source],capture_output=True,text=True,timeout=1020)
if r.returncode:raise ValueError('bootstrap_repair_guest_outcome_unknown')
out=json.loads(r.stdout)
if out.get('exitcode')!=0:raise ValueError('bootstrap_repair_guest_failed')
print(out['out-data'])
'''


def repair_bootstrap(*, config, host, node, spec, owner, artifact_sha256, runner=subprocess.run):
    if (spec.kind != 'android' or owner.request_sha256 != fingerprint(spec.model_dump())
            or owner.tenant_id != spec.tenant_id or owner.identity_id != spec.identity_id
            or owner.resource_id != spec.resource_id or owner.request_id != spec.request_id
            or owner.kind != spec.kind or owner.vcpus != spec.vcpus
            or owner.memory_mib != spec.memory_mib or owner.disk_mib != spec.disk_mib
            or not re.fullmatch('[a-f0-9]{64}', artifact_sha256)
            or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}', host)
            or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}', node)):
        raise ProvisionError('invalid_bootstrap_repair_scope')
    payload = {'spec': spec.model_dump(), 'owner': owner.model_dump(), 'node': node,
        'guest_source': GUEST_REPAIR_SOURCE,
        'intent': {'owner_sha256': fingerprint(owner.model_dump()), 'artifact_sha256': artifact_sha256}}
    result = runner(['ssh', '-F', str(Path(config).absolute()), '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', host,
        '/usr/bin/python3 -c ' + shlex.quote(HOST_REPAIR_SOURCE)],
        input=json.dumps(payload), text=True, capture_output=True, timeout=1050)
    if result.returncode:
        raise ProvisionError('bootstrap_repair_outcome_unknown')
    try:
        output = json.loads(result.stdout)
        if (output.get('bootstrap_repair_verified') is not True or output.get('cloud_init_ready') is not False
                or output.get('raw_cloud_init_status') != 'error'
                or output.get('owner_sha256') != payload['intent']['owner_sha256']
                or output.get('artifact_sha256') != artifact_sha256):
            raise ValueError()
        return output
    except (ValueError, KeyError):
        raise ProvisionError('bootstrap_repair_unconfirmed') from None
