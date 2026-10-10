import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def installer():
    definition=importlib.util.spec_from_file_location('runtime_installer',ROOT/'deploy/on-prem/install-device-runtime.py')
    module=importlib.util.module_from_spec(definition);definition.loader.exec_module(module);return module

@pytest.fixture
def bundle(tmp_path,installer):
    files=installer.LINUX|installer.COMMON|{'wearing-0.2.0-py3-none-any.whl','dependency-1.0-py3-none-any.whl'}
    manifest={'version':1,'kind':'linux','files':{}}
    for name in files:
        body=(name+'\n').encode();(tmp_path/name).write_bytes(body)
        manifest['files'][name]={'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    return tmp_path,manifest,installer.digest(manifest)

def test_every_dependency_byte_and_manifest_hash_checked(installer,bundle):
    path,manifest,sha=bundle
    assert installer.verify_bundle(path,sha)[1]=='wearing-0.2.0-py3-none-any.whl'
    (path/'dependency-1.0-py3-none-any.whl').write_text('tamper')
    with pytest.raises(ValueError,match='runtime_file_changed'):installer.verify_bundle(path,sha)

@pytest.mark.parametrize('bad',['../credential','model.key','connector.json','extra.sh'])
def test_unexpected_files_never_enter_bundle(installer,bundle,bad):
    path,manifest,_=bundle;manifest['files'][bad]={'bytes':1,'sha256':'a'*64}
    (path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='runtime_file_not_allowed'):installer.verify_bundle(path,installer.digest(manifest))

def test_missing_file_extra_file_symlink_and_manifest_change_fail(installer,bundle):
    path,manifest,sha=bundle
    with pytest.raises(ValueError,match='runtime_manifest_changed'):installer.verify_bundle(path,'0'*64)
    extra=path/'secret.json';extra.write_text('{}')
    with pytest.raises(ValueError,match='unexpected_runtime_file'):installer.verify_bundle(path,sha)
    extra.unlink();victim=path/'hermes-source.tar.gz';body=victim.read_bytes();victim.unlink()
    target=path.parent/'external';target.write_bytes(body);victim.symlink_to(target)
    with pytest.raises(ValueError,match='runtime_file_changed'):installer.verify_bundle(path,sha)

def test_android_port_input_rejected_before_any_host_or_vm_action(tmp_path):
    script=ROOT/'deploy/on-prem/setup-android-phone.sh'
    for value in ('x','5555;bad','1023','65536','-1'):
        result=subprocess.run(['bash',str(script),'unused'],env={'PATH':'/usr/bin:/bin','PAJIO_ANDROID_ADB_PORT':value},capture_output=True,text=True)
        assert result.returncode==2 and result.stderr.strip()=='Invalid loopback ADB port'
    source=script.read_text()
    assert '${PAJIO_ANDROID_ADB_PORT:-5555}' in source and 'Existing Android port binding changed' in source
    assert 'EnvironmentFile=/etc/pajio-phone-transport.env' in source
    assert '-p "$adb_serial:5555"' in source


def test_upload_preparation_refuses_world_writable_or_symlink(tmp_path):
    import ast
    source=(ROOT/'src/wearing/cloud/device_delivery_ssh.py').read_text()
    tree=ast.parse(source)
    prepare=next(node.value.value for node in ast.walk(tree) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prepare' for t in node.targets))
    target=tmp_path/'upload';target.mkdir();target.chmod(0o777)
    assert subprocess.run([__import__('sys').executable,'-c',prepare,str(target)],capture_output=True).returncode!=0
    target.chmod(0o700)
    assert subprocess.run([__import__('sys').executable,'-c',prepare,str(target)],capture_output=True).returncode==0
    link=tmp_path/'link';link.symlink_to(target)
    assert subprocess.run([__import__('sys').executable,'-c',prepare,str(link)],capture_output=True).returncode!=0


def test_partial_bundle_copy_is_removed_and_retry_reaches_venv(installer,bundle,tmp_path,monkeypatch):
    import os,sys
    source,manifest,artifact=bundle
    nested=tmp_path/'input';nested.mkdir()
    for item in list(source.iterdir()):
        if item!=nested:item.rename(nested/item.name)
    source=nested;fs=tmp_path/'guest';(fs/'etc').mkdir(parents=True);(fs/'opt').mkdir()
    (fs/'etc/machine-id').write_text('1'*32)
    real_path=Path
    def path(value):
        text=str(value)
        return fs/text.lstrip('/') if text.startswith(('/etc/','/opt/','/var/lib/','/run/','/home/')) else real_path(value)
    owner={'kind':'linux'};proof={'version':1,'owner_sha256':installer.digest(owner),'artifact_sha256':artifact}
    monkeypatch.setattr(installer,'Path',path)
    monkeypatch.setattr(installer,'private',lambda value:owner if str(value).endswith('device-owner.json') else proof)
    monkeypatch.setattr(installer.os,'geteuid',lambda:0)
    monkeypatch.setattr(installer.socket,'gethostname',lambda:'pajio-1200')
    monkeypatch.setattr(installer.fcntl,'flock',lambda *_:None)
    rawstat=Path.stat
    def stat(self,*args,**kwargs):
        values=list(rawstat(self,*args,**kwargs));values[4]=0;values[5]=0;return os.stat_result(values)
    monkeypatch.setattr(Path,'stat',stat)
    rawopen=os.open
    def opening(value,flags,*args,**kwargs):return rawopen(tmp_path/'install.lock' if str(value)=='/run/lock/pajio-runtime-install.lock' else value,flags,*args,**kwargs)
    monkeypatch.setattr(installer.os,'open',opening)
    def journal(value,data):
        target=path(value);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(data))
    monkeypatch.setattr(installer,'write',journal)
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        if '-m' in args and 'venv' in args:raise RuntimeError('reached_venv')
    monkeypatch.setattr(installer,'run',run)
    original=installer.shutil.copyfileobj
    def interrupted(inp,out):out.write(inp.read(1));raise OSError('synthetic_copy_interrupt')
    monkeypatch.setattr(installer.shutil,'copyfileobj',interrupted)
    machine=hashlib.sha256(('1'*32).encode()).hexdigest()
    with pytest.raises(OSError,match='synthetic_copy_interrupt'):installer.install(source,artifact,1200,machine)
    stage=fs/'opt/pajio-native'/('bundle-'+artifact)
    assert not stage.exists()
    monkeypatch.setattr(installer.shutil,'copyfileobj',original)
    with pytest.raises(RuntimeError,match='reached_venv'):installer.install(source,artifact,1200,machine)
    assert stage.exists();installer.verify_bundle(stage,artifact)
    # A half-created venv containing Python is repaired by repeating venv.
    partial=fs/'opt/pajio-native/venv/bin';partial.mkdir(parents=True);(partial/'python').touch()
    with pytest.raises(RuntimeError,match='reached_venv'):installer.install(source,artifact,1200,machine)
    assert sum('venv' in c for c in calls)==2


def test_retry_reuses_only_exact_regular_uploaded_files(tmp_path):
    import sys
    from wearing.cloud.device_delivery_ssh import UPLOAD_CHECK
    directory=tmp_path/'bundle';directory.mkdir();file=directory/'asset.whl';file.write_bytes(b'public pinned data')
    expected={file.name:hashlib.sha256(file.read_bytes()).hexdigest()}
    def check():return subprocess.run([sys.executable,'-c',UPLOAD_CHECK,str(directory)],input=json.dumps(expected),text=True,capture_output=True).returncode
    assert check()==0
    file.write_bytes(b'tampered');assert check()!=0
    file.write_bytes(b'public pinned data');extra=directory/'extra';extra.touch();assert check()!=0
    extra.unlink();file.rename(tmp_path/'original');file.symlink_to(tmp_path/'original');assert check()!=0


def test_runtime_uses_verified_namespace_and_digest(installer):
    assert installer.REDROID=='docker.m.daocloud.io/redroid/redroid@sha256:11d58a64bfbde2253d1cce81bff409ff58174980222d1bada232d9ef59181191'


def test_mobile_node_archive_accepts_official_top_directory_only():
    import ast,tarfile
    tree=ast.parse((ROOT/'deploy/on-prem/setup-device-mobile.py').read_text())
    guard=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and isinstance(n.body[0],ast.Raise) and any(isinstance(child,ast.Constant) and child.value=='invalid_node_archive' for child in ast.walk(n)))
    root=tarfile.TarInfo('node-v26.7.0-linux-x64');root.type=tarfile.DIRTYPE
    leaf=tarfile.TarInfo('node-v26.7.0-linux-x64/bin/node')
    class Archive:
        def __init__(self,entries):self.entries=entries
        def getmembers(self):return self.entries
    compiled=compile(ast.Module(body=[guard],type_ignores=[]),'<actual-node-guard>','exec')
    exec(compiled,{'archive':Archive([root,leaf])})
    for bad in [tarfile.TarInfo('node-v26.7.0-linux-x64'),tarfile.TarInfo('another/node')]:
        with pytest.raises(ValueError,match='invalid_node_archive'):exec(compiled,{'archive':Archive([bad])})


def test_large_image_hashing_is_bounded_on_sender_and_receiver(tmp_path):
    """Actual 833MiB sparse file; a read_bytes implementation exceeds this bound."""
    import os,sys
    path=tmp_path/'redroid-amd64.tar'
    size=873349120
    with path.open('wb') as stream:stream.truncate(size)
    env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
    script='''import json,resource,sys,tracemalloc
from pathlib import Path
from wearing.cloud.device_delivery_ssh import upload_digests
tracemalloc.start()
values=upload_digests(Path(sys.argv[1]))
peak=tracemalloc.get_traced_memory()[1]
rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({'digests':values,'peak':peak,'rss':rss}))
'''
    value=json.loads(subprocess.run([sys.executable,'-c',script,str(tmp_path)],env=env,check=True,capture_output=True,text=True,timeout=30).stdout)
    assert value['peak']<2*1024*1024
    assert value['rss']/(1024 if sys.platform=='darwin' else 1)<192*1024
    from wearing.cloud.device_delivery_ssh import UPLOAD_CHECK
    checked='import tracemalloc,resource;tracemalloc.start()\n'+UPLOAD_CHECK+'''\nprint(json.dumps({'peak':tracemalloc.get_traced_memory()[1],'rss':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))\n'''
    result=subprocess.run([sys.executable,'-c',checked,str(tmp_path)],input=json.dumps(value['digests']),env=env,check=True,capture_output=True,text=True,timeout=30)
    measured=json.loads(result.stdout)
    assert measured['peak']<2*1024*1024
    assert measured['rss']/(1024 if sys.platform=='darwin' else 1)<192*1024
    # A changed byte still rejects reuse; bounded allocation does not weaken SHA.
    with path.open('r+b') as out:out.write(b'x')
    assert subprocess.run([sys.executable,'-c',UPLOAD_CHECK,str(tmp_path)],input=json.dumps(value['digests']),env=env,capture_output=True,text=True,timeout=30).returncode==1
