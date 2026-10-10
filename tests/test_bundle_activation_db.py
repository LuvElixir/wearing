"""Atomic invitation-to-activation boundary; all identities are disposable fixtures."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import uuid

import pytest
from sqlalchemy import create_engine, event, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from wearing.cloud.control import (ControlError, ControlStore, bundles, bundle_activations,
                                    invitations, members, ownership, users)
from wearing.cloud.invitations import InvitationError, InvitationStore, code_hash
from wearing.cloud.bundle_activation import ActivationStore
from wearing.cloud.postgres import migrate_database, DatabaseBoundaryError


def issue_bundle(ops, issuer, *, tenant=None, directory=None):
    """Synthetic control evidence only; never invokes provider or IdP."""
    api = InvitationStore(ops)
    tenant = tenant or 'bundle_' + uuid.uuid4().hex
    ident, bid = uuid.uuid4().hex, uuid.uuid4().hex
    api.reserve_tenant(tenant)
    instance = 'instance_' + tenant
    ops.bind(tenant, instance, 'https://worker.example', tenant + '.json')
    base = int(bid[:6], 16) * 4 + 1000
    data = {k: dict(vmid=base+i, request_id=uuid.uuid4().hex, vcpus=1,
                   memory_mib=1024, disk_mib=8192, image_sha256='a'*64,
                   core_reservation_sha256='b'*64 if k == 'core' else None)
            for i,k in enumerate(('core','linux','android'))}
    code = 'pajio_' + secrets.token_urlsafe(32)
    def issue_at(parent):
        plan = Path(parent)/f'{bid}.json'
        plan.write_text(json.dumps({'fixture': bid}));plan.chmod(0o600)
        row = api.bind_bundle(bundle_id=bid, tenant_id=tenant, instance_id=instance, host='fixture',
            reservation_sha256=secrets.token_hex(32), members=data,
            reservation_expires_at=int(time.time())+7200, worker_plan_path=plan)
        api.issue(issuer=issuer, tenant_id=tenant, invitation_id=ident, code=code,
                  expires_at=int(time.time())+3600,bundle_id=bid,worker_plan_path=plan)
        return code,ident,tenant,row,plan
    if directory is not None:
        return issue_at(directory)
    with tempfile.TemporaryDirectory() as parent:
        return issue_at(parent)


@pytest.fixture
def sqlite_bundle(tmp_path):
    url='sqlite:///'+str(tmp_path/'control.sqlite3')
    stores=[ControlStore(url,initialize=True,operator=True),ControlStore(url),ControlStore(url,activation=True)]
    yield stores
    for store in stores:store.close()


def test_redeem_has_exactly_one_atomic_outbox_and_retries_same_event(sqlite_bundle):
    ops,web,_=sqlite_bundle
    code,ident,tenant,bundle,_=issue_bundle(ops,'https://fixture.example')
    def redeem(_):
        return InvitationStore(web).redeem_hash(code_hash(code),issuer='https://fixture.example',subject='fixture')
    with ThreadPoolExecutor(max_workers=6) as pool: result=list(pool.map(redeem,range(6)))
    assert len({v['activation_id'] for v in result})==1
    with ops.transaction() as db:
        row=db.execute(select(bundle_activations)).mappings().one()
        own=db.execute(select(ownership)).mappings().one()
        assert row['bundle_id']==bundle['id'] and row['invitation_id']==ident
        assert row['member_digest']==own['member_digest'] and row['ownership_revision']==own['revision']
        assert row['generation']==0 and row['state']=='reserved'


def test_outbox_failure_rolls_back_member_identity_and_code(sqlite_bundle):
    ops,web,_=sqlite_bundle
    code,*_=issue_bundle(ops,'https://fixture.example')
    def fail(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO wearing_bundle_activations'):
            raise RuntimeError('synthetic outbox fault')
    event.listen(web.engine,'before_cursor_execute',fail)
    try:
        with pytest.raises(RuntimeError,match='synthetic'):
            InvitationStore(web).redeem_hash(code_hash(code),issuer='https://fixture.example',subject='fixture')
    finally:event.remove(web.engine,'before_cursor_execute',fail)
    with ops.transaction() as db:
        for table in (users,members,ownership,bundle_activations):assert not db.execute(select(table)).all()
        assert db.execute(select(invitations)).mappings().one()['redeemed_user_id'] is None
    assert InvitationStore(web).check(code,issuer='https://fixture.example')['eligible']


def test_plan_and_bundle_cannot_drift_and_expiry_has_grace(sqlite_bundle,tmp_path):
    ops,_,_=sqlite_bundle
    code,ident,tenant,bundle,plan=issue_bundle(ops,'https://fixture.example',directory=tmp_path)
    bad=json.loads(bundle['members_json']);bad['linux']['vmid']=bad['core']['vmid']
    with pytest.raises(InvitationError):
        InvitationStore(ops).bind_bundle(bundle_id=uuid.uuid4().hex,tenant_id=tenant,instance_id=bundle['instance_id'],
            host='fixture',reservation_sha256='a'*64,members=bad,
            reservation_expires_at=int(time.time())+7200,worker_plan_path=plan)
    plan.write_text('changed')
    with pytest.raises(InvitationError):
        InvitationStore(ops).bind_bundle(bundle_id=bundle['id'],tenant_id=tenant,instance_id=bundle['instance_id'],
            host='fixture',reservation_sha256=bundle['reservation_sha256'],members=json.loads(bundle['members_json']),
            reservation_expires_at=bundle['reservation_expires_at'],worker_plan_path=plan)
    for flags in ({'operator':True,'activation':True},{'registration':True,'activation':True}):
        with pytest.raises(ControlError):ControlStore('sqlite://',**flags)


@pytest.fixture
def bundle_pg():
    path=os.environ.get('WEARING_POSTGRES_TEST_CONFIG')
    if not path:pytest.skip('requires explicit disposable PostgreSQL QA configuration')
    config=json.loads(Path(path).read_text());assert config.get('qa_only') is True
    database='bundle_qa_'+uuid.uuid4().hex
    admin=create_engine(config['admin'],hide_parameters=True)
    owner=make_url(config['migration']).username;quote=admin.dialect.identifier_preparer.quote
    with admin.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
        db.execute(text(f'CREATE DATABASE {quote(database)} OWNER {quote(owner)}'))
    urls={k:make_url(config[k]).set(database=database) for k in ('app','operator','activation','registration','migration','admin')}
    target_admin=create_engine(urls['admin'],hide_parameters=True)
    stores=[]
    try:
        migrate_database(urls['migration'])
        ops=ControlStore(urls['operator'],operator=True);web=ControlStore(urls['app'])
        act=ControlStore(urls['activation'],activation=True);reg=ControlStore(urls['registration'],registration=True)
        stores=[ops,web,act,reg]
        yield dict(ops=ops,web=web,act=act,reg=reg,admin=target_admin,urls=urls,issuer='https://bundle-fixture.example')
    finally:
        for store in stores:store.close()
        target_admin.dispose()
        with admin.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
            db.execute(text(f'DROP DATABASE {quote(database)}'))
        admin.dispose()


def admitted(pg):
    code,ident,tenant,bundle,_=issue_bundle(pg['ops'],pg['issuer'])
    result=InvitationStore(pg['web']).redeem_hash(code_hash(code),issuer=pg['issuer'],subject='fixture')
    current=pg['web'].session(pg['web'].login(pg['issuer'],'fixture'))
    return result,current,bundle


def test_pg_exactly_one_outbox_safe_owner_status_and_role_isolation(bundle_pg):
    pg=bundle_pg
    code,ident,tenant,bundle,_=issue_bundle(pg['ops'],pg['issuer'])
    def redeem(_):return InvitationStore(pg['web']).redeem_hash(code_hash(code),issuer=pg['issuer'],subject='fixture')
    with ThreadPoolExecutor(max_workers=4) as pool: result=list(pool.map(redeem,range(4)))
    assert len({v['activation_id'] for v in result})==1
    current=pg['web'].session(pg['web'].login(pg['issuer'],'fixture'))
    status=ActivationStore(pg['web']).status(current)
    assert set(status)=={'state','members','reason','updated_at','retry_after'}
    assert status['state']=='reserved' and set(status['members'])=={'core','linux','android'}
    with pg['web'].transaction(user_id=current.user_id,tenant_id='other') as db:
        assert db.scalar(text('SELECT wearing_control.bundle_activation_status(:tenant)'),{'tenant':tenant}) is None
    for store in (pg['web'],pg['reg']):
        with pytest.raises(DBAPIError):
            with store.transaction() as db:db.execute(text("SELECT wearing_control.activation_claim(:worker,120)"),{'worker':'a'*32})
    for statement in ('SELECT * FROM wearing_control.wearing_users','SELECT * FROM wearing_control.wearing_bundle_activations',
                      'DELETE FROM wearing_control.wearing_memberships','SET ROLE wearing_operator','SET ROLE wearing_web'):
        with pytest.raises(DBAPIError):
            with pg['act'].transaction() as db:db.execute(text(statement))
    with pg['web'].transaction(user_id=current.user_id,tenant_id=tenant) as db:
        assert not db.execute(select(bundles)).all()
    with pytest.raises(DatabaseBoundaryError):ControlStore(pg['urls']['activation'])


def test_pg_lease_takeover_fences_old_worker_and_ready_requires_all(bundle_pg):
    pg=bundle_pg;result,current,bundle=admitted(pg);api=ActivationStore(pg['act'])
    one=api.claim('a'*32,30);assert one['bundle']['worker_plan_sha256']==bundle['worker_plan_sha256']
    assert api.claim('b'*32,30) is None
    assert api.heartbeat(one['id'],'a'*32,one['generation'],30)
    with pg['admin'].begin() as db:
        db.execute(text('UPDATE wearing_control.wearing_bundle_activations SET lease_until=1 WHERE id=:id'),{'id':one['id']})
    two=api.claim('b'*32,30);assert two['generation']==one['generation']+1
    assert api.heartbeat(one['id'],'a'*32,one['generation'],30) is None
    assert api.release(one['id'],'a'*32,one['generation']) is None
    sql='SELECT wearing_control.activation_update(:id,:worker,:generation,:state,:step,:receipt,:reason,CAST(:members AS jsonb))'
    args=dict(id=two['id'],worker='b'*32,generation=two['generation'],state='ready',step='complete',receipt='c'*64,reason=None,
              members=json.dumps({k:{'state':'pending'} for k in ('core','linux','android')}))
    with pg['act'].transaction() as db:assert db.scalar(text(sql),args) is None
    args['members']=json.dumps({k:{'state':'ready'} for k in ('core','linux','android')})
    with pg['act'].transaction() as db:assert db.scalar(text(sql),args)['state']=='ready'
    assert ActivationStore(pg['web']).status(current)['state']=='ready'
    assert api.release(two['id'],'b'*32,two['generation'])
    assert api.claim('c'*32) is None


def test_pg_owner_change_fences_lease_and_immutable_bundle(bundle_pg):
    pg=bundle_pg;result,current,bundle=admitted(pg);api=ActivationStore(pg['act']);lease=api.claim('a'*32)
    pg['ops'].grant(pg['issuer'],'fixture',current.tenant_id,active=False)
    assert api.heartbeat(lease['id'],'a'*32,lease['generation']) is None
    assert api.release(lease['id'],'a'*32,lease['generation']) is None
    with pytest.raises(ControlError):ActivationStore(pg['web']).status(current)
    for statement in ("UPDATE wearing_control.wearing_bundles SET host='other'",
                      "UPDATE wearing_control.wearing_invitations SET bundle_id=NULL",
                      "UPDATE wearing_control.wearing_bundle_activations SET ownership_revision=99"):
        with pytest.raises(DBAPIError):
            with pg['admin'].begin() as db:db.execute(text(statement))


def test_pg_outbox_insert_failure_rolls_back_and_new_issue_needs_bundle(bundle_pg):
    pg=bundle_pg;code,ident,tenant,bundle,_=issue_bundle(pg['ops'],pg['issuer'])
    with pg['admin'].begin() as db:
        db.execute(text("ALTER TABLE wearing_control.wearing_bundle_activations ADD CHECK (state='never')"))
    with pytest.raises(DBAPIError):InvitationStore(pg['web']).redeem_hash(code_hash(code),issuer=pg['issuer'],subject='fixture')
    with pg['ops'].transaction() as db:
        for table in (users,members,ownership,bundle_activations):assert not db.execute(select(table)).all()
        assert db.execute(select(invitations)).mappings().one()['redeemed_user_id'] is None
    with pytest.raises(InvitationError,match='bundle_required'):
        InvitationStore(pg['ops']).issue(issuer=pg['issuer'],tenant_id='new',invitation_id=uuid.uuid4().hex,
            code='pajio_'+secrets.token_urlsafe(32),expires_at=int(time.time())+3600)
