"""Authoritative synthetic control/tenant state, never self-reported active flags."""
import hashlib
import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from sqlalchemy import delete, insert, select, update

from wearing.cloud.account_deletion_control import AccountDeletionControl
from wearing.cloud.control import ControlStore, users, tenants, members, ownership, routes
from wearing.cloud.device_admission import (AccountProof, AdmissionError, AdmissionSources,
    TrustedSSHAdmission, control_evidence, tenant_evidence, readonly_control, remote_source)
from wearing.cloud.device_provisioning import ProvisionBook, ProvisionError
from wearing.cloud.instance import initialize_instance
from wearing.config import write_private_json
from wearing.store import Store
from test_device_provisioning import Provider, spec, policy, NOW


@pytest.fixture
def account(tmp_path):
    control = ControlStore('sqlite:///' + str(tmp_path / 'control.sqlite3'), initialize=True, operator=True)
    root = tmp_path / 'instance'
    instance = initialize_instance(root, 'tenant_a', 'https://fixture.invalid')
    Store(root / 'data/wearing.sqlite3')
    (root / 'data/wearing.sqlite3').chmod(0o600)
    control.grant('fixture', 'alice', 'tenant_a')
    control.bind('tenant_a', instance.instance_id, 'https://fixture.invalid', 'fixture.json')
    with control.transaction() as db:
        uid = db.scalar(select(users.c.id).where(users.c.subject == 'alice'))
    AccountDeletionControl(control).register('tenant_a', 'private', owner_user_id=uid)
    yield control, root, instance, uid
    control.close()


def test_control_and_tenant_evidence_select_only_necessary_metadata(account):
    control, root, instance, uid = account
    before = hashlib.sha256((root / 'data/wearing.sqlite3').read_bytes()).hexdigest()
    proof = control_evidence(control, 'tenant_a')
    assert proof['owner_user_id'] == uid and proof['instance_id'] == instance.instance_id
    assert set(proof) == {'tenant_id','instance_id','owner_user_id','ownership_revision','member_digest','observed_at'}
    metadata = tenant_evidence(root, 'tenant_a', 'daily', instance.instance_id)
    assert metadata['identity_id'] == 'daily'
    assert before == hashlib.sha256((root / 'data/wearing.sqlite3').read_bytes()).hexdigest()
    assert 'gateway' not in json.dumps(proof) and 'fixture' not in json.dumps(proof)
    # Query-only connection state is not accidentally retained in a shared pool.
    with control.transaction(mutating=True) as db:
        db.execute(update(tenants).where(tenants.c.id == 'tenant_a').values(deletion_state='active'))


@pytest.mark.parametrize('change', ['user_frozen', 'tenant_frozen', 'inactive', 'unknown', 'shared',
                                    'member_digest', 'member_count', 'owner', 'instance', 'missing_route'])
def test_live_authoritative_control_changes_fail_closed(account, change):
    control, _, _, uid = account
    with control.transaction(mutating=True) as db:
        if change == 'user_frozen': db.execute(update(users).where(users.c.id == uid).values(deletion_state='frozen'))
        elif change == 'tenant_frozen': db.execute(update(tenants).where(tenants.c.id == 'tenant_a').values(deletion_state='frozen'))
        elif change == 'inactive': db.execute(update(members).values(active=False))
        elif change in ('unknown', 'shared'): db.execute(update(ownership).values(classification=change))
        elif change == 'member_digest': db.execute(update(ownership).values(member_digest='0' * 64))
        elif change == 'member_count': db.execute(update(ownership).values(member_count=2))
        elif change == 'owner': db.execute(update(ownership).values(owner_user_id=None))
        elif change == 'instance': db.execute(update(ownership).values(instance_id='instance_other'))
        else: db.execute(delete(routes))
    with pytest.raises(AdmissionError): control_evidence(control, 'tenant_a')


def test_pending_deletion_denies_before_freeze_and_cannot_be_self_reported_active(account):
    control, _, _, _ = account
    sid = control.login('fixture', 'alice', auth_time=int(time.time()))
    session = control.session(sid)
    deletion = AccountDeletionControl(control)
    plan = deletion.preview(session)
    receipt = deletion.request(session, 'synthetic-delete-request', plan['revision'])
    assert receipt['state'] == 'awaiting_operator'
    with control.transaction() as db:
        assert db.scalar(select(tenants.c.deletion_state)) == 'active'
    with pytest.raises(AdmissionError, match='account_frozen_or_deleting'):
        control_evidence(control, 'tenant_a')


def test_web_role_and_missing_control_ownership_do_not_prove_admission(account):
    control, _, _, _ = account
    control.operator = False
    with pytest.raises(AdmissionError, match='control_operator_required'): control_evidence(control, 'tenant_a')
    control.operator = True
    with pytest.raises(AdmissionError): control_evidence(control, 'tenant_missing')


def test_sqlite_control_reader_rejects_writes(account):
    control, *_ = account
    with readonly_control(control) as db:
        with pytest.raises(Exception): db.execute(delete(tenants))
    assert control_evidence(control, 'tenant_a')


@pytest.mark.parametrize('change', ['identity', 'tenant', 'instance', 'tombstone', 'volume_owner', 'database_missing', 'database_symlink'])
def test_tenant_evidence_verifies_identity_volume_scope_and_freeze(account, change):
    _, root, instance, _ = account
    target_tenant, target_id, target_instance = 'tenant_a', 'daily', instance.instance_id
    if change == 'identity': target_id = 'not_present'
    elif change == 'tenant': target_tenant = 'tenant_b'
    elif change == 'instance': target_instance = 'instance_other'
    elif change == 'tombstone': write_private_json(root / 'deletion-tombstone.json', {})
    elif change == 'volume_owner': write_private_json(root / 'data/instance-owner.json', {'tenant_id':'tenant_b','instance_id':instance.instance_id})
    else:
        path = root / 'data/wearing.sqlite3';path.rename(path.with_suffix('.backup'))
        if change == 'database_symlink': path.symlink_to(path.with_suffix('.backup'))
    with pytest.raises(ValueError): tenant_evidence(root, target_tenant, target_id, target_instance)


def transport(tmp_path, responses):
    config = tmp_path / 'ssh-config';config.write_text('')
    sources = AdmissionSources.model_validate({'control': {'host':'control', 'root':'/var/lib/wearing/gateway'},
        'operator_env':'/etc/pajio/operator.env','tenants':{'tenant_a':{'host':'tenant-a','root':'/var/lib/wearing/instance'}}})
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        value = responses[len(calls)-1]
        if isinstance(value, Exception): raise value
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), 'must not appear in errors')
    return TrustedSSHAdmission(ssh_config=config, sources=sources, runner=run, clock=lambda:NOW), calls


def replies():
    c={'tenant_id':'tenant_a','instance_id':'instance_a','owner_user_id':'user_a','ownership_revision':1,
       'member_digest':'f'*64,'observed_at':NOW}
    t={'tenant_id':'tenant_a','identity_id':'daily','instance_id':'instance_a','observed_at':NOW}
    return [c,t,dict(c)]


def test_trusted_ssh_checks_control_tenant_control_with_exact_host_trust(tmp_path):
    guard,calls = transport(tmp_path,replies())
    proof = guard.check(spec())
    assert proof.owner_user_id == 'user_a'
    assert [a[-2] for a,_ in calls] == ['control','tenant-a','control']
    assert [json.loads(k['input'])['action'] for _,k in calls] == ['control','tenant','control']
    for argv, kwargs in calls:
        assert 'BatchMode=yes' in argv and 'StrictHostKeyChecking=yes' in argv
        assert not kwargs.get('shell') and 'sudo -n' in argv[-1]
        assert 'WEARING_CONTROL_OPERATOR_DATABASE_URL=' not in argv[-1]
    assert 'SELECT 1 FROM identities WHERE id=?' in remote_source()
    compile(remote_source(), '<exact-remote-admission>', 'exec')


@pytest.mark.parametrize('change', ['owner_changed','scope','wrong_instance','stale','future','timeout','error','missing'])
def test_ssh_evidence_ambiguity_and_wrong_scope_fail_closed(tmp_path, change):
    r = replies()
    if change == 'owner_changed':r[2]['ownership_revision']=2
    elif change == 'scope':r[1]['identity_id']='other'
    elif change == 'wrong_instance':r[1]['instance_id']='instance_b'
    elif change == 'stale':r[0]['observed_at']=NOW-61
    elif change == 'future':r[0]['observed_at']=NOW+1
    elif change == 'timeout':r[0]=subprocess.TimeoutExpired('ssh',1,stderr='sensitive data')
    elif change == 'error':r[0]={'error':'account_frozen_or_deleting'}
    else:r[0]={}
    guard,_ = transport(tmp_path,r)
    with pytest.raises(AdmissionError) as error:guard.check(spec())
    assert 'sensitive' not in str(error.value)


class LiveLocalAdmission:
    """Trusted test boundary queries actual control and instance metadata."""
    def __init__(self, control, root):self.control,self.root=control,root;self.calls=0
    def check(self, item):
        self.calls += 1
        c = control_evidence(self.control,item.tenant_id)
        tenant_evidence(self.root,item.tenant_id,item.identity_id,c['instance_id'])
        return AccountProof(**{**c,'identity_id':item.identity_id,'source_sha256':'1'*64,'observed_at':NOW})


def checked_book(tmp_path, account):
    control,root,_,_=account
    admission=LiveLocalAdmission(control,root)
    return ProvisionBook(tmp_path/'ledger',operator=True,clock=lambda:NOW,admission=admission),Provider(),admission


def test_book_plan_reserve_apply_recheck_and_persist_trusted_scope(tmp_path, account):
    book,provider,admission=checked_book(tmp_path,account)
    plan=book.plan(spec(),policy(),provider)
    before=admission.calls
    book.reserve(spec(),policy(),provider,plan_sha256=plan['plan_sha256'])
    assert admission.calls>before
    before=admission.calls
    assert book.apply(spec().request_id,provider,plan_sha256=plan['plan_sha256'])['state']=='staged'
    assert admission.calls>=before+5 and provider.calls==['clone','prepare']
    with book._tx() as db:
        binding=json.loads(db.execute('SELECT scope FROM device_accounts').fetchone()[0])
    assert binding['instance_id']==account[2].instance_id and binding['owner_user_id']==account[3]


@pytest.mark.parametrize('phase',['plan','reserve','apply','repeat_reserve','repeat_apply'])
def test_freeze_blocks_every_public_operator_phase_even_idempotent_retries(tmp_path,account,phase):
    book,provider,_=checked_book(tmp_path,account)
    plan=book.plan(spec(),policy(),provider)
    if phase in ('apply','repeat_reserve','repeat_apply'):
        book.reserve(spec(),policy(),provider,plan_sha256=plan['plan_sha256'])
    if phase=='repeat_apply':book.apply(spec().request_id,provider,plan_sha256=plan['plan_sha256'])
    before=list(provider.calls)
    with account[0].transaction(mutating=True) as db:db.execute(update(users).values(deletion_state='frozen'))
    with pytest.raises(ProvisionError,match='account_frozen_or_deleting'):
        if phase=='plan':book.plan(spec(),policy(),provider)
        elif phase in ('reserve','repeat_reserve'):book.reserve(spec(),policy(),provider,plan_sha256=plan['plan_sha256'])
        else:book.apply(spec().request_id,provider,plan_sha256=plan['plan_sha256'])
    assert provider.calls==before


def test_freeze_during_clone_retains_unknown_work_and_does_not_configure(tmp_path,account):
    book,provider,_=checked_book(tmp_path,account)
    plan=book.plan(spec(),policy(),provider)
    book.reserve(spec(),policy(),provider,plan_sha256=plan['plan_sha256'])
    original=provider.clone_stopped
    def clone(*args):
        original(*args)
        with account[0].transaction(mutating=True) as db:db.execute(update(tenants).values(deletion_state='frozen'))
    provider.clone_stopped=clone
    with pytest.raises(ProvisionError,match='account_frozen_or_deleting'):
        book.apply(spec().request_id,provider,plan_sha256=plan['plan_sha256'])
    assert provider.calls==['clone'] and provider.vms[1].state=='stopped'
    assert book.status(spec().request_id)['state']=='needs_operator'
    with pytest.raises(ProvisionError,match='reservation_cannot_cancel'):book.cancel_unattempted(spec().request_id,provider)


def test_changed_account_revision_requires_new_review_and_never_rebinds_reserved_vm(tmp_path,account):
    book,provider,_=checked_book(tmp_path,account)
    plan=book.plan(spec(),policy(),provider)
    book.reserve(spec(),policy(),provider,plan_sha256=plan['plan_sha256'])
    with account[0].transaction(mutating=True) as db:db.execute(update(ownership).values(revision=2))
    with pytest.raises(ProvisionError,match='reviewed_plan_changed'):
        book.reserve(spec(),policy(),provider,plan_sha256=plan['plan_sha256'])
    with pytest.raises(ProvisionError,match='account_binding_changed'):
        book.apply(spec().request_id,provider,plan_sha256=plan['plan_sha256'])
    assert provider.calls==[]


def test_no_guard_or_caller_boolean_can_authorize_provisioning(tmp_path):
    book=ProvisionBook(tmp_path/'ledger',operator=True,clock=lambda:NOW)
    with pytest.raises(ProvisionError,match='account_admission_required'):book.plan(spec(),policy(),Provider())
    book.admission=type('Untrusted',(),{'check':lambda self,item:{'active':True}})()
    with pytest.raises(ProvisionError,match='account_evidence_unavailable'):book.plan(spec(),policy(),Provider())


@pytest.mark.parametrize('action', ['plan','reserve','apply'])
def test_operator_cli_requires_trusted_sources_before_ledger_or_host_access(tmp_path,monkeypatch,capsys,action):
    import sys
    from wearing.cloud.device_operator import main
    root=tmp_path/'must-not-create'
    monkeypatch.setattr(sys,'argv',['device-operator',action,'--root',str(root)])
    with pytest.raises(SystemExit) as error:main()
    assert error.value.code==2 and 'trusted_admission_sources_required' in capsys.readouterr().err
    assert not root.exists()


def test_spec_does_not_accept_self_reported_active_state():
    from wearing.cloud.device_provisioning import DeviceSpec
    with pytest.raises(ValueError):DeviceSpec.model_validate({**spec().model_dump(),'active':True})


def test_unregistered_tenant_source_never_issues_ssh(tmp_path):
    guard,calls=transport(tmp_path,[])
    with pytest.raises(AdmissionError,match='tenant_metadata_target_unregistered'):
        guard.check(spec(tenant_id='tenant_other'))
    assert calls==[]


def test_unrelated_tenant_catalog_change_does_not_rebind_existing_request(tmp_path):
    guard,_=transport(tmp_path,replies()+replies())
    before=guard.check(spec())
    sources=guard.sources.model_dump()
    sources['tenants']['tenant_other']={'host':'other','root':'/var/lib/wearing/instance'}
    guard.sources=AdmissionSources.model_validate(sources)
    assert guard.check(spec()).scope()==before.scope()
