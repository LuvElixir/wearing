"""Synthetic host/relay integration. No device, service, media or account I/O."""
from dataclasses import replace
from types import SimpleNamespace
import os
from pathlib import Path
import subprocess
import sys

import pytest

from wearing.device_gateway import DeviceGateway, GatewayScope, GatewayError
from wearing.cloud.relay import RelayStore, RelayError, PairRequest, PollRequest, ConnectionRequest, ClaimRequest, ResourceControl
from wearing.config import write_private_json
from wearing.connectors.remote.adapter import NativeAdapter
from wearing.connectors.remote.client import Connector
from wearing.phone_proxy import DeviceLock, lock_path, guarded_phone_action

READ = 'phone.mobile_take_screenshot'
WRITE = 'phone.mobile_click_on_screen_at_coordinates'
TOKEN = 'a' * 64
ACTOR = 'b' * 64
RESOURCE = 'phone_synthetic'
SPEC = {'resource_id':RESOURCE, 'name':'Synthetic device', 'kind':'android', 'methods':[READ,WRITE]}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr('pathlib.Path.home', lambda: tmp_path / 'home')


@pytest.fixture
def host(tmp_path):
    clock = [1000.0]
    gate = DeviceGateway(tmp_path/'gateway', private_access_ready=True, clock=lambda:clock[0])
    scope = GatewayScope('tenant_test','daily',ACTOR,'connector_test',RESOURCE)
    return gate, scope, clock


def private(host):
    gate, scope, _ = host
    value = gate.begin_human(scope,'human_test',expected_epoch=gate.snapshot(RESOURCE)['epoch'])
    return gate.activate_human(scope,'human_test',value['epoch'])


def test_default_cannot_open_private_session(tmp_path):
    gate = DeviceGateway(tmp_path/'disabled')
    scope = GatewayScope('tenant_test','daily',ACTOR,'connector_test',RESOURCE)
    with pytest.raises(GatewayError,match='unavailable'):
        gate.begin_human(scope,'session_test',expected_epoch=0)
    assert gate.snapshot(RESOURCE)['state']=='agent_ready'


def test_takeover_waits_for_real_phone_lock_and_fences_old_result(host):
    gate, scope, _ = host
    permit=gate.permit_agent(RESOURCE)
    lock=DeviceLock(lock_path(RESOURCE));lock.acquire()
    try:
        value=gate.begin_human(scope,'human_test',expected_epoch=0)
        with pytest.raises(GatewayError,match='inflight'):
            gate.activate_human(scope,'human_test',value['epoch'])
        with pytest.raises(GatewayError):gate.validate_agent(permit)
    finally:lock.release()
    assert gate.activate_human(scope,'human_test',value['epoch'])['state']=='human_private'


def test_native_lock_cross_process_phone_compatibility_and_exception_cleanup(host, tmp_path):
    gate, scope, _ = host
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    child = '''
import sys
from pathlib import Path
Path.home = lambda: Path(sys.argv[1])
from wearing.phone_proxy import DeviceLock, DeviceBusy, lock_path
if sys.argv[3] == 'hold-filelock':
    from filelock import FileLock
    with FileLock(lock_path(sys.argv[2]), timeout=0):
        print('held', flush=True)
        sys.stdin.readline()
else:
    lock = DeviceLock(lock_path(sys.argv[2]))
    try:
        lock.acquire()
    except DeviceBusy:
        print('busy')
    else:
        print('acquired')
        lock.release()
'''
    argv = [sys.executable, '-c', child, str(tmp_path / 'home'), RESOURCE]
    lock_path(RESOURCE).parent.mkdir(parents=True, exist_ok=True)
    held = subprocess.Popen(argv + ['hold-filelock'], env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert held.stdout.readline().strip() == 'held'
        pending = gate.begin_human(scope, 'cross_process', expected_epoch=0)
        with pytest.raises(GatewayError, match='inflight'):
            gate.activate_human(scope, 'cross_process', pending['epoch'])
    finally:
        held.communicate('\n', timeout=10)
    assert held.returncode == 0
    assert gate.activate_human(scope, 'cross_process', pending['epoch'])['state'] == 'human_private'
    with pytest.raises(RuntimeError, match='synthetic operation failed'):
        with gate.native_lock(RESOURCE):
            probe = subprocess.run(argv + ['probe'], env=env, capture_output=True, text=True, timeout=10)
            assert probe.returncode == 0 and probe.stdout.strip() == 'busy', probe.stderr
            raise RuntimeError('synthetic operation failed')
    probe = subprocess.run(argv + ['probe'], env=env, capture_output=True, text=True, timeout=10)
    assert probe.returncode == 0 and probe.stdout.strip() == 'acquired', probe.stderr


def test_gateway_startup_requires_only_standard_library(tmp_path):
    # -S omits site-packages, reproducing the boundary that exposed the managed
    # interpreter's missing filelock without changing any installed environment.
    code = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
Path.home = lambda: Path(sys.argv[2])
from device_gateway import DeviceGateway
gate = DeviceGateway(Path(sys.argv[2]) / 'gateway')
with gate.native_lock('synthetic_startup'):
    assert gate.snapshot('synthetic_startup')['state'] == 'agent_ready'
print('stdlib gateway startup and lock passed')
'''
    result = subprocess.run([sys.executable, '-S', '-c', code,
                             str(Path(__file__).resolve().parents[1] / 'src/wearing'), str(tmp_path)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'stdlib gateway startup and lock passed'


@pytest.mark.parametrize('field', ['tenant_id','identity_id','user_id','connector_id','resource_id'])
def test_human_scope_is_exact(host,field):
    gate,scope,_=host;value=private(host)
    with pytest.raises(GatewayError):
        gate.validate_human(replace(scope,**{field:'another'}),'human_test',value['epoch'])


def test_expiry_and_restart_never_return_agent_ownership(host):
    gate,scope,clock=host;value=private(host)
    clock[0]+=31
    assert gate.snapshot(RESOURCE)['state']=='paused'
    with pytest.raises(GatewayError):gate.renew_human(scope,'human_test',value['epoch'])
    with pytest.raises(GatewayError):gate.permit_agent(RESOURCE)
    value=gate.begin_human(scope,'human_next',expected_epoch=gate.snapshot(RESOURCE)['epoch'])
    gate.activate_human(scope,'human_next',value['epoch'])
    gate.recover([RESOURCE])
    assert gate.snapshot(RESOURCE)['state']=='paused'


def test_return_requires_human_confirmations_and_trusted_media_clear(host):
    gate,scope,_=host;value=private(host);epoch=value['epoch']
    for kwargs in ({},{'safe_screen_confirmed':True,'scope_confirmed':True},{'safe_screen_confirmed':True,'scope_confirmed':True,'clear_media':True}):
        with pytest.raises(GatewayError):gate.finish_human(scope,'human_test',epoch,**kwargs)
    assert gate.snapshot(RESOURCE)['state']=='human_private'
    def clear():
        with pytest.raises(GatewayError):gate.permit_agent(RESOURCE)
        return True
    done=gate.finish_human(scope,'human_test',epoch,safe_screen_confirmed=True,scope_confirmed=True,clear_media=clear)
    assert done['state']=='agent_ready' and done['epoch']>epoch
    assert gate.finish_human(scope,'human_test',done['epoch'])==done


def test_failed_media_clear_pauses_instead_of_releasing(host):
    gate,scope,_=host;value=private(host)
    with pytest.raises(GatewayError,match='not_cleared'):
        gate.finish_human(scope,'human_test',value['epoch'],safe_screen_confirmed=True,scope_confirmed=True,clear_media=lambda:False)
    assert gate.snapshot(RESOURCE)['state']=='paused'


def test_two_human_claims_have_one_owner(host):
    from concurrent.futures import ThreadPoolExecutor
    gate,scope,_=host
    def begin(index):
        try:return gate.begin_human(scope,'session_'+str(index),expected_epoch=0)['state']
        except GatewayError:return 'rejected'
    with ThreadPoolExecutor(2) as workers:
        assert sorted(workers.map(begin,range(2)))==['handoff_pending','rejected']


@pytest.mark.asyncio
async def test_actual_local_dispatch_guard_blocks_calls_and_discards_late_contents(host):
    gate,scope,_=host
    calls=[]
    async def source():calls.append(True);return 'SYNTHETIC_SECRET_FRAME'
    assert await guarded_phone_action(RESOURCE,source,gate)=='SYNTHETIC_SECRET_FRAME'
    private(host)
    with pytest.raises(GatewayError):await guarded_phone_action(RESOURCE,source,gate)
    assert len(calls)==1


@pytest.mark.asyncio
async def test_local_dispatch_does_not_return_observation_crossing_handoff(host):
    gate,scope,_=host
    async def source():
        gate.begin_human(scope,'human_test',expected_epoch=0)
        return 'SYNTHETIC_SECRET_FRAME'
    with pytest.raises(GatewayError):await guarded_phone_action(RESOURCE,source,gate)
    assert b'SYNTHETIC_SECRET_FRAME' not in gate.path.read_bytes()


@pytest.mark.asyncio
async def test_native_remote_adapter_uses_same_gate_before_mcp(host,tmp_path,monkeypatch):
    gate,scope,_=host
    adapter=NativeAdapter(tmp_path/'adapter',private_gateway=gate)
    calls=[]
    async def phone():calls.append('mcp');raise AssertionError('must not reach transport')
    monkeypatch.setattr(adapter,'phone_session',phone)
    private(host)
    for method in (READ,WRITE):
        with pytest.raises(GatewayError):await adapter.execute(SimpleNamespace(resource_id=RESOURCE,method=method,params={}))
    assert calls==[]


@pytest.mark.asyncio
async def test_native_remote_late_observation_is_discarded(host,tmp_path,monkeypatch):
    gate,scope,_=host
    adapter=NativeAdapter(tmp_path/'adapter',private_gateway=gate)
    async def invoke(name,arguments):
        gate.begin_human(scope,'human_test',expected_epoch=0)
        return SimpleNamespace(model_dump=lambda **kwargs:{'secret':'SYNTHETIC_SCREEN'})
    async def phone():return SimpleNamespace(call_tool=invoke)
    monkeypatch.setattr(adapter,'phone_session',phone)
    with pytest.raises(GatewayError):await adapter.execute(SimpleNamespace(resource_id=RESOURCE,method=READ,params={}))
    assert b'SYNTHETIC_SCREEN' not in gate.path.read_bytes()


@pytest.mark.asyncio
async def test_repeated_native_takeover_still_validates_exact_actor(host,tmp_path):
    gate,scope,_=host;private(host)
    adapter=NativeAdapter(tmp_path/'adapter',private_gateway=gate,private_media=object())
    with pytest.raises(GatewayError,match='scope_mismatch'):
        await adapter.apply_human_control({'session_id':'human_test','action':'takeover','epoch':1,'revision':1},replace(scope,user_id='another_actor'))


@pytest.fixture
def relay(tmp_path):
    store=RelayStore(tmp_path/'relay','tenant_test',human_access_ready=True)
    bundle=store.pair_code('daily',[SPEC],[])
    store.pair(PairRequest(code=bundle['code'],token=TOKEN))
    connection=store.connect(TOKEN,ConnectionRequest())['connection_id']
    store.poll(TOKEN,PollRequest(connection_id=connection,availability={RESOURCE:True},human_access_ready=True,human_availability={RESOURCE:True}))
    return store,bundle,connection


def request(relay):
    store,_,_=relay
    status=store.human_status('daily',ACTOR,RESOURCE)
    return store.request_human('daily',ACTOR,RESOURCE,expected_generation=status['control_generation'],request_id='request_test')


def test_cloud_default_readiness_and_wrong_scopes_fail_closed(relay):
    store,_,_=relay
    store.human_access_ready=False
    assert store.human_status('daily',ACTOR,RESOURCE)['supported'] is False
    with pytest.raises(RelayError,match='unavailable'):request(relay)
    for identity,resource in [('wrong',RESOURCE),('daily','phone_wrong')]:
        with pytest.raises(RelayError) as e:store.human_status(identity,ACTOR,resource)
        assert e.value.status==404
    store.human_access_ready=True;request(relay)
    with pytest.raises(RelayError) as e:store.human_status('daily','other_actor',RESOURCE)
    assert e.value.status==404


def test_request_blocks_cloud_reads_writes_and_manual_resume(relay):
    store,_,connection=relay
    queued=store.enqueue('daily',RESOURCE,READ,{})
    value=request(relay)
    assert value['state']=='handoff_pending'
    assert request(relay)['session_id']==value['session_id']
    assert store.read_result(queued.command_id,'daily')['state']=='blocked'
    for method in (READ,WRITE):
        with pytest.raises(RelayError,match='private_or_paused'):store.enqueue('daily',RESOURCE,method,{})
    with pytest.raises(RelayError):store.claim(TOKEN,ClaimRequest(connection_id=connection,command_id=queued.command_id))
    with pytest.raises(RelayError,match='explicit_return'):
        store.control('daily',ResourceControl(resource_id=RESOURCE,paused=False,expected_generation=1))


@pytest.mark.asyncio
async def test_real_connector_directive_gateway_ack_and_explicit_return(relay,tmp_path):
    store,bundle,connection=relay
    gateway=DeviceGateway(tmp_path/'gateway',private_access_ready=True)
    cleared=[]
    media=SimpleNamespace(clear=lambda scope,session:cleared.append(session) or True)
    adapter=NativeAdapter(tmp_path/'native',private_gateway=gateway,private_media=media)
    root=tmp_path/'node'
    write_private_json(root/'connector.json',{**bundle,'endpoint':'https://synthetic.invalid','ca_pem':'test','token':TOKEN,'local_data':str(tmp_path),'connection_id':connection})
    node=Connector(root,adapter)
    value=request(relay)
    def poll(acks=None,control_acks=None):
        return store.poll(TOKEN,PollRequest(connection_id=connection,availability={RESOURCE:True},human_access_ready=True,human_availability={RESOURCE:True},human_acks=acks or {},control_acks=control_acks or {}))
    controls=poll()['human_controls']
    await node.apply_human_controls(controls)
    assert gateway.snapshot(RESOURCE)['state']=='human_private'
    poll(node.human_acks)
    assert store.human_status('daily',ACTOR,RESOURCE)['state']=='human_private'
    with pytest.raises(RelayError):store.return_human('daily',ACTOR,RESOURCE,session_id=value['session_id'],epoch=value['epoch'],safe_screen_confirmed=False,scope_confirmed=True)
    result=store.return_human('daily',ACTOR,RESOURCE,session_id=value['session_id'],epoch=value['epoch'],safe_screen_confirmed=True,scope_confirmed=True)
    assert result['state']=='return_pending'
    with pytest.raises(GatewayError):gateway.permit_agent(RESOURCE)
    await node.apply_human_controls(poll()['human_controls'])
    # Replay a lost return ACK must not call the media clear or return twice.
    await node.apply_human_controls(poll()['human_controls'])
    assert len(cleared)==1
    response=poll(node.human_acks)
    assert store.human_status('daily',ACTOR,RESOURCE)['state']=='agent_ready'
    poll(control_acks={RESOURCE:response['controls'][0]['generation']})
    assert store.enqueue('daily',RESOURCE,READ,{}).resource_id==RESOURCE


def test_close_disconnect_and_stale_ack_do_not_auto_return(relay):
    store,_,connection=relay;value=request(relay)
    result=store.close_human('daily',ACTOR,RESOURCE,session_id=value['session_id'],epoch=value['epoch'])
    assert result['state']=='paused'
    stale={'session_id':value['session_id'],'epoch':value['epoch'],'revision':1,'gateway_epoch':1,'state':'human_private'}
    store.poll(TOKEN,PollRequest(connection_id=connection,human_access_ready=True,human_acks={RESOURCE:stale}))
    assert store.human_status('daily',ACTOR,RESOURCE)['state']=='paused'
    store.disconnect(TOKEN,PollRequest(connection_id=connection))
    with pytest.raises(RelayError):store.enqueue('daily',RESOURCE,READ,{})


def test_connector_offline_status_fails_closed_without_waiting_ten_minutes(relay):
    store,_,_=relay;request(relay)
    with store.tx() as db:db.execute('UPDATE connectors SET expires=0')
    value=store.human_status('daily',ACTOR,RESOURCE)
    assert value['state']=='paused' and not value['device_confirmed']


def test_physical_disconnect_pauses_even_while_connector_remains_online(relay):
    store,_,connection=relay;request(relay)
    store.poll(TOKEN,PollRequest(connection_id=connection,human_access_ready=True,
                               availability={RESOURCE:False},human_availability={RESOURCE:False}))
    assert store.human_status('daily',ACTOR,RESOURCE)['state']=='paused'
    with pytest.raises(RelayError,match='offline'):
        value=store.human_status('daily',ACTOR,RESOURCE)
        store.request_human('daily',ACTOR,RESOURCE,expected_generation=value['control_generation'],request_id='retry_offline')


@pytest.mark.asyncio
async def test_actual_poll_loop_keeps_physical_connectivity_when_agent_is_paused(relay,tmp_path,monkeypatch):
    import asyncio
    from wearing.connectors.remote import client as module
    store,bundle,connection=relay
    class Adapter:
        human_access_ready=True
        async def availability(self,specs):return {RESOURCE:True}
    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    root=tmp_path/'node'
    write_private_json(root/'connector.json',{**bundle,'endpoint':'https://synthetic.invalid','ca_pem':'test','token':TOKEN,'local_data':str(tmp_path),'connection_id':connection})
    node=Connector(root,Adapter());node.journal.pause(RESOURCE)
    stop=asyncio.Event();captured=[]
    async def respond(client,path,payload):
        if path=='/v1/poll':
            captured.append(payload)
            result=store.poll(TOKEN,PollRequest(**payload))
            assert request(relay)['state']=='handoff_pending'
            stop.set()
            return result
        assert path=='/v1/disconnect'
        return store.disconnect(TOKEN,PollRequest(**payload))
    async def immediate(_):pass
    monkeypatch.setattr(module,'client_for',lambda *args:Client())
    monkeypatch.setattr(module,'response',respond)
    monkeypatch.setattr(module.asyncio,'sleep',immediate)
    await node.run(stop)
    assert captured[0]['availability']=={RESOURCE:False}
    assert captured[0]['human_availability']=={RESOURCE:True}
    assert store.human_status('daily',ACTOR,RESOURCE)['state']=='paused'


@pytest.mark.asyncio
async def test_connector_rejects_foreign_scope_before_adapter(relay,tmp_path):
    store,bundle,connection=relay;request(relay)
    class Adapter:
        async def apply_human_control(self,*args):raise AssertionError('foreign scope reached gateway')
    root=tmp_path/'node'
    write_private_json(root/'connector.json',{**bundle,'endpoint':'https://synthetic.invalid','ca_pem':'test','token':TOKEN,'local_data':str(tmp_path),'connection_id':connection})
    node=Connector(root,Adapter())
    controls=store.poll(TOKEN,PollRequest(connection_id=connection,human_access_ready=True,human_availability={RESOURCE:True}))['human_controls']
    for field in ('tenant_id','identity_id','connector_id','resource_id'):
        with pytest.raises(ValueError):await node.apply_human_controls([{**controls[0],field:'other'}])


@pytest.mark.asyncio
async def test_connector_cancellation_pauses_private_gateway(relay,tmp_path,monkeypatch):
    import asyncio
    store,bundle,connection=relay
    gate=DeviceGateway(tmp_path/'gateway',private_access_ready=True)
    adapter=NativeAdapter(tmp_path/'adapter',private_gateway=gate)
    scope=GatewayScope('tenant_test','daily',ACTOR,bundle['connector_id'],RESOURCE)
    value=gate.begin_human(scope,'human_test',expected_epoch=0)
    gate.activate_human(scope,'human_test',value['epoch'])
    root=tmp_path/'node'
    write_private_json(root/'connector.json',{**bundle,'endpoint':'https://synthetic.invalid','ca_pem':'test','token':TOKEN,'local_data':str(tmp_path),'connection_id':connection})
    node=Connector(root,adapter)
    async def cancelled(*args):raise asyncio.CancelledError()
    monkeypatch.setattr(node,'_run',cancelled)
    with pytest.raises(asyncio.CancelledError):await node.run()
    assert gate.snapshot(RESOURCE)['state']=='paused'


def test_private_protocol_cannot_accept_secret_fields(relay):
    from pydantic import ValidationError
    store,_,connection=relay
    with pytest.raises(ValidationError):PollRequest(connection_id=connection,text='SYNTHETIC_PASSWORD')
    with pytest.raises(TypeError):store.request_human('daily',ACTOR,RESOURCE,expected_generation=0,request_id='request',password='SYNTHETIC_PASSWORD')
    assert b'SYNTHETIC_PASSWORD' not in store.path.read_bytes()
