"""Real HTTP/transaction and crash-recovery tests without real phones or accounts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json

import httpx
import pytest

from wearing.cloud.commands import CommandRejected, DeviceCommand
from wearing.cloud.instance import initialize_instance
from wearing.cloud.relay import (RelayStore, RelayError, PairRequest, PollRequest,
    ConnectionRequest, ClaimRequest, ResultRequest, create_relay_app, utc)
from wearing.config import write_private_json
from wearing.connectors.remote.client import Connector, Journal, PairBundle

READ='phone.mobile_list_elements_on_screen'
WRITE='phone.mobile_click_on_screen_at_coordinates'
SPEC={'resource_id':'phone_test','name':'Test phone','kind':'android','methods':[READ,WRITE]}
TOKEN='a'*64

@pytest.fixture
def paired(tmp_path):
    root=tmp_path/'tenant'
    initialize_instance(root,'tenant_alice','http://127.0.0.1:18865')
    store=RelayStore(root/'data/device-relay','tenant_alice')
    bundle=store.pair_code('daily',[SPEC],[])
    store.pair(PairRequest(code=bundle['code'],token=TOKEN))
    connection=store.connect(TOKEN,ConnectionRequest())['connection_id']
    store.poll(TOKEN,PollRequest(connection_id=connection,availability={'phone_test':True}))
    return root,store,bundle,connection


def queue(store,method=WRITE):
    return store.enqueue('daily','phone_test',method,{'x':50,'y':100})


def test_remote_pause_fences_queued_and_resume_requires_current_connection_ack(paired):
    from wearing.cloud.relay import ResourceControl
    _, s, _, conn = paired
    command = queue(s)
    s.control('daily', ResourceControl(resource_id='phone_test', paused=True, expected_generation=0))
    assert s.read_result(command.command_id, 'daily')['state'] == 'blocked'
    with pytest.raises(RelayError):
        claim(s, command, conn)
    with pytest.raises(RelayError, match='paused_or_syncing'):
        queue(s)
    s.poll(TOKEN, PollRequest(connection_id=conn, availability={'phone_test': True}, control_acks={'phone_test':1}))
    assert s.inventory('daily')[0]['paused'] and not s.inventory('daily')[0]['control_pending']
    with pytest.raises(RelayError, match='control_changed'):
        s.control('daily', ResourceControl(resource_id='phone_test', paused=False, expected_generation=0))
    s.control('daily', ResourceControl(resource_id='phone_test', paused=False, expected_generation=1))
    with pytest.raises(RelayError, match='paused_or_syncing'):
        queue(s)
    s.poll(TOKEN, PollRequest(connection_id=conn, availability={'phone_test': True}, control_acks={'phone_test':1}))
    assert s.inventory('daily')[0]['control_pending']
    s.poll(TOKEN, PollRequest(connection_id=conn, availability={'phone_test': True}, control_acks={'phone_test':2}))
    assert s.inventory('daily')[0]['online']
    new = s.connect(TOKEN, ConnectionRequest(previous_connection_id=conn))['connection_id']
    s.poll(TOKEN, PollRequest(connection_id=new, availability={'phone_test':True}))
    assert s.inventory('daily')[0]['control_pending']
    with pytest.raises(RelayError, match='paused_or_syncing'):
        queue(s)
    s.poll(TOKEN, PollRequest(connection_id=new, availability={'phone_test':True}, control_acks={'phone_test':2}))
    assert queue(s).command_id != command.command_id


def test_pause_discards_inflight_contents_and_never_clears_action_review(paired):
    from wearing.cloud.relay import ResourceControl
    _,s,_,conn = paired
    c=queue(s); claim(s,c,conn)
    with pytest.raises(RelayError, match='resource_not_paired'):
        s.control('overseas', ResourceControl(resource_id='phone_test',paused=True,expected_generation=0))
    s.control('daily', ResourceControl(resource_id='phone_test',paused=True,expected_generation=0))
    assert not s.result(TOKEN, ResultRequest(connection_id=conn, command_id=c.command_id, state='completed',result={'private':'discard me'}))['accepted']
    assert s.read_result(c.command_id,'daily')['result'] is None
    s.control('daily', ResourceControl(resource_id='phone_test',paused=False,expected_generation=1))
    s.poll(TOKEN,PollRequest(connection_id=conn,availability={'phone_test':True},control_acks={'phone_test':2}))
    with pytest.raises(RelayError,match='previous_action_needs_review'):
        queue(s)


def test_remote_resume_cannot_override_local_pause_and_stale_controls_are_rejected(tmp_path):
    j=Journal(tmp_path/'node')
    j.pause('phone_test')
    j.apply_controls([{'resource_id':'phone_test','generation':1,'paused':True}], {'phone_test'})
    j.apply_controls([{'resource_id':'phone_test','generation':2,'paused':False}], {'phone_test'})
    assert j.paused('phone_test')
    with pytest.raises(ValueError,match='obsolete_remote_control'):
        j.apply_controls([{'resource_id':'phone_test','generation':1,'paused':True}], {'phone_test'})
    assert j.control_acks()=={'phone_test':2}
    j.pause('phone_test',False)
    assert not j.paused('phone_test')
    with pytest.raises(ValueError,match='invalid_remote_controls'):
        j.apply_controls([{'resource_id':'phone_other','generation':3,'paused':False}], {'phone_test'})


def claim(store,c,conn,token=TOKEN):
    return store.claim(token,ClaimRequest(connection_id=conn,command_id=c.command_id))


def test_pairing_consumption_is_atomic_and_same_token_can_recover(paired):
    root,store,bundle,connection=paired
    assert store.pair(PairRequest(code=bundle['code'],token=TOKEN))['connector_id']==bundle['connector_id']
    with pytest.raises(RelayError,match='pairing_consumed'):
        store.pair(PairRequest(code=bundle['code'],token='b'*64))
    with pytest.raises(RelayError,match='resource_already_paired'):
        store.pair_code('daily',[SPEC],[])


def test_two_pending_pair_codes_cannot_double_bind_a_device(tmp_path):
    s=RelayStore(tmp_path/'s','tenant_alice')
    a,b=[s.pair_code('daily',[SPEC],[]) for _ in range(2)]
    s.pair(PairRequest(code=a['code'],token=TOKEN))
    with pytest.raises(RelayError,match='resource_already_paired'):
        s.pair(PairRequest(code=b['code'],token='b'*64))


def test_tenant_owner_cannot_be_changed(paired):
    root,store,*_=paired
    with pytest.raises(RelayError,match='owner_mismatch'):
        RelayStore(root/'data/device-relay','tenant_bob')
    assert store.inventory('daily')[0]['resource_id']=='phone_test'


def test_atomic_lease_and_claim_have_one_winner(paired):
    root,store,bundle,connection=paired
    def enqueue():
        try: return queue(store)
        except RelayError as e: return e.code
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:enqueue(),range(2)))
    assert sum(isinstance(v,DeviceCommand) for v in results)==1
    assert 'resource_busy' in results
    command=next(v for v in results if isinstance(v,DeviceCommand))
    def admit():
        try: claim(store,command,connection); return True
        except RelayError: return False
    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(lambda _:admit(),range(2)))==1


@pytest.mark.parametrize('changed', ['identity','resource','method','token','connection'])
def test_authority_cannot_be_selected_by_a_forged_request(paired,changed):
    root,s,b,conn=paired
    with pytest.raises((RelayError,CommandRejected)):
        if changed=='identity': s.enqueue('overseas','phone_test',WRITE,{})
        elif changed=='resource': s.enqueue('daily','phone_other',WRITE,{})
        elif changed=='method': s.enqueue('daily','phone_test','phone.shell',{})
        elif changed=='token': s.poll('b'*64,PollRequest(connection_id=conn))
        else: s.poll(TOKEN,PollRequest(connection_id='connection_other'))
    assert queue(s)


def test_expired_pairing_is_not_consumed(tmp_path):
    s=RelayStore(tmp_path/'s','tenant_alice')
    b=s.pair_code('daily',[SPEC],[])
    with s.tx() as db: db.execute('UPDATE pairs SET expires=0')
    with pytest.raises(RelayError,match='pairing_expired'):
        s.pair(PairRequest(code=b['code'],token=TOKEN))


def test_reconnect_invalidates_queued_work_and_blocks_new_input(paired):
    _,s,b,conn=paired
    c=queue(s)
    new=s.connect(TOKEN,ConnectionRequest(previous_connection_id=conn))['connection_id']
    assert new!=conn
    assert s.connect(TOKEN,ConnectionRequest(previous_connection_id=conn))['connection_id']==new
    assert s.read_result(c.command_id,'daily')['state']=='unknown'
    with pytest.raises(RelayError,match='connection_stale'): claim(s,c,conn)
    s.poll(TOKEN,PollRequest(connection_id=new,availability={'phone_test':True}))
    with pytest.raises(RelayError,match='previous_action_needs_review'): queue(s)
    observe=queue(s,READ)
    claim(s,observe,new)
    s.result(TOKEN,ResultRequest(connection_id=new,command_id=observe.command_id,state='completed',result={'content':[]}))
    with pytest.raises(RelayError,match='previous_action_needs_review'): queue(s)
    s.acknowledge(c.command_id)
    assert queue(s)


def test_revocation_discards_inflight_result_and_durable_restart_keeps_it(paired):
    root,s,b,conn=paired
    c=queue(s); claim(s,c,conn)
    s.revoke(b['connector_id'])
    s=RelayStore(root/'data/device-relay','tenant_alice')
    with pytest.raises(RelayError,match='not_authenticated'):
        s.result(TOKEN,ResultRequest(connection_id=conn,command_id=c.command_id,state='completed',result={'private_screen':'secret'}))
    assert s.read_result(c.command_id,'daily')=={'command_id':c.command_id,'state':'unknown','result':None}
    assert not s.inventory('daily')


def test_result_idempotence_and_no_other_identity_reads(paired):
    _,s,_,conn=paired
    c=queue(s); claim(s,c,conn)
    receipt=ResultRequest(connection_id=conn,command_id=c.command_id,state='completed',result={'content':[{'text':'ok'}]})
    assert s.result(TOKEN,receipt)['accepted']
    assert s.result(TOKEN,receipt)['accepted']
    with pytest.raises(RelayError,match='result_conflict'):
        s.result(TOKEN,receipt.model_copy(update={'result':{'text':'different'}}))
    with pytest.raises(RelayError,match='command_not_found'): s.read_result(c.command_id,'overseas')


class FakeAdapter:
    def __init__(self): self.actions=0
    async def execute(self,c):
        self.actions+=1
        return {'content':[{'type':'text','text':'observed'}],'isError':False}


def device(tmp_path,bundle,connection,adapter):
    root=tmp_path/'connector'
    write_private_json(root/'connector.json',{**bundle,'endpoint':'https://device.invalid','ca_pem':'test',
        'token':TOKEN,'local_data':str(tmp_path),'connection_id':connection})
    return Connector(root,adapter)


@pytest.mark.asyncio
async def test_local_journal_prevents_repeat_and_recovers_crash_as_unknown(paired,tmp_path):
    root,s,b,conn=paired
    adapter=FakeAdapter(); node=device(tmp_path,b,conn,adapter)
    c=queue(s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_relay_app(root)),base_url='https://device.invalid',headers={'Authorization':'Bearer '+TOKEN}) as client:
        await node.execute(client,c)
        await node.execute(client,c)
        assert adapter.actions==1
        assert s.read_result(c.command_id,'daily')['state']=='completed'
        c2=queue(s)
        assert node.journal.begin(c2)
        claim(s,c2,conn)
        node.journal.recover()  # Process died after persisting/admission, before a known result.
        await node.execute(client,c2)
        assert adapter.actions==1
        assert s.read_result(c2.command_id,'daily')['state']=='unknown'
        with pytest.raises(RelayError,match='previous_action_needs_review'): queue(s)


@pytest.mark.asyncio
async def test_local_pause_wins_after_cloud_claim(paired,tmp_path):
    root,s,b,conn=paired
    adapter=FakeAdapter(); node=device(tmp_path,b,conn,adapter)
    c=queue(s)
    node.journal.pause('phone_test')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_relay_app(root)),base_url='https://device.invalid',headers={'Authorization':'Bearer '+TOKEN}) as client:
        await node.execute(client,c)
    assert adapter.actions==0
    assert s.read_result(c.command_id,'daily')['state']=='blocked'


@pytest.mark.asyncio
async def test_claim_response_lost_does_not_dispatch(paired,tmp_path):
    root,s,b,conn=paired
    adapter=FakeAdapter(); node=device(tmp_path,b,conn,adapter)
    c=queue(s)
    import wearing.connectors.remote.client as mod
    original=mod.response
    async def lose(client,path,payload):
        result=await original(client,path,payload)
        if path=='/v1/claim': raise httpx.ReadTimeout('lost_admission_response')
        return result
    from unittest.mock import patch
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_relay_app(root)),base_url='https://device.invalid',headers={'Authorization':'Bearer '+TOKEN}) as client:
        with patch.object(mod,'response',lose): await node.execute(client,c)
    assert adapter.actions==0
    assert s.read_result(c.command_id,'daily')['state']=='unknown'


def test_journal_collision_and_expired_local_authority(paired,tmp_path):
    _,s,b,conn=paired
    c=queue(s); j=Journal(tmp_path/'journal')
    assert j.begin(c)
    with pytest.raises(ValueError,match='collision'): j.begin(c.model_copy(update={'params':{'x':0}}))
    assert not j.begin(c)


@pytest.mark.asyncio
async def test_http_surface_hides_operator_routes_tokens_and_browser_requests(paired):
    root,s,b,conn=paired
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_relay_app(root)),base_url='https://device.invalid') as c:
        assert (await c.post('/v1/poll',json={'connection_id':conn})).status_code==401
        assert (await c.get('/api/tasks')).status_code==404
        assert (await c.get('/internal/runtime')).status_code==404
        r=await c.post('/v1/pair',json={'code':'x','token':'TOP_SECRET'})
        assert r.status_code==422 and 'TOP_SECRET' not in r.text
        r=await c.post('/v1/connect',json={},headers={'Origin':'https://evil.invalid','Authorization':'Bearer '+TOKEN})
        assert r.status_code==403
        assert (await c.post('/v1/pair',content=b'x'*(8*1024*1024+1))).status_code==413


def test_bundle_refuses_insecure_or_redirectable_endpoint(paired):
    _,_,b,_=paired
    for endpoint in ('http://127.0.0.1:1234','https://example.com/path','https://secret@example.com','https://example.com/?token=s'):
        with pytest.raises(ValueError): PairBundle.model_validate({**b,'endpoint':endpoint,'ca_pem':'test'})

@pytest.mark.parametrize('admitted',[False,True])
def test_cancelled_calls_fence_dispatch_and_late_results(paired,admitted):
    _,s,b,conn=paired
    c=queue(s)
    if admitted: claim(s,c,conn)
    s.cancel(c.command_id,'daily')
    assert s.read_result(c.command_id,'daily')['state']==('unknown' if admitted else 'blocked')
    with pytest.raises(RelayError,match='not_queued'): claim(s,c,conn)
    assert not s.result(TOKEN,ResultRequest(connection_id=conn,command_id=c.command_id,state='completed',result={'screen':'private'}))['accepted']
    assert s.read_result(c.command_id,'daily')['result'] is None
