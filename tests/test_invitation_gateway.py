import base64
import hashlib
from html import unescape
import json
import re
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select, update

from test_gateway import lab, login, ORIGIN, ISSUER
from test_invitations import issue
from wearing.cloud.control import ControlStore, invitations, states
from wearing.cloud.gateway import create_gateway_app, load_gateway
from wearing.cloud.invitations import InvitationStore
from wearing.cloud.mobile_auth import CALLBACK
from wearing.cloud.join import native_ready


def ticket(response):
    assert response.status_code in (200, 422, 503)
    return re.search(r'name="ticket" value="([A-Za-z0-9_-]{43})"', response.text)[1]


def operator(root):
    return ControlStore(load_gateway(root).database_url.get_secret_value(), operator=True)


async def post(client, path, previous, **fields):
    return await client.post(path, data={'ticket': ticket(previous), **fields}, headers={'Origin': ORIGIN})


async def test_invited_oidc_creates_private_membership_without_secrets_in_cookie(tmp_path):
    async with lab(tmp_path) as (root, _, _, _, _, provider, app):
        ops = operator(root)
        code, issued = issue(ops)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
            assert (await client.get('/')).headers['location'] == '/join'
            first = await client.get('/join')
            assert '服务器地址' not in first.text and 'token' not in first.text
            assert first.headers['referrer-policy'] == 'same-origin'
            assert "form-action 'self'" in first.headers['content-security-policy']
            account = await post(client, '/join/check', first, code=code)
            assert '创建你的账号' in account.text
            redirect = await post(client, '/join/login', account)
            assert redirect.status_code == 302
            cookie = client.cookies.get('__Host-wearing-session')
            assert code not in cookie and hashlib.sha256(code.encode()).hexdigest() not in base64.b64decode(cookie.split('.')[0]).decode()
            assert code not in redirect.headers['location']
            params = provider.authorize(redirect.headers['location'], 'new-user')
            assert (await client.get('/auth/callback', params=params)).status_code == 303
            assert (await client.get('/auth/session')).json()['tenant_id'] == issued['tenant_id']
            assert InvitationStore(ops).status(issued['id'])['status'] == 'redeemed'
            assert (await post(client, '/join/login', account)).status_code == 400
        ops.close()


async def test_foreign_origin_stolen_ticket_duplicates_and_body_limit(tmp_path):
    async with lab(tmp_path) as (root, *_, app):
        ops = operator(root)
        code, issued = issue(ops)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as a, httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as b:
            form = await a.get('/join')
            await b.get('/join')
            raw = {'ticket': ticket(form), 'code': code}
            assert (await a.post('/join/check', data=raw, headers={'Origin': 'https://evil.example'})).status_code == 400
            assert (await a.post('/join/check', data=raw, headers={'Origin': 'null'})).status_code == 400
            assert (await a.post('/join/check', data=raw)).status_code == 400
            assert (await b.post('/join/check', data=raw, headers={'Origin': ORIGIN})).status_code == 400
            fresh = await a.get('/join')
            assert (await post(a, '/join/check', fresh, code=code)).status_code == 200
            assert (await post(a, '/join/check', fresh, code=code)).status_code == 400
            assert (await a.post('/join/check', content=b'x' * 8193, headers={'Origin': ORIGIN,'Content-Type':'application/x-www-form-urlencoded'})).status_code == 413
            fresh = await a.get('/join')
            assert (await a.post('/join/check', content='ticket='+ticket(fresh)+'&code=x&code=y', headers={'Origin': ORIGIN,'Content-Type':'application/x-www-form-urlencoded'})).status_code == 400
            assert InvitationStore(ops).status(issued['id'])['status'] == 'issued'
        ops.close()


async def test_expired_code_recheck_and_existing_member_does_not_consume(tmp_path):
    async with lab(tmp_path) as (root, _, _, _, _, provider, app):
        ops = operator(root)
        code, issued = issue(ops)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
            form = await post(client, '/join/check', await client.get('/join'), code=code)
            redirect = await post(client, '/join/login', form)
            params = provider.authorize(redirect.headers['location'], 'alice')
            assert (await client.get('/auth/callback', params=params)).status_code == 303
            assert InvitationStore(ops).status(issued['id'])['status'] == 'issued'
            assert (await client.get('/join')).headers['location'] == '/'
            client.cookies.clear()
            form = await post(client, '/join/check', await client.get('/join'), code=code)
            InvitationStore(ops).revoke(issued['id'])
            redirect = await post(client, '/join/login', form)
            params = provider.authorize(redirect.headers['location'], 'new-user')
            assert (await client.get('/auth/callback', params=params)).status_code == 403
        ops.close()


async def test_mobile_join_preserves_pkce_and_existing_login_without_code(tmp_path):
    async with lab(tmp_path) as (root, _, _, _, _, provider, app):
        ops = operator(root)
        code, issued = issue(ops)
        verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
            form = await client.get('/auth/mobile/start', params={'entry':'invite', 'state':state, 'challenge':challenge})
            form = await post(client, '/join/check', form, code=code)
            redirect = await post(client, '/join/login', form)
            params = provider.authorize(redirect.headers['location'], 'mobile-new')
            handoff = await client.get('/auth/callback', params=params)
            url = urlparse(handoff.headers['location'])
            assert url.scheme == 'pajio' and url.netloc == 'auth'
            proof = {k:v[0] for k,v in parse_qs(url.query).items()}
            assert (await client.post('/auth/mobile/exchange', json={**proof,'verifier':secrets.token_urlsafe(48)})).status_code == 400
            session = await client.post('/auth/mobile/exchange', json={**proof,'verifier':verifier})
            assert session.status_code == 200 and session.json()['tenant_id'] == issued['tenant_id']
            assert (await client.post('/auth/mobile/exchange', json={**proof,'verifier':verifier})).status_code == 400
            form = await client.get('/auth/mobile/start', params={'entry':'invite', 'state':state,'challenge':challenge})
            redirect = await post(client, '/join/existing', form)
            params = provider.authorize(redirect.headers['location'], 'alice')
            response = await client.get('/auth/callback', params=params)
            assert response.headers['location'].startswith('pajio://auth?')
        ops.close()


async def test_mobile_signup_completes_on_same_origin_with_fixed_callback_and_exchanges_once(tmp_path):
    async with lab(tmp_path) as (root, _, _, _, workers, provider, _):
        ops = operator(root)
        code, issued = issue(ops)
        verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        app = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=workers,
            registration_transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'subject': 'mobile-registered-user'})))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
            form = await client.get('/auth/mobile/start', params={'entry': 'invite', 'state': state,
                'challenge': challenge, 'redirect_uri': 'pajio://untrusted'})
            assert form.headers['referrer-policy'] == 'same-origin'
            form = await post(client, '/join/check', form, code=code)
            assert form.headers['referrer-policy'] == 'same-origin'
            directives = {parts[0]: parts[1:] for item in form.headers['content-security-policy'].split(';')
                          if (parts := item.strip().split())}
            issuer = urlparse(ISSUER)
            assert directives['form-action'] == ["'self'", issuer.scheme + '://' + issuer.netloc]
            assert CALLBACK == 'pajio://auth'
            assert 'pajio:' not in directives['form-action'] and '*' not in directives['form-action']
            result = await post(client, '/join/create', form, username='testuser', password='synthetic-password-42')
            assert result.status_code == 200 and 'location' not in result.headers
            assert '账号已准备好' in result.text and '返回 Pajio' in result.text
            assert 'no-store' in result.headers['cache-control'] and result.headers['referrer-policy'] == 'no-referrer'
            assert '<script' not in result.text and '<form' not in result.text
            links = re.findall(r'href="([^"]+)"', result.text)
            assert len(links) == 1
            callback = urlparse(unescape(links[0]))
            assert callback.scheme + '://' + callback.netloc == CALLBACK and callback.path == ''
            proof = {k: v[0] for k, v in parse_qs(callback.query).items()}
            assert set(proof) == {'code', 'state'} and proof['state'] == state
            assert (await client.post('/auth/mobile/exchange', json={**proof, 'verifier': secrets.token_urlsafe(48)})).status_code == 400
            exchange = await client.post('/auth/mobile/exchange', json={**proof, 'verifier': verifier})
            assert exchange.status_code == 200 and exchange.json()['tenant_id'] == issued['tenant_id']
            assert (await client.post('/auth/mobile/exchange', json={**proof, 'verifier': verifier})).status_code == 400
        ops.close()


@pytest.mark.parametrize('target', [
    'https://evil.invalid/auth?code=' + 'a' * 43 + '&state=' + 'b' * 32,
    'pajio://untrusted?code=' + 'a' * 43 + '&state=' + 'b' * 32,
    'pajio://auth/extra?code=' + 'a' * 43 + '&state=' + 'b' * 32,
    'pajio://auth?code=' + 'a' * 43 + '&state=' + 'b' * 32 + '&other=1',
    'pajio://auth?code=' + 'a' * 43 + '&state=' + 'b' * 32 + '#extra',
    'pajio://auth?code=' + 'a' * 43 + '&state=short',
    'pajio://auth?code=' + 'a' * 43 + '&code=' + 'b' * 43,
])
def test_native_completion_rejects_nonfixed_or_malformed_targets(target):
    with pytest.raises(ValueError):
        native_ready(target)


async def test_real_form_signup_consumes_only_broker_bound_identity(tmp_path):
    async with lab(tmp_path) as (root, _, _, _, workers, provider, _):
        ops = operator(root)
        code, issued = issue(ops)
        calls = []
        def broker(request):
            data = json.loads(request.content)
            calls.append(data)
            assert data == {'code_hash':hashlib.sha256(code.encode()).hexdigest(),'username':'testuser','password':'a-long-passphrase'}
            return httpx.Response(200, json={'subject':'registered-user'})
        app = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle),worker_transport=workers,registration_transport=httpx.MockTransport(broker))
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
            form = await post(client, '/join/check', await client.get('/join'), code=code)
            bad = await post(client, '/join/create', form, username='testuser',password='short')
            assert bad.status_code == 422 and not calls
            result = await post(client, '/join/create', bad, username='testuser',password='a-long-passphrase')
            assert result.status_code == 303 and result.headers['location'] == '/'
            assert (await client.get('/auth/session')).json()['tenant_id'] == issued['tenant_id']
            with ops.transaction() as db:
                assert 'a-long-passphrase' not in str(db.execute(select(states)).all())
            assert (await post(client, '/join/create', bad, username='testuser',password='a-long-passphrase')).status_code == 400
            assert len(calls) == 1
        ops.close()


async def test_registration_unavailable_preserves_code_and_never_echoes_password(tmp_path):
    async with lab(tmp_path) as (root, *_, app):
        ops=operator(root)
        code, issued=issue(ops)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url=ORIGIN) as client:
            form = await post(client,'/join/check',await client.get('/join'),code=code)
            failure = await post(client,'/join/create',form,username='testuser',password='secret-password-123')
            assert failure.status_code == 503 and 'secret-password-123' not in failure.text
            assert InvitationStore(ops).status(issued['id'])['status'] == 'issued'
            assert (await client.get('/auth/session')).status_code == 401
        ops.close()


async def test_join_get_limit_bounds_state_creation(tmp_path):
    async with lab(tmp_path) as (root, *_, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url=ORIGIN) as client:
            for _ in range(24):
                assert (await client.get('/join')).status_code == 200
            assert (await client.get('/join')).status_code == 429
            assert (await client.get('/join')).status_code == 429
