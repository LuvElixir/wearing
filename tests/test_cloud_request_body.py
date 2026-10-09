"""Public upload boundaries; synthetic HTTP only, no provider or cloud calls."""
import asyncio
from contextlib import asynccontextmanager
import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from wearing.cloud import request_body
from wearing.cloud.control import ControlStore
from wearing.cloud.gateway import create_gateway_app, initialize_gateway, load_gateway, register_route
from wearing.cloud.instance import initialize_instance
from wearing.cloud.relay import create_relay_app, PairRequest, RelayStore
from wearing.cloud.request_body import RequestBodyBoundary, RequestBodyError, rejected_body


ORIGIN = 'https://entry.example'
ISSUER = 'https://identity.example'
TOKEN = 'a' * 64


def guarded(endpoint, *, limit=16, idle=.03, total=.08):
    app = Starlette(routes=[Route('/', endpoint, methods=['POST'])],
                    exception_handlers={RequestBodyError: rejected_body})
    app.add_middleware(RequestBodyBoundary, limit=limit, idle_seconds=idle, total_seconds=total)
    return app


async def echo(request):
    return JSONResponse({'bytes': len(await request.body())})


@asynccontextmanager
async def client_for(app, origin=ORIGIN):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=origin) as client:
        yield client


async def test_chunked_body_limit_counts_actual_bytes_and_rejects_declared_oversize_without_read():
    read = []
    async def chunks():
        read.append(True)
        yield b'a' * 9
        yield b'b' * 8
    async with client_for(guarded(echo)) as client:
        response = await client.post('/', content=chunks(), headers={'content-length': '17'})
        assert response.status_code == 413 and read == []
        response = await client.post('/', content=chunks())
        assert response.status_code == 413 and read == [True]
        assert response.json()['code'] == 'request_too_large'
        assert (await client.post('/', content=b'x' * 16)).json() == {'bytes': 16}


@pytest.mark.parametrize('headers', [ [('content-length', '1'), ('content-length', '1')],
                                    {'content-length': '-1'}, {'content-length': 'bogus'} ])
async def test_ambiguous_length_is_rejected_without_reading(headers):
    async def unread():
        raise AssertionError('Malformed length must be rejected before consuming body')
        yield b''
    async with client_for(guarded(echo)) as client:
        response = await client.post('/', content=unread(), headers=headers)
        assert response.status_code == 400


async def test_idle_and_total_deadlines_stop_slow_upload_and_cancel_receive():
    cancelled = []
    async def idle():
        yield b'a'
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)
        yield b'b'
    async with client_for(guarded(echo)) as client:
        result = await client.post('/', content=idle())
        assert result.status_code == 408 and cancelled == [True]
        assert result.headers['cache-control'] == 'no-store'
    async def drip():
        for _ in range(20):
            await asyncio.sleep(.01)
            yield b'a'
    async with client_for(guarded(echo, limit=100, idle=.1, total=.035)) as client:
        result = await client.post('/', content=drip())
        assert result.status_code == 408


async def test_form_parsing_and_streamed_response_are_unchanged():
    async def form(request):
        parsed = await request.form()
        assert parsed['state'] == 'synthetic-state'
        async def result():
            yield b'first'
            await asyncio.sleep(.05)  # Response streaming exceeds upload deadline.
            yield b'last'
        return StreamingResponse(result())
    async with client_for(guarded(form, limit=1024, idle=.01, total=.02)) as client:
        result = await client.post('/', data={'state': 'synthetic-state', 'code': 'synthetic-code'})
        assert result.status_code == 200 and result.content == b'firstlast'


async def test_non_http_scopes_are_passed_through_without_reading():
    seen = []
    async def app(scope, receive, send):
        seen.append(scope['type'])
    async def unread():
        raise AssertionError('Non-HTTP receive must not be called')
    guard = RequestBodyBoundary(app, limit=1)
    await guard({'type': 'websocket'}, unread, unread)
    await guard({'type': 'lifespan'}, unread, unread)
    assert seen == ['websocket', 'lifespan']


@asynccontextmanager
async def gateway(tmp_path):
    root, tenant = tmp_path / 'entry', tmp_path / 'tenant'
    initialize_gateway(root, ORIGIN, ISSUER, 'synthetic-client', development=True)
    initialize_instance(tenant, 'tenant_A', ORIGIN)
    control = ControlStore(load_gateway(root).database_url.get_secret_value())
    control.grant(ISSUER, 'alice', 'tenant_A')
    register_route(root, tenant, 'http://127.0.0.1:39001')
    sent = []
    class ResponseBody(httpx.AsyncByteStream):
        def __init__(self, size):
            self.size = size
        async def __aiter__(self):
            yield json.dumps({'bytes': self.size}).encode()
    async def worker(request):
        sent.append(request.url.path)
        return httpx.Response(200, stream=ResponseBody(len(request.content)), headers={'content-type': 'application/json'})
    app = create_gateway_app(root, worker_transport=httpx.MockTransport(worker))
    async with app.router.lifespan_context(app):
        try:
            yield app, control.login(ISSUER, 'alice'), sent
        finally:
            control.close()


async def test_gateway_authentication_precedes_upload_and_upload_limits_still_match(tmp_path):
    async def unread():
        raise AssertionError('Unauthenticated upload was read')
        yield b''
    async with gateway(tmp_path) as (app, sid, sent), client_for(app) as client:
        assert (await client.post('/api/tasks', content=unread())).status_code == 401
        headers = {'Authorization': 'Bearer ' + sid}
        assert (await client.post('/api/tasks', content=b'x' * (1024 * 1024 + 1), headers=headers)).status_code == 413
        assert sent == []
        for path, limit in [('/api/workspace/import', 20 * 1024 * 1024), ('/api/life/assets', 15 * 1024 * 1024)]:
            result = await client.post(path, content=b'x' * limit, headers=headers)
            assert result.status_code == 200 and result.json()['bytes'] == limit
            assert (await client.post(path, content=b'x' * (limit + 1), headers=headers)).status_code == 413
        assert sent == ['/api/workspace/import', '/api/life/assets']


async def test_gateway_mobile_and_deletion_bodies_get_deadlines(tmp_path, monkeypatch):
    monkeypatch.setattr(request_body, 'BODY_IDLE_SECONDS', .02)
    async def slow():
        yield b'{'
        await asyncio.sleep(1)
        yield b'}'
    async with gateway(tmp_path) as (app, sid, _), client_for(app) as client:
        result = await client.post('/auth/mobile/exchange', content=slow())
        assert result.status_code == 408 and result.json()['code'] == 'request_body_timeout'
        # The existing account-deletion small_json implementation is protected
        # through ASGI too, without changing its permission or receipt contract.
        result = await client.post('/auth/account-deletion/reauth', content=slow(),
                                   headers={'Authorization': 'Bearer ' + sid})
        assert result.status_code == 408


async def test_gateway_revoke_during_chunked_upload_never_dispatches(tmp_path):
    async with gateway(tmp_path) as (app, sid, sent), client_for(app) as client:
        async def revoked():
            yield b'first'
            app.state.control.grant(ISSUER, 'alice', 'tenant_A', active=False)
            await asyncio.sleep(.001)
            yield b'last'
        response = await client.post('/api/workspace/import', content=revoked(),
                                     headers={'Authorization': 'Bearer ' + sid})
        assert response.status_code == 401 and sent == []


def relay(tmp_path):
    root = tmp_path / 'tenant'
    initialize_instance(root, 'tenant_A', 'http://127.0.0.1:18865')
    store = RelayStore(root / 'data/device-relay', 'tenant_A')
    bundle = store.pair_code('daily', [{'resource_id': 'phone_test', 'name': 'Test', 'kind': 'android',
                                      'methods': ['phone.mobile_list_elements_on_screen']}], [])
    store.pair(PairRequest(code=bundle['code'], token=TOKEN))
    return create_relay_app(root), store


@pytest.mark.parametrize('credential', [None, 'Bearer ' + 'b' * 64, 'Bearer malformed'])
async def test_relay_rejects_unknown_or_missing_credential_before_body(tmp_path, credential):
    app, _ = relay(tmp_path)
    async def unread():
        raise AssertionError('Unauthenticated connector upload was consumed')
        yield b''
    async with client_for(app) as client:
        result = await client.post('/v1/result', content=unread(), headers={'Authorization': credential} if credential else {})
        assert result.status_code == 401 and result.headers['cache-control'] == 'no-store'


async def test_relay_revocation_during_upload_is_checked_again(tmp_path):
    app, store = relay(tmp_path)
    with store.tx() as db:
        connector = store.auth(db, TOKEN)['id']
    async def revoked():
        yield b'{'
        store.revoke(connector)
        yield b'}'
    async with client_for(app) as client:
        result = await client.post('/v1/connect', content=revoked(), headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'})
        assert result.status_code == 401


async def test_relay_valid_upload_times_out_and_pairing_remains_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(request_body, 'BODY_IDLE_SECONDS', .02)
    app, _ = relay(tmp_path)
    async def slow():
        yield b'{'
        await asyncio.sleep(1)
        yield b'}'
    async with client_for(app) as client:
        result = await client.post('/v1/connect', content=slow(), headers={'Authorization': 'Bearer ' + TOKEN})
        assert result.status_code == 408
        assert (await client.post('/v1/pair', content=slow())).status_code == 408
        result = await client.post('/v1/pair', content=b'x' * (8 * 1024 * 1024 + 1))
        assert result.status_code == 413
