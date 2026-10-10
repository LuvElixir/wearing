#!/usr/bin/python3
"""Install a reviewed offline native bundle in a NEW dedicated device VM only.

Root operator entry. Every byte is verified before execution; artifact hash and
owner come from this clone's cloud-init, never from a tenant request. Repeating
an incomplete install is idempotent, but a paired device is never reinstalled.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import tempfile

LINUX={'setup-linux-desktop.sh','start-x11.sh','wait-x11.sh','start-desktop-session.sh',
       'pajio-x11.service','pajio-desktop-session.service','install-mozilla-firefox.sh',
       'pajio-firefox.user.js','pajio-browser.service','enable-linux-browser.sh'}
ANDROID={'setup-android-phone.sh','setup-device-mobile.py','pajio-private-input.apk','scrcpy-server-v5.0.1',
         'scrcpy-5.0.1-LICENSE','scrcpy-notices.json','node-v26.7.0-linux-x64.tar.xz',
         'redroid-amd64.tar','redroid-oci-manifest.json','verify-redroid-image.py'}
COMMON={'requirements-media.txt','hermes-source.tar.gz'}
REDROID_ARCHIVE_SHA256='113191519c4e5aa9864fbe15b79d816ed3d77f4fabc4c4a33840afeb9806a4ce'
REDROID_ARCHIVE_BYTES=873349120
REDROID='docker.m.daocloud.io/redroid/redroid@sha256:11d58a64bfbde2253d1cce81bff409ff58174980222d1bada232d9ef59181191'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def private(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_uid!=0 or path.stat().st_mode&0o077:
        raise ValueError('private_root_metadata_required')
    return json.loads(path.read_text())


def verify_bundle(directory,expected):
    directory=Path(directory)
    if directory.is_symlink() or not directory.is_dir():raise ValueError('invalid_runtime_bundle')
    manifest=json.loads((directory/'manifest.json').read_text())
    if set(manifest)!={'version','kind','files'} or manifest['version']!=1 or manifest['kind'] not in ('linux','android') or digest(manifest)!=expected:
        raise ValueError('runtime_manifest_changed')
    files=manifest['files'];required=COMMON|(LINUX if manifest['kind']=='linux' else ANDROID)
    if not isinstance(files,dict) or not required<=set(files) or len(files)>150:raise ValueError('runtime_bundle_incomplete')
    wheels=[v for v in files if re.fullmatch(r'wearing-[A-Za-z0-9_.+-]+\.whl',v)]
    if len(wheels)!=1:raise ValueError('runtime_wheel_required')
    for name,info in files.items():
        if name not in required and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,199}\.whl',name):
            raise ValueError('runtime_file_not_allowed')
        if not isinstance(info,dict) or set(info)!={'sha256','bytes'} or type(info['bytes']) is not int or not 0<info['bytes']<=(REDROID_ARCHIVE_BYTES if name=='redroid-amd64.tar' else 300*1024*1024) or not re.fullmatch('[a-f0-9]{64}',info['sha256']):
            raise ValueError('invalid_runtime_file_manifest')
        if name=='redroid-amd64.tar' and (info['bytes']!=REDROID_ARCHIVE_BYTES or info['sha256']!=REDROID_ARCHIVE_SHA256):
            raise ValueError('unapproved_redroid_archive')
        path=directory/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=info['bytes']:
            raise ValueError('runtime_file_changed')
        with path.open('rb') as f:
            checksum=hashlib.file_digest(f,'sha256').hexdigest()
        if checksum!=info['sha256']:raise ValueError('runtime_file_changed')
    if set(v.name for v in directory.iterdir())!=set(files)|{'manifest.json'}:raise ValueError('unexpected_runtime_file')
    return manifest,wheels[0]


def write(path,value):
    path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():raise ValueError('unsafe_runtime_receipt')
    fd,temporary_name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    temporary=Path(temporary_name)
    with os.fdopen(fd,'w') as f:json.dump(value,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)


def run(argv,**kwargs):
    # Installer never returns command output, which may later contain account
    # metadata. Bounded failures leave the exact artifact journal for retry.
    subprocess.run(argv,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1800,**kwargs)


def install(directory,artifact_sha256,vmid,machine_sha256):
    if os.geteuid()!=0:raise ValueError('operator_required')
    if hashlib.sha256(Path('/etc/machine-id').read_text().strip().encode()).hexdigest()!=machine_sha256:raise ValueError('runtime_guest_identity_changed')
    if not 100<=vmid<=999999999 or socket.gethostname()!='pajio-'+str(vmid):raise ValueError('fresh_clone_hostname_required')
    if Path('/etc/pve').exists() or Path('/var/lib/wearing/instance').exists():raise ValueError('dedicated_device_vm_required')
    run(['systemd-detect-virt','--vm','--quiet'])
    owner=private('/etc/pajio-native/device-owner.json');expected=private('/etc/pajio-native/bootstrap-expected.json')
    proof={'version':1,'owner_sha256':digest(owner),'artifact_sha256':artifact_sha256}
    if expected!=proof:raise ValueError('bootstrap_owner_or_artifact_changed')
    manifest,wheel=verify_bundle(directory,artifact_sha256)
    if owner['kind']!=manifest['kind']:raise ValueError('runtime_kind_changed')
    account='pajio-desktop' if manifest['kind']=='linux' else 'pajio-phone';home=Path('/home')/account
    marker=Path('/etc/pajio-native/bootstrap-installed.json')
    if marker.exists():
        if private(marker)!=proof:raise ValueError('runtime_already_owned')
        return {'installed':True,'already_installed':True,'product_ready':False,**proof}
    if (home/'.pajio-connector/connector.json').exists():raise ValueError('paired_device_cannot_reinstall')
    lock=os.open('/run/lock/pajio-runtime-install.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    journal=Path('/var/lib/pajio-native/runtime-install.json')
    if journal.exists() and private(journal)!=proof:raise ValueError('runtime_intent_changed')
    if not journal.exists():write(journal,proof)
    # Work only from root-owned immutable copies; uploads may be operator-owned.
    target=Path('/opt/pajio-native');target.mkdir(mode=0o755,exist_ok=True)
    if target.is_symlink() or target.stat().st_uid!=0 or target.stat().st_mode&0o022:raise ValueError('unsafe_runtime_target')
    stage=target/('bundle-'+artifact_sha256)
    if stage.exists():
        if stage.is_symlink() or stage.stat().st_uid!=0 or stage.stat().st_mode&0o077:raise ValueError('unsafe_runtime_stage')
        verify_bundle(stage,artifact_sha256)
    else:
        temporary=Path(tempfile.mkdtemp(prefix='.bundle-'+artifact_sha256+'-',dir=target))
        try:
            for name in list(manifest['files'])+['manifest.json']:
                with (Path(directory)/name).open('rb') as inp,(temporary/name).open('xb') as out:shutil.copyfileobj(inp,out)
                (temporary/name).chmod(0o600)
            verify_bundle(temporary,artifact_sha256)
            os.rename(temporary,stage)
        finally:
            if temporary.exists():shutil.rmtree(temporary)
    venv=target/'venv'
    run(['/usr/bin/python3','-m','venv',str(venv)])
    run([str(venv/'bin/python'),'-m','pip','install','--disable-pip-version-check','--no-index','--find-links',str(stage),'--require-hashes','-r',str(stage/'requirements-media.txt')])
    run([str(venv/'bin/python'),'-m','pip','install','--disable-pip-version-check','--no-index','--no-deps','--force-reinstall',str(stage/wheel)])
    source_code="""from pathlib import Path
from wearing.runtime import unpack_source,HERMES_REVISION,SOURCE_SHA256
import sys
p=Path('/opt/pajio-native/source');p.mkdir(exist_ok=True)
unpack_source(Path(sys.argv[1]),p)
(p/('hermes-agent-'+HERMES_REVISION)/'.wearing-source-verified').write_text(SOURCE_SHA256)
"""
    run([str(venv/'bin/python'),'-c',source_code,str(stage/'hermes-source.tar.gz')])
    if manifest['kind']=='linux':
        run(['/bin/bash',str(stage/'setup-linux-desktop.sh')])
        run(['/bin/bash',str(stage/'install-mozilla-firefox.sh')])
        # Do not dismiss Firefox first-run terms or launch a profile on behalf of
        # a new user. Enrollment reports terms pending until actual acceptance.
    else:
        if vmid>45535:raise ValueError('android_vmid_out_of_range')
        serial='127.0.0.1:'+str(20000+vmid)
        rid='phone_'+hashlib.sha256(serial.encode()).hexdigest()[:20]
        if owner['resource_id']!=rid:raise ValueError('android_transport_binding_changed')
        shutil.copyfile(stage/'pajio-private-input.apk',target/'pajio-private-input.apk')
        (target/'pajio-private-input.apk').chmod(0o644)
        run(['systemctl','enable','--now','docker'])
        definition=importlib.util.spec_from_file_location('redroid_verifier',stage/'verify-redroid-image.py')
        verifier=importlib.util.module_from_spec(definition);definition.loader.exec_module(verifier)
        image=verifier.ensure_loaded(stage)
        run(['/bin/bash',str(stage/'setup-android-phone.sh'),image],env={**os.environ,'PAJIO_ANDROID_ADB_PORT':str(20000+vmid)})
        run([str(venv/'bin/python'),str(stage/'setup-device-mobile.py'),str(stage),str(vmid)])
    u=pwd.getpwnam(account)
    # Marker is used only by the restricted NativeAdapter, never an Agent shell.
    marker_code="""import json,os,pwd
from pathlib import Path
from wearing.runtime import HERMES_REVISION,SOURCE_SHA256
import sys
u=pwd.getpwnam(sys.argv[1]);d=Path(u.pw_dir)/'.pajio'
for p in (d,d/'runtime',d/'hermes'):
 p.mkdir(mode=0o700,exist_ok=True);os.chown(p,u.pw_uid,u.pw_gid)
p=d/'runtime/native-driver.json'
p.write_text(json.dumps({'version':1,'revision':HERMES_REVISION,'source_sha256':SOURCE_SHA256,'source':'/opt/pajio-native/source/hermes-agent-'+HERMES_REVISION,'python':'/opt/pajio-native/venv/bin/python'}));p.chmod(0o600);os.chown(p,u.pw_uid,u.pw_gid)
"""
    run([str(venv/'bin/python'),'-c',marker_code,account])
    # Android also needs a persistent user manager for the connector service.
    run(['loginctl','enable-linger',account]);run(['systemctl','start',f'user@{u.pw_uid}.service'])
    write(marker,proof)
    return {'installed':True,'already_installed':False,'product_ready':False,**proof}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--artifact-sha256',required=True);parser.add_argument('--vmid',type=int,required=True)
    parser.add_argument('--machine-sha256',required=True)
    a=parser.parse_args()
    try:print(json.dumps(install(a.bundle,a.artifact_sha256,a.vmid,a.machine_sha256)))
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and re.fullmatch('[a-z_]{1,80}',str(error)) else 'runtime_install_incomplete'
        parser.exit(2,code+'\n')

if __name__=='__main__':main()
