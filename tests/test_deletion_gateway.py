"""Synthetic signed OIDC, isolated control/worker DBs; never contact a provider."""
import asyncio
import base64
import json
import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from wearing.cloud.account_deletion_control import AccountDeletionControl
from wearing.cloud.control import ControlStore, ControlError
from wearing.cloud.deletion_gateway import PREFIX, ReceiptCodec, fresh_auth
from wearing.cloud.gateway import create_gateway_app, load_gateway, forward_worker
from wearing.cloud.session_guard import SessionRevoked
from test_gateway import lab, login, ORIGIN, ISSUER
from test_gateway_voice import Connector, Remote, start
from test_mobile_gateway import authorize, CHALLENGE, STATE, VERIFIER


def registered(root, current):
    operator = ControlStore(load_gateway(root).database_url.get_secret_value(), operator=True)
    try:
        AccountDeletionControl(operator).register(current.tenant_id, 'private', owner_user_id=current.user_id)
    finally:
        operator.close()


def cookie_sid(client):
    return json.loads(base64.b64decode(client.cookies.get('__Host-wearing-session').split('.')[0]))['sid']


async def web_reauth(client, provider, *, subject='alice', claims=None):
    account = (await client.get('/auth/session')).json()
    begin = await client.post(PREFIX + '/reauth', json={}, headers={'Origin': ORIGIN, 'X-Wearing-CSRF': account['csrf']})
    assert begin.status_code == 200
    response = await client.get(begin.json()['authorize_url'])
    assert response.status_code == 302
    values = parse_qs(urlparse(response.headers['location']).query)
    assert values['max_age'] == ['0'] and values['prompt'] == ['login']
    assert json.loads(values['claims'][0]) == {'id_token': {'auth_time': {'essential': True}}}
    return await client.get('/auth/callback', params=provider.authorize(response.headers['location'], subject,
                                      overrides={'auth_time': int(time.time())} if claims is None else claims))


async def test_deletion_plan_receipt_survives_submission_lost_response_and_blocks_business(tmp_path):
    async with lab(tmp_path) as (root, _, _, control, workers, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            assert (await login(client, provider)).status_code == 303
            current = control.session(cookie_sid(client))
            registered(root, current)
            plan = (await client.get(PREFIX + '/plan')).json()
            assert plan['ready'] and plan['reauth_required']
            recovery = plan['receipt_token']  # durable client save happens BEFORE request
            fields = {k: plan[k] for k in ['request_key', 'receipt_token']}
            fields.update(plan_revision=plan['revision'], confirm='DELETE')
            account = (await client.get('/auth/session')).json()
            headers = {'Origin': ORIGIN, 'X-Wearing-CSRF': account['csrf']}
            assert (await client.post(PREFIX + '/request', json=fields, headers=headers)).json()['code'] == 'reauth_required'
            status_headers = {'Authorization': 'Bearer ' + recovery}
            assert (await client.get(PREFIX + '/status', headers=status_headers)).json()['state'] == 'not_submitted'
            assert (await web_reauth(client, provider)).status_code == 303
            account = (await client.get('/auth/session')).json()
            sid = cookie_sid(client)
            old_cookie = client.cookies.get('__Host-wearing-session')
            headers['X-Wearing-CSRF'] = account['csrf']
            sent = await client.post(PREFIX + '/request', json=fields, headers=headers)
            assert sent.status_code == 202 and sent.json()['data_erased'] is False
            # Forget the response: the PRE-submission credential recovers the exact job.
            state = (await client.get(PREFIX + '/status', headers=status_headers)).json()
            assert state['id'] == sent.json()['id'] and state['state'] == 'awaiting_operator'
            assert state['code'] == 'adapter_unconfigured'
            client.cookies.set('__Host-wearing-session', old_cookie)
            for path in ['/auth/session', '/api/bootstrap', PREFIX + '/plan']:
                assert (await client.get(path)).status_code == 401
                assert (await client.get(path, headers=status_headers)).status_code == 401
            assert (await client.post(PREFIX + '/request', json=fields, headers=status_headers)).status_code == 401
            assert (await client.get(PREFIX + '/status?user_id=other', headers=status_headers)).status_code == 401
            assert (await client.get(PREFIX + '/status', headers={'Authorization': 'Bearer ' + sid})).status_code == 401
            client.cookies.clear()
            assert (await login(client, provider)).status_code == 403
            assert control.session(sid) is None
            with pytest.raises(ControlError): control.switch(sid, 'tenant_A')
            # Restart uses same server signing key and immutable request.
            restart = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=workers)
            async with restart.router.lifespan_context(restart), httpx.AsyncClient(transport=httpx.ASGITransport(app=restart), base_url=ORIGIN) as other:
                assert (await other.get(PREFIX + '/status', headers=status_headers)).json()['id'] == state['id']


@pytest.mark.parametrize('claims,subject', [({}, 'alice'), ({'auth_time': True}, 'alice'),
    ({'auth_time': '123'}, 'alice'), ({'auth_time': 1.5}, 'alice'), ({'auth_time': 1}, 'alice'),
    ({'auth_time': 9999999999}, 'alice'), (None, 'bob')])
async def test_reauth_requires_signed_fresh_numeric_auth_time_and_same_subject(tmp_path, claims, subject):
    async with lab(tmp_path) as (_, _, _, control, _, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            assert (await login(client, provider, overrides={'auth_time': int(time.time())})).status_code == 303
            sid = cookie_sid(client)
            assert control.session(sid).auth_time is None  # ordinary sign-in never counts as action reauth
            assert (await web_reauth(client, provider, claims=claims, subject=subject)).status_code == 400
            assert control.session(sid).auth_time is None


async def test_native_reauth_is_pkce_bound_and_preserves_user_and_selected_tenant(tmp_path):
    async with lab(tmp_path) as (_, _, _, control, _, provider, app):
        control.grant(ISSUER, 'alice', 'tenant_B')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as native, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as browser:
            body = await authorize(native, provider)
            token = (await native.post('/auth/mobile/exchange', json=body)).json()['access_token']
            assert control.session(token).auth_time is None
            control.switch(token, 'tenant_B')
            native.headers['Authorization'] = 'Bearer ' + token
            begin = await native.post(PREFIX + '/reauth', json={'challenge': CHALLENGE, 'state': STATE})
            redirect = await browser.get(begin.json()['authorize_url'])
            done = await browser.get('/auth/callback', params=provider.authorize(redirect.headers['location'], overrides={'auth_time': int(time.time())}))
            assert done.status_code == 303 and done.headers['location'].startswith('pajio://auth?')
            payload = {k: v[0] for k, v in parse_qs(urlparse(done.headers['location']).query).items()}
            assert (await native.post('/auth/mobile/exchange', json={**payload, 'verifier': 'z' * 64})).status_code == 400
            exchange = await native.post('/auth/mobile/exchange', json={**payload, 'verifier': VERIFIER})
            assert exchange.status_code == 200
            result = exchange.json()
            assert result['tenant_id'] == 'tenant_B'
            fresh = control.session(result['access_token'])
            assert fresh.user_id == control.session(token).user_id and fresh_auth(fresh.auth_time)
            assert (await native.post('/auth/mobile/exchange', json={**payload, 'verifier': VERIFIER})).status_code == 400


async def test_receipt_tampering_and_other_account_cannot_submit_or_enumerate(tmp_path):
    async with lab(tmp_path) as (root, _, _, control, _, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as a, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as b:
            await login(a, provider)
            registered(root, control.session(cookie_sid(a)))
            plan = (await a.get(PREFIX + '/plan')).json()
            await login(b, provider, 'bob')
            assert (await web_reauth(b, provider, subject='bob')).status_code == 303
            csrf = (await b.get('/auth/session')).json()['csrf']
            payload = {'request_key': plan['request_key'], 'receipt_token': plan['receipt_token'], 'plan_revision': plan['revision'], 'confirm': 'DELETE'}
            assert (await b.post(PREFIX + '/request', json=payload, headers={'Origin': ORIGIN, 'X-Wearing-CSRF': csrf})).status_code == 422
            invalid = plan['receipt_token'][:-8] + 'tampered'
            assert (await a.get(PREFIX + '/status', headers={'Authorization': 'Bearer ' + invalid})).status_code == 401
            assert (await b.get(PREFIX + '/status')).status_code == 401


async def test_revocation_during_http_upload_prevents_upstream_dispatch():
    allowed = True
    called = []
    class Request:
        headers = {}
        url = httpx.URL(ORIGIN + '/api/conversation')
        scope = {'query_string': b''}
        method = 'POST'
        async def stream(self):
            nonlocal allowed
            yield b'{'
            allowed = False
            yield b'}'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: called.append(request))) as wire:
        with pytest.raises(SessionRevoked):
            await forward_worker(wire, Request(), 'http://127.0.0.1:39001', ORIGIN, 'tenant_A', 'k' * 64, access_check=lambda: allowed)
    assert called == []


async def test_deletion_cancels_http_inflight_wait_and_leaks_no_late_body(tmp_path):
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def delayed(request):
        entered.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return httpx.Response(200, content=b'private-late-result')
    async with lab(tmp_path) as (root, _, _, control, _, provider, _):
        app = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=httpx.MockTransport(delayed))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            await login(client, provider)
            current = control.session(cookie_sid(client))
            registered(root, current)
            book = AccountDeletionControl(control)
            plan = book.preview(current)
            pending = asyncio.create_task(client.get('/api/bootstrap'))
            await entered.wait()
            book.request(current, 'test_request_key_1234567890', plan['revision'])
            response = await asyncio.wait_for(pending, 2)
            assert response.status_code == 401 and cancelled.is_set() and 'private-late' not in response.text


async def test_voice_freeze_before_connection_finishes_sends_no_first_frame(tmp_path):
    async with lab(tmp_path) as (root, _, _, control, _, _, _):
        token = control.login(ISSUER, 'alice')
        current = control.session(token)
        registered(root, current)
        book = AccountDeletionControl(control)
        plan = book.preview(current)
        remote = Remote()
        @asynccontextmanager
        async def connector(url, **kwargs):
            book.request(current, 'voice_handshake_request_1234567890', plan['revision'])
            yield remote
        app = create_gateway_app(root, voice_connector=connector)
        try:
            client = TestClient(app, base_url=ORIGIN)
            with client.websocket_connect('wss://wearing.example/api/voice/stream') as ws:
                ws.send_json(start(token))
                with pytest.raises(WebSocketDisconnect): ws.receive_json()
            assert remote.messages == []
        finally:
            async with app.router.lifespan_context(app): pass


async def test_voice_freeze_during_stream_rejects_old_token_frames(tmp_path):
    async with lab(tmp_path) as (root, _, _, control, _, _, _):
        token = control.login(ISSUER, 'alice')
        current = control.session(token)
        registered(root, current)
        book = AccountDeletionControl(control)
        plan = book.preview(current)
        connector = Connector()
        app = create_gateway_app(root, voice_connector=connector)
        try:
            client = TestClient(app, base_url=ORIGIN)
            with client.websocket_connect('wss://wearing.example/api/voice/stream') as ws:
                ws.send_json(start(token))
                assert ws.receive_json()['type'] == 'ready'
                book.request(current, 'voice_stream_request_1234567890', plan['revision'])
                ws.send_bytes(b'\0\0' * 80)
                with pytest.raises(WebSocketDisconnect): ws.receive_json()
            assert len(connector.calls[0][2].messages) == 1
        finally:
            async with app.router.lifespan_context(app): pass


async def test_streaming_http_stops_chunks_and_closes_response_after_freeze():
    allowed = True
    closed = False
    class ByteStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal allowed
            yield b'allowed-first'
            allowed = False
            yield b'private-after-freeze'
        async def aclose(self):
            nonlocal closed
            closed = True
    class Request:
        headers = {}
        url = httpx.URL(ORIGIN + '/api/task-events')
        scope = {'query_string': b''}
        method = 'GET'
        async def stream(self): yield b''
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=ByteStream()))) as wire:
        response = await forward_worker(wire, Request(), 'http://127.0.0.1:39001', ORIGIN, 'tenant_A', 'k' * 64,
                                        access_check=lambda: allowed)
        chunks = [value async for value in response.body_iterator]
    assert chunks == [b'allowed-first'] and closed


async def test_pending_mobile_handoff_cannot_restore_account_after_deletion(tmp_path):
    async with lab(tmp_path) as (root, _, _, control, _, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as native:
            handoff = await authorize(native, provider)
            token = control.login(ISSUER, 'alice')
            current = control.session(token)
            registered(root, current)
            book = AccountDeletionControl(control)
            book.request(current, 'pending_handoff_request_1234567890', book.preview(current)['revision'])
            assert (await native.post('/auth/mobile/exchange', json=handoff)).status_code == 403
            assert (await native.get('/auth/session')).status_code == 401


async def test_unknown_ownership_and_stale_plan_never_freeze_account(tmp_path):
    async with lab(tmp_path) as (root, _, _, control, _, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            await login(client, provider)
            unknown = (await client.get(PREFIX + '/plan')).json()
            assert not unknown['ready'] and unknown['blockers'][0]['code'] == 'ownership_unknown'
            assert (await web_reauth(client, provider)).status_code == 303
            account = (await client.get('/auth/session')).json()
            csrf = {'Origin': ORIGIN, 'X-Wearing-CSRF': account['csrf']}
            payload = {'request_key': unknown['request_key'], 'receipt_token': unknown['receipt_token'],
                       'plan_revision': unknown['revision'], 'confirm': 'DELETE'}
            denied = await client.post(PREFIX + '/request', json=payload, headers=csrf)
            assert denied.status_code == 409 and denied.json()['code'] == 'ownership_not_ready'
            current = control.session(cookie_sid(client))
            registered(root, current)
            changed = await client.post(PREFIX + '/request', json=payload, headers=csrf)
            assert changed.status_code == 409 and changed.json()['code'] == 'plan_changed'
            assert control.session(cookie_sid(client)) is not None
