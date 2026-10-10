"""Real PostgreSQL invitation/registration privilege and concurrency acceptance."""
from concurrent.futures import ThreadPoolExecutor
import secrets
import time
import uuid

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from test_control_postgres import pg
from wearing.cloud.control import ControlStore, digest, invitations, members, ownership, users
from wearing.cloud.invitations import InvitationStore, InvitationError, code_hash
from wearing.cloud.postgres import DatabaseBoundaryError


def fresh(pg):
    ops = InvitationStore(pg['operator_store'])
    tenant = 'invite_' + uuid.uuid4().hex
    ops.reserve_tenant(tenant)
    pg['operator_store'].bind(tenant, 'instance_' + tenant, 'https://worker.example', tenant + '.json')
    code, ident = 'pajio_' + secrets.token_urlsafe(32), uuid.uuid4().hex
    ops.issue(issuer=pg['issuer'], tenant_id=tenant, invitation_id=ident, code=code, expires_at=int(time.time())+3600)
    return code, ident, tenant


def test_pg_check_redemption_private_owner_and_no_direct_web_dml(pg):
    code, ident, tenant = fresh(pg)
    api = InvitationStore(pg['web'])
    hashed = api.check_code(code, issuer=pg['issuer'])
    with pg['web'].transaction(issuer=pg['issuer'], subject='new') as db:
        assert db.execute(select(invitations)).all() == []
    result = api.redeem_hash(hashed, issuer=pg['issuer'], subject='new')
    assert result['tenant_id'] == tenant and result['status'] == 'admitted'
    session = pg['web'].session(pg['web'].login(pg['issuer'], 'new'))
    assert pg['web'].private_owner_scope(session, pg['web'].route(session))
    assert api.redeem_hash(hashed, issuer=pg['issuer'], subject='new')['status'] == 'already_member'
    for statement in ["UPDATE wearing_control.wearing_invitations SET revoked_at=1",
                      "INSERT INTO wearing_control.wearing_users(id,issuer,subject) VALUES('bad','bad','bad')",
                      "INSERT INTO wearing_control.wearing_memberships VALUES('bad','bad',true)"]:
        with pytest.raises(DBAPIError):
            with pg['web'].transaction() as db:
                db.execute(text(statement))
    with pytest.raises(InvitationError):
        api.redeem_hash(hashed, issuer=pg['issuer'], subject='intruder')


def test_pg_redemption_concurrency_revocation_and_no_frozen_resurrection(pg):
    code, ident, tenant = fresh(pg)
    api, ops = InvitationStore(pg['web']), pg['operator_store']
    def claim(i):
        try:
            return api.redeem_hash(code_hash(code), issuer=pg['issuer'], subject=f'new_{i}')
        except InvitationError:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(claim, range(6)))
    assert sum(r is not None for r in results) == 1
    winner = next(r for r in results if r)
    with ops.transaction() as db:
        subject = db.scalar(select(users.c.subject).where(users.c.id == winner['user_id']))
    ops.grant(pg['issuer'], subject, tenant, active=False)
    with pytest.raises(InvitationError):
        api.redeem_hash(code_hash(code), issuer=pg['issuer'], subject=subject)
    code2, ident2, _ = fresh(pg)
    InvitationStore(ops).revoke(ident2)
    with pytest.raises(InvitationError):
        api.redeem_hash(code_hash(code2), issuer=pg['issuer'], subject='second')


def test_pg_registration_has_only_fixed_functions_not_web_or_operator_permissions(pg):
    if 'registration' not in pg:
        pytest.skip('QA role must include the separate registration login')
    reg = ControlStore(pg['registration'], registration=True)
    try:
        api = InvitationStore(reg)
        code, _, _ = fresh(pg)
        hashed, intent = code_hash(code), uuid.uuid4().hex
        assert api.check_code(code, issuer=pg['issuer']) == hashed
        row = api.reserve_registration(hashed, issuer=pg['issuer'], registration_id=intent, username_hash=digest('new'))
        assert api.reserve_registration(hashed, issuer=pg['issuer'], registration_id=uuid.uuid4().hex,
                                          username_hash=digest('new')) == row
        with pytest.raises(InvitationError):
            InvitationStore(pg['web']).redeem_hash(hashed, issuer=pg['issuer'], subject='new')
        with pytest.raises(InvitationError):
            api.release_registration(hashed, issuer=pg['issuer'], registration_id=uuid.uuid4().hex)
        assert api.release_registration(hashed, issuer=pg['issuer'], registration_id=intent) == {'released': True}
        next_intent = uuid.uuid4().hex
        api.reserve_registration(hashed, issuer=pg['issuer'], registration_id=next_intent, username_hash=digest('available'))
        with pytest.raises(InvitationError):
            api.bind_registration_subject(hashed, issuer=pg['issuer'], registration_id=intent, subject='late')
        bound = api.bind_registration_subject(hashed, issuer=pg['issuer'], registration_id=next_intent, subject='new')
        assert bound == api.get_registration(hashed, issuer=pg['issuer'])
        with pytest.raises(InvitationError):
            api.release_registration(hashed, issuer=pg['issuer'], registration_id=next_intent)
        for statement in ['SELECT * FROM wearing_control.wearing_users', 'SELECT * FROM wearing_control.wearing_invitations',
                          "SELECT wearing_control.invitation_redeem('"+'a'*64+"','issuer','subject')",
                          "SET ROLE wearing_web", "SET ROLE wearing_operator", "SET ROLE inv_owner"]:
            with pytest.raises(DBAPIError):
                with reg.transaction() as db:
                    db.execute(text(statement))
        with pytest.raises(DBAPIError):
            with pg['web'].transaction() as db:
                db.execute(text("SELECT wearing_control.invitation_get_registration(:h,:i)"), {'h': hashed,'i':pg['issuer']})
        assert InvitationStore(pg['web']).redeem_hash(hashed, issuer=pg['issuer'], subject='new')['status']=='admitted'
        for kwargs in ({}, {'operator':True}):
            with pytest.raises(DatabaseBoundaryError):
                ControlStore(pg['registration'], **kwargs)
    finally:
        reg.close()


def test_pg_function_scope_and_startup_body_public_grant_guard(pg):
    code, _, _ = fresh(pg)
    with pg['web'].transaction() as db:
        assert db.scalar(text('SELECT wearing_control.invitation_check(:h,:i)'), {'h':code_hash(code),'i':pg['issuer']}) is None
    admin = pg['admin_engine']
    signature='wearing_control.invitation_check(text,text)'
    try:
        with admin.begin() as db:
            db.execute(text(f'GRANT EXECUTE ON FUNCTION {signature} TO PUBLIC'))
        with pytest.raises(DatabaseBoundaryError):
            ControlStore(pg['app'])
    finally:
        with admin.begin() as db:
            db.execute(text(f'REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC'))
    good=ControlStore(pg['app']);good.close()


def test_pg_redeem_fails_when_issuer_context_is_unset_even_with_code(pg):
    code, _, _ = fresh(pg)
    # A brand-new connection never received scoped()/set_config().
    from sqlalchemy import create_engine
    engine = create_engine(pg['app'], hide_parameters=True)
    try:
        with engine.begin() as db:
            assert db.scalar(text('SELECT wearing_control.invitation_check(:h,:i)'),
                             {'h':code_hash(code),'i':pg['issuer']}) is None
    finally:
        engine.dispose()


def test_pg_registration_concurrent_different_names_and_bind_release_race(pg):
    if 'registration' not in pg:
        pytest.skip('QA role must include the separate registration login')
    reg = ControlStore(pg['registration'], registration=True)
    try:
        code, _, _ = fresh(pg)
        api, hashed = InvitationStore(reg), code_hash(code)
        def reserve(name):
            try:
                return api.reserve_registration(hashed, issuer=pg['issuer'], registration_id=uuid.uuid4().hex,
                                                username_hash=digest(name))
            except InvitationError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            attempts=list(pool.map(reserve,['one','two','three','four']))
        assert sum(x is not None for x in attempts)==1
        winner=next(x for x in attempts if x)
        def call(fn):
            try:return fn()
            except InvitationError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(call,[
                lambda:api.release_registration(hashed,issuer=pg['issuer'],registration_id=winner['registration_id']),
                lambda:api.bind_registration_subject(hashed,issuer=pg['issuer'],registration_id=winner['registration_id'],subject='new')]))
        assert sum(x is not None for x in results)==1
    finally:
        reg.close()


def test_pg_registration_table_grant_and_runtime_membership_broadening_refused(pg):
    if 'registration' not in pg:
        pytest.skip('QA role must include the separate registration login')
    admin=pg['admin_engine']
    try:
        with admin.begin() as db:
            db.execute(text('GRANT SELECT ON wearing_control.wearing_invitations TO wearing_registration'))
        with pytest.raises(DatabaseBoundaryError):
            ControlStore(pg['registration'],registration=True)
    finally:
        with admin.begin() as db:
            db.execute(text('REVOKE SELECT ON wearing_control.wearing_invitations FROM wearing_registration'))
    try:
        with admin.begin() as db:
            db.execute(text('GRANT wearing_registration TO wearing_web'))
        with pytest.raises(DatabaseBoundaryError):
            ControlStore(pg['app'])
    finally:
        with admin.begin() as db:
            db.execute(text('REVOKE wearing_registration FROM wearing_web'))


def test_pg_wrong_scope_cannot_redeem_even_when_code_exists(pg):
    code,_,_=fresh(pg)
    with pg['web'].transaction(issuer=pg['issuer'],subject='other') as db:
        assert db.scalar(text('SELECT wearing_control.invitation_redeem(:h,:i,:s)'),
            {'h':code_hash(code),'i':pg['issuer'],'s':'new'}) is None
    assert InvitationStore(pg['web']).check_code(code,issuer=pg['issuer']) == code_hash(code)
