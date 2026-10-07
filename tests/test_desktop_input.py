from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from pydantic import ValidationError
import httpx
from wearing.cloud.instance import initialize_instance
from wearing.cloud.relay import instance_relay, PairRequest, ConnectionRequest, PollRequest, ClaimRequest, RelayError
from wearing.cloud.desktop_approval import InputProposal, InputDecision, propose, decide, list_proposals
from wearing.desktop_input import DesktopAction, DesktopFrames, DesktopApproval, action_hash
from wearing.cloud.worker import create_tenant_app
from wearing.connectors.remote.client import Connector
from wearing.config import write_private_json

TOKEN='a'*64
ACTION={'app':'WearingProbe','frame_id':'b'*32,'action':'set_value','element':3,'element_label':'Test input','value':'test'}
SPEC={'resource_id':'computer_test','name':'Test computer','kind':'computer','methods':['computer.observe','computer.input']}


@pytest.fixture
def paired(tmp_path):
    root=tmp_path/'tenant';initialize_instance(root,'tenant_test','https://wearing.example')
    s=instance_relay(root);b=s.pair_code('daily',[SPEC],[]);s.pair(PairRequest(code=b['code'],token=TOKEN))
    conn=s.connect(TOKEN,ConnectionRequest())['connection_id'];s.poll(TOKEN,PollRequest(connection_id=conn,availability={'computer_test':True}))
    return root,s,b,conn


def request(s):return propose(s,'daily',InputProposal(resource_id='computer_test',action=ACTION,reason='Test one action'))
def decision(row,choice='once'):return InputDecision(approval_id=row['approval_id'],revision=row['revision'],choice=choice)


def test_no_device_command_until_user_decides_and_repeat_cannot_replay(paired):
    _,s,_,conn=paired;p=request(s)
    assert p['state']=='awaiting_user'
    with s.tx() as db:assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==0
    with pytest.raises(RelayError,match='approval_required'):s.enqueue('daily','computer_test','computer.input',ACTION)
    with ThreadPoolExecutor(2) as pool:
        def run(_):
            try:return decide(s,'daily',decision(p))
            except RelayError:return None
        rows=list(pool.map(run,range(2)))
    assert sum(r is not None for r in rows)==1
    with s.tx() as db:assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==1
    command=s.poll(TOKEN,PollRequest(connection_id=conn,availability={'computer_test':True}))['command']
    authority=s.claim(TOKEN,ClaimRequest(connection_id=conn,command_id=command['command_id']))['input_approval']
    from wearing.cloud.commands import DeviceCommand
    assert DesktopApproval.model_validate(authority).permits(DeviceCommand.model_validate(command))
    altered=DeviceCommand.model_validate(command).model_copy(update={'params':{**command['params'],'value':'different'}})
    assert not DesktopApproval.model_validate(authority).permits(altered)


@pytest.mark.parametrize('cause',['deny','expiry','takeover','reconnect','wrong_identity','changed_revision'])
def test_denial_stale_or_other_identity_never_queues_input(paired,cause):
    _,s,_,conn=paired;p=request(s)
    identity='daily';body=decision(p)
    if cause=='deny':body=decision(p,'deny')
    elif cause=='expiry':
        with s.tx() as db:db.execute('UPDATE desktop_proposals SET expires=0')
    elif cause=='takeover':
        from wearing.cloud.relay import ResourceControl
        s.control('daily',ResourceControl(resource_id='computer_test',paused=True,expected_generation=0))
    elif cause=='reconnect':s.connect(TOKEN,ConnectionRequest(previous_connection_id=conn))
    elif cause=='wrong_identity':identity='overseas'
    elif cause=='changed_revision':body=InputDecision(approval_id=p['approval_id'],revision='0'*64,choice='once')
    if cause=='deny':assert decide(s,identity,body)['state']=='denied'
    else:
        with pytest.raises(RelayError):decide(s,identity,body)
    with s.tx() as db:assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==0
    assert list_proposals(s,'overseas')==[]


def test_read_only_grant_and_arbitrary_native_parameters_are_refused(paired):
    _,s,_,_=paired
    with s.tx() as db:db.execute('UPDATE connectors SET resources=?',(json.dumps([{**SPEC,'methods':['computer.observe']}]),))
    with pytest.raises(RelayError,match='not_granted'):request(s)
    for extra in [{'bring_to_front':True},{'coordinate':[0,0]},{'shell':'rm anything'},{'text':'not valid for set_value'}]:
        with pytest.raises(ValidationError):DesktopAction.model_validate({**ACTION,**extra})


def frames():
    @dataclass
    class Lease:epoch:int=1;holder:str='agent'
    class Guard:
        state=Lease()
        def get(self):return self.state
        def assert_agent_may_act(self):
            if self.state.holder!='agent':raise ValueError('human')
            return self.state
    guard=Guard();calls=[];callbacks=[]
    def dispatch(args):
        calls.append(args)
        if args['action']=='set_value':assert callbacks[-1]('test','test')=='once'
        return '{"ok":true,"app":"WearingProbe","elements":[{"index":3,"label":"Test input"}]}'
    f=DesktopFrames(dispatch,guard,callbacks.append)
    _,meta=f.observe({'app':'WearingProbe','action':'capture'})
    action={**ACTION,'frame_id':meta['frame_id']}
    authority=DesktopApproval(approval_id='approval_test',command_id='command_test',scope={'tenant_id':'tenant_test','identity_id':'daily'},
        resource_id='computer_test',connection_id='connection_test',params_hash=action_hash(action),expires_at=datetime.now(timezone.utc)+timedelta(seconds=60))
    return f,guard,calls,callbacks,action,authority


def test_native_frame_consumed_once_and_no_persistent_approval():
    f,_,calls,callbacks,action,authority=frames();assert json.loads(f.act(action,authority))['ok']
    assert callbacks[-1] is None
    with pytest.raises(ValueError):f.act(action,authority)
    assert len(calls)==3


@pytest.mark.parametrize('change',['frame','app','expiry','handoff_cycle','payload','capture','label'])
def test_native_stale_frame_never_dispatches(change):
    f,guard,calls,callbacks,action,authority=frames()
    if change=='frame':action['frame_id']='c'*32
    elif change=='app':action['app']='DifferentApp'
    elif change=='expiry':f.frame['deadline']=0
    elif change=='handoff_cycle':guard.state.epoch+=2
    elif change=='payload':action['value']='different'
    elif change=='label':
        action['element_label']='Another target';authority=authority.model_copy(update={'params_hash':action_hash(action)})
    elif change=='capture':f.observe({'app':'DifferentApp','action':'capture'})
    before=len(calls)
    with pytest.raises(ValueError):f.act(action,authority)
    assert len(calls)==before and callbacks==[]


async def test_browser_decision_requires_instance_session_csrf_and_identity(paired,monkeypatch):
    root,s,_,_=paired;p=request(s)
    app=create_tenant_app(root,engine_autostart=False);child=app
    async def no(*_):return None
    monkeypatch.setattr(child.state.runtime,'start',no)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://wearing.example') as c:
        assert (await c.get('/api/devices/input-approvals')).status_code==401
        auth={'Authorization':'Bearer '+(root/'gateway.key').read_text().strip(),'X-Wearing-Tenant':'tenant_test','Origin':'https://wearing.example'}
        c.headers.update(auth)
        csrf=(await c.get('/api/bootstrap')).json()['token']
        assert (await c.post('/api/devices/input-approvals',json=decision(p).model_dump())).status_code==403
        c.headers['X-Wearing-Token']=csrf
        assert len((await c.get('/api/devices/input-approvals')).json()['approvals'])==1
        assert (await c.post('/api/devices/input-approvals',json=decision(p,'deny').model_dump())).json()['state']=='denied'
    await child.state.service.hermes.close()


@pytest.mark.parametrize('tamper',['missing','hash','identity','expired'])
async def test_connector_refuses_invalid_input_authority_before_native_execution(paired,tmp_path,monkeypatch,tamper):
    root,s,b,conn=paired;p=request(s);approved=decide(s,'daily',decision(p))
    from wearing.cloud.commands import DeviceCommand
    from wearing.cloud.relay import create_relay_app
    command=DeviceCommand.model_validate(s.poll(TOKEN,PollRequest(connection_id=conn,availability={'computer_test':True}))['command'])
    node_root=tmp_path/'node'
    write_private_json(node_root/'connector.json',{**b,'endpoint':'https://relay.example','ca_pem':'TEST CA',
        'token':TOKEN,'connection_id':conn,'local_data':str(tmp_path/'local')})
    class Adapter:
        called=False
        async def execute(self,*_,**__):self.called=True;return {}
    adapter=Adapter();node=Connector(node_root,adapter)
    from wearing.connectors.remote import client as module
    original=module.response
    async def altered(client,path,payload):
        current=await original(client,path,payload)
        if path=='/v1/claim':
            if tamper=='missing':current.pop('input_approval')
            elif tamper=='hash':current['input_approval']['params_hash']='0'*64
            elif tamper=='identity':current['input_approval']['scope']['identity_id']='overseas'
            else:current['input_approval']['expires_at']='2000-01-01T00:00:00Z'
        return current
    monkeypatch.setattr(module,'response',altered)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_relay_app(root)),
            base_url='https://relay.example',headers={'Authorization':'Bearer '+TOKEN}) as client:
        await node.execute(client,command)
    assert not adapter.called
    assert s.read_result(command.command_id,'daily')['state']=='unknown'


def test_empty_or_invalid_native_window_never_creates_input_frame():
    f,_,_,_,_,_=frames()
    f.dispatch=lambda _:json.dumps({'app':'','window_title':'Window','elements':[]})
    _,meta=f.observe({'app':'WearingProbe','action':'capture'})
    assert meta is None and f.frame is None


def test_changed_actual_view_is_recaptured_and_input_is_refused():
    f,_,calls,callbacks,action,authority=frames()
    f.dispatch=lambda _:json.dumps({'app':'WearingProbe','elements':[{'index':3,'label':'Different input'}]})
    with pytest.raises(ValueError,match='view_changed'):f.act(action,authority)
    assert callbacks==[] and f.frame is None and len(calls)==1
