"""Native enrollment against the explicit disposable QA PostgreSQL roles."""
from types import SimpleNamespace

import httpx
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from starlette.applications import Starlette
import pytest

from test_control_postgres import pg
from test_invitations_postgres import fresh
from test_native_enrollment import start, proof, account, BrokerWire
from test_registration import Provider, KEY, URL
from wearing.cloud.control import ControlStore, OIDCStateCache, states
from wearing.cloud.mobile_auth import exchange_handoff
from wearing.cloud.native_enrollment import NativeEnrollment, PREFIX, operation_key
from wearing.cloud.registration import RegistrationBroker, RegistrationClient


async def test_pg_native_states_scoped_insert_delete_recovery_and_real_invitation_membership(pg, tmp_path):
    if 'registration' not in pg:
        pytest.skip('QA role must include the separate registration login')
    code, _, tenant = fresh(pg)
    provider = Provider(lose_first=True)
    broker = RegistrationBroker(ControlStore(pg['registration'], registration=True), tmp_path/'private-broker',
                                issuer=pg['issuer'], provider_url=URL, provider_key=KEY,
                                transport=httpx.MockTransport(provider.handle))
    origin = 'https://native-qa.example'
    web, cache = pg['web'], OIDCStateCache(pg['web'])
    enrollment = NativeEnrollment(SimpleNamespace(issuer=pg['issuer'], public_origin=origin, session_key=SecretStr('s'*64)),
                                  web, cache, RegistrationClient(transport=BrokerWire(broker)))
    app = Starlette(routes=enrollment.routes())
    body = start(code)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=origin) as client:
            assert (await client.post(PREFIX+'verify', json=body)).json()['status'] == 'verified'
            assert (await client.post(PREFIX+'register', json=account(body))).json()['status'] == 'pending'
            with web.transaction() as db:
                assert db.execute(select(states).where(states.c.id_hash == operation_key(body['operation_id']))).all() == []
            with pytest.raises(DBAPIError):
                with web.transaction(mutating=True, state_hash=operation_key(body['operation_id'])) as db:
                    db.execute(update(states).where(states.c.id_hash == operation_key(body['operation_id'])).values(expires=1))
            completed = (await client.post(PREFIX+'status', json=proof(body))).json()
            assert completed['status'] == 'completed'
            handoff = completed['handoff']
            wrong = await exchange_handoff(cache, {**handoff, 'verifier': 'x'*64})
            assert wrong is None
            result = await exchange_handoff(cache, {**handoff, 'verifier': proof(body)['verifier']})
            assert result['tenant_id'] == tenant and result['enrollment_operation'] == body['operation_id']
            enrollment.consume_handoff(body['operation_id'], handoff['code'])
            session_id = web.login(pg['issuer'], result['subject'])
            web.switch(session_id, tenant)
            session = web.session(session_id)
            assert web.private_owner_scope(session, web.route(session))
            assert [call[0] for call in provider.calls] == ['create', 'inspect']
            assert (await client.post(PREFIX+'status', json=proof(body))).json()['next_action'] == 'existing_login'
    finally:
        broker.close()
