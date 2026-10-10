"""SQLite dev parity and authenticated progress endpoint isolation."""
from types import SimpleNamespace
import time

import httpx
import pytest
from sqlalchemy import update

from test_bundle_activation_db import sqlite_bundle, issue_bundle
from test_gateway import lab, login, ORIGIN, ISSUER
from test_invitation_gateway import operator, post
from wearing.cloud.bundle_activation import ActivationError, ActivationStore, public_progress
from wearing.cloud.control import members, ownership, routes, bundle_activations
from wearing.cloud.invitations import InvitationStore, code_hash


def admitted(stores):
    ops, web, activation = stores
    code, _, _, _, _ = issue_bundle(ops, ISSUER)
    InvitationStore(web).redeem_hash(code_hash(code), issuer=ISSUER, subject='activation-fixture')
    current = web.session(web.login(ISSUER, 'activation-fixture'))
    return ActivationStore(activation), current


def test_expired_generation_cannot_renew_release_or_publish(sqlite_bundle):
    api, current = admitted(sqlite_bundle)
    now = [int(time.time())]
    api.clock = lambda: now[0]
    one = api.claim('a' * 32, 30)
    assert api.claim('b' * 32) is None
    now[0] += 31
    two = api.claim('b' * 32)
    assert two['generation'] == one['generation'] + 1
    assert api.heartbeat(one['id'], 'a' * 32, one['generation']) is None
    assert api.release(one['id'], 'a' * 32, one['generation']) is None
    assert api.update(one['id'], 'a' * 32, one['generation'], state='ready', step='complete',
        receipt_sha256='c' * 64, reason=None, members={k: {'state': 'ready'} for k in ('core','linux','android')}) is None
    assert api.status(current)['state'] == 'reserved'


@pytest.mark.parametrize('change', ['member', 'owner', 'route'])
def test_fresh_ownership_fences_existing_and_new_leases(sqlite_bundle, change):
    api, current = admitted(sqlite_bundle)
    event = api.claim('a' * 32)
    with sqlite_bundle[0].transaction(mutating=True) as db:
        if change == 'member': db.execute(update(members).where(members.c.user_id == current.user_id).values(active=False))
        if change == 'owner': db.execute(update(ownership).where(ownership.c.tenant_id == current.tenant_id).values(revision=2))
        if change == 'route': db.execute(update(routes).where(routes.c.tenant_id == current.tenant_id).values(instance_id='other'))
    assert api.heartbeat(event['id'], 'a' * 32, event['generation']) is None
    assert api.release(event['id'], 'a' * 32, event['generation']) is None
    api.clock = lambda: time.time()+1000
    assert api.claim('b' * 32) is None
    with pytest.raises(ActivationError): api.status(current)


def test_status_is_owner_scoped_and_terminal_progress_cannot_regress(sqlite_bundle):
    api, current = admitted(sqlite_bundle)
    with pytest.raises(ActivationError): api.status(SimpleNamespace(user_id='other', tenant_id=current.tenant_id))
    event = api.claim('a' * 32)
    args=(event['id'], 'a' * 32, event['generation'])
    def save(state):
        return api.update(*args, state=state, step='pairing', receipt_sha256='c'*64, reason=None,
            members={k: {'state': 'ready' if state=='ready' else 'preparing'} for k in ('core','linux','android')})
    assert save('pairing')
    assert save('preparing') is None
    assert save('ready')
    assert save('pairing') is None
    assert api.status(current)['state']=='ready'
    assert api.release(*args)
    assert api.claim('b'*32) is None


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1])
def test_nonfinite_progress_timestamp_is_rejected(value):
    with pytest.raises(ActivationError):
        public_progress({'state':'reserved', 'members':{k:{'state':'pending'} for k in ('core','linux','android')},'updated_at':value})


async def test_gateway_requires_session_and_returns_only_own_progress(tmp_path):
    async with lab(tmp_path) as (root, _, _, _, _, provider, app):
        ops = operator(root)
        code, _, _, _, _ = issue_bundle(ops, ISSUER)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
            assert (await client.get('/auth/provisioning')).status_code == 401
            form = await post(client, '/join/check', await client.get('/join'), code=code)
            redirect = await post(client, '/join/login', form)
            params = provider.authorize(redirect.headers['location'], 'new-activation-user')
            assert (await client.get('/auth/callback', params=params)).status_code == 303
            result = await client.get('/auth/provisioning')
            assert result.status_code == 200
            assert result.json()['state'] == 'reserved'
            assert set(result.json()) == {'state','members','updated_at','reason','retry_after'}
            assert 'no-store' in result.headers['cache-control']
            session = (await client.get('/auth/session')).json()
            with ops.transaction(mutating=True) as db:
                db.execute(update(ownership).where(ownership.c.tenant_id == session['tenant_id']).values(revision=2))
            assert (await client.get('/auth/provisioning')).status_code == 404
        ops.close()
