"""Synthetic native enrollment through gateway, private broker, and IdP stub."""
import asyncio
from contextlib import asynccontextmanager
import json
import hashlib
import secrets
import time
import uuid

import httpx
import pytest
from sqlalchemy import select, update

from test_gateway import lab, ORIGIN, ISSUER
from test_invitations import issue
from test_mobile_gateway import VERIFIER, CHALLENGE, STATE
from test_registration import Provider, KEY, PASSWORD, URL
from wearing.cloud.control import ControlStore, states, invitations
from wearing.cloud.gateway import create_gateway_app, load_gateway
from wearing.cloud.invitations import InvitationStore, code_hash
from wearing.cloud.native_enrollment import PREFIX, operation_key
from wearing.cloud.registration import RegistrationBroker, RegistrationError


class BrokerWire(httpx.AsyncBaseTransport):
    def __init__(self, broker):
        self.broker, self.calls = broker, []
        self.gate = None
        self.entered = asyncio.Event()
        self.lose_response = False

    async def handle_async_request(self, request):
        body = json.loads(request.content)
        action = request.url.path
        self.calls.append(action)
        self.entered.set()
        if self.gate:
            await self.gate.wait()
        try:
            if action == '/native/register':
                result = self.broker.register(body['code_hash'], body['username'], body['password'], recovery_binding=body['recovery_binding'])
            else:
                assert action == '/native/status' and 'password' not in body
                result = self.broker.inspect_native(body['code_hash'], body['username'], body['recovery_binding'])
                if result.get('rejected'):
                    raise RegistrationError(result['rejected'])
            if self.lose_response:
                self.lose_response = False
                raise httpx.ReadTimeout('synthetic response lost')
            return httpx.Response(200, json=result)
        except RegistrationError as error:
            if self.lose_response:
                self.lose_response = False
                raise httpx.ReadTimeout('synthetic rejection response lost')
            return httpx.Response(409 if error.code == 'username_unavailable' else 422 if error.code == 'password_invalid' else 503,
                                  json={'code': error.code})


@asynccontextmanager
async def enrollment_lab(tmp_path):
    async with lab(tmp_path) as (root, a, b, control, workers, oidc, _):
        url = load_gateway(root).database_url.get_secret_value()
        ops = ControlStore(url, operator=True)
        code, issued = issue(ops)
        provider = Provider()
        broker = RegistrationBroker(ControlStore(url, registration=True), tmp_path/'broker-private', issuer=ISSUER,
                                    provider_url=URL, provider_key=KEY, transport=httpx.MockTransport(provider.handle))
        wire = BrokerWire(broker)
        app = create_gateway_app(root, oidc_transport=httpx.MockTransport(oidc.handle), worker_transport=workers,
                                 registration_transport=wire)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
            try:
                yield client, app, ops, code, issued, provider, broker, wire
            finally:
                broker.close()
                ops.close()


def start(code):
    return {'operation_id': uuid.uuid4().hex, 'receipt': secrets.token_urlsafe(32), 'code': code,
            'challenge': CHALLENGE, 'state': STATE}


def proof(body):
    return {k: body[k] for k in ('operation_id', 'receipt', 'state')} | {'verifier': VERIFIER}


def account(body, **overrides):
    return {**proof(body), 'username': 'fresh_user', 'password': PASSWORD, **overrides}


def read_operation(store, body):
    with store.transaction() as db:
        return json.loads(db.scalar(select(states.c.value).where(states.c.id_hash == operation_key(body['operation_id']))))


async def test_native_real_registration_exchange_and_owner_binding_without_browser_or_password_persistence(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        first = await client.post(PREFIX+'verify', json=body)
        assert first.status_code == 200 and first.json()['status'] == 'verified'
        assert (await client.post(PREFIX+'verify', json=body)).json() == first.json()
        response = await client.post(PREFIX+'register', json=account(body))
        assert response.status_code == 200
        result = response.json()
        assert result['status'] == 'completed' and result['next_action'] == 'exchange'
        assert set(result['handoff']) == {'code', 'state'} and result['state'] == STATE
        assert result['expires_at'] == first.json()['expires_at']
        assert provider.calls == [('create', {'username', 'registration_id', 'fingerprint', 'password'})]
        assert 'set-cookie' not in response.headers and response.headers['referrer-policy'] == 'no-referrer'
        assert (await client.get('/auth/session')).status_code == 401
        exchange = await client.post('/auth/mobile/exchange', json={**result['handoff'], 'verifier': VERIFIER})
        assert exchange.status_code == 200 and exchange.json()['tenant_id'] == issued['tenant_id']
        sid = exchange.json()['access_token']
        native_session = app.state.control.session(sid)
        assert app.state.control.private_owner_scope(native_session, app.state.control.route(native_session))
        assert (await client.post('/auth/mobile/exchange', json={**result['handoff'], 'verifier': VERIFIER})).status_code == 400
        final = (await client.post(PREFIX+'status', json=proof(body))).json()
        assert final['status'] == 'completed' and final['next_action'] == 'existing_login' and 'handoff' not in final
        raw = json.dumps(read_operation(ops, body)) + ''.join(p.read_text() for p in broker.root.glob('*.json'))
        for forbidden in (PASSWORD, code, body['receipt'], VERIFIER, sid, KEY):
            assert forbidden not in raw
        assert len(wire.calls) == 1


async def test_unknown_create_response_recovers_by_status_without_password_even_after_restart(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        provider.lose_first = True
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        response = await client.post(PREFIX+'register', json=account(body))
        assert response.status_code == 202 and response.json()['status'] == 'pending'
        assert (await client.post(PREFIX+'register', json=account(body, password='Changed-Password-42'))).json()['status'] == 'pending'
        # New broker object uses only private receipts; no submitted password.
        resumed = RegistrationBroker(ControlStore(str(ops.engine.url), registration=True), broker.root, issuer=ISSUER,
                                      provider_url=URL, provider_key=KEY, transport=httpx.MockTransport(provider.handle))
        wire.broker = resumed
        try:
            response = await client.post(PREFIX+'status', json=proof(body))
            assert response.status_code == 200 and response.json()['status'] == 'completed'
            assert [call[0] for call in provider.calls] == ['create', 'inspect']
            assert wire.calls == ['/native/register', '/native/status']
        finally:
            resumed.close()


async def test_lost_broker_confirmed_response_can_be_recovered_without_recreate(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        wire.lose_response = True
        response = await client.post(PREFIX+'register', json=account(body))
        assert response.status_code == 202
        assert (await client.post(PREFIX+'status', json=proof(body))).json()['status'] == 'completed'
        assert [c[0] for c in provider.calls] == ['create']


async def test_lost_definitive_rejection_recovers_by_inspect_then_allows_new_attempt(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        provider.conflict = (409, 'username_unavailable')
        wire.lose_response = True
        assert (await client.post(PREFIX+'register', json=account(body))).status_code == 202
        rejected = (await client.post(PREFIX+'status', json=proof(body))).json()
        assert rejected['status'] == 'rejected' and rejected['code'] == 'username_unavailable'
        assert len(provider.calls) == 1
        provider.conflict = None
        complete = (await client.post(PREFIX+'register', json=account(body, username='different_user'))).json()
        assert complete['status'] == 'completed' and len(provider.calls) == 2


async def test_rejection_release_crash_is_reconciled_without_releasing_new_attempt(tmp_path, monkeypatch):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        provider.conflict = (409, 'username_unavailable')
        release = broker.invites.release_registration
        def fail_release(*args, **kwargs):
            raise OSError('synthetic storage interruption')
        monkeypatch.setattr(broker.invites, 'release_registration', fail_release)
        assert (await client.post(PREFIX+'register', json=account(body))).status_code == 202
        previous = read_operation(ops, body)
        assert broker.invites.get_registration(code_hash(code), issuer=ISSUER)
        monkeypatch.setattr(broker.invites, 'release_registration', release)
        assert (await client.post(PREFIX+'status', json=proof(body))).json()['status'] == 'rejected'
        next_id = uuid.uuid4().hex
        broker.invites.reserve_registration(code_hash(code), issuer=ISSUER, registration_id=next_id,
                                            username_hash=hashlib.sha256(b'next_user').hexdigest())
        # Re-reading the old rejected receipt must not free someone else's new
        # reservation even when release rejects its stale registration ID.
        assert broker.inspect_native(code_hash(code), previous['username'], previous['recovery_binding']) == {'rejected': 'username_unavailable'}
        assert broker.invites.get_registration(code_hash(code), issuer=ISSUER)['registration_id'] == next_id


async def test_handoff_failure_after_redemption_recovers_without_new_identity(tmp_path, monkeypatch):
    import wearing.cloud.native_enrollment as module
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        original = module.issue_handoff
        async def fail_handoff(*args, **kwargs):
            raise OSError('synthetic cache unavailable')
        monkeypatch.setattr(module, 'issue_handoff', fail_handoff)
        # ASGI test transport propagates unexpected server errors. Real gateway
        # boundary returns an opaque failure and never exposes submitted data.
        with pytest.raises(OSError):
            await client.post(PREFIX+'register', json=account(body))
        assert InvitationStore(ops).status(issued['id'])['status'] == 'redeemed'
        value = read_operation(ops, body)
        assert value['subject'] and value['status'] == 'pending'
        value['busy_until'] = 0
        with ops.transaction() as db:
            db.execute(update(states).where(states.c.id_hash == operation_key(body['operation_id'])).values(value=json.dumps(value)))
        monkeypatch.setattr(module, 'issue_handoff', original)
        result = (await client.post(PREFIX+'status', json=proof(body))).json()
        assert result['status'] == 'completed' and len(provider.calls) == 1 and len(wire.calls) == 1


async def test_definitive_username_rejection_retry_same_operation_is_bounded(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        provider.conflict = (409, 'username_unavailable')
        for attempt in range(5):
            result = (await client.post(PREFIX+'register', json=account(body))).json()
            assert result['status'] == 'rejected' and result['code'] == 'username_unavailable'
            assert result['attempts_remaining'] == 4-attempt
        assert (await client.post(PREFIX+'register', json=account(body))).status_code == 429
        assert len(provider.calls) == 5
        assert InvitationStore(ops).status(issued['id'])['status'] == 'issued'


async def test_parallel_duplicate_registration_single_create_and_pending_cancel_is_honest(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        wire.gate = asyncio.Event()
        task = asyncio.create_task(client.post(PREFIX+'register', json=account(body)))
        await wire.entered.wait()
        try:
            duplicate = await client.post(PREFIX+'register', json=account(body))
            assert duplicate.status_code == 202
            cancel = (await client.post(PREFIX+'cancel', json=proof(body))).json()
            assert cancel['status'] == 'pending' and cancel['cancel_requested']
        finally:
            wire.gate.set()
        final = (await task).json()
        assert final['status'] == 'completed' and final['next_action'] == 'existing_login' and 'handoff' not in final
        assert len(provider.calls) == 1


async def test_cancel_before_create_and_after_complete_disable_handoff_without_deleting_account(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        assert (await client.post(PREFIX+'cancel', json=proof(body))).json()['status'] == 'cancelled'
        assert (await client.post(PREFIX+'register', json=account(body))).json()['status'] == 'cancelled'
        assert wire.calls == []
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        result = (await client.post(PREFIX+'register', json=account(body))).json()
        assert (await client.post(PREFIX+'cancel', json=proof(body))).json()['status'] == 'completed'
        assert (await client.post('/auth/mobile/exchange', json={**result['handoff'], 'verifier': VERIFIER})).status_code == 400
        assert InvitationStore(ops).status(issued['id'])['status'] == 'redeemed'


async def test_foreign_origin_receipt_pkce_duplicate_json_extra_fields_and_body_limit(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        for origin in ['null', 'https://evil.example']:
            assert (await client.post(PREFIX+'verify', json=body, headers={'Origin': origin})).status_code == 400
        assert (await client.post(PREFIX+'verify?code=secret', json=body)).status_code == 400
        assert (await client.post(PREFIX+'verify', json={**body, 'tenant_id': 'tenant_B'})).status_code == 422
        assert (await client.post(PREFIX+'verify', content='{"code":"one","code":"two"}', headers={'Content-Type': 'application/json'})).status_code == 422
        assert (await client.post(PREFIX+'verify', content=b'x'*4097, headers={'Content-Type': 'application/json'})).status_code == 413
        await client.post(PREFIX+'verify', json=body)
        for wrong in [{'receipt': 'x'*43}, {'verifier': 'x'*64}, {'state': 'x'*48}]:
            assert (await client.post(PREFIX+'status', json={**proof(body), **wrong})).status_code == 404
        assert (await client.post(PREFIX+'verify', json={**body, 'challenge': 'x'*43})).status_code == 404
        assert provider.calls == []


async def test_expiry_and_rate_limits_do_not_extend_receipt_or_consume_invitation(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        key = operation_key(body['operation_id'])
        value = read_operation(ops, body)
        value['expires'] = int(time.time())-1
        with ops.transaction() as db:
            db.execute(update(states).where(states.c.id_hash == key).values(value=json.dumps(value)))
        assert (await client.post(PREFIX+'status', json=proof(body))).status_code == 410
        assert (await client.post(PREFIX+'verify', json=body)).status_code == 410
        other = start(code)
        for _ in range(60):
            response = await client.post(PREFIX+'verify', json=other)
        assert response.status_code == 200
        assert (await client.post(PREFIX+'verify', json=other)).status_code == 429
        assert InvitationStore(ops).status(issued['id'])['status'] == 'issued'


async def test_new_operation_cannot_adopt_existing_unknown_registration_same_invite_or_username(tmp_path):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        provider.lose_first = True
        assert (await client.post(PREFIX+'register', json=account(body))).status_code == 202
        thief = start(code)
        await client.post(PREFIX+'verify', json=thief)
        assert (await client.post(PREFIX+'register', json=account(thief))).status_code == 202
        assert (await client.post(PREFIX+'status', json=proof(thief))).status_code == 202
        assert [c[0] for c in provider.calls] == ['create']
        assert (await client.post(PREFIX+'status', json=proof(body))).json()['status'] == 'completed'


@pytest.mark.parametrize('failure', [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteError])
async def test_only_transport_connection_failure_permits_explicit_register_retry(tmp_path, monkeypatch, failure):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        original = wire.handle_async_request
        async def failed(request):
            raise failure('synthetic connection failure')
        monkeypatch.setattr(wire, 'handle_async_request', failed)
        response = await client.post(PREFIX+'register', json=account(body))
        known_unsent = failure in (httpx.ConnectError, httpx.ConnectTimeout)
        assert response.json()['status'] == ('verified' if known_unsent else 'pending')
        assert response.json()['attempts_remaining'] == (5 if known_unsent else 4)
        assert provider.calls == [] and InvitationStore(ops).status(issued['id'])['status'] == 'issued'
        monkeypatch.setattr(wire, 'handle_async_request', original)
        retry = await client.post(PREFIX+'register', json=account(body))
        assert retry.json()['status'] == ('completed' if known_unsent else 'pending')
        assert len(provider.calls) == (1 if known_unsent else 0)


async def test_broker_error_text_cannot_assert_request_was_not_dispatched(tmp_path, monkeypatch):
    async with enrollment_lab(tmp_path) as (client, app, ops, code, issued, provider, broker, wire):
        body = start(code)
        await client.post(PREFIX+'verify', json=body)
        async def failed(request):
            return httpx.Response(503, json={'code': 'registration_not_dispatched'})
        monkeypatch.setattr(wire, 'handle_async_request', failed)
        assert (await client.post(PREFIX+'register', json=account(body))).json()['status'] == 'pending'
