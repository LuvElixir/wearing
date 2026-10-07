import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import xml.etree.ElementTree as ET

from filelock import FileLock
import httpx
import pytest

from wearing.cloud.instance import initialize_instance
from wearing.cloud.relay import (instance_relay, create_relay_app, PairRequest,
    ConnectionRequest, PollRequest, ClaimRequest)
from wearing.config import write_private_json
from wearing.connectors.remote.client import Connector
from wearing.connectors.remote.daemon_state import desired, set_desired
from wearing.connectors.remote.service import ConnectorService, ServiceError, windows_task_xml, ps_quote

TOKEN='a'*64
READ='phone.mobile_list_elements_on_screen'
SPEC={'resource_id':'phone_test','name':'Test','kind':'android','methods':[READ]}


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    root=tmp_path/'node';root.mkdir(mode=0o700)
    tenant=tmp_path/'tenant';initialize_instance(tenant,'tenant_test','http://127.0.0.1:18865')
    s=instance_relay(tenant);b=s.pair_code('daily',[SPEC],[]);s.pair(PairRequest(code=b['code'],token=TOKEN))
    write_private_json(root/'connector.json',{**b,'endpoint':'https://relay.example','ca_pem':'TEST CA',
        'token':TOKEN,'connection_id':None,'local_data':str(tmp_path/'local')})
    home=tmp_path/'home';home.mkdir();monkeypatch.setattr(Path,'home',lambda:home)
    monkeypatch.setattr('wearing.connectors.remote.service.platform.system',lambda:'Darwin')
    return root,tenant,s


def fake_system(monkeypatch):
    calls=[];loaded=set()
    def invoke(args,check=True):
        calls.append(args)
        if args[1]=='bootstrap':
            p=Path(args[-1]);v=plistlib.loads(p.read_bytes());loaded.add(v['Label'])
        elif args[1]=='bootout':loaded.discard(args[-1].split('/')[-1])
        code=1 if args[1]=='print' and args[-1].split('/')[-1] not in loaded else 0
        return subprocess.CompletedProcess(args,code,'','')
    monkeypatch.setattr('wearing.connectors.remote.service.command',invoke)
    return calls


def test_install_is_private_idempotent_and_preserves_pairing(prepared,monkeypatch):
    root,_,_=prepared;before=(root/'connector.json').read_bytes();calls=fake_system(monkeypatch)
    s=ConnectorService(root);first=s.install();assert first['installed']
    definition=plistlib.loads(s.plist_path().read_bytes())
    assert definition['ProgramArguments']==s.argv
    assert definition['KeepAlive']=={'SuccessfulExit':False} and definition['WorkingDirectory']==str(Path.home())
    assert TOKEN not in s.plist_path().read_text() and 'TEST CA' not in s.plist_path().read_text()
    assert s.plist_path().stat().st_mode & 0o077==0
    s.install();assert sum(c[1]=='bootstrap' for c in calls)==1
    assert (root/'connector.json').read_bytes()==before


def test_stop_survives_scheduler_restart_and_start_does_not_race_drain(prepared,monkeypatch):
    root,_,_=prepared;fake_system(monkeypatch);s=ConnectorService(root);s.install()
    with FileLock(root/'runner.lock'):
        assert s.stop()['state']=='stopping' and desired(root)=='stopped'
        with pytest.raises(ServiceError,match='等待停止'):s.start()
    assert s.status()['state']=='stopped'
    s.start();assert desired(root)=='running'


def test_task_modified_after_install_is_not_stopped_or_overwritten(prepared,monkeypatch):
    root,_,_=prepared;fake_system(monkeypatch);s=ConnectorService(root);s.install()
    p=s.plist_path();v=plistlib.loads(p.read_bytes());v['ProgramArguments']=['/bin/echo','another task'];p.write_bytes(plistlib.dumps(v));p.chmod(0o600)
    with pytest.raises(ServiceError,match='已被修改'):s.stop()
    assert desired(root)=='running'


def test_adoption_requires_exact_program_root_and_label(prepared,monkeypatch):
    root,_,_=prepared;calls=fake_system(monkeypatch);s=ConnectorService(root)
    label='com.wearing.connector.first-test';p=Path.home()/'Library/LaunchAgents'/(label+'.plist');p.parent.mkdir(parents=True)
    write_private_json(root/'unrelated.json',{})
    p.write_bytes(plistlib.dumps({'Label':label,'ProgramArguments':['/bin/echo','not this root']}));p.chmod(0o600)
    with pytest.raises(ServiceError,match='没有指向'):s.install(label)
    assert not (root/'service.json').exists() and calls==[]
    p.write_bytes(plistlib.dumps({'Label':label,'ProgramArguments':s.argv}));p.chmod(0o600)
    before=p.read_bytes();s.install(label);assert p.read_bytes()==before


def test_uninstall_retains_all_device_data_and_wont_kill_busy_runner(prepared,monkeypatch):
    root,_,_=prepared;calls=fake_system(monkeypatch);s=ConnectorService(root);s.install()
    before=(root/'connector.json').read_bytes()
    with FileLock(root/'runner.lock'):
        with pytest.raises(ServiceError,match='原动作'):s.uninstall()
        assert not any(c[1]=='bootout' for c in calls)
    assert s.uninstall()=={'installed':False,'data_preserved':True}
    assert (root/'connector.json').read_bytes()==before and (root/'actions.sqlite3').exists()
    assert desired(root)=='stopped'


def test_stale_connected_report_is_not_live_status(prepared,monkeypatch):
    root,_,_=prepared;fake_system(monkeypatch);s=ConnectorService(root);s.install()
    write_private_json(root/'status.json',{'state':'connected','observed_at':'2000-01-01T00:00:00+00:00'})
    with FileLock(root/'runner.lock'):assert not s.status()['relay_connected']


def test_windows_task_contract_and_quoting():
    argv=[r'C:\Program Files\Wearing\python.exe','-m','wearing.cli','connector','run','--root',r"C:\Users\O'Brien\Wearing & test"]
    value=windows_task_xml('test',argv,Path(r'C:\Users\Tester'),'S-1-5-21-123','Wearing test')
    n=ET.fromstring(value);ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    assert n.findtext('t:Principals/t:Principal/t:RunLevel',namespaces=ns)=='LeastPrivilege'
    assert n.findtext('t:Principals/t:Principal/t:LogonType',namespaces=ns)=='InteractiveToken'
    assert n.findtext('t:Settings/t:AllowHardTerminate',namespaces=ns)=='false'
    assert n.findtext('t:Settings/t:ExecutionTimeLimit',namespaces=ns)=='PT0S'
    assert n.findtext('t:Actions/t:Exec/t:Arguments',namespaces=ns)==subprocess.list2cmdline(argv[1:])
    assert ps_quote("a';Remove-Item anything;'")=="'a'';Remove-Item anything;'''"


def test_windows_task_for_another_user_cannot_be_stopped(prepared,monkeypatch):
    root,_,_=prepared;monkeypatch.setattr('wearing.connectors.remote.service.platform.system',lambda:'Windows')
    s=ConnectorService(root);sid='S-1-5-21-123'
    write_private_json(s.manifest,{'root':str(root),'platform':'Windows','label':s.label,'argv':s.argv,'user_sid':sid})
    changed=windows_task_xml(s.label,s.argv,s.home,'S-1-5-21-999',s.marker)
    monkeypatch.setattr('wearing.connectors.remote.service.powershell',lambda _:subprocess.CompletedProcess([],0,changed,''))
    with pytest.raises(ServiceError,match='不属于'):s.stop()
    assert desired(root)=='running'


async def test_stop_during_claim_does_not_start_native_action(prepared,monkeypatch):
    root,tenant,s=prepared;count=0
    class Adapter:
        async def execute(self,_):
            nonlocal count
            count+=1
            return {}
    node=Connector(root,Adapter());node.connection=s.connect(TOKEN,ConnectionRequest())['connection_id']
    s.poll(TOKEN,PollRequest(connection_id=node.connection,availability={'phone_test':True}))
    c=s.enqueue('daily','phone_test',READ,{})
    from wearing.connectors.remote import client as module
    original=module.response
    async def stop_on_claim(client,path,payload):
        result=await original(client,path,payload)
        if path=='/v1/claim':set_desired(root,'stopped')
        return result
    monkeypatch.setattr(module,'response',stop_on_claim)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_relay_app(tenant)),
            base_url='https://relay.example',headers={'Authorization':'Bearer '+TOKEN}) as client:
        await node.execute(client,c)
    assert count==0 and s.read_result(c.command_id,'daily')['state']=='blocked'


def test_disconnect_is_idempotent_and_fences_only_current_generation(prepared):
    _,_,s=prepared
    conn=s.connect(TOKEN,ConnectionRequest())['connection_id'];s.poll(TOKEN,PollRequest(connection_id=conn,availability={'phone_test':True}))
    queued=s.enqueue('daily','phone_test',READ,{})
    assert s.disconnect(TOKEN,PollRequest(connection_id=conn))=={'disconnected':True}
    assert s.read_result(queued.command_id,'daily')['state']=='blocked'
    assert not s.inventory('daily')[0]['connected']
    assert s.disconnect(TOKEN,PollRequest(connection_id=conn))['disconnected']
    new=s.connect(TOKEN,ConnectionRequest(previous_connection_id=conn))['connection_id']
    from wearing.cloud.relay import RelayError
    with pytest.raises(RelayError):s.disconnect(TOKEN,PollRequest(connection_id=conn))
    s.poll(TOKEN,PollRequest(connection_id=new,availability={'phone_test':True}))
    assert s.enqueue('daily','phone_test',READ,{})


async def test_graceful_stop_finishes_admitted_action_once_then_disconnects(prepared,monkeypatch):
    root,tenant,s=prepared;started=asyncio.Event();release=asyncio.Event();count=0
    class Adapter:
        async def availability(self,_):return {'phone_test':True}
        async def execute(self,_):
            nonlocal count
            count+=1;started.set();await release.wait();return {'content':[{'type':'text','text':'read only result'}]}
    monkeypatch.setattr('wearing.connectors.remote.client.client_for',lambda config,root:httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_relay_app(tenant)),base_url='https://relay.example',headers={'Authorization':'Bearer '+TOKEN}))
    node=Connector(root,Adapter());task=asyncio.create_task(node.run())
    try:
        for _ in range(100):
            if s.inventory('daily')[0]['online']:break
            await asyncio.sleep(.01)
        c=s.enqueue('daily','phone_test',READ,{})
        await asyncio.wait_for(started.wait(),3)
        set_desired(root,'stopped');assert not task.done()
        release.set();await asyncio.wait_for(task,5)
        assert count==1 and s.read_result(c.command_id,'daily')['state']=='completed'
        assert not s.inventory('daily')[0]['connected']
        assert json.loads((root/'status.json').read_text())['state']=='stopped'
        # Scheduler/login can invoke the process again; persisted stop forbids work.
        await node.run();assert count==1
    finally:
        task.cancel()
        if not task.done():
            try:await task
            except asyncio.CancelledError:pass
