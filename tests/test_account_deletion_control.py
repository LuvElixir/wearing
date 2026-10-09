"""Deletion admission/freeze on synthetic accounts only; no external adapters."""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, update

from wearing.account_deletion import DeletionError
from wearing.cloud.account_deletion_control import AccountDeletionControl
from wearing.cloud.control import ControlError, ControlStore, deletion_requests, members, ownership, sessions, tenants, users


@pytest.fixture
def controls(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'control.sqlite3')
    operator = ControlStore(url, initialize=True, operator=True)
    web = ControlStore(url)
    for user, tenant in [('alice','private_a'),('bob','private_b'),('alice','shared'),('bob','shared')]:
        operator.grant('synthetic', user, tenant)
    for tenant in ['private_a','private_b','shared']:
        operator.bind(tenant, 'instance_' + tenant, 'https://fixture.invalid', tenant + '.json')
    a_sid, b_sid = web.login('synthetic','alice', auth_time=int(time.time())), web.login('synthetic','bob')
    a, b = web.session(a_sid), web.session(b_sid)
    ops, public = AccountDeletionControl(operator), AccountDeletionControl(web)
    ops.register('private_a','private',owner_user_id=a.user_id)
    ops.register('private_b','private',owner_user_id=b.user_id)
    ops.register('shared','shared',owner_user_id=b.user_id)
    try: yield operator, web, ops, public, a_sid, b_sid, a, b
    finally: operator.close(); web.close()


def request(public, a):
    plan = public.preview(a)
    assert plan['ready']
    return public.request(a, 'synthetic-request-00001', plan['revision'])


def test_request_immediately_fences_all_sessions_and_new_login_but_preserves_b(controls):
    operator, web, ops, public, a_sid, b_sid, a, b = controls
    another = web.login('synthetic', 'alice')
    receipt = request(public, a)
    assert receipt['state'] == 'awaiting_operator' and receipt['data_erased'] is False
    assert web.session(a_sid) is None and web.session(another) is None
    assert web.route(a) is None and web.memberships(a) == []
    with pytest.raises(ControlError): web.login('synthetic','alice')
    with pytest.raises(ControlError): web.switch(a_sid,'shared')
    with pytest.raises(ControlError): operator.grant('synthetic','alice','other')
    with pytest.raises(ControlError): operator.grant('synthetic','bob','private_a')
    with pytest.raises(ControlError): operator.bind('private_a','new','https://fixture.invalid','new.json')
    with pytest.raises(ControlError): operator.grant('synthetic','third','shared')
    assert web.session(b_sid).user_id == b.user_id
    assert web.route(b) is not None
    assert public.status(b.user_id,job_id=receipt['id']) is None
    assert public.status(a.user_id,request_key='synthetic-request-00001') == receipt
    assert ops.freeze(receipt['id'])['state'] == 'frozen'
    assert ops.freeze(receipt['id'])['data_erased'] is False
    operator.grant('synthetic','third','shared')
    with operator.transaction() as db:
        assert db.scalar(select(tenants.c.deletion_state).where(tenants.c.id=='private_a')) == 'frozen'
        assert db.scalar(select(tenants.c.deletion_state).where(tenants.c.id=='shared')) == 'active'
        assert db.scalar(select(sessions.c.id_hash).where(sessions.c.user_id==a.user_id)) is None
        assert db.scalar(select(members.c.active).where(members.c.user_id==b.user_id,members.c.tenant_id=='shared')) is True


def test_ownership_unknown_and_inactive_peer_are_not_inferred_private(controls):
    operator, _, ops, public, _, _, a, _ = controls
    operator.grant('synthetic','alice','legacy')
    plan = public.preview(a)
    assert any(v['code']=='ownership_unknown' for v in plan['blockers'])
    with pytest.raises(DeletionError): public.request(a,'synthetic-legacy-001',plan['revision'])
    operator.grant('synthetic','past-member','private_a',active=False)
    assert any(v['code']=='private_has_other_members' for v in public.preview(a)['blockers'])
    with pytest.raises(DeletionError): AccountDeletionControl(public.store).register('private_a','private',owner_user_id=a.user_id)


def test_shared_owner_must_transfer_and_registration_is_revision_checked(controls):
    _, _, ops, public, _, _, a, b = controls
    assert any(v['code']=='shared_owner_transfer_required' for v in public.preview(b)['blockers'])
    with pytest.raises(DeletionError): ops.register('shared','shared',owner_user_id=a.user_id)


def test_stale_membership_and_exact_idempotency(controls):
    operator, _, _, public, _, _, a, _ = controls
    before = public.preview(a)
    operator.grant('synthetic','third','shared')
    with pytest.raises(DeletionError,match='plan_changed'): public.request(a,'synthetic-stale-0001',before['revision'])
    receipt = request(public,a)
    assert public.request(a,receipt['request_key'],receipt['plan_revision']) == receipt
    with pytest.raises(DeletionError,match='request_conflict'): public.request(a,'synthetic-another-01',receipt['plan_revision'])


def test_admission_races_other_account_enrollment_without_toctou(controls):
    operator, _, _, public, _, _, a, _ = controls
    plan = public.preview(a)
    def enroll():
        try: operator.grant('synthetic','other','private_a'); return 'enrolled'
        except ControlError: return 'blocked'
    def admit():
        try: public.request(a,'synthetic-race-00001',plan['revision']); return 'accepted'
        except DeletionError: return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [pool.submit(f) for f in (enroll,admit)]
        result = [f.result() for f in outcomes]
    assert result in [['enrolled','stale'],['blocked','accepted']]


def test_operator_freeze_revalidates_full_stored_plan_and_never_completes(controls):
    operator, _, ops, public, _, _, a, _ = controls
    receipt = request(public,a)
    with operator.transaction(mutating=True) as db:
        db.execute(update(deletion_requests).where(deletion_requests.c.id==receipt['id']).values(plan_json='{"tenants":[]}'))
    with pytest.raises(DeletionError,match='ownership_changed'): ops.freeze(receipt['id'])
    assert public.status(a.user_id,job_id=receipt['id'])['state'] == 'awaiting_operator'


def test_request_and_block_survive_new_control_store(controls):
    _, web, _, public, a_sid, _, a, _ = controls
    receipt = request(public,a)
    fresh = ControlStore(str(web.engine.url))
    try:
        assert fresh.session(a_sid) is None
        assert AccountDeletionControl(fresh).status(a.user_id,job_id=receipt['id']) == receipt
    finally: fresh.close()
