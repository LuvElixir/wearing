"""Android-only field, cleanup and existing-container boundary regressions."""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from wearing.android_text import describe_hierarchy, focused_field, replace_text
from wearing.private_media_android import AndroidScrcpySource, PRIVATE_IME_SHA256
from wearing.private_media_sources import CapturedFrame, SourceError


def tree(*, text='before', password='false', resource='app:id/input', package='app', focused='true'):
    return ('<hierarchy><node class="android.widget.EditText" resource-id="' + resource + '" package="' + package +
            '" focused="' + focused + '" enabled="true" text="' + text + '" bounds="[0,0][100,40]"' +
            ('' if password is None else ' password="' + password + '"') + '/></hierarchy>')


@pytest.mark.parametrize('flag', [None, '', 'TRUE', 'unknown', 'true'])
def test_unproven_password_flag_rejected_and_masked(flag):
    xml = tree(text='synthetic-private', password=flag)
    with pytest.raises(ValueError):
        focused_field(xml, 'synthetic-private')
    view = describe_hierarchy(xml)
    assert view['elements'][0]['password'] is True
    assert 'synthetic-private' not in json.dumps(view)


def install_device(monkeypatch, after, *, cleanup_failure=False):
    calls = []
    trees = iter([tree(), after])
    values = iter(['before', 'synthetic-private'])
    field = SimpleNamespace(selector={}, get_text=lambda **_: next(values))
    class Device:
        _dev = object()
        def dump_hierarchy(self): return next(trees)
        def __call__(self, **_): return field
        def stop_uiautomator(self):
            calls.append('cleanup')
            if cleanup_failure: raise OSError('synthetic-private-must-not-escape')
    def write(*args): calls.append('write'); return True
    monkeypatch.setitem(sys.modules, 'uiautomator2', SimpleNamespace(connect=lambda *a, **k: Device()))
    monkeypatch.setitem(sys.modules, 'uiautomator2.core', SimpleNamespace(_jsonrpc_call=write))
    return calls


@pytest.mark.parametrize('changed', [dict(password='true'), dict(password=None),
                                    dict(resource='other:id/input'), dict(package='other'), dict(focused='false')])
def test_exact_text_after_write_not_success_if_identity_or_privacy_changed(monkeypatch, changed):
    calls = install_device(monkeypatch, tree(text='synthetic-private', **changed))
    result = replace_text({'serial':'synthetic', 'expected_text':'before', 'text':'synthetic-private'})
    assert not result['ok'] and result['unknown'] and not result['input_readback_verified']
    assert 'synthetic-private' not in json.dumps(result)
    assert calls == ['write', 'cleanup']  # never retry the write


def test_cleanup_failure_is_structured_unknown_without_text_or_replay(monkeypatch):
    calls = install_device(monkeypatch, tree(text='synthetic-private'), cleanup_failure=True)
    result = replace_text({'serial':'synthetic', 'expected_text':'before', 'text':'synthetic-private'})
    assert not result['ok'] and result['unknown'] and result['cleanup_confirmed'] is False
    assert 'synthetic-private' not in json.dumps(result)
    assert calls == ['write', 'cleanup']


@pytest.mark.parametrize('failure', ['socket', 'terminate', 'wait', 'kill', 'thread'])
def test_media_cleanup_does_not_skip_ime_or_cache_on_earlier_failure(tmp_path, monkeypatch, failure):
    source = AndroidScrcpySource(serial='synthetic', server=tmp_path/'unused', unicode_ime=True)
    source.previous_ime='org.keyboard/.IME'; source.ime_apk='/data/app/test/base.apk'; source.ime_uid=10001
    source.latest = source.static_refresh = CapturedFrame(Image.new('RGB', (2, 2)), 1)
    source.port = 2222; source.remote_installed = True
    state = {'failed': True}
    calls = []
    class Socket:
        def shutdown(self, *_): pass
        def close(self):
            if failure == 'socket' and state['failed']: raise OSError('sensitive-detail')
    class Process:
        def poll(self): return None
        def terminate(self):
            if failure == 'terminate' and state['failed']: raise OSError('sensitive-detail')
        def wait(self, **_):
            if failure in ('wait', 'kill') and state['failed']: raise subprocess.TimeoutExpired('sensitive-detail', 3)
        def kill(self):
            if failure == 'kill' and state['failed']: raise OSError('sensitive-detail')
    class Thread:
        def join(self, **_):
            if failure == 'thread' and state['failed']: raise RuntimeError('sensitive-detail')
        def is_alive(self): return False
    source.sock=Socket(); source.process=Process(); source.thread=Thread()
    def adb(*args, **_):
        calls.append(args)
        if args == ('shell', 'sha256sum', '/data/app/test/base.apk'):
            return (PRIVATE_IME_SHA256+'  /data/app/test/base.apk\n').encode()
        if args == ('shell', 'settings', 'get', 'secure', 'default_input_method'): return b'org.keyboard/.IME\n'
        if args == ('shell', 'ps', '-A', '-o', 'NAME'): return b'NAME\ninit\n'
        return b''
    monkeypatch.setattr(source, '_adb', adb)
    monkeypatch.setattr(source, '_ime_request', lambda *_: None)
    with pytest.raises(SourceError, match='^private_android_cleanup_failed$'):
        source.release_all()
    assert source.closed and source.cleanup_errors
    assert source.latest is None and source.static_refresh is None and source.ime_nonce == bytearray(32)
    assert source.previous_ime is None  # later cleanup still ran
    assert ('shell', 'am', 'force-stop', 'io.pajio.privateinput') in calls
    assert source.port is None and not source.remote_installed
    state['failed'] = False
    source.release_all()  # explicit retry only clears pending resources
    assert not source.cleanup_errors and source.process is None and source.thread is None and source.sock is None


@pytest.fixture
def container_contract():
    # Execute the exact read-only validator used by the shell installer, rather
    # than asserting the presence of keywords in a script.
    text = (Path(__file__).resolve().parents[1]/'deploy/on-prem/setup-android-phone.sh').read_text()
    code = re.search(r"validate_existing_container\(\) \{\n  python3 -c '(.*?)' \"\$image\" \"\$adb_port\"", text, re.S).group(1)
    image='mirror/redroid@sha256:'+'1'*64
    item={'Id':'a'*64, 'Name':'/pajio-phone', 'Config':{'Labels':{'io.pajio.role':'tenant-android'}, 'Image':image,
          'Cmd':['androidboot.use_memfd=1','androidboot.redroid_width=720','androidboot.redroid_height=1280',
                 'androidboot.redroid_dpi=320','androidboot.redroid_fps=24','androidboot.redroid_gpu_mode=guest',
                 'androidboot.redroid_net_ndns=2','androidboot.redroid_net_dns1=223.5.5.5','androidboot.redroid_net_dns2=1.1.1.1']},
          'HostConfig':{'PortBindings':{'5555/tcp':[{'HostIp':'127.0.0.1','HostPort':'21212'}]},
                        'PublishAllPorts':False,'NetworkMode':'default','PidMode':'','IpcMode':'private','UTSMode':'',
                        'Privileged':True,'NanoCpus':2000000000,'Memory':3221225472,'MemorySwap':3221225472,
                        'RestartPolicy':{'Name':'unless-stopped','MaximumRetryCount':0}},
          'NetworkSettings':{'Networks':{'bridge':{}}},
          'Mounts':[{'Type':'bind','Source':'/var/lib/pajio-phone/data','Destination':'/data','RW':True,'Propagation':'rprivate'}]}
    def run(value):
        return subprocess.run([sys.executable,'-c',code,image,'21212'], input=json.dumps(value), capture_output=True, text=True)
    return item, run


def test_existing_container_same_identity_mount_network_and_limits_accepted(container_contract):
    item, run = container_contract
    for mode in ('default','bridge'):
        item['HostConfig']['NetworkMode']=mode
        result=run([item]); assert result.returncode == 0 and not result.stdout and not result.stderr


@pytest.mark.parametrize('changed', ['mount_source','mount_extra','mount_readonly','network_host','network_extra',
                                     'pid','ipc','port','port_extra','identity','image','label','memory','command','missing'])
def test_existing_container_drift_refuses_reuse_without_dumping_inspect(container_contract, changed):
    initial, run = container_contract; item=copy.deepcopy(initial)
    if changed=='mount_source': item['Mounts'][0]['Source']='/private/other-user'
    elif changed=='mount_extra': item['Mounts'].append({'Source':'/private/secret'})
    elif changed=='mount_readonly': item['Mounts'][0]['RW']=False
    elif changed=='network_host': item['HostConfig']['NetworkMode']='host'
    elif changed=='network_extra': item['NetworkSettings']['Networks']['other']={}
    elif changed=='pid': item['HostConfig']['PidMode']='host'
    elif changed=='ipc': item['HostConfig']['IpcMode']='host'
    elif changed=='port': item['HostConfig']['PortBindings']['5555/tcp'][0]['HostIp']='0.0.0.0'
    elif changed=='port_extra': item['HostConfig']['PortBindings']['1234/tcp']=[]
    elif changed=='identity': item['Name']='/other'
    elif changed=='image': item['Config']['Image']='other'
    elif changed=='label': item['Config']['Labels']['io.pajio.role']='other'
    elif changed=='memory': item['HostConfig']['Memory']=0
    elif changed=='command': item['Config']['Cmd'].append('androidboot.additional=true')
    elif changed=='missing': del item['HostConfig']['NetworkMode']
    result=run([item])
    assert result.returncode == 2 and not result.stdout
    assert result.stderr.strip()=='Existing Android container binding changed; refusing reuse'


def test_driver_value_error_cannot_echo_input_or_retry(monkeypatch):
    calls=[]
    field=SimpleNamespace(selector={}, get_text=lambda **_: 'before')
    class Device:
        _dev=object()
        def dump_hierarchy(self): return tree()
        def __call__(self, **_): return field
        def stop_uiautomator(self): calls.append('cleanup')
    def write(*_):
        calls.append('write')
        raise ValueError('synthetic-private-must-not-escape')
    monkeypatch.setitem(sys.modules, 'uiautomator2', SimpleNamespace(connect=lambda *a, **k: Device()))
    monkeypatch.setitem(sys.modules, 'uiautomator2.core', SimpleNamespace(_jsonrpc_call=write))
    result=replace_text({'serial':'synthetic', 'expected_text':'before', 'text':'synthetic-private'})
    assert not result['ok'] and result['unknown']
    assert 'synthetic-private' not in json.dumps(result) and calls == ['write', 'cleanup']


def test_observation_cleanup_failure_does_not_report_success_or_exception_content(monkeypatch):
    from wearing.android_text import observe
    def stop(): raise OSError('synthetic-private-must-not-escape')
    device=SimpleNamespace(_dev=object(), stop_uiautomator=stop)
    monkeypatch.setitem(sys.modules, 'uiautomator2', SimpleNamespace(connect=lambda *a, **k: device))
    monkeypatch.setitem(sys.modules, 'uiautomator2.core', SimpleNamespace(_jsonrpc_call=lambda *_: tree()))
    result=observe({'serial':'synthetic'})
    assert not result['ok'] and result['cleanup_confirmed'] is False
    assert 'synthetic-private' not in json.dumps(result)


def test_private_text_revalidates_human_lease_after_apk_io(tmp_path, monkeypatch):
    source=AndroidScrcpySource(serial='synthetic', server=tmp_path/'unused', unicode_ime=True)
    source.previous_ime='org.keyboard/.IME'; source.ime_apk='/data/app/test/base.apk'; source.ime_uid=10001
    allowed=[True]; calls=[]
    def guard():
        if not allowed[0]: raise SourceError('lease_expired')
    source.set_guard(guard)
    def adb(*args, **kwargs):
        calls.append(args)
        assert not kwargs.get('stdin')
        allowed[0]=False
        return (PRIVATE_IME_SHA256+'  /data/app/test/base.apk\n').encode()
    monkeypatch.setattr(source, '_adb', adb)
    with pytest.raises(SourceError, match='lease_expired'):
        source.apply({'action':'text', 'text':'synthetic-private'})
    assert len(calls)==1 and 'app_process' not in calls[0]


@pytest.mark.asyncio
async def test_partial_android_cleanup_never_acks_gateway_return(tmp_path):
    from wearing.device_gateway import DeviceGateway, GatewayScope
    from wearing.private_media import PrivateSession
    scope=GatewayScope('tenant_test','daily','actor_test','connector_test','phone_test')
    gate=DeviceGateway(tmp_path/'gateway', private_access_ready=True)
    claim=gate.begin_human(scope,'session_test',expected_epoch=0)
    gate.activate_human(scope,'session_test',claim['epoch'])
    source=AndroidScrcpySource(serial='synthetic', server=tmp_path/'unused')
    state={'failed':True}
    class Process:
        def poll(self): return None
        def terminate(self):
            if state['failed']: raise OSError('synthetic-detail')
        def wait(self, **_): pass
    class Peer:
        async def close(self): pass
    source.process=Process()
    session=PrivateSession(gate,scope,'session_test',3,claim['epoch'],source,Peer())
    assert not await session.close()
    assert session.closed and not session.cleared and session.cleanup_code=='native_cleanup_failed'
    assert gate.snapshot(scope.resource_id)['state']=='paused'
    assert source.ime_nonce == bytearray(32)
    state['failed']=False
    assert await session.close()
    assert session.cleared and gate.snapshot(scope.resource_id)['state']=='paused'
