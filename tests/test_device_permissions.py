import asyncio
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from filelock import FileLock, Timeout

from wearing.cloud.device_permissions import (ApplyPermission, ChangePermission, PermissionBundle,
    create_permission, apply_permission, read_permission, bundle_digest)
from wearing.cloud.device_setup import PairDevices, create_pairing
from wearing.cloud.relay import (RelayError, PairRequest, ConnectionRequest, PollRequest,
    ClaimRequest, create_relay_app)
from wearing.cloud.worker import create_tenant_app
from wearing.config import write_private_json
from wearing.connectors.remote.client import Connector, read_bundle
from wearing.connectors.remote.permissions import update_permissions, require_settled
from wearing.connectors.remote.adapter import NativeAdapter
from test_device_setup import prepare, TOKEN, SPEC, ORIGIN

PC={'resource_id':'computer_test','name':'我的电脑','kind':'computer','methods':['computer.status','computer.observe']}


def test_owned_download_is_privatized_but_symlink_is_rejected(tmp_path):
    file=tmp_path/'wearing-permissions.json';file.write_text('{"download":true}');file.chmod(0o644)
    assert read_bundle(file)=='{"download":true}' and file.stat().st_mode & 0o777==0o600
    link=tmp_path/'link';link.symlink_to(file)
    with pytest.raises(ValueError):read_bundle(link)


def paired(tmp_path):
    root,s=prepare(tmp_path)
    p=create_pairing(s,root,'daily',PairDevices(request_id='a'*32,
        offer={'schema_version':1,'resources':[PC,SPEC]}))
    s.pair(PairRequest(code=p['code'],token=TOKEN))
    return root,s,p


def change(root,s,mode='input',request_id='b'*32):
    r=s.inventory('daily')[0]
    return create_permission(s,root,'daily',ChangePermission(request_id=request_id,
        resource_id=PC['resource_id'],revision=r['permission_revision'],mode=mode))


def commit(s,b,check_only=False,token=TOKEN):
    return apply_permission(s,token,ApplyPermission(**{k:b[k] for k in ('request_id','code','digest')}),check_only=check_only)


def test_two_sided_update_preserves_phone_and_invalidates_old_connection(tmp_path):
    root,s,p=paired(tmp_path)
    conn=s.connect(TOKEN,ConnectionRequest())['connection_id']
    s.poll(TOKEN,PollRequest(connection_id=conn,availability={r['resource_id']:True for r in [PC,SPEC]}))
    before=s.inventory('daily');b=change(root,s)
    PermissionBundle.model_validate(b)
    assert change(root,s)==b and commit(s,b,True)['policy_revision']==2
    assert s.inventory('daily')==before  # generation/download/preflight never expands a grant
    assert 'wearing_computer_request_input' not in {t['name'] for t in s.schemas('daily')}
    result=commit(s,b)
    assert result==commit(s,b) and result['policy_revision']==2
    after=s.inventory('daily');assert all(r['policy_revision']==2 and not r['connected'] for r in after)
    assert set(next(r for r in after if r['kind']=='android')['methods'])==set(next(r for r in before if r['kind']=='android')['methods'])
    assert all(r['connector_id']==p['connector_id'] for r in after)
    assert 'wearing_computer_request_input' in {t['name'] for t in s.schemas('daily')}
    with pytest.raises(RelayError):s.poll(TOKEN,PollRequest(connection_id=conn))
    with pytest.raises(RelayError):s.connect(TOKEN,ConnectionRequest(previous_connection_id=conn))
    new=s.connect(TOKEN,ConnectionRequest())['connection_id'];assert new!=conn
    s.poll(TOKEN,PollRequest(connection_id=new,availability={PC['resource_id']:True}))
    command=s.enqueue('daily',PC['resource_id'],'computer.observe',{})
    assert command.policy_revision==2 and command.connection_id==new
    s.claim(TOKEN,ClaimRequest(connection_id=new,command_id=command.command_id))


def test_identity_tampering_expiry_and_parallel_changes_are_fenced(tmp_path):
    root,s,p=paired(tmp_path);b=change(root,s)
    assert read_permission(s,'daily',b['request_id'])['state']=='pending'
    with pytest.raises(RelayError):read_permission(s,'overseas',b['request_id'],True)
    bad={**b,'code':'z'*43}
    with pytest.raises(RelayError):commit(s,bad)
    with pytest.raises(RelayError):commit(s,b,token='z'*64)
    with pytest.raises(ValueError):PermissionBundle.model_validate({**b,'resources':[PC]})
    other=change(root,s,request_id='c'*32)
    with ThreadPoolExecutor(2) as pool:
        def attempt(bundle):
            try:return commit(s,bundle)['policy_revision']
            except RelayError:return 'conflict'
        values=list(pool.map(attempt,[b,other]))
    assert sorted(values,key=str)==[2,'conflict']
    assert {r['policy_revision'] for r in s.inventory('daily')}=={2}
    downgrade=change(root,s,'observe','d'*32);commit(s,downgrade)
    assert 'wearing_computer_request_input' not in {t['name'] for t in s.schemas('daily')}
    with pytest.raises(RelayError):commit(s,b)
    expired=change(root,s,'input','e'*32)
    with s.tx() as db:db.execute('UPDATE permission_updates SET expires=0 WHERE id=?',(expired['request_id'],))
    assert read_permission(s,'daily',expired['request_id'])['state']=='expired'
    with pytest.raises(RelayError,match='expired'):commit(s,expired)


def test_active_and_uncertain_actions_block_permission_commit(tmp_path):
    root,s,p=paired(tmp_path);b=change(root,s)
    conn=s.connect(TOKEN,ConnectionRequest())['connection_id']
    s.poll(TOKEN,PollRequest(connection_id=conn,availability={PC['resource_id']:True}))
    cmd=s.enqueue('daily',PC['resource_id'],'computer.observe',{})
    with pytest.raises(RelayError,match='busy'):commit(s,b)
    s.claim(TOKEN,ClaimRequest(connection_id=conn,command_id=cmd.command_id));s.cancel(cmd.command_id,'daily')
    with pytest.raises(RelayError,match='busy'):commit(s,b)
    assert s.inventory('daily')[0]['policy_revision']==1


class Adapter:
    verify_binding=NativeAdapter.verify_binding
    async def inventory(self):
        return {'resources':[{**PC,'methods':['computer.status','computer.observe','computer.input']},SPEC]}


@pytest.mark.parametrize('lost_ack',[False,True])
async def test_paired_daemon_delivers_explicit_change_without_download_or_restart(tmp_path,monkeypatch,lost_ack):
    root,s,p=paired(tmp_path)
    local=tmp_path/'connector';local.mkdir()
    write_private_json(local/'connector.json',{**p,'token':TOKEN,'local_data':str(tmp_path/'data'),'connection_id':None})
    before=s.inventory('daily');r=before[0]
    b=create_permission(s,root,'daily',ChangePermission(request_id='b'*32,resource_id=PC['resource_id'],revision=r['permission_revision'],mode='input',delivery='connector'))
    stop=asyncio.Event();connections=[]
    app=create_relay_app(root)
    def client(config,local):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://relay.example',headers={'Authorization':'Bearer '+config['token']})
    import wearing.connectors.remote.client as module
    import wearing.connectors.remote.permissions as permissions
    monkeypatch.setattr(module,'client_for',client);monkeypatch.setattr(permissions,'client_for',client)
    original=module.response
    original_permission=permissions.response
    lost=False
    async def permission_wire(client,path,payload):
        nonlocal lost
        value=await original_permission(client,path,payload)
        if lost_ack and not lost and path.endswith('/apply'):
            lost=True
            raise httpx.ReadError('Lost permission acknowledgement')
        return value
    monkeypatch.setattr(permissions,'response',permission_wire)
    async def wire(client,path,payload):
        value=await original(client,path,payload)
        if path=='/v1/connect':connections.append(value['connection_id'])
        if path=='/v1/poll' and s.inventory('daily')[0]['policy_revision']==2:stop.set()
        return value
    monkeypatch.setattr(module,'response',wire)
    class DaemonAdapter(Adapter):
        async def availability(self,resources):return {r['resource_id']:True for r in resources}
    await asyncio.wait_for(Connector(local,DaemonAdapter()).run(stop),8)
    assert len(connections)==2 and connections[0]!=connections[1]
    c=json.loads((local/'connector.json').read_text())
    assert c['policy_revision']==2 and c['token']==TOKEN
    assert set(next(r for r in c['resources'] if r['kind']=='android')['methods'])==set(SPEC['methods'])
    assert read_permission(s,'daily',b['request_id'])['state']=='applied'
    assert json.loads((local/'permission-update.json').read_text())['automatic']


def test_manual_or_expired_changes_are_never_auto_delivered(tmp_path):
    root,s,p=paired(tmp_path);change(root,s)
    conn=s.connect(TOKEN,ConnectionRequest())['connection_id']
    polled=s.poll(TOKEN,PollRequest(connection_id=conn,permission_delivery=True))
    assert 'permission_update' not in polled
    r=s.inventory('daily')[0]
    b=create_permission(s,root,'daily',ChangePermission(request_id='c'*32,resource_id=PC['resource_id'],revision=r['permission_revision'],mode='input',delivery='connector'))
    assert 'permission_update' not in s.poll(TOKEN,PollRequest(connection_id=conn))
    assert s.poll(TOKEN,PollRequest(connection_id=conn,permission_delivery=True))['permission_update']==b
    with s.tx() as db:db.execute('UPDATE permission_updates SET expires=0')
    assert 'permission_update' not in s.poll(TOKEN,PollRequest(connection_id=conn,permission_delivery=True))


async def test_local_crash_after_cloud_commit_retries_without_replay(tmp_path,monkeypatch):
    root,s,p=paired(tmp_path);b=change(root,s)
    local=tmp_path/'connector';local.mkdir()
    config={**p,'token':TOKEN,'local_data':str(tmp_path/'data'),'connection_id':None}
    write_private_json(local/'connector.json',config)
    bundle_path=tmp_path/'update.json';write_private_json(bundle_path,b)
    app=create_relay_app(root)
    def client(config,local):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://relay.example',
            headers={'Authorization':'Bearer '+config['token']})
    import wearing.connectors.remote.permissions as module
    monkeypatch.setattr(module,'client_for',client)
    original=module.response
    async def lost(client,path,payload):
        value=await original(client,path,payload)
        if path.endswith('/apply'):raise httpx.ReadError('simulated dropped reply')
        return value
    monkeypatch.setattr(module,'response',lost)
    with pytest.raises(httpx.ReadError):await update_permissions(bundle_path,local,Adapter())
    assert s.inventory('daily')[0]['policy_revision']==2
    with pytest.raises(ValueError,match='pending'):require_settled(local)
    # No action has executed. Even a newly launched runner cannot use the staged ceiling.
    with pytest.raises(ValueError,match='pending'):await Connector(local,Adapter()).run()
    monkeypatch.setattr(module,'response',original)
    assert await update_permissions(bundle_path,local,Adapter())=={'applied':True,'policy_revision':2}
    require_settled(local)
    assert await update_permissions(bundle_path,local,Adapter())=={'applied':True,'policy_revision':2}
    updated=json.loads((local/'connector.json').read_text())
    assert updated['token']==TOKEN and updated['code']==p['code'] and updated['local_data']==config['local_data']
    with s.tx() as db:assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==0
    assert (local/'permission-update.json').stat().st_mode & 0o777==0o600
    # A repeated command verifies the cloud again; it cannot present a revoked
    # pairing as a successful two-sided update based on the local file alone.
    s.revoke(p['connector_id'])
    with pytest.raises(httpx.HTTPStatusError):await update_permissions(bundle_path,local,Adapter())


async def test_local_inventory_destination_and_running_process_are_checked_before_mutation(tmp_path,monkeypatch):
    root,s,p=paired(tmp_path);b=change(root,s)
    local=tmp_path/'connector';local.mkdir()
    config={**p,'token':TOKEN,'local_data':str(tmp_path/'data'),'connection_id':None}
    write_private_json(local/'connector.json',config)
    path=tmp_path/'update.json';write_private_json(path,b)
    with FileLock(local/'runner.lock'):
        with pytest.raises(Timeout):await update_permissions(path,local,Adapter())
    changed={**b,'endpoint':'https://other.example'};changed['digest']=bundle_digest(changed)
    write_private_json(path,changed)
    with pytest.raises(ValueError,match='scope'):await update_permissions(path,local,Adapter())
    write_private_json(path,b)
    class Readonly(Adapter):
        async def inventory(self):return {'resources':[PC,SPEC]}
    with pytest.raises(ValueError):await update_permissions(path,local,Readonly())
    assert not (local/'permission-update.json').exists()
    assert json.loads((local/'connector.json').read_text())==config
    assert s.inventory('daily')[0]['policy_revision']==1


async def test_expired_uncommitted_stage_restores_only_authenticated_old_grant(tmp_path,monkeypatch):
    root,s,p=paired(tmp_path);b=change(root,s)
    local=tmp_path/'connector';local.mkdir()
    config={**p,'token':TOKEN,'local_data':str(tmp_path/'data'),'connection_id':None}
    write_private_json(local/'connector.json',config)
    path=tmp_path/'update.json';write_private_json(path,b)
    app=create_relay_app(root)
    import wearing.connectors.remote.permissions as module
    monkeypatch.setattr(module,'client_for',lambda config,local:httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),base_url='https://relay.example',headers={'Authorization':'Bearer '+TOKEN}))
    original=module.response
    async def lost_before_send(client,path,payload):
        if path.endswith('/apply'):raise httpx.ConnectError('not submitted')
        return await original(client,path,payload)
    monkeypatch.setattr(module,'response',lost_before_send)
    with pytest.raises(httpx.ConnectError):await update_permissions(path,local,Adapter())
    with pytest.raises(ValueError,match='pending'):require_settled(local)
    with s.tx() as db:db.execute('UPDATE permission_updates SET expires=0')
    monkeypatch.setattr(module,'response',original)
    with pytest.raises(ValueError,match='expired'):await update_permissions(path,local,Adapter())
    require_settled(local)
    assert json.loads((local/'connector.json').read_text())==config
    assert s.inventory('daily')[0]['policy_revision']==1


async def test_browser_permission_routes_are_private_identity_bound_and_csrf_protected(tmp_path):
    root,s,p=paired(tmp_path)
    app=create_tenant_app(root,engine_autostart=False)
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as c:
        body={'request_id':'b'*32,'resource_id':PC['resource_id'],'revision':s.inventory('daily')[0]['permission_revision'],'mode':'input'}
        assert (await c.post('/api/devices/permissions',json=body)).status_code==401
        c.headers.update({'Authorization':'Bearer '+(root/'gateway.key').read_text().strip(),'X-Wearing-Tenant':'tenant_A'})
        assert (await c.post('/api/devices/permissions',json=body)).status_code==403
        c.headers.update({'X-Wearing-Token':(await c.get('/api/bootstrap')).json()['token'],'Origin':ORIGIN})
        response=await c.post('/api/devices/permissions',json=body);assert response.status_code==200
        assert 'code' not in response.json()
        path='/api/devices/permissions/'+'b'*32
        assert (await c.get(path)).json()['state']=='pending'
        download=await c.get(path+'/download');assert download.status_code==200
        assert 'attachment' in download.headers['content-disposition']
        PermissionBundle.model_validate(download.json())
        assert s.inventory('daily')[0]['policy_revision']==1
        other=(await c.post('/api/identities',json={'name':'海外','region':'international','description':''})).json()
        assert (await c.get(path+'/download',headers={'X-Wearing-Identity':other['id']})).status_code==404
        c.headers.pop('Authorization')
        assert (await c.get(path+'/download')).status_code==401
