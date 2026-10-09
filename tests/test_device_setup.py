import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from pydantic import ValidationError

from wearing.cloud.commands import DeviceCommand
from wearing.cloud.device_setup import DeviceOffer, PairDevices, create_pairing
from wearing.cloud.relay import (RelayStore, RelayError, PairRequest, ConnectionRequest,
    PollRequest, ClaimRequest, ResultRequest, DeviceReview, utc, CONNECTION_SECONDS)
from wearing.cloud.instance import initialize_instance, read_private
from wearing.cloud.worker import create_tenant_app
from wearing.config import write_private_json
from wearing.connectors.remote.adapter import NativeAdapter
from wearing.connectors.remote.client import PairBundle

READ='phone.mobile_list_elements_on_screen'
WRITE='phone.mobile_press_button'
SPEC={'resource_id':'phone_test','kind':'android','name':'测试手机','methods':[READ,WRITE]}
OFFER={'schema_version':1,'resources':[SPEC]}
TOKEN='a'*64
ORIGIN='https://wearing.example'


def prepare(tmp_path):
    root=tmp_path/'instance';initialize_instance(root,'tenant_A',ORIGIN)
    store=RelayStore(root/'data/device-relay','tenant_A')
    write_private_json(root/'data/device-endpoint.json', {'endpoint':'https://relay.example','ca_pem':'test certificate'})
    return root,store


def request(offer=OFFER,request_id='a'*32):
    return PairDevices.model_validate({'request_id':request_id,'offer':offer})


@pytest.mark.parametrize('changes', [
    {'tools':[{'name':'shell'}]}, {'endpoint':'https://attacker.example'},
    {'resources':[{**SPEC,'methods':['phone.shell']}]},
    {'resources':[{**SPEC,'kind':'computer'}]},
    {'resources':[SPEC,SPEC]}, {'schema_version':True}])
def test_offer_cannot_inject_transport_tools_or_capabilities(changes):
    with pytest.raises(ValidationError):DeviceOffer.model_validate({**OFFER,**changes})


def test_browser_pairing_is_scoped_canonical_and_idempotent(tmp_path):
    root,s=prepare(tmp_path)
    offer={'schema_version':1,'resources':[{**SPEC,'methods':[READ]}]}
    first=create_pairing(s,root,'daily',request(offer))
    assert create_pairing(s,root,'daily',request(offer))==first
    assert first['endpoint']=='https://relay.example'
    PairBundle.model_validate(first)
    with pytest.raises(RelayError,match='request_changed'):create_pairing(s,root,'overseas',request(offer))
    with s.tx() as db:
        tools=json.loads(db.execute('SELECT tools FROM pairs').fetchone()[0])
    assert [t['name'] for t in tools]==['mobile_list_elements_on_screen']
    s.pair(PairRequest(code=first['code'],token=TOKEN))
    assert s.inventory('overseas')==[]
    with pytest.raises(RelayError,match='already_paired'):create_pairing(s,root,'daily',request(offer,'b'*32))


def test_lost_response_concurrent_retry_has_one_returned_bundle(tmp_path):
    root,s=prepare(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        values=list(pool.map(lambda _:create_pairing(s,root,'daily',request()),range(2)))
    assert values[0]==values[1]
    s.pair(PairRequest(code=values[0]['code'],token=TOKEN))
    with s.tx() as db:db.execute('UPDATE pairing_requests SET expires=0')
    with pytest.raises(RelayError,match='expired'):create_pairing(s,root,'daily',request())


def test_missing_or_invalid_destination_mints_no_pairing(tmp_path):
    root,s=prepare(tmp_path)
    write_private_json(root/'data/device-endpoint.json',{'endpoint':'http://relay.example','ca_pem':'test'})
    with pytest.raises(ValueError):create_pairing(s,root,'daily',request())
    with s.tx() as db:assert db.execute('SELECT COUNT(*) FROM pairs').fetchone()[0]==0


def uncertain(root,s):
    b=s.pair_code('daily',[SPEC],[]);s.pair(PairRequest(code=b['code'],token=TOKEN))
    conn=s.connect(TOKEN,ConnectionRequest())['connection_id']
    s.poll(TOKEN,PollRequest(connection_id=conn,availability={'phone_test':True}))
    command=s.enqueue('daily','phone_test',WRITE,{'button':'HOME'})
    s.claim(TOKEN,ClaimRequest(connection_id=conn,command_id=command.command_id))
    s.cancel(command.command_id,'daily')
    return conn,command


def quiescent(s,command,conn):
    # A post-deadline serial heartbeat, not simply the existence of a connection.
    with s.tx() as db:
        past=utc()-timedelta(seconds=3)
        row=db.execute('SELECT envelope FROM commands WHERE id=?',(command.command_id,)).fetchone()
        old=DeviceCommand.model_validate_json(row[0]).model_copy(update={'expires_at':past,'created_at':past-timedelta(seconds=60)})
        db.execute('UPDATE commands SET envelope=?,updated=? WHERE id=?',(old.model_dump_json(),past.timestamp(),command.command_id))
    s.poll(TOKEN,PollRequest(connection_id=conn,availability={'phone_test':True}))


def review_request(r,**changes):
    return DeviceReview.model_validate({'command_id':r['command_id'],'revision':r['revision'],
        'checked':True,'note':'已经查看设备，原操作已结束。',**changes})


def test_review_requires_settled_online_device_and_preserves_receipt(tmp_path):
    root,s=prepare(tmp_path);conn,command=uncertain(root,s)
    r=s.reviews('daily')[0];assert not r['can_review'] and s.reviews('overseas')==[]
    with pytest.raises(RelayError,match='not_ready'):s.review('daily',review_request(r))
    quiescent(s,command,conn)
    r=s.reviews('daily')[0];assert r['can_review'] and s.inventory('daily')[0]['needs_review']
    with pytest.raises(RelayError,match='not_found'):s.review('overseas',review_request(r))
    with pytest.raises(RelayError,match='required'):s.review('daily',review_request(r,checked=False))
    with pytest.raises(RelayError,match='changed'):s.review('daily',review_request(r,revision='0'*64))
    with pytest.raises(RelayError,match='previous_action'):s.enqueue('daily','phone_test',WRITE,{'button':'HOME'})
    assert s.review('daily',review_request(r))=={'reviewed':True,'replayed':False}
    assert not s.reviews('daily') and not s.inventory('daily')[0]['needs_review']
    assert s.read_result(command.command_id,'daily')['state']=='unknown'
    # A delayed receipt cannot overwrite the human review or leak screen contents.
    assert not s.result(TOKEN,ResultRequest(connection_id=conn,command_id=command.command_id,
        state='completed',result={'private':'late screenshot'}))['accepted']
    assert s.read_result(command.command_id,'daily')['result'] is None
    with s.tx() as db:
        assert db.execute('SELECT source,note FROM device_reviews').fetchone()[0]=='browser'
        assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==1
    assert s.enqueue('daily','phone_test',WRITE,{'button':'HOME'}).command_id != command.command_id


def test_offline_or_busy_device_cannot_clear_review(tmp_path):
    root,s=prepare(tmp_path);conn,command=uncertain(root,s);quiescent(s,command,conn)
    s.poll(TOKEN,PollRequest(connection_id=conn,availability={'phone_test':False}))
    assert not s.reviews('daily')[0]['can_review']
    s.poll(TOKEN,PollRequest(connection_id=conn,availability={'phone_test':True}))
    observation=s.enqueue('daily','phone_test',READ,{})
    assert not s.reviews('daily')[0]['can_review']
    s.cancel(observation.command_id,'daily')
    assert s.reviews('daily')[0]['can_review']


def test_computer_ids_are_stable_and_local_binding_cannot_expand(tmp_path):
    a=NativeAdapter(tmp_path/'a');b=NativeAdapter(tmp_path/'b')
    assert a.computer_id()==a.computer_id() and a.computer_id()!=b.computer_id()
    local=[{**SPEC,'methods':[READ]}]
    a.verify_binding([DeviceOffer.model_validate({'schema_version':1,'resources':local}).resources[0]],local)
    with pytest.raises(ValueError):a.verify_binding(DeviceOffer.model_validate(OFFER).resources,local)


async def test_pairing_and_review_routes_require_auth_csrf_and_identity(tmp_path, monkeypatch):
    monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '1')
    root,s=prepare(tmp_path)
    app=create_tenant_app(root,engine_autostart=False)
    headers={'Authorization':'Bearer '+(root/'gateway.key').read_text().strip(),'X-Wearing-Tenant':'tenant_A'}
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as c:
        for path in ['/api/devices/offer','/api/devices/pair','/api/devices/reviews','/api/devices/refresh-tools']:
            assert (await c.post(path,json={})).status_code==401
        c.headers.update(headers)
        assert (await c.post('/api/devices/offer',json=OFFER)).status_code==403
        c.headers.update({'X-Wearing-Token':(await c.get('/api/bootstrap')).json()['token'],'Origin':ORIGIN})
        offer=(await c.post('/api/devices/offer',json=OFFER));assert offer.status_code==200
        paired=await c.post('/api/devices/pair',json=request().model_dump(mode='json'))
        assert paired.status_code==200 and paired.headers['cache-control']=='no-store'
        assert 'token' not in paired.json()['bundle']
        link='/api/devices/pair/'+'a'*32+'/download'
        downloaded=await c.get(link)
        assert downloaded.status_code==200 and downloaded.json()==paired.json()['bundle']
        assert 'attachment' in downloaded.headers['content-disposition']
        other=(await c.post('/api/identities',json={'name':'海外','region':'international','description':''})).json()
        assert (await c.get(link,headers={'X-Wearing-Identity':other['id']})).status_code==404
        assert (await c.get(link+'?identity='+other['id'],headers={'X-Wearing-Identity':'daily'})).status_code==409
        c.headers.pop('Authorization')
        assert (await c.get(link)).status_code==401
        c.headers.update(headers)
        bad=await c.post('/api/devices/offer',json={**OFFER,'private_key':'do-not-echo'})
        assert bad.status_code==422 and 'do-not-echo' not in bad.text


@pytest.mark.parametrize('legacy', [False, True])
async def test_manual_pair_api_enables_versioned_private_remote_tools(tmp_path, monkeypatch, legacy):
    monkeypatch.setenv('PAJIO_TRIAL_LIMITS','1')
    from wearing.remote_proxy import remote_enabled, tool_schemas
    root,relay=prepare(tmp_path)
    flag=root/'data/remote-devices.json'
    if legacy:write_private_json(flag,{'enabled':True})
    assert not remote_enabled(root)
    app=create_tenant_app(root,engine_autostart=False)
    headers={'Authorization':'Bearer '+(root/'gateway.key').read_text().strip(),'X-Wearing-Tenant':'tenant_A'}
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
        # Neither unauthenticated nor missing-CSRF requests may enable the gate.
        assert (await client.post('/api/devices/pair',json=request().model_dump(mode='json'))).status_code==401
        client.headers.update(headers)
        assert (await client.post('/api/devices/pair',json=request().model_dump(mode='json'))).status_code==403
        assert not remote_enabled(root)
        client.headers.update({'X-Wearing-Token':(await client.get('/api/bootstrap')).json()['token'],'Origin':ORIGIN})
        response=await client.post('/api/devices/pair',json=request().model_dump(mode='json'))
        assert response.status_code==200
        assert json.loads(read_private(flag))=={'schema_version':1,'enabled':True}
        assert remote_enabled(root)
        bundle=response.json()['bundle']
        relay.pair(PairRequest(code=bundle['code'],token=TOKEN))
        assert {t.name for t in tool_schemas(relay,'daily')}=={'wearing_list_devices','mobile_list_elements_on_screen','mobile_press_button'}
        assert {t.name for t in tool_schemas(relay,'another_identity')}=={'wearing_list_devices'}
        # Retrying the same authorized pairing repairs the old shape and returns
        # the same pairing bundle, rather than minting a second connector.
        write_private_json(flag,{'enabled':True})
        response=await client.post('/api/devices/pair',json=request().model_dump(mode='json'))
        assert response.status_code==200 and response.json()['bundle']==bundle
        assert remote_enabled(root)


def test_operator_pair_cli_writes_the_same_gate_and_explains_old_engine_activation(tmp_path, monkeypatch, capsys):
    from wearing.cli import main
    from wearing.cloud.device_setup import tools_for
    from wearing.remote_proxy import remote_enabled
    root,_=prepare(tmp_path)
    inventory=tmp_path/'inventory.json';ca=tmp_path/'ca.pem';output=tmp_path/'pair.json'
    write_private_json(inventory,{'resources':[SPEC],'tools':tools_for([SPEC])})
    ca.write_text('synthetic certificate');ca.chmod(0o600)
    monkeypatch.setattr('sys.argv',['wearing','tenant','pair-device','--root',str(root),
        '--endpoint','https://relay.example','--ca',str(ca),'--inventory',str(inventory),'--output',str(output)])
    main()
    assert json.loads(read_private(root/'data/remote-devices.json'))=={'schema_version':1,'enabled':True}
    assert remote_enabled(root)
    bundle=json.loads(read_private(output));assert bundle['tenant_id']=='tenant_A'
    text=capsys.readouterr().out
    assert '自动刷新' in text and '旧引擎' in text and '版本激活' in text
    assert bundle['code'] not in text
