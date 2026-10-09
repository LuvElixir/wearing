import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from wearing.cloud.instance import initialize_instance
from wearing.cloud.relay import instance_relay,PairRequest,ConnectionRequest,PollRequest,ClaimRequest,ResultRequest,RelayError
from wearing.cloud.desktop_approval import InputProposal,InputDecision,propose,list_proposals,decide
from wearing.cloud.desktop_runs import bind,request_and_wait,MARKER,answer
from wearing.cloud.desktop_tasks import auto_answer
from wearing.hermes import HermesClient
from wearing.config import Settings
from wearing.service import TaskService,TaskError
from wearing.store import Store
from wearing.goals import GoalBook

TOKEN='a'*64
ACTION={'app':'WearingProbe','frame_id':'b'*32,'action':'set_value','element':3,'element_label':'Test input','value':'test'}


@pytest.fixture
async def rig(tmp_path):
    root=tmp_path/'instance';initialize_instance(root,'tenant_test','https://wearing.example')
    store=Store(root/'data/wearing.sqlite3');book=GoalBook(store);relay=instance_relay(root)
    spec={'resource_id':'computer_test','name':'Test computer','kind':'computer','methods':['computer.observe','computer.input']}
    b=relay.pair_code('daily',[spec],[]);relay.pair(PairRequest(code=b['code'],token=TOKEN))
    conn=relay.connect(TOKEN,ConnectionRequest())['connection_id'];relay.poll(TOKEN,PollRequest(connection_id=conn,availability={'computer_test':True}))
    gate=asyncio.Event();requested=asyncio.Event();calls=[]
    engine={'status':'running','approval':None,'choice':None}
    async def wire(req):
        calls.append((req.method,req.url.path))
        if req.url.path=='/v1/capabilities':return httpx.Response(200,json={'wearing':{}})
        if req.url.path=='/v1/runs':return httpx.Response(202,json={'run_id':'run_test'})
        if req.url.path.endswith('/approval'):
            engine['choice']=json.loads(req.content)['choice'];engine['status']='running';gate.set()
            return httpx.Response(200,json={'resolved':1})
        if req.url.path.endswith('/stop'):
            engine['status']='cancelled';gate.set();return httpx.Response(200,json={})
        return httpx.Response(200,json={'status':engine['status'],'approval':engine['approval'],'output':'', 'session_id':'session_test'})
    client=HermesClient(Settings(root/'data',hermes_key='test'),httpx.MockTransport(wire))
    service=TaskService(store,client);service.desktop_relay=lambda:relay;service.start_guard=book.guard
    task=store.create_message('只验证一次测试填写');await service.start(task['id'])
    class Session:
        async def elicit_form(self,message,_schema):
            engine.update(status='waiting_for_approval',approval={'request_id':'request_test','command':message,'pattern_key':'mcp_elicitation'})
            requested.set();await gate.wait()
            return SimpleNamespace(action='accept' if engine['choice']=='once' else 'decline')
    yield SimpleNamespace(root=root,store=store,book=book,relay=relay,conn=conn,service=service,task=task,
        gate=gate,requested=requested,engine=engine,calls=calls,context=SimpleNamespace(session=Session()))
    await client.close()


def proposal(r):return propose(r.relay,'daily',InputProposal(resource_id='computer_test',action=ACTION,reason='One test action'),for_run=True)


async def start_wait(r):
    p=proposal(r);call=asyncio.create_task(request_and_wait(r.relay,'daily',p,r.context))
    await r.requested.wait();await r.service.refresh(r.task['id'])
    return p,call


async def finish_device(r):
    for _ in range(40):
        polled=r.relay.poll(TOKEN,PollRequest(connection_id=r.conn,availability={'computer_test':True}))
        if polled['command']:break
        await asyncio.sleep(.01)
    c=polled['command'];assert c and c['task_id']==r.task['id']
    r.relay.claim(TOKEN,ClaimRequest(connection_id=r.conn,command_id=c['command_id']))
    r.relay.result(TOKEN,ResultRequest(connection_id=r.conn,command_id=c['command_id'],state='completed',
        result={'isError':False,'content':[{'type':'text','text':'native receipt'}]}))
    return c


async def test_approval_continues_original_tool_call_without_second_run(rig):
    r=rig;p,call=await start_wait(r)
    task=r.store.get(r.task['id']);assert task['status']=='waiting_for_approval'
    assert task['approval']['kind']=='desktop_input'
    assert not call.done()
    with r.relay.tx() as db:assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==0
    await r.service.approve(task['id'],'request_test','once')
    await finish_device(r);value=await call
    assert value['state']=='completed' and value['receipt']['result']['isError'] is False
    assert r.calls.count(('POST','/v1/runs'))==1
    assert any(e['kind']=='desktop_receipt' for e in r.store.events(task['id']))
    with pytest.raises(TaskError):await r.service.approve(task['id'],'request_test','once')


@pytest.mark.parametrize('outcome',['deny','stop','expiry','goal_revision','reconnect'])
async def test_refusal_or_changed_context_never_dispatches(rig,outcome):
    r=rig;p,call=await start_wait(r)
    if outcome=='deny':await r.service.approve(r.task['id'],'request_test','deny')
    elif outcome=='stop':await r.service.stop(r.task['id'])
    else:
        if outcome=='expiry':
            with r.relay.tx() as db:db.execute('UPDATE desktop_proposals SET expires=0')
        elif outcome=='reconnect':r.relay.connect(TOKEN,ConnectionRequest(previous_connection_id=r.conn))
        else:
            g=r.book.create('daily','Test goal','Test only','Actual receipt',1)
            with r.store.connection() as db:
                db.execute('INSERT INTO goal_steps VALUES(?,?,1,0,NULL,?)',(r.task['id'],g['id'],'test'))
                db.execute('UPDATE personal_goals SET revision=2 WHERE id=?',(g['id'],))
        with pytest.raises(TaskError):await r.service.approve(r.task['id'],'request_test','once')
        r.engine['choice']='deny';r.gate.set()
    try:await call
    except RelayError:pass
    with r.relay.tx() as db:assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==0


async def test_mcp_accept_cannot_replace_recorded_user_consent(rig):
    r=rig;p,call=await start_wait(r)
    r.engine['choice']='once';r.gate.set()
    with pytest.raises(RelayError,match='consent_required'):await call
    with r.relay.tx() as db:assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==0


async def test_binding_cannot_move_to_other_identity_or_run(rig):
    r=rig;p,call=await start_wait(r)
    for update in ({'run_id':'another_run'},{'identity_id':'overseas'}):
        with pytest.raises(RelayError):bind(r.relay,{**r.store.get(r.task['id']),**update},r.engine['approval'])
    with pytest.raises(RelayError):bind(r.relay,r.store.get(r.task['id']),{**r.engine['approval'],'pattern_key':'other'})
    call.cancel()
    with pytest.raises(asyncio.CancelledError):await call
    assert list_proposals(r.relay,'daily')[0]['state']=='cancelled'


async def delegate(r):
    p=propose(r.relay,'daily',InputProposal(resource_id='computer_test',action=ACTION,reason='Fill the test form',checkpoint='routine'),for_run=True)
    call=asyncio.create_task(request_and_wait(r.relay,'daily',p,r.context))
    await r.requested.wait();await r.service.refresh(r.task['id'])
    await r.service.approve(r.task['id'],'request_test','task')
    await finish_device(r)
    value=await call
    assert value['task_grant_id'] and r.engine['choice']=='once'
    return value['task_grant_id']


async def test_one_human_task_decision_continues_multiple_actions_original_run(rig):
    r=rig;grant=await delegate(r)
    for n in range(3):
        p=propose(r.relay,'daily',InputProposal(resource_id='computer_test',action={**ACTION,'value':f'step {n}'},reason='Continue the same test form',checkpoint='routine'),for_run=True)
        class NoPrompt:
            async def elicit_form(self,*args):raise AssertionError('Routine actions must not prompt again')
        call=asyncio.create_task(request_and_wait(r.relay,'daily',p,SimpleNamespace(session=NoPrompt()),session_grant=grant))
        c=await finish_device(r);value=await call
        assert value['state']=='completed' and c['task_id']==r.task['id']
    assert r.calls.count(('POST','/v1/runs'))==1
    assert r.calls.count(('POST','/v1/runs/run_test/approval'))==1
    assert len([e for e in r.store.events(r.task['id']) if e['kind']=='desktop_receipt'])==4


@pytest.mark.parametrize('change',['app','commitment','sensitive_label','key','expiry','budget','new_run','another_active','stop','reconnect','pause','policy'])
async def test_task_delegation_never_crosses_boundary(rig,change):
    r=rig;grant=await delegate(r);action=ACTION;checkpoint='routine'
    if change=='app':action={**ACTION,'app':'AnotherApp'}
    if change=='commitment':checkpoint='commitment'
    if change=='sensitive_label':action={**ACTION,'element_label':'立即付款'}
    if change=='key':action={'app':'WearingProbe','frame_id':'b'*32,'action':'key','keys':'ENTER'}
    p=propose(r.relay,'daily',InputProposal(resource_id='computer_test',action=action,reason='Continue',checkpoint=checkpoint),for_run=True)
    if change in ('expiry','budget','policy'):
        with r.relay.tx() as db:
            if change=='expiry':db.execute('UPDATE desktop_task_grants SET expires=0')
            elif change=='budget':db.execute('UPDATE desktop_task_grants SET remaining=0')
            else:db.execute('UPDATE connectors SET policy_revision=policy_revision+1')
    elif change=='new_run':r.store.update(r.task['id'],run_id='another_run')
    elif change=='another_active':
        other=r.store.create_message('Another');r.store.update(other['id'],status='running',run_id='another_run')
    elif change=='stop':await r.service.stop(r.task['id'])
    elif change=='reconnect':r.relay.connect(TOKEN,ConnectionRequest(previous_connection_id=r.conn))
    elif change=='pause':
        from wearing.cloud.relay import ResourceControl
        r.relay.control('daily',ResourceControl(resource_id='computer_test',paused=True,expected_generation=0))
    assert not auto_answer(r.relay,'daily',p,grant)
    with r.relay.tx() as db:assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==1


async def test_human_task_permission_cannot_cover_commitment(rig):
    r=rig;p,call=await start_wait(r)
    with pytest.raises(TaskError):await r.service.approve(r.task['id'],'request_test','task')
    r.engine['choice']='deny';r.gate.set();await call


async def test_revoked_permission_blocks_already_queued_routine_action(rig):
    r=rig;grant=await delegate(r)
    p=propose(r.relay,'daily',InputProposal(resource_id='computer_test',action=ACTION,reason='Continue',checkpoint='routine'),for_run=True)
    assert auto_answer(r.relay,'daily',p,grant)
    v=decide(r.relay,'daily',InputDecision(approval_id=p['approval_id'],revision=p['revision'],choice='once'))
    with r.relay.tx() as db:db.execute('UPDATE desktop_task_grants SET revoked=1')
    with pytest.raises(RelayError):r.relay.claim(TOKEN,ClaimRequest(connection_id=r.conn,command_id=v['command_id']))

async def test_task_choice_cannot_change_other_approval_types(rig):
    r=rig
    r.store.update(r.task['id'],status='waiting_for_approval',approval={'request_id':'other_request','kind':'other'})
    with pytest.raises(TaskError):await r.service.approve(r.task['id'],'other_request','task')
    assert ('POST','/v1/runs/run_test/approval') not in r.calls

@pytest.mark.parametrize('choice',['deny','expiry'])
async def test_stopped_prompt_never_generates_another_approval_loop(rig,choice):
    r=rig;p,call=await start_wait(r)
    if choice=='deny':await r.service.approve(r.task['id'],'request_test','deny')
    else:
        with r.relay.tx() as db:db.execute('UPDATE desktop_proposals SET expires=0')
        r.engine['choice']='deny';r.gate.set()
    await call
    with pytest.raises(RelayError,match='workflow_stopped'):proposal(r)
    with r.relay.tx() as db:assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==0
