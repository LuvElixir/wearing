"""Isolated cloud fixtures: no real account, engine, or user data."""
import re

import httpx
import pytest

from wearing.cloud.mobile_auth import session_storage_scope
from wearing.cloud.worker import TenantBoundary
from test_gateway import ISSUER, ORIGIN, lab
from test_mobile_gateway import authorize


async def test_bootstrap_storage_namespace_is_verified_account_and_tenant_bound(tmp_path):
    async with lab(tmp_path) as (_, _, _, control, workers, provider, app):
        control.grant(ISSUER, 'bob', 'tenant_A')
        control.grant(ISSUER, 'alice', 'tenant_B')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            async def native(subject):
                body = await authorize(client, provider, subject)
                return (await client.post('/auth/mobile/exchange', json=body)).json()

            first = await native('alice')
            auth = {'Authorization': 'Bearer ' + first['access_token'], 'X-Pajio-Expected-Tenant': 'tenant_A'}
            spoof = [('X-Pajio-Storage-Scope', 'f' * 64), ('X-Pajio-Storage-Scope', 'e' * 64)]
            response = await client.get('/api/bootstrap?storage_scope=' + 'd' * 64,
                                        headers=[*auth.items(), *spoof])
            assert response.status_code == 200
            scope_a = response.json()['storage_scope']
            assert re.fullmatch('[a-f0-9]{64}', scope_a)
            assert scope_a == session_storage_scope(first['user_id'], first['tenant_id'])
            assert scope_a not in {'f' * 64, 'e' * 64, 'd' * 64}
            forwarded = workers.requests[-1].headers
            assert forwarded.get_list('x-pajio-storage-scope') == [scope_a]
            assert first['access_token'] not in response.text
            assert first['user_id'] not in response.text

            # A native root document establishes an HttpOnly cookie. Its later
            # bootstrap keeps the same scope without exposing bearer tokens.
            assert (await client.get('/', headers=auth)).status_code == 200
            assert (await client.get('/api/bootstrap')).json()['storage_scope'] == scope_a

            assert (await client.post('/auth/logout', headers=auth)).status_code == 200
            assert (await client.get('/api/bootstrap', headers=auth)).status_code == 401
            again = await native('alice')
            again_auth = {'Authorization': 'Bearer ' + again['access_token']}
            assert again['access_token'] != first['access_token']
            assert (await client.get('/api/bootstrap', headers=again_auth)).json()['storage_scope'] == scope_a

            # Membership in the same tenant must not merge personal drafts.
            bob = await native('bob')
            assert bob['tenant_id'] == 'tenant_A'
            scope_bob = (await client.get('/api/bootstrap', headers={'Authorization': 'Bearer ' + bob['access_token']})).json()['storage_scope']
            assert scope_bob != scope_a
            assert scope_bob == session_storage_scope(bob['user_id'], 'tenant_A')

            # Operator-side drift is rejected by the old native expectation;
            # a separately selected tenant gets a distinct trusted namespace.
            control.switch(again['access_token'], 'tenant_B')
            assert (await client.get('/api/bootstrap', headers={**again_auth, 'X-Pajio-Expected-Tenant': 'tenant_A'})).status_code == 401
            changed = await client.get('/api/bootstrap', headers={**again_auth, 'X-Pajio-Expected-Tenant': 'tenant_B'})
            assert changed.status_code == 200
            assert changed.json()['storage_scope'] == session_storage_scope(again['user_id'], 'tenant_B')
            assert changed.json()['storage_scope'] not in {scope_a, scope_bob}


@pytest.mark.parametrize('kind', ['http', 'websocket'])
async def test_worker_storage_scope_is_validated_only_after_internal_auth_and_stripped(kind):
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope)

    gate = TenantBoundary(inner, 'tenant_A', 'k' * 64)
    credentials = [(b'authorization', b'Bearer ' + b'k' * 64), (b'x-wearing-tenant', b'tenant_A')]
    path = '/api/voice/stream' if kind == 'websocket' else '/api/bootstrap'
    for values, allowed in [([], True), ([b'a' * 64], True), ([b'a' * 63], False),
                            ([b'A' * 64], False), ([b'z' * 64], False),
                            ([b'a' * 64, b'a' * 64], False), ([b'\xff' * 64], False)]:
        seen.clear()
        sent = []

        async def send(value):
            sent.append(value)

        await gate({'type': kind, 'path': path, 'method': 'GET', 'headers': credentials + [
            (b'x-pajio-storage-scope', value) for value in values]}, None, send)
        assert bool(seen) == allowed
        if allowed:
            assert seen[0]['headers'] == []
            assert seen[0].get('pajio.storage_scope') == ('a' * 64 if values else None)
        elif kind == 'websocket':
            assert sent == [{'type': 'websocket.close', 'code': 1008}]
        else:
            assert sent[0]['status'] == 401

    seen.clear()
    sent = []
    await gate({'type': kind, 'path': path, 'method': 'GET', 'headers': [
        (b'x-pajio-storage-scope', b'a' * 64)]}, None, send)
    assert not seen


async def test_private_worker_without_account_scope_keeps_read_access_but_no_namespace(tmp_path):
    async with lab(tmp_path) as (_, a, _, _, workers, _, _):
        # Existing private preview forwarding deliberately has no OIDC account.
        async with httpx.AsyncClient(transport=workers.apps[39001], base_url=ORIGIN) as client:
            headers = {'Authorization': 'Bearer ' + (a / 'gateway.key').read_text().strip(),
                       'X-Wearing-Tenant': 'tenant_A'}
            response = await client.get('/api/bootstrap', headers=headers)
            assert response.status_code == 200
            assert response.json()['storage_scope'] is None
            assert (await client.get('/api/bootstrap', headers={'X-Pajio-Storage-Scope': 'a' * 64})).status_code == 401
