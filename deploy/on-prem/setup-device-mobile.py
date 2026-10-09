#!/usr/bin/python3
"""Pinned native Android drivers for a freshly created private phone account."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tarfile
import tempfile


def run(argv,**kwargs):
    subprocess.run(argv,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=600,**kwargs)


def install(bundle,vmid):
    if os.geteuid()!=0 or not 100<=vmid<=45535:raise ValueError('operator_android_vmid_required')
    from wearing import mobile
    from wearing.config import write_private_json
    from wearing.private_media_android import SCRCPY_SHA256,PRIVATE_IME_SHA256
    bundle=Path(bundle);target=Path('/opt/pajio-native');u=pwd.getpwnam('pajio-phone');home=Path(u.pw_dir)
    if home!=Path('/home/pajio-phone') or u.pw_shell!='/usr/sbin/nologin':raise ValueError('phone_account_changed')
    owner=json.loads(Path('/etc/pajio-native/device-owner.json').read_text());serial='127.0.0.1:'+str(20000+vmid);rid=mobile.resource_id(serial)
    if owner['resource_id']!=rid or owner['kind']!='android':raise ValueError('phone_owner_changed')
    if (home/'.pajio-connector/connector.json').exists():raise ValueError('paired_device_cannot_reinstall')
    for name,expected in [('scrcpy-server-v5.0.1',SCRCPY_SHA256),('pajio-private-input.apk',PRIVATE_IME_SHA256),('scrcpy-5.0.1-LICENSE','01c12035bf35af37241298dc7ad538eb2a07e5c940437bc6876feeaa9d1951d0')]:
        if hashlib.sha256((bundle/name).read_bytes()).hexdigest()!=expected:raise ValueError('pinned_android_artifact_changed')
    notice=target/'notices';notice.mkdir(mode=0o755,exist_ok=True)
    shutil.copyfile(bundle/'scrcpy-5.0.1-LICENSE',notice/'scrcpy-5.0.1-LICENSE')
    shutil.copyfile(bundle/'scrcpy-notices.json',notice/'manifest.json')
    shutil.copyfile(bundle/'scrcpy-server-v5.0.1',target/'scrcpy-server-v5.0.1');(target/'scrcpy-server-v5.0.1').chmod(0o644)
    node=target/'node-v26.7.0-linux-x64'
    if not node.exists():
        temporary=Path(tempfile.mkdtemp(prefix='.node-',dir=target))
        try:
            with tarfile.open(bundle/'node-v26.7.0-linux-x64.tar.xz','r:xz') as archive:
                if any((not v.name.startswith('node-v26.7.0-linux-x64/') and not (v.name=='node-v26.7.0-linux-x64' and v.isdir())) or v.isdev() for v in archive.getmembers()):raise ValueError('invalid_node_archive')
                archive.extractall(temporary,filter='data')
            os.rename(temporary/node.name,node)
        finally:shutil.rmtree(temporary)
    if node.is_symlink() or node.stat().st_uid!=0 or node.stat().st_mode&0o022:raise ValueError('unsafe_node_install')
    version=subprocess.check_output([str(node/'bin/node'),'--version'],text=True,timeout=5).strip()
    if version!='v26.7.0':raise ValueError('node_version_changed')
    runtime=home/'.pajio/runtime'
    for p in (home/'.pajio',runtime,runtime/'mobile'):
        if p.is_symlink():raise ValueError('unsafe_phone_runtime')
        p.mkdir(mode=0o700,exist_ok=True);os.chown(p,u.pw_uid,u.pw_gid)
    for name in ('package.json','package-lock.json'):
        dest=runtime/'mobile'/name;shutil.copyfile(mobile.PACKAGE/name,dest);os.chown(dest,u.pw_uid,u.pw_gid);dest.chmod(0o600)
    user=['runuser','-u','pajio-phone','--','env','HOME='+str(home),'PATH='+str(node/'bin')+':/usr/bin:/bin']
    run(user+[str(node/'bin/npm'),'ci','--ignore-scripts','--no-audit','--no-fund'],cwd=runtime/'mobile')
    u2=runtime/'android-u2'
    run(user+['/usr/bin/python3','-m','venv',str(u2)])
    # Files in the verified bundle remain root-private. Copy only reviewed
    # wheels/lock to a private service-user cache for unprivileged pip install.
    cache=runtime/'wheel-cache';cache.mkdir(mode=0o700,exist_ok=True);os.chown(cache,u.pw_uid,u.pw_gid)
    for path in bundle.glob('*.whl'):
        out=cache/path.name;shutil.copyfile(path,out);out.chmod(0o600);os.chown(out,u.pw_uid,u.pw_gid)
    requirement=cache/'requirements.txt';shutil.copyfile(mobile.U2_PACKAGE/'requirements.txt',requirement);os.chown(requirement,u.pw_uid,u.pw_gid);requirement.chmod(0o600)
    run(user+[str(u2/'bin/python'),'-m','pip','install','--disable-pip-version-check','--no-index','--find-links',str(cache),'--require-hashes','-r',str(requirement)])
    # The pinned uiautomator2 wheel supplies its device server. Bootstrap only
    # this fresh, owner-validated phone; no application data is read or reset.
    run(user+[str(u2/'bin/python'),'-c','import sys,uiautomator2 as u; assert u.connect(sys.argv[1]).info',serial])
    for path,value in [(runtime/'mobile/installed.json',{'version':mobile.VERSION,'node':str(node/'bin/node')}),
                       (u2/'installed.json',{'version':mobile.U2_VERSION,'requirements_sha256':hashlib.sha256((mobile.U2_PACKAGE/'requirements.txt').read_bytes()).hexdigest()}),
                       (home/'.pajio/phone.json',{'schema_version':2,'selected':rid,'devices':{rid:{'resource_id':rid,'serial':serial,'enabled':True,'platform':'android','name':'专属 Android 手机'}}})]:
        write_private_json(path,value);os.chown(path,u.pw_uid,u.pw_gid)
    return {'native_drivers_installed':True,'resource_id':rid,'product_ready':False}

if __name__=='__main__':
    try:print(json.dumps(install(Path(sys.argv[1]),int(sys.argv[2]))))
    except Exception:raise SystemExit('android_native_install_incomplete')
