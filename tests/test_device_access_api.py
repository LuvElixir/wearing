"""Metadata routes cannot acquire a secret channel through client parameters."""
import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from wearing.cloud.relay import RelayError
from wearing.device_access_api import install_device_access_routes

ACTOR = 'a' * 64


class Relay:
    def __init__(self):
        self.calls = []

    def human_status(self, identity, actor, resource):
        self.calls.append(('status', identity, actor, resource))
        return {'supported': False, 'state': 'unavailable'}

    def request_human(self, identity, actor, resource, **values):
        self.calls.append(('request', identity, actor, resource, values))
        raise RelayError('human_access_unavailable', 409)

    def close_human(self, identity, actor, resource, **values):
        self.calls.append(('close', identity, actor, resource, values))
        return {'state': 'paused'}

    def return_human(self, identity, actor, resource, **values):
        self.calls.append(('return', identity, actor, resource, values))
        raise RelayError('human_return_not_ready', 409)


def fixture(*, local=False, actor=ACTOR):
    relay, app = Relay(), FastAPI()

    @app.middleware('http')
    async def trusted_scope(request: Request, call_next):
        request.state.identity_id = 'daily'
        if actor is not None:
            request.scope['pajio.storage_scope'] = actor
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        # Production create_app uses the same non-echoing validation behavior.
        return JSONResponse({'detail': 'invalid fields'}, status_code=422)

    install_device_access_routes(app, lambda: relay, local_devices=local)
    return app, relay


async def test_actor_is_trusted_scope_and_client_cannot_enable_channel():
    app, relay = fixture()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        status = await client.get('/api/devices/access/phone_1', headers={'x-owner': 'b' * 64})
        assert status.json()['supported'] is False
        denied = await client.post('/api/devices/access/phone_1/request', json={
            'expected_generation': 0, 'request_id': 'request_1'})
        assert denied.status_code == 409
        assert all(call[2] == ACTOR for call in relay.calls)


@pytest.mark.parametrize('actor', [None, 'local', 'wrong', 'b' * 63])
async def test_missing_or_invalid_worker_owner_is_denied(actor):
    app, relay = fixture(actor=actor)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.get('/api/devices/access/phone_1')
    assert response.status_code == 401
    assert relay.calls == []


@pytest.mark.parametrize('fields', [
    {'human_access_ready': True}, {'user_id': 'other'}, {'identity_id': 'other'},
    {'text': 'SYNTHETIC-SECRET'}, {'frame': 'data:image/png;base64,SECRET'},
    {'expected_generation': True}, {'expected_generation': -1},
])
async def test_start_only_accepts_control_metadata(fields):
    app, relay = fixture()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.post('/api/devices/access/phone_1/request', json={
            'expected_generation': 0, 'request_id': 'request_1', **fields})
    assert response.status_code == 422
    assert 'SECRET' not in response.text
    assert relay.calls == []


async def test_user_confirmation_does_not_forge_gateway_clear_ack():
    app, relay = fixture()
    body = {'session_id': 'session_1', 'epoch': 1,
            'safe_screen_confirmed': True, 'scope_confirmed': True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        forged = await client.post('/api/devices/access/phone_1/return', json={**body, 'media_cleared': True})
        assert forged.status_code == 422 and relay.calls == []
        refused = await client.post('/api/devices/access/phone_1/return', json=body)
        assert refused.status_code == 409
        paused = await client.post('/api/devices/access/phone_1/close', json={'session_id': 'session_1', 'epoch': 1})
        assert paused.json()['state'] == 'paused'


async def test_local_entry_reports_unavailable_and_never_calls_relay():
    app, relay = fixture(local=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.get('/api/devices/access/phone_1')
        assert response.json() == {'supported': False, 'state': 'unavailable',
                                   'unavailable_reason': 'private_gateway_not_configured'}
        denied = await client.post('/api/devices/access/phone_1/request', json={
            'expected_generation': 0, 'request_id': 'request_1'})
        assert denied.status_code == 409
    assert relay.calls == []
