"""Deletion journal/fixture behavior only. No production runtime or credentials."""
import json
import os
from pathlib import Path
import shutil
import socket
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from wearing.account_deletion import DeletionError, DeletionJobs, Receipt, digest
from wearing.account_deletion_fixture import SyntheticDeletionAdapter
from wearing.account_deletion_cli import run

USER='user_a'
OTHER='user_b'
ROWS=[
    dict(tenant_id='private_a',classification='private',owner_user_id=USER,member_ids=[USER],instance_id='instance_a'),
    dict(tenant_id='private_b',classification='private',owner_user_id=OTHER,member_ids=[OTHER],instance_id='instance_b'),
    dict(tenant_id='shared',classification='shared',owner_user_id=OTHER,member_ids=[USER,OTHER],instance_id='instance_shared'),
]


@pytest.fixture(autouse=True)
def no_network_or_process(monkeypatch):
    import subprocess
    import asyncio
    def forbidden(*a,**kw):raise AssertionError('Deletion tests must remain isolated')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(subprocess,'run',forbidden)
    monkeypatch.setattr(asyncio,'create_subprocess_exec',forbidden)


@pytest.fixture
def rig(tmp_path):
    clock=[1000.0]
    jobs=DeletionJobs(tmp_path/'journal',initialize=True,mode='synthetic',clock=lambda:clock[0])
    for row in ROWS:jobs.register(row['tenant_id'],row['classification'],row['member_ids'],owner_user_id=row['owner_user_id'],instance_id=row['instance_id'])
    adapter=SyntheticDeletionAdapter.create(ROWS,clock=lambda:clock[0])
    plan=jobs.preview(USER)
    yield jobs,adapter,plan,clock
    shutil.rmtree(adapter.root)


def requested(rig):
    jobs,adapter,plan,clock=rig
    return jobs.request(USER,'stable_request_001',plan['revision'])


def test_plan_private_and_shared_scope_is_exact_and_other_owner_not_selected(rig):
    jobs,_,plan,_=rig
    assert plan['ready']
    assert {r['tenant_id']:r['action'] for r in plan['tenants']}=={'private_a':'erase_private','shared':'leave_shared'}
    other=jobs.preview(OTHER)
    assert not other['ready'] and other['blockers']==[{'tenant_id':'shared','code':'shared_owner_transfer_required'}]
    assert jobs.preview('unknown')['blockers']==[{'tenant_id':None,'code':'account_not_registered'}]


@pytest.mark.parametrize('classification,owner,members,instance,reason',[
    ('unknown',None,[USER],'instance_a','ownership_unknown'),
    ('private',OTHER,[USER,OTHER],'instance_a','not_private_owner'),
    ('private',USER,[USER,OTHER],'instance_a','private_has_other_members'),
    ('private',USER,[USER],None,'instance_unregistered'),
])
def test_no_private_destruction_inferred_from_incomplete_or_conflicting_registry(tmp_path,classification,owner,members,instance,reason):
    jobs=DeletionJobs(tmp_path/'journal',initialize=True)
    jobs.register('tenant',classification,members,owner_user_id=owner,instance_id=instance)
    plan=jobs.preview(USER)
    assert not plan['ready'] and plan['blockers'][0]['code']==reason
    with pytest.raises(DeletionError,match='ownership_not_ready'):jobs.request(USER,'stable_request_001',plan['revision'])


def test_plan_revision_and_request_key_replay_then_registry_freeze(rig):
    jobs,_,plan,_=rig
    jobs.register('private_a','private',[USER],owner_user_id=USER,instance_id='instance_a',revision=1)
    with pytest.raises(DeletionError,match='plan_changed'):jobs.request(USER,'stable_request_001',plan['revision'])
    fresh=jobs.preview(USER);first=jobs.request(USER,'stable_request_001',fresh['revision'])
    assert jobs.request(USER,'stable_request_001',fresh['revision'])==first
    with pytest.raises(DeletionError,match='request_conflict'):jobs.request(USER,'stable_request_001',plan['revision'])
    with pytest.raises(DeletionError,match='tenant_deletion_in_progress'):jobs.register('private_a','shared',[USER,OTHER],owner_user_id=OTHER,instance_id='instance_a',revision=2)
    with pytest.raises(DeletionError,match='already_requested'):jobs.request(USER,'another_request_key',fresh['revision'])


def test_unconfigured_production_adapter_cannot_complete_or_claim_revocation(tmp_path):
    jobs=DeletionJobs(tmp_path/'journal',initialize=True)
    jobs.register('tenant','private',[USER],owner_user_id=USER,instance_id='instance_a')
    row=jobs.request(USER,'stable_request_001',jobs.preview(USER)['revision'])
    result=jobs.run(row['id'])
    assert result['state']=='waiting' and result['code']=='adapter_unconfigured'
    assert not any(s['state']=='succeeded' for s in result['steps'])
    assert all(s['attempts']==0 for s in result['steps'][1:])


def test_real_fixture_files_removed_but_shared_and_foreign_bytes_retained(rig):
    jobs,adapter,plan,clock=rig;row=requested(rig)
    foreign=adapter.root/digest('private_b')/'primary/synthetic.txt'
    shared=adapter.root/digest('shared')/'primary/synthetic.txt'
    before=(foreign.read_bytes(),shared.read_bytes())
    result=jobs.run(row['id'],adapter)
    assert result['state']=='completed' and result['mode']=='synthetic'
    assert all(s['state']=='succeeded' and s['evidence'] for s in result['steps'])
    assert not (adapter.root/digest('private_a')/'primary').exists()
    assert not (adapter.root/digest('private_a')/'indexes').exists()
    assert not (adapter.root/digest('private_a')/'backups').exists()
    assert (foreign.read_bytes(),shared.read_bytes())==before
    state=adapter.snapshot()
    assert state['tenants']['shared']['detached_users']==[USER]
    assert state['tenants']['shared']['worker_running'] and state['tenants']['private_b']['worker_running']
    assert state['accounts'][USER]['finalized'] and not state['accounts'][OTHER]['frozen']


def test_restart_after_effect_before_receipt_reuses_operation_and_no_repeat_effect(rig):
    jobs,adapter,plan,clock=rig;row=requested(rig)
    class Crash:
        mode='synthetic'
        def execute(self,op):adapter.execute(op);raise KeyboardInterrupt('simulated process death')
    with pytest.raises(KeyboardInterrupt):jobs.run_one(row['id'],Crash())
    first=jobs.status(row['id'])['steps'][0]
    assert first['state']=='running' and len(adapter.snapshot()['effects'])==1
    reopened=DeletionJobs(jobs.root,mode='synthetic',clock=lambda:clock[0])
    resumed=reopened.run_one(row['id'],SyntheticDeletionAdapter(adapter.root,clock=lambda:clock[0]))
    assert resumed['steps'][0]['operation_id']==first['operation_id']
    assert resumed['steps'][0]['attempts']==2 and resumed['steps'][0]['state']=='succeeded'
    assert len(adapter.snapshot()['effects'])==1


def test_provider_failure_then_inflight_and_backup_retention_never_false_complete(rig):
    jobs,adapter,plan,clock=rig;row=requested(rig)
    adapter.set_fixture_state('private_a',provider_unavailable=True)
    result=jobs.run(row['id'],adapter)
    assert result['code']=='provider_unavailable' and result['state']=='waiting'
    assert (adapter.root/digest('private_a')/'primary').exists()
    adapter.set_fixture_state('private_a',provider_unavailable=False,inflight=True)
    assert jobs.run(row['id'],adapter)['code']=='instance_busy'
    adapter.set_fixture_state('private_a',inflight=False,retained_until=2000.0)
    result=jobs.run(row['id'],adapter)
    assert result['state']=='waiting' and result['code']=='backup_retained'
    assert not (adapter.root/digest('private_a')/'primary').exists()
    assert (adapter.root/digest('private_a')/'backups').exists()
    clock[0]=2001.0
    assert jobs.run(row['id'],adapter)['state']=='completed'


def test_untrusted_adapter_receipt_and_secret_error_never_enter_journal(rig):
    jobs,adapter,plan,clock=rig;row=requested(rig)
    class Wrong:
        mode='synthetic'
        def execute(self,op):return Receipt('wrong','done',evidence='0'*64)
    assert jobs.run_one(row['id'],Wrong())['code']=='invalid_receipt'
    class Failure:
        mode='synthetic'
        def execute(self,op):raise ValueError('TOKEN-secret /Users/private/file https://secret.invalid')
    result=jobs.run_one(row['id'],Failure())
    assert result['code']=='adapter_failed' and 'TOKEN' not in json.dumps(result)
    assert b'TOKEN-secret' not in jobs.path.read_bytes()
    class Other:
        mode='operator'
        def execute(self,op):pytest.fail('wrong mode adapter must not run')
    assert jobs.run_one(row['id'],Other())['code']=='adapter_mismatch'


def test_parallel_operator_cannot_run_same_stage_twice(rig):
    jobs,adapter,plan,clock=rig;row=requested(rig)
    entered=threading.Event();release=threading.Event()
    class Delayed:
        mode='synthetic'
        def execute(self,op):entered.set();assert release.wait(3);return adapter.execute(op)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(jobs.run_one,row['id'],Delayed())
        assert entered.wait(3)
        try:
            with pytest.raises(DeletionError,match='job_already_running'):jobs.run_one(row['id'],adapter)
        finally:release.set()
        assert future.result()['steps'][0]['attempts']==1


def test_fixture_rejects_symlink_without_touching_target_or_later_sources(rig,tmp_path):
    jobs,adapter,plan,clock=rig;row=requested(rig)
    outside=tmp_path/'outside';outside.mkdir();(outside/'valuable').write_text('keep')
    primary=adapter.root/digest('private_a')/'primary'
    (primary/'escape').symlink_to(outside,target_is_directory=True)
    result=jobs.run(row['id'],adapter)
    assert result['state']=='waiting' and result['code']=='unsafe_storage'
    assert (outside/'valuable').read_text()=='keep'
    assert (primary/'synthetic.txt').exists() and (adapter.root/digest('private_a')/'indexes').exists()


def test_fixture_cannot_adopt_arbitrary_folder_or_symlink(rig,tmp_path):
    _,adapter,_,_=rig
    with pytest.raises(DeletionError):SyntheticDeletionAdapter(tmp_path)
    link=tmp_path/'linked';link.symlink_to(adapter.root,target_is_directory=True)
    with pytest.raises(DeletionError):SyntheticDeletionAdapter(link)


@pytest.mark.parametrize('kind',['hardlink','fifo'])
def test_fixture_refuses_other_unsafe_nodes_without_erasing_outside(rig,tmp_path,kind):
    jobs,adapter,_,_=rig;row=requested(rig)
    outside=tmp_path/'valuable';outside.write_text('private outside fixture')
    target=adapter.root/digest('private_a')/'primary/unsafe'
    if kind=='hardlink':os.link(outside,target)
    else:os.mkfifo(target)
    result=jobs.run(row['id'],adapter)
    assert result['code']=='unsafe_storage' and result['state']=='waiting'
    assert outside.read_text()=='private outside fixture'
    assert (adapter.root/digest('private_a')/'primary/synthetic.txt').exists()


def test_finalization_checks_new_residual_files_instead_of_relying_on_prior_steps(rig):
    jobs,adapter,_,_=rig;row=requested(rig)
    while True:
        state=jobs.run_one(row['id'],adapter)
        if next(s for s in state['steps'] if s['phase']=='erase_backups')['state']=='succeeded':break
        assert state['state']!='waiting'
    (adapter.root/digest('private_a')/'new-residual.txt').write_text('new data must prevent final success')
    result=jobs.run(row['id'],adapter)
    assert result['state']=='waiting' and result['code']=='unsafe_storage'
    assert not adapter.snapshot()['accounts'][USER]['finalized']


def test_path_identifiers_and_existing_non_journal_directory_are_refused(tmp_path):
    target=tmp_path/'existing';target.mkdir(mode=0o700);(target/'valuable').write_text('keep')
    with pytest.raises(DeletionError,match='journal_directory_not_empty'):DeletionJobs(target,initialize=True)
    assert (target/'valuable').read_text()=='keep'
    jobs=DeletionJobs(tmp_path/'journal',initialize=True)
    with pytest.raises(DeletionError,match='invalid_identifier'):jobs.register('../other','private',[USER],owner_user_id=USER,instance_id='instance')


def test_one_instance_cannot_be_registered_to_two_tenants_or_boolean_revision(rig):
    jobs,_,_,_=rig
    with pytest.raises(DeletionError,match='instance_already_owned'):
        jobs.register('second','private',[OTHER],owner_user_id=OTHER,instance_id='instance_a')
    with pytest.raises(DeletionError,match='invalid_registry_revision'):
        jobs.register('private_a','private',[USER],owner_user_id=USER,instance_id='instance_a',revision=True)


def test_journal_refuses_world_readable_root_and_database_hardlink(tmp_path):
    public=tmp_path/'public';public.mkdir(mode=0o755)
    with pytest.raises(DeletionError,match='unsafe_storage'):DeletionJobs(public,initialize=True)
    assert not list(public.iterdir())
    jobs=DeletionJobs(tmp_path/'journal',initialize=True)
    os.link(jobs.path,tmp_path/'database-copy')
    with pytest.raises(DeletionError,match='unsafe_storage'):DeletionJobs(jobs.root)


def test_live_ownership_drift_stops_before_freeze_and_preserves_data(rig):
    jobs,adapter,plan,clock=rig;row=requested(rig)
    source=adapter.root/'fixture.json';value=json.loads(source.read_text())
    value['tenants']['private_a']['member_ids'].append(OTHER)
    source.write_text(json.dumps(value))
    result=jobs.run(row['id'],adapter)
    assert result['code']=='ownership_changed' and not adapter.snapshot()['accounts'][USER]['frozen']
    assert (adapter.root/digest('private_a')/'primary').exists()


def test_operator_cli_creates_and_reports_durable_job_without_fake_completion(tmp_path):
    common=['--journal',str(tmp_path/'journal')]
    assert run(common+['init'])['production_adapter_configured'] is False
    run(common+['register','--tenant','tenant','--classification','private','--owner',USER,'--member',USER,'--instance','instance'])
    plan=run(common+['plan','--user',USER])
    row=run(common+['request','--user',USER,'--request-key','cli_request_00001','--plan-revision',plan['revision']])
    pending=run(common+['resume','--job',row['id']])
    assert pending['state']=='waiting' and pending['code']=='adapter_unconfigured'
    assert run(common+['status','--job',row['id']])==pending
