"""Real HTTP schemas + persistent relay, with synthetic connector metadata only.

These tests do not exercise production authentication, ADB, pixels, input or a
private media transport. The trusted worker context is injected by the fixture.
"""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from wearing.cloud.relay import (
    ConnectionRequest, PairRequest, PollRequest, RelayError, RelayStore,
)
from wearing.device_access_api import install_device_access_routes

ACTOR = 'a' * 64
TOKEN = 'b' * 64
RESOURCE = 'phone_http_synthetic'
READ = 'phone.mobile_take_screenshot'
BASE = '/api/devices/access/' + RESOURCE
SPEC = {'resource_id': RESOURCE, 'name': 'Synthetic phone', 'kind': 'android',
        'methods': [READ]}


def setup(tmp_path, *, ready=False, advertised=True):
    store = RelayStore(tmp_path / 'relay', 'tenant_http', human_access_ready=ready)
    bundle = store.pair_code('daily', [SPEC], [])
    store.pair(PairRequest(code=bundle['code'], token=TOKEN))
    connection = store.connect(TOKEN, ConnectionRequest())['connection_id']
    store.poll(TOKEN, PollRequest(connection_id=connection,
                                availability={RESOURCE: True},
                                human_access_ready=advertised,
                                human_availability={RESOURCE: True}))
    context = SimpleNamespace(identity='daily', actor=ACTOR)
    app = FastAPI()

    @app.middleware('http')
    async def trusted_scope(request: Request, call_next):
        request.state.identity_id = context.identity
        request.scope['pajio.storage_scope'] = context.actor
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        return JSONResponse({'detail': 'invalid fields'}, status_code=422)

    install_device_access_routes(app, lambda: store, local_devices=False)
    return SimpleNamespace(store=store, context=context, app=app,
                           connection=connection)


def client_for(fixture):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=fixture.app),
                            base_url='http://synthetic.test')


def poll(fixture, *, acks=None, control_acks=None):
    return fixture.store.poll(TOKEN, PollRequest(
        connection_id=fixture.connection, availability={RESOURCE: True},
        human_access_ready=True, human_availability={RESOURCE: True}, human_acks=acks or {},
        control_acks=control_acks or {}))


async def start(client, request_id='request_one', generation=0):
    return await client.post(BASE + '/request', json={
        'expected_generation': generation, 'request_id': request_id})


def ack_for(directive, state, gateway_epoch=1):
    return {RESOURCE: {
        'session_id': directive['session_id'], 'epoch': directive['epoch'],
        'revision': directive['revision'], 'gateway_epoch': gateway_epoch,
        'state': state,
    }}


@pytest.mark.parametrize('server_ready,advertised', [(False, True), (True, False)])
async def test_default_or_unready_host_cannot_be_enabled_from_http(
        tmp_path, server_ready, advertised):
    fixture = setup(tmp_path, ready=server_ready, advertised=advertised)
    async with client_for(fixture) as client:
        status = await client.get(BASE)
        assert status.status_code == 200
        assert status.json()['supported'] is False
        assert status.json()['unavailable_reason'] == 'private_gateway_unavailable'
        response = await start(client)
        assert response.status_code == 409
        forged = await client.post(BASE + '/request', json={
            'expected_generation': 0, 'request_id': 'request_one',
            'human_access_ready': True})
        assert forged.status_code == 422
    with fixture.store.tx() as db:
        assert db.execute('SELECT COUNT(*) FROM human_access').fetchone()[0] == 0


async def test_opaque_owner_and_wrong_scope_never_reveal_session(tmp_path):
    fixture = setup(tmp_path, ready=True)
    async with client_for(fixture) as client:
        begun = await start(client)
        assert begun.status_code == 200
        session = begun.json()['session_id']
        with fixture.store.tx() as db:
            assert db.execute('SELECT actor FROM human_access').fetchone()[0] == ACTOR
        own = await client.get(BASE, headers={'x-owner': 'c' * 64})
        assert own.json()['session_id'] == session
        assert ACTOR not in own.text
        for field, value in [('identity', 'other'), ('actor', 'c' * 64)]:
            previous = getattr(fixture.context, field)
            setattr(fixture.context, field, value)
            denied = await client.get(BASE)
            assert denied.status_code == 404
            assert session not in denied.text and ACTOR not in denied.text
            setattr(fixture.context, field, previous)
        unknown = await client.get('/api/devices/access/phone_unknown')
        assert unknown.status_code == 404


async def test_request_idempotency_and_epoch_guards_reach_persistent_store(tmp_path):
    fixture = setup(tmp_path, ready=True)
    async with client_for(fixture) as client:
        first = (await start(client)).json()
        repeated = await start(client)
        assert repeated.json() == first
        second = await start(client, 'request_two', first['control_generation'])
        assert second.status_code == 409
        stale_close = await client.post(BASE + '/close', json={
            'session_id': first['session_id'], 'epoch': first['epoch'] + 1})
        assert stale_close.status_code == 409
        body = {'session_id': first['session_id'], 'epoch': first['epoch']}
        closed = (await client.post(BASE + '/close', json=body)).json()
        assert closed['state'] == 'paused'
        assert (await client.post(BASE + '/close', json=body)).json() == closed
        stale_generation = await start(client, 'request_two', 0)
        assert stale_generation.status_code == 409
        fresh = await start(client, 'request_two', closed['control_generation'])
        assert fresh.status_code == 200
        assert fresh.json()['epoch'] > first['epoch']
        assert fresh.json()['session_id'] != first['session_id']
        assert (await client.post(BASE + '/close', json=body)).status_code == 409
        assert (await client.get(BASE)).json()['state'] == 'handoff_pending'


@pytest.mark.parametrize('extra', [
    {'media_cleared': True}, {'gateway_epoch': 2},
    {'human_acks': {RESOURCE: {'state': 'agent_ready'}}},
    {'frame': 'SYNTHETIC_SECRET'}, {'text': 'SYNTHETIC_SECRET'},
    {'user_id': 'c' * 64}, {'scope_confirmed': 1},
])
async def test_return_cannot_smuggle_ack_credentials_or_actor(tmp_path, extra):
    fixture = setup(tmp_path, ready=True)
    async with client_for(fixture) as client:
        first = (await start(client)).json()
        response = await client.post(BASE + '/return', json={
            'session_id': first['session_id'], 'epoch': first['epoch'],
            'safe_screen_confirmed': True, 'scope_confirmed': True, **extra})
        assert response.status_code == 422
        assert 'SYNTHETIC_SECRET' not in response.text
        assert (await client.get(BASE)).json()['state'] == 'handoff_pending'
    assert b'SYNTHETIC_SECRET' not in fixture.store.path.read_bytes()


async def test_user_return_waits_for_paired_gateway_ack_and_control_roundtrip(tmp_path):
    fixture = setup(tmp_path, ready=True)
    async with client_for(fixture) as client:
        value = (await start(client)).json()
        body = {'session_id': value['session_id'], 'epoch': value['epoch'],
                'safe_screen_confirmed': True, 'scope_confirmed': True}
        assert (await client.post(BASE + '/return', json=body)).status_code == 409
        takeover = poll(fixture)['human_controls'][0]
        private_ack = ack_for(takeover, 'human_private')
        # Paired connector transport is a different app. Public user routes
        # cannot impersonate its readiness or ACK endpoint.
        assert (await client.post('/v1/poll', json={
            'connection_id': fixture.connection,
            'human_acks': private_ack})).status_code == 404
        with pytest.raises(RelayError):
            fixture.store.poll('d' * 64, PollRequest(
                connection_id=fixture.connection, human_access_ready=True,
                human_acks=private_ack))
        poll(fixture, acks=private_ack)
        assert (await client.get(BASE)).json()['state'] == 'human_private'
        missing_confirmation = await client.post(BASE + '/return', json={
            **body, 'safe_screen_confirmed': False})
        assert missing_confirmation.status_code == 422
        pending = (await client.post(BASE + '/return', json=body)).json()
        assert pending['state'] == 'return_pending'
        assert pending['device_confirmed'] is False
        assert (await client.post(BASE + '/return', json=body)).json() == pending
        with pytest.raises(RelayError):
            fixture.store.enqueue('daily', RESOURCE, READ, {})
        returned = poll(fixture, acks=private_ack)['human_controls'][0]
        assert (await client.get(BASE)).json()['state'] == 'return_pending'
        with pytest.raises(RelayError, match='invalid_human_ack'):
            poll(fixture, acks=ack_for(returned, 'agent_ready', 1))
        assert (await client.get(BASE)).json()['state'] == 'return_pending'
        response = poll(fixture, acks=ack_for(returned, 'agent_ready', 2))
        assert (await client.get(BASE)).json()['state'] == 'agent_ready'
        with pytest.raises(RelayError):
            fixture.store.enqueue('daily', RESOURCE, READ, {})
        poll(fixture, control_acks={RESOURCE: response['controls'][0]['generation']})
        assert fixture.store.enqueue('daily', RESOURCE, READ, {}).resource_id == RESOURCE


async def test_disconnect_keeps_http_session_paused_and_old_ack_cannot_restore(tmp_path):
    fixture = setup(tmp_path, ready=True)
    async with client_for(fixture) as client:
        await start(client)
        directive = poll(fixture)['human_controls'][0]
        poll(fixture, acks=ack_for(directive, 'human_private'))
        fixture.store.disconnect(TOKEN, PollRequest(connection_id=fixture.connection))
        state = (await client.get(BASE)).json()
        assert state['state'] == 'paused' and state['device_confirmed'] is False
        fixture.connection = fixture.store.connect(TOKEN, ConnectionRequest(
            previous_connection_id=fixture.connection))['connection_id']
        poll(fixture, acks=ack_for(directive, 'human_private'))
        assert (await client.get(BASE)).json()['state'] == 'paused'
        with pytest.raises(RelayError):
            fixture.store.enqueue('daily', RESOURCE, READ, {})
