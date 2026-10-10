"""Real gateway/control/worker tests: owner authority is not a caller header."""
import asyncio
import json
from contextlib import asynccontextmanager
import httpx
import pytest
from sqlalchemy import update
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from wearing.cloud.account_deletion_control import AccountDeletionControl
from wearing.cloud.control import ControlStore, ControlError, ownership, routes
from wearing.cloud.gateway import create_gateway_app, load_gateway, forward_worker
from wearing.cloud.mobile_auth import session_storage_scope
from wearing.cloud.session_guard import SessionRevoked
from test_gateway import lab, login, ORIGIN, ISSUER
from test_gateway_voice import Connector, start


def register(root, control, classification='private'):
    operator=ControlStore(load_gateway(root).database_url.get_secret_value(), operator=True)
    owner=control.session(control.login(ISSUER,'alice')).user_id
    AccountDeletionControl(operator).register('tenant_A', classification, owner_user_id=owner)
    return operator, owner


async def test_private_space_whole_proxy_denies_other_member_and_trusted_count_not_rls_count(tmp_path):
    async with lab(tmp_path) as (root, a, b, control, workers, provider, app):
        operator, owner = register(root, control)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
                await login(client, provider)
                assert (await client.get('/api/bootstrap', headers={'X-Pajio-Private-Owner-Scope':'f'*64})).status_code==200
                outgoing=workers.requests[-1]
                assert outgoing.headers['X-Pajio-Private-Owner-Scope']==session_storage_scope(owner,'tenant_A')
                # Operator grant refreshes the trusted FULL membership count to 2.
                operator.grant(ISSUER,'charlie','tenant_A')
                n=len(workers.requests)
                assert (await client.get('/api/bootstrap')).status_code==403
                assert len(workers.requests)==n
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
                await login(client, provider, 'charlie')
                n=len(workers.requests)
                for path in ['/api/bootstrap','/api/workspace/page','/api/workspace/file?path=x','/api/devices/r/files/transfers']:
                    assert (await client.get(path,headers={'X-Pajio-Private-Owner-Scope':session_storage_scope(owner,'tenant_A')})).status_code==403
                assert len(workers.requests)==n
                # Even a registry claiming count1 never authorizes a different actor.
                with operator.transaction(mutating=True) as db:
                    db.execute(update(ownership).where(ownership.c.tenant_id=='tenant_A').values(member_count=1))
                assert (await client.get('/api/bootstrap')).status_code==403
        finally: operator.close()


@pytest.mark.parametrize('classification', [None, 'unknown', 'shared'])
async def test_shared_unknown_missing_registry_retains_api_without_file_authority(tmp_path, classification):
    async with lab(tmp_path) as (root, a, b, control, workers, provider, app):
        operator=None
        if classification: operator,_=register(root,control,classification)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url=ORIGIN) as client:
                await login(client,provider)
                bootstrap=await client.get('/api/bootstrap',headers={'X-Pajio-Private-Owner-Scope':'a'*64})
                assert bootstrap.status_code==200
                assert 'X-Pajio-Private-Owner-Scope' not in workers.requests[-1].headers
                client.headers['X-Wearing-Token']=bootstrap.json()['token']
                reply=await client.get('/api/devices/computer_test/files')
                assert reply.status_code==403 and reply.json()['detail']=='files_private_owner_required'
        finally:
            if operator: operator.close()


async def test_private_registry_mutation_revokes_inflight_wait_and_route_change(tmp_path):
    from wearing.cloud.session_guard import checked_wait
    async with lab(tmp_path) as (root, a, b, control, workers, provider, app):
        operator, owner=register(root,control)
        try:
            session=control.session(control.login(ISSUER,'alice')); route=control.route(session)
            original=control.private_owner_scope(session,route)
            def valid():
                try: return control.private_owner_scope(session,route)==original
                except ControlError: return False
            entered=asyncio.Event(); cancelled=asyncio.Event()
            async def upstream():
                entered.set()
                try: await asyncio.sleep(10)
                finally: cancelled.set()
            task=asyncio.create_task(checked_wait(upstream(),valid,interval=.01))
            await entered.wait()
            with operator.transaction(mutating=True) as db:
                db.execute(update(ownership).where(ownership.c.tenant_id=='tenant_A').values(member_digest='f'*64))
            with pytest.raises(SessionRevoked): await task
            assert cancelled.is_set()
            with operator.transaction(mutating=True) as db:
                db.execute(update(routes).where(routes.c.tenant_id=='tenant_A').values(upstream='http://127.0.0.1:39999'))
            with pytest.raises(ControlError): control.private_owner_scope(session,route)
        finally: operator.close()


async def test_private_owner_change_revokes_existing_voice_and_denies_new_voice(tmp_path):
    async with lab(tmp_path) as (root,a,b,control,workers,provider,_):
        operator,owner=register(root,control); connector=Connector()
        app=create_gateway_app(root,voice_connector=connector)
        try:
            access=control.login(ISSUER,'alice')
            client=TestClient(app,base_url=ORIGIN)
            with client.websocket_connect('wss://wearing.example/api/voice/stream') as ws:
                ws.send_json(start(access)); assert ws.receive_json()['type']=='ready'
                operator.grant(ISSUER,'charlie','tenant_A')
                with pytest.raises(WebSocketDisconnect): ws.receive_json()
            assert len(connector.calls)==1 and len(connector.calls[0][2].messages)==1
            access=control.login(ISSUER,'charlie')
            with client.websocket_connect('wss://wearing.example/api/voice/stream') as ws:
                ws.send_json(start(access))
                with pytest.raises(WebSocketDisconnect): ws.receive_json()
            assert len(connector.calls)==1
        finally:
            operator.close()
            async with app.router.lifespan_context(app): pass
