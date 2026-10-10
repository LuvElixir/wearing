import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import secrets
import time
import uuid

import pytest
from sqlalchemy import select, update

from wearing.cloud.control import ControlError, ControlStore, digest, invitations, members, ownership, tenants, users
from wearing.cloud.invitations import InvitationError, InvitationStore, code_hash, issue_to_file

ISSUER = 'https://identity.example'


@pytest.fixture
def invitation_lab(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'control.sqlite3')
    ops = ControlStore(url, initialize=True, operator=True)
    web = ControlStore(url)
    reg = ControlStore(url, registration=True)
    try:
        yield ops, web, reg
    finally:
        for store in (ops, web, reg):
            store.close()


def issue(ops, tenant=None, expires_at=None):
    tenant = tenant or 'tenant_' + uuid.uuid4().hex
    api = InvitationStore(ops)
    api.reserve_tenant(tenant)
    ops.bind(tenant, 'instance_' + tenant, 'https://worker.example', tenant + '.json')
    ident, code = uuid.uuid4().hex, 'pajio_' + secrets.token_urlsafe(32)
    row = api.issue(issuer=ISSUER, tenant_id=tenant, invitation_id=ident, code=code,
                    expires_at=expires_at or int(time.time()) + 3600)
    return code, row


def test_admission_owns_new_space_and_is_not_a_password(invitation_lab):
    ops, web, _ = invitation_lab
    code, issued = issue(ops)
    with pytest.raises(ControlError):
        web.login(ISSUER, 'alice')
    api = InvitationStore(web)
    hashed = api.check_code(code, issuer=ISSUER)
    admitted = api.redeem_hash(hashed, issuer=ISSUER, subject='alice')
    assert admitted['status'] == 'admitted'
    sid = web.login(ISSUER, 'alice')
    session = web.session(sid)
    assert session.tenant_id == issued['tenant_id']
    assert web.private_owner_scope(session, web.route(session))
    assert api.redeem_hash(hashed, issuer=ISSUER, subject='alice')['status'] == 'already_member'
    with pytest.raises(InvitationError):
        api.redeem_hash(hashed, issuer=ISSUER, subject='bob')
    assert api.check(code, issuer=ISSUER) == {'eligible': False}
    with ops.transaction() as db:
        row = db.execute(select(invitations)).mappings().one()
        assert row['code_hash'] == digest(code) and code not in str(dict(row))
        assert len(db.execute(select(members)).all()) == 1


@pytest.mark.parametrize('revoked', [False, True])
def test_expiry_and_revoke_before_redemption(invitation_lab, revoked):
    ops, web, _ = invitation_lab
    code, row = issue(ops)
    hashed = InvitationStore(web).check_code(code, issuer=ISSUER)
    if revoked:
        InvitationStore(ops).revoke(row['id'])
    else:
        with ops.transaction(mutating=True) as db:
            db.execute(update(invitations).values(created_at=1, expires_at=2))
    assert InvitationStore(web).check(code, issuer=ISSUER) == {'eligible': False}
    with pytest.raises(InvitationError):
        InvitationStore(web).redeem_hash(hashed, issuer=ISSUER, subject='alice')
    with ops.transaction() as db:
        assert not db.execute(select(users)).all()


def test_member_does_not_consume_another_invitation_and_revocation_not_resurrected(invitation_lab):
    ops, web, _ = invitation_lab
    first, one = issue(ops)
    second, two = issue(ops)
    api = InvitationStore(web)
    api.redeem_hash(code_hash(first), issuer=ISSUER, subject='alice')
    assert api.redeem_hash(code_hash(second), issuer=ISSUER, subject='alice')['status'] == 'already_member'
    assert InvitationStore(ops).status(two['id'])['status'] == 'issued'
    InvitationStore(ops).revoke(one['id'])
    assert web.session(web.login(ISSUER, 'alice'))
    ops.grant(ISSUER, 'alice', one['tenant_id'], active=False)
    with pytest.raises(InvitationError):
        api.redeem_hash(code_hash(first), issuer=ISSUER, subject='alice')


def test_existing_or_former_tenant_never_invited(invitation_lab):
    ops, _, _ = invitation_lab
    ops.grant(ISSUER, 'alice', 'tenant_A')
    ops.grant(ISSUER, 'alice', 'tenant_A', active=False)
    api = InvitationStore(ops)
    with pytest.raises(InvitationError):
        api.reserve_tenant('tenant_A')
    with pytest.raises(InvitationError):
        api.issue(issuer=ISSUER, tenant_id='tenant_A', invitation_id=uuid.uuid4().hex,
                  code='pajio_' + secrets.token_urlsafe(32), expires_at=int(time.time()) + 3600)


def test_operator_change_after_check_fails_closed(invitation_lab):
    ops, web, _ = invitation_lab
    code, row = issue(ops)
    api = InvitationStore(web)
    hashed = api.check_code(code, issuer=ISSUER)
    ops.grant(ISSUER, 'other', row['tenant_id'])
    with pytest.raises(InvitationError):
        api.redeem_hash(hashed, issuer=ISSUER, subject='alice')


def test_concurrent_subjects_have_one_winner_and_same_subject_retries(invitation_lab):
    ops, web, _ = invitation_lab
    code, _ = issue(ops)
    def attempt(subject):
        try:
            return InvitationStore(web).redeem_hash(code_hash(code), issuer=ISSUER, subject=subject)
        except InvitationError:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, ['alice', 'bob', 'carol', 'dana', 'ed', 'frank']))
    assert sum(r is not None for r in results) == 1
    next_code, _ = issue(ops)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: InvitationStore(web).redeem_hash(code_hash(next_code), issuer=ISSUER, subject='new'), range(6)))
    assert [r['status'] for r in results].count('admitted') == 1
    assert len({r['user_id'] for r in results}) == 1


def test_registration_intent_is_immutable_and_binds_only_matching_subject(invitation_lab):
    ops, web, reg = invitation_lab
    code, _ = issue(ops)
    hashed = code_hash(code)
    api = InvitationStore(reg)
    intent = uuid.uuid4().hex
    row = api.reserve_registration(hashed, issuer=ISSUER, registration_id=intent, username_hash=digest('alice'))
    assert row['registration_id'] == intent and row['subject'] is None
    assert api.reserve_registration(hashed, issuer=ISSUER, registration_id=uuid.uuid4().hex,
                                     username_hash=digest('alice')) == row
    with pytest.raises(InvitationError):
        api.reserve_registration(hashed, issuer=ISSUER, registration_id=uuid.uuid4().hex, username_hash=digest('bob'))
    with pytest.raises(InvitationError):
        InvitationStore(web).redeem_hash(hashed, issuer=ISSUER, subject='alice')
    bound = api.bind_registration_subject(hashed, issuer=ISSUER, registration_id=intent, subject='idp_alice')
    assert bound == api.get_registration(hashed, issuer=ISSUER)
    assert api.bind_registration_subject(hashed, issuer=ISSUER, registration_id=intent, subject='idp_alice') == bound
    with pytest.raises(InvitationError):
        api.bind_registration_subject(hashed, issuer=ISSUER, registration_id=intent, subject='other')
    with pytest.raises(InvitationError):
        InvitationStore(web).redeem_hash(hashed, issuer=ISSUER, subject='other')
    assert InvitationStore(web).redeem_hash(hashed, issuer=ISSUER, subject='idp_alice')['status'] == 'admitted'


def test_release_requires_exact_unbound_intent_and_late_bind_cannot_win(invitation_lab):
    ops, _, reg = invitation_lab
    code, _ = issue(ops)
    api, hashed, first, second = InvitationStore(reg), code_hash(code), uuid.uuid4().hex, uuid.uuid4().hex
    api.reserve_registration(hashed, issuer=ISSUER, registration_id=first, username_hash=digest('occupied'))
    with pytest.raises(InvitationError):
        api.release_registration(hashed, issuer=ISSUER, registration_id=second)
    assert api.release_registration(hashed, issuer=ISSUER, registration_id=first) == {'released': True}
    api.reserve_registration(hashed, issuer=ISSUER, registration_id=second, username_hash=digest('new'))
    with pytest.raises(InvitationError):
        api.bind_registration_subject(hashed, issuer=ISSUER, registration_id=first, subject='late')
    api.bind_registration_subject(hashed, issuer=ISSUER, registration_id=second, subject='new')
    with pytest.raises(InvitationError):
        api.release_registration(hashed, issuer=ISSUER, registration_id=second)


def test_web_and_registration_roles_cannot_call_operator_or_each_other(invitation_lab):
    ops, web, reg = invitation_lab
    code, row = issue(ops)
    for store in (web, reg):
        with pytest.raises(InvitationError):
            InvitationStore(store).revoke(row['id'])
    with pytest.raises(InvitationError):
        InvitationStore(web).reserve_registration(code_hash(code), issuer=ISSUER, registration_id=uuid.uuid4().hex,
                                                username_hash=digest('alice'))
    with pytest.raises(InvitationError):
        InvitationStore(reg).redeem_hash(code_hash(code), issuer=ISSUER, subject='alice')


def test_private_issue_file_is_durable_retry_without_plaintext_output(invitation_lab, tmp_path):
    ops, _, _ = invitation_lab
    api = InvitationStore(ops)
    api.reserve_tenant('new')
    ops.bind('new', 'instance_new', 'https://worker.example', 'new.json')
    folder = tmp_path / 'private'
    folder.mkdir(mode=0o700)
    output = folder / 'invite.json'
    first = issue_to_file(ops, issuer=ISSUER, tenant_id='new', output=output)
    raw = output.read_bytes()
    assert output.stat().st_mode & 0o777 == 0o600
    assert 'code' not in first and 'code_hash' not in first
    assert issue_to_file(ops, issuer=ISSUER, tenant_id='new', output=output) == first
    assert output.read_bytes() == raw
    with pytest.raises(InvitationError):
        issue_to_file(ops, issuer=ISSUER, tenant_id='another', output=output)
    assert output.read_bytes() == raw
    os.chmod(output, 0o644)
    with pytest.raises(InvitationError):
        issue_to_file(ops, issuer=ISSUER, tenant_id='new', output=output)


@pytest.mark.parametrize('code', ['', 'abc', 'pajio_' + 'x'*42, 'pajio_' + 'x'*44, None, 1])
def test_invalid_code_unified(invitation_lab, code):
    assert InvitationStore(invitation_lab[1]).check(code, issuer=ISSUER) == {'eligible': False}


def test_registration_release_races_subject_binding_under_same_lock(invitation_lab):
    ops, _, reg = invitation_lab
    code, _ = issue(ops)
    api, hashed, ident = InvitationStore(reg), code_hash(code), uuid.uuid4().hex
    api.reserve_registration(hashed, issuer=ISSUER, registration_id=ident, username_hash=digest('new'))
    def attempt(method):
        try:
            return method()
        except InvitationError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [
            lambda: api.release_registration(hashed, issuer=ISSUER, registration_id=ident),
            lambda: api.bind_registration_subject(hashed, issuer=ISSUER, registration_id=ident, subject='new')]))
    assert sum(result is not None for result in results) == 1


def test_revocation_races_redemption_without_reactivating_code(invitation_lab):
    ops, web, _ = invitation_lab
    code, row = issue(ops)
    def claim():
        try:
            return InvitationStore(web).redeem_hash(code_hash(code), issuer=ISSUER, subject='new')
        except InvitationError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        claim_job = pool.submit(claim)
        revoke_job = pool.submit(InvitationStore(ops).revoke, row['id'])
        result, revoked = claim_job.result(), revoke_job.result()
    assert revoked['revoked'] is True
    with ops.transaction() as db:
        assert bool(db.scalar(select(members.c.user_id))) == bool(result)
    assert InvitationStore(web).check(code, issuer=ISSUER) == {'eligible': False}


def test_database_failure_keeps_same_durable_operator_code(invitation_lab, tmp_path, monkeypatch):
    ops, _, _ = invitation_lab
    api = InvitationStore(ops)
    api.reserve_tenant('new')
    ops.bind('new', 'instance_new', 'https://worker.example', 'new.json')
    folder = tmp_path / 'private'
    folder.mkdir(mode=0o700)
    output = folder / 'invite.json'
    original = InvitationStore.issue
    with monkeypatch.context() as context:
        context.setattr(InvitationStore, 'issue', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('synthetic offline')))
        with pytest.raises(RuntimeError):
            issue_to_file(ops, issuer=ISSUER, tenant_id='new', output=output)
    saved = output.read_bytes()
    row = issue_to_file(ops, issuer=ISSUER, tenant_id='new', output=output)
    assert row['status'] == 'issued' and output.read_bytes() == saved


def test_account_deletion_and_transaction_failure_do_not_partially_admit(invitation_lab):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    ops, web, _ = invitation_lab
    code, _ = issue(ops)
    with ops.transaction(mutating=True) as db:
        db.execute(text("CREATE TRIGGER synthetic_failure BEFORE INSERT ON wearing_tenant_ownership BEGIN SELECT RAISE(ABORT,'synthetic'); END"))
    with pytest.raises(DBAPIError):
        InvitationStore(web).redeem_hash(code_hash(code), issuer=ISSUER, subject='new')
    with ops.transaction() as db:
        assert not db.execute(select(users)).all()
        assert not db.execute(select(members)).all()
        assert db.scalar(select(invitations.c.redeemed_at)) is None
