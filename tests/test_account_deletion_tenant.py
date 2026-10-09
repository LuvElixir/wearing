"""Real tenant ASGI app in a new temp root; no external provider calls."""
import json
from dataclasses import replace

import httpx
import pytest

from wearing.account_deletion import digest
from wearing.cloud.instance import InstanceError, initialize_instance, load_instance
from wearing.cloud.worker import create_tenant_app
from wearing.cloud.account_deletion_tenant import PATH, PHASES, tombstoned
from wearing.config import write_private_json
from wearing.profile import write_private_text

ORIGIN='https://fixture.invalid'
KEY='x'*64


def payload(instance,phase='freeze_tenant',**change):
    return dict(job_id='a'*32,plan_revision='b'*64,operation_id=digest([phase]),
                tenant_id=instance.tenant_id,instance_id=instance.instance_id,phase=phase,
                owner_scope='c'*64,**change)


@pytest.fixture
def tenant(tmp_path, monkeypatch):
    monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '1')
    root=tmp_path/'instance';instance=initialize_instance(root,'tenant_a',ORIGIN)
    write_private_text(root/'deletion-operator.key',KEY)
    app=create_tenant_app(root,engine_autostart=False)
    return root,instance,app


async def test_complete_empty_tenant_freeze_readback_drain_and_restart_fence(tenant):
    root,instance,app=tenant
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
        gateway={'Authorization':'Bearer '+(root/'gateway.key').read_text().strip(),'X-Wearing-Tenant':'tenant_a'}
        assert (await client.get('/api/bootstrap',headers=gateway)).status_code==200
        for phase in PHASES:
            request=payload(instance,phase)
            response=await client.post(PATH,json=request,headers={'Authorization':'Bearer '+KEY})
            assert response.status_code==200,response.text
            result=response.json();assert result['state']=='done',result
            read=await client.get(PATH,params={k:request[k] for k in ('job_id','plan_revision','phase','operation_id')},headers={'Authorization':'Bearer '+KEY})
            assert read.json()==result
        assert app.state.recovery_task.done() and app.state.notification_task.done()
        assert tombstoned(root)
        assert (await client.get('/api/bootstrap',headers=gateway)).status_code==410
        with pytest.raises(InstanceError):load_instance(root)
        assert load_instance(root,allow_deleting=True)==instance
    restarted=create_tenant_app(root,engine_autostart=True)
    async with restarted.router.lifespan_context(restarted), httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),base_url=ORIGIN) as client:
        assert not hasattr(restarted.state,'recovery_task')
        assert (await client.get('/api/bootstrap')).status_code==410
        request=payload(instance,'drain_actions')
        response=await client.post(PATH,json=request,headers={'Authorization':'Bearer '+KEY})
        assert response.json()['state']=='done'


async def test_wrong_auth_scope_extra_fields_and_phase_order_never_freeze(tenant):
    root,instance,app=tenant
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as c:
        p=payload(instance)
        for headers in [{},{'Authorization':'Bearer '+(root/'gateway.key').read_text().strip()},
                        [('Authorization','Bearer '+KEY),('Authorization','Bearer '+KEY)]]:
            assert (await c.post(PATH,json=p,headers=headers)).status_code==401
        h={'Authorization':'Bearer '+KEY}
        for bad in [{**p,'tenant_id':'tenant_b'},{**p,'instance_id':'instance_b'}, {**p,'path':'/etc'},
                    {**p,'phase':'erase_primary'},{**p,'phase':'drain_actions'},{**p,'job_id':'bad'}]:
            assert (await c.post(PATH,json=bad,headers=h)).status_code==409
        assert not tombstoned(root)
        assert (await c.post(PATH,json=p,headers=h)).json()['state']=='done'
        assert (await c.post(PATH,json={**p,'job_id':'d'*32},headers=h)).status_code==409
        assert (await c.post(PATH,json=payload(instance,'drain_actions'),headers=h)).status_code==409


async def test_messaging_without_provider_revoke_stays_waiting_and_keeps_credentials(tenant):
    root,instance,app=tenant
    with app.state.store.connection() as db:
        db.execute("INSERT INTO messaging_connections(identity_id,provider,bot_id,name,secret,allowed_users,enabled,enabled_since,cursor,revision) VALUES('daily','telegram','fixture','fixture','synthetic-secret','[]',0,0,0,'r')")
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,headers={'Authorization':'Bearer '+KEY}) as c:
        assert (await c.post(PATH,json=payload(instance))).json()['state']=='done'
        value=(await c.post(PATH,json=payload(instance,'revoke_credentials'))).json()
        assert value['state']=='waiting' and value['code']=='adapter_unconfigured'
        with app.state.store.connection() as db:
            assert db.execute('SELECT secret,enabled FROM messaging_connections').fetchone()[:]==('synthetic-secret',0)
        assert 'synthetic-secret' not in json.dumps(value)


async def test_cloud_revoke_response_loss_stays_waiting_then_retries_real_revoke(tenant):
    from wearing.cloud_apps import CloudAppError
    root,instance,app=tenant;calls=[]
    row={'app_id':'synthetic','secret':'synthetic-secret','revision':'r','oauth':{'refresh_token':'r-token','access_token':'a-token'}}
    app.state.cloud_apps._write('daily',row)
    async def failed(*args):calls.append(args);raise CloudAppError('synthetic network failure')
    app.state.cloud_apps.network.revoke=failed
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,headers={'Authorization':'Bearer '+KEY}) as c:
        assert (await c.post(PATH,json=payload(instance))).json()['state']=='done'
        result=(await c.post(PATH,json=payload(instance,'revoke_credentials'))).json()
        assert result['state']=='waiting' and result['code']=='provider_unavailable'
        assert app.state.cloud_apps._read('daily')['revocation_pending'] is True
        async def okay(*args):calls.append(args);return {}
        app.state.cloud_apps.network.revoke=okay
        assert (await c.post(PATH,json=payload(instance,'revoke_credentials'))).json()['state']=='done'
        assert app.state.cloud_apps._read('daily') is None
        assert len(calls)==3


async def test_existing_relay_process_fences_after_marker(tenant):
    from wearing.cloud.relay import create_relay_app
    root,instance,app=tenant;relay=create_relay_app(root)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,headers={'Authorization':'Bearer '+KEY}) as c:
        assert (await c.post(PATH,json=payload(instance))).json()['state']=='done'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=relay),base_url=ORIGIN) as r:
            assert (await r.get('/health')).status_code==410
        with pytest.raises(InstanceError):create_relay_app(root)


async def test_active_unknown_native_os_write_is_not_declared_drained(tenant):
    root,instance,app=tenant
    with app.state.store.connection() as db:
        db.execute("INSERT INTO native_devices(identity,installation,secret_hash,name,revision,enabled,policy,capabilities) VALUES('daily','device','hash','fixture',1,1,'{}','{}')")
        db.execute("INSERT INTO native_commands(id,identity,installation,task_id,run_id,request_key,fingerprint,command,state,created,expires) VALUES('command','daily','device','task','run','request','hash',?,'executing','now','later')", (json.dumps({'method':'calendar.create'}),))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,headers={'Authorization':'Bearer '+KEY}) as c:
        for phase in PHASES:
            r=(await c.post(PATH,json=payload(instance,phase))).json()
            assert r['state']==('waiting' if phase=='drain_actions' else 'done'),r
        with app.state.store.connection() as db:
            assert db.execute('SELECT state FROM native_commands').fetchone()[0]=='unknown'
            assert db.execute('SELECT enabled FROM native_devices').fetchone()[0]==0


async def test_never_started_queue_is_cancelled_and_drains(tenant):
    root,instance,app=tenant
    task,_=app.state.store.accept_message('synthetic queued','daily','request-queue',{'running'})
    with app.state.store.connection() as db:
        db.execute("UPDATE message_handoffs SET state='queued' WHERE task_id=?",(task['id'],))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,headers={'Authorization':'Bearer '+KEY}) as c:
        for phase in PHASES:assert (await c.post(PATH,json=payload(instance,phase))).json()['state']=='done'
        assert app.state.store.get(task['id'])['status']=='stopped'
        assert app.state.store.message_receipt(task['id'])['queue_state']=='cancelled'


async def test_admitted_start_without_response_remains_unknown(tenant):
    root,instance,app=tenant
    task=app.state.store.create('synthetic ambiguous','assistant')
    assert app.state.store.reserve_start(task['id'],{'input':'synthetic'},'synthetic-key',set())
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,headers={'Authorization':'Bearer '+KEY}) as c:
        for phase in PHASES:
            result=(await c.post(PATH,json=payload(instance,phase))).json()
        assert result['state']=='waiting' and result['code']=='instance_busy'
        assert app.state.store.get(task['id'])['status']=='ambiguous'


async def test_started_run_stop_is_read_back_without_background_dispatch(tenant):
    root,instance,app=tenant
    task=app.state.store.create('synthetic running','assistant')
    app.state.store.update(task['id'],status='running',run_id='synthetic-run')
    remote=['running'];calls=[]
    async def status(run):calls.append(('status',run));return {'status':remote[0]}
    async def stop(run):calls.append(('stop',run));remote[0]='cancelled';return {}
    app.state.service.hermes.status=status;app.state.service.hermes.stop=stop
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,headers={'Authorization':'Bearer '+KEY}) as c:
        for phase in PHASES:
            result=(await c.post(PATH,json=payload(instance,phase))).json()
            assert result['state']=='done',result
        assert app.state.store.get(task['id'])['status']=='stopped'
        assert calls==[('status','synthetic-run'),('stop','synthetic-run'),('status','synthetic-run')]


async def test_freeze_cancels_and_awaits_health_sampler_without_late_write_or_restart(tenant):
    import asyncio
    from contextlib import suppress
    from wearing.health_history import HealthHistory, HealthMonitor
    root, instance, app = tenant
    entered, stopped = asyncio.Event(), asyncio.Event()
    class SlowReadOnlyProbe:
        async def snapshot(self, *args):
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                stopped.set()
    history = HealthHistory(app.state.store, require_owner=True)
    monitor = HealthMonitor(history, SlowReadOnlyProbe())
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'Authorization':'Bearer '+KEY}) as client:
        # The synthetic probe replaces a lifecycle sampler if the root has mounted it.
        previous = getattr(app.state, 'health_task', None)
        if previous:
            previous.cancel()
            with suppress(asyncio.CancelledError): await previous
        app.state.health_task = asyncio.create_task(monitor.run(asyncio.Event()))
        await asyncio.wait_for(entered.wait(), 1)
        with history.store.connection() as db:
            count = db.execute('SELECT COUNT(*) FROM health_samples').fetchone()[0]
        result = (await client.post(PATH, json=payload(instance))).json()
        assert result['state'] == 'done'
        assert app.state.health_task.done() and stopped.is_set() and not monitor.running
        with history.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM health_samples').fetchone()[0] == count
    restarted = create_tenant_app(root, engine_autostart=True)
    async with restarted.router.lifespan_context(restarted):
        assert getattr(restarted.state, 'health_task', None) is None
        assert not restarted.state.health_monitor.running
