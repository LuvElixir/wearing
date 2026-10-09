"""Opt-in, new synthetic users/databases in an explicitly disposable PG cluster."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from test_control_postgres import pg  # the same explicit qa_only cluster guard
from wearing.account_deletion import DeletionError
from wearing.cloud.account_deletion_control import AccountDeletionControl
from wearing.cloud.control import ControlError, ControlStore, deletion_requests, members, ownership, sessions, users
from wearing.cloud.postgres import migrate_database


def registered(pg):
    web, operator = pg['web'], pg['operator_store']
    sid = web.login(pg['issuer'],'alice')
    a = web.session(sid)
    AccountDeletionControl(operator).register(pg['a'],'private',owner_user_id=a.user_id)
    return AccountDeletionControl(web), AccountDeletionControl(operator), sid, a


def test_pg_request_is_self_scoped_immutable_and_immediately_freezes(pg):
    public, ops, sid, a = registered(pg)
    b = pg['web'].session(pg['web'].login(pg['issuer'],'bob'))
    plan = public.preview(a)
    receipt = public.request(a,'pg-synthetic-request-0001',plan['revision'])
    assert public.request(a,receipt['request_key'],plan['revision']) == receipt
    assert pg['web'].session(sid) is None
    assert pg['web'].route(a) is None
    with pytest.raises(ControlError): pg['web'].login(pg['issuer'],'alice')
    with pytest.raises(ControlError): pg['operator_store'].grant(pg['issuer'],'bob',pg['a'])
    with pg['web'].transaction() as db:
        assert db.execute(select(ownership)).all() == []
        assert db.execute(select(deletion_requests)).all() == []
    with pg['web'].transaction(user_id=b.user_id) as db:
        assert db.execute(select(deletion_requests)).all() == []
        assert db.execute(select(ownership)).all() == []
    assert public.status(b.user_id,job_id=receipt['id']) is None
    assert public.status(a.user_id,request_key=receipt['request_key']) == receipt
    # The database also rejects minting another ordinary session after admission.
    with pytest.raises(DBAPIError):
        with pg['web'].transaction(user_id=a.user_id,session_hash='b'*64) as db:
            db.execute(insert(sessions).values(id_hash='b'*64,user_id=a.user_id,tenant_id=pg['a'],csrf='c'*32,expires=2147483647))
    assert ops.freeze(receipt['id'])['state'] == 'frozen'
    assert pg['web'].route(b) is not None
    assert public.status(a.user_id,job_id=receipt['id'])['data_erased'] is False


@pytest.mark.parametrize('statement',[
    "UPDATE wearing_control.wearing_users SET deletion_state='active'",
    "UPDATE wearing_control.wearing_tenant_ownership SET classification='private'",
    "DELETE FROM wearing_control.wearing_tenant_ownership",
    "UPDATE wearing_control.wearing_deletion_requests SET state='completed'",
    "DELETE FROM wearing_control.wearing_deletion_requests",
    "TRUNCATE wearing_control.wearing_deletion_requests",
    "INSERT INTO wearing_control.wearing_deletion_requests(id,user_id,request_key,plan_revision,plan_json,created_at,state) VALUES ('fake','fake','fake','fake','{}',1,'completed')",
    "UPDATE wearing_control.wearing_sessions SET auth_time=2147483647",
])
def test_pg_web_cannot_administer_deletion_or_forge_progress(pg, statement):
    _, _, _, a = registered(pg)
    with pytest.raises(DBAPIError):
        with pg['web'].transaction(user_id=a.user_id) as db: db.execute(text(statement))


def test_pg_rls_insert_cannot_request_for_another_user(pg):
    _, _, _, a = registered(pg)
    b = pg['web'].session(pg['web'].login(pg['issuer'],'bob'))
    with pytest.raises(DBAPIError):
        with pg['web'].transaction(user_id=a.user_id) as db:
            db.execute(insert(deletion_requests).values(id=uuid.uuid4().hex,user_id=b.user_id,request_key='synthetic-forged-0001',plan_revision='a'*64,plan_json='{}',created_at=1))


def test_pg_membership_admission_lock_prevents_plan_toctou(pg):
    public, _, _, a = registered(pg)
    plan = public.preview(a)
    def grant():
        try: pg['operator_store'].grant(pg['issuer'],'bob',pg['a']); return 'enrolled'
        except ControlError: return 'blocked'
    def admit():
        try: public.request(a,'synthetic-pg-race-0001',plan['revision']); return 'accepted'
        except DeletionError: return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = [pool.submit(f) for f in (grant,admit)]
        result = [f.result() for f in work]
    assert result in [['enrolled','stale'],['blocked','accepted']]


def test_pg_new_login_cannot_escape_concurrent_deletion(pg):
    public, _, _, a = registered(pg)
    plan = public.preview(a)
    def login():
        try: return pg['web'].login(pg['issuer'],'alice')
        except ControlError: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        signin = pool.submit(login)
        admission = pool.submit(public.request,a,'synthetic-pg-login-race',plan['revision'])
        sid, receipt = signin.result(), admission.result()
    assert receipt['state'] == 'awaiting_operator'
    assert sid is None or pg['web'].session(sid) is None


def test_upgrade_0001_preserves_existing_accounts_and_unknown_ownership(pg):
    # Fresh database, separate migration owner; never upgrades the fixture's
    # shared QA database backwards and never adopts an existing user database.
    name = 'pajio_delete_upgrade_' + uuid.uuid4().hex
    owner = make_url(pg['migration']).username
    quote = pg['admin_engine'].dialect.identifier_preparer.quote
    with pg['admin_engine'].connect().execution_options(isolation_level='AUTOCOMMIT') as db:
        db.execute(text(f'CREATE DATABASE {quote(name)} OWNER {quote(owner)}'))
    target_url = make_url(pg['migration']).set(database=name)
    engine = create_engine(target_url,hide_parameters=True)
    try:
        config = Config()
        config.set_main_option('script_location',str(Path(__file__).parents[1]/'src/wearing/cloud/migrations'))
        with engine.begin() as db:
            config.attributes['connection'] = db
            command.upgrade(config,'wearing_control_0001')
        admin_target = create_engine(make_url(pg['admin']).set(database=name),hide_parameters=True)
        try:
            with admin_target.begin() as db:
                assert db.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='wearing_control' AND column_name='deletion_state'")) == 0
                db.execute(text("INSERT INTO wearing_control.wearing_users(id,issuer,subject) VALUES ('legacy','synthetic','legacy')"))
                db.execute(text("INSERT INTO wearing_control.wearing_tenants(id) VALUES ('legacy')"))
                db.execute(text("INSERT INTO wearing_control.wearing_memberships VALUES ('legacy','legacy',true)"))
            migrate_database(target_url)
            migrate_database(target_url)
            with admin_target.connect() as db:
                assert db.execute(text("SELECT issuer,subject,deletion_state FROM wearing_control.wearing_users WHERE id='legacy'")).one() == ('synthetic','legacy','active')
                assert db.scalar(text('SELECT count(*) FROM wearing_control.wearing_tenant_ownership')) == 0
        finally: admin_target.dispose()
        web = ControlStore(make_url(pg['app']).set(database=name))
        try:
            legacy = web.session(web.login('synthetic','legacy'))
            plan = AccountDeletionControl(web).preview(legacy)
            assert plan['ready'] is False and plan['blockers'][0]['code'] == 'ownership_unknown'
        finally: web.close()
    finally:
        engine.dispose()
        with pg['admin_engine'].connect().execution_options(isolation_level='AUTOCOMMIT') as db:
            db.execute(text(f'DROP DATABASE {quote(name)}'))
