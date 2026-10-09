"""Synthetic control DB, synthetic resource IDs, injected cloud CLI only."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest
from sqlalchemy import select, update

from wearing.account_deletion import DeletionError, DeletionJobs, Operation, digest
from wearing.account_deletion_operator import OperatorRegistry, ProductionDeletionAdapter, checked_asset
from wearing.cloud.account_deletion_control import AccountDeletionControl
from wearing.cloud.control import ControlStore, members
from wearing.cloud.deletion_tencent import DeletionTencentCLI, TencentDeletionProvider


def asset(user='user_a', **changes):
    return dict(tenant_id='tenant_a', instance_id='instance_a', owner_user_id=user,
                account_id='123456', region='ap-hongkong', cvm_id='ins-aaaaaaaa',
                system_disk_id='disk-aaaaaaaa', disk_ids=['disk-aaaaaaaa','disk-bbbbbbbb'],
                snapshot_ids=['snap-aaaaaaaa'], exclusive=True, complete=True,
                indexes_on_disks=True, backups_only_snapshots=True, other_resources=[],
                worker_upstream='https://tenant.invalid', operator_credential_ref='tenant_a.key', **changes)


class FakeCLI:
    region='ap-hongkong'
    def __init__(self):
        self.calls, self.lose, self.truncated = [], None, False
        self.account='123456'
        self.vm = {'InstanceId':'ins-aaaaaaaa','InstanceState':'RUNNING','LatestOperationState':'SUCCESS',
                   'InstanceChargeType':'POSTPAID_BY_HOUR','SystemDisk':{'DiskId':'disk-aaaaaaaa'},
                   'DataDisks':[{'DiskId':'disk-bbbbbbbb'}]}
        self.disks = [{'DiskId':d,'DiskState':'ATTACHED','Attached':True,'InstanceId':'ins-aaaaaaaa',
                       'AutoSnapshotPolicyIds':[], 'InstanceIdList':[], 'DiskBackupCount':0,
                       'BackupDisk':False,'DiskChargeType':'POSTPAID_BY_HOUR'} for d in ['disk-aaaaaaaa','disk-bbbbbbbb']]
        self.snapshots = [{'SnapshotId':'snap-aaaaaaaa','DiskId':'disk-bbbbbbbb','SnapshotState':'NORMAL',
                           'SnapshotType':'PRIVATE_SNAPSHOT','ShareReference':0,'Images':[], 'CopyingToRegions':[],
                           'CopyFromRemote':False,'IsLocked':False,'AutoSnapshotPolicyId':''}]
    def call(self, service, action, params):
        self.calls.append((service, action, deepcopy(params)))
        result={'RequestId':'synthetic-request'}
        if action=='GetCallerIdentity': return dict(result,AccountId=self.account)
        if action=='DescribeInstances':
            assert params['InstanceIds']==['ins-aaaaaaaa']
            rows=[self.vm] if self.vm else [];return dict(result,TotalCount=len(rows),InstanceSet=deepcopy(rows))
        if action=='DescribeDisks':
            assert params['DiskIds']==['disk-aaaaaaaa','disk-bbbbbbbb']
            return dict(result,TotalCount=len(self.disks)+(1 if self.truncated else 0),DiskSet=deepcopy(self.disks) if params['Offset']==0 else [])
        if action=='DescribeSnapshots':
            disk=params['Filters'][0]['Values'][0]
            rows=[s for s in self.snapshots if s['DiskId']==disk]
            return dict(result,TotalCount=len(rows),SnapshotSet=deepcopy(rows))
        if action=='StopInstances':
            assert params=={'InstanceIds':['ins-aaaaaaaa'],'StopType':'SOFT','StoppedMode':'KEEP_CHARGING'}
            self.vm['InstanceState']='STOPPED'
        elif action=='TerminateInstances':
            assert params=={'InstanceIds':['ins-aaaaaaaa'],'ReleaseAddress':False,'ReleasePrepaidDataDisks':False}
            self.vm=None;self.disks=self.disks[1:]
            self.disks[0].update(InstanceId='',Attached=False,DiskState='UNATTACHED')
        elif action=='TerminateDisks':
            assert params=={'DiskIds':['disk-bbbbbbbb'],'DeleteSnapshot':0};self.disks=[]
        elif action=='DeleteSnapshots':
            assert params=={'SnapshotIds':['snap-aaaaaaaa'],'DeleteBindImages':False};self.snapshots=[]
        else: raise AssertionError(action)
        if action==self.lose: raise DeletionError('provider_unavailable')
        return result
    @property
    def mutations(self): return [c for c in self.calls if not c[1].startswith(('Describe','Get'))]


class FakeTenant:
    def __init__(self): self.calls=[];self.block=None
    def execute(self,a,p):
        self.calls.append(deepcopy(p))
        if self.block==p['phase']: raise DeletionError('adapter_unconfigured')
        return {'request':p,'state':'done','evidence':digest(['synthetic',p])}


@pytest.fixture
def stack(tmp_path):
    control=ControlStore('sqlite:///'+str(tmp_path/'control.db'),initialize=True,operator=True)
    user=control.grant('fixture','alice','tenant_a')
    other=control.grant('fixture','bob','tenant_b')
    control.bind('tenant_a','instance_a','https://tenant.invalid','a.json')
    control.bind('tenant_b','instance_b','https://other.invalid','b.json')
    sid=control.login('fixture','alice'); session=control.session(sid)
    ctl=AccountDeletionControl(control)
    ctl.register('tenant_a','private',owner_user_id=session.user_id)
    plan=ctl.preview(session); req=ctl.request(session,'test-request-key-0001',plan['revision'])
    jobs=DeletionJobs(tmp_path/'journal',initialize=True)
    registry=OperatorRegistry(jobs);a=asset(session.user_id);registry.register(a)
    fake=FakeCLI();provider=TencentDeletionProvider(jobs,fake);tenant=FakeTenant()
    adapter=ProductionDeletionAdapter(control,jobs,registry,lambda a:provider,tenant)
    yield control,ctl,req,jobs,registry,fake,tenant,adapter,a
    control.close()


def finish(adapter,job):
    for _ in range(10):
        result=adapter.resume(job['id'])
        if result['state']=='completed':return result
    raise AssertionError(result)


def test_complete_pipeline_freezes_imports_reconciles_and_marks_actual_receipt(stack):
    control,ctl,req,jobs,registry,cloud,tenant,adapter,a=stack
    job=adapter.prepare(req['id'])
    assert ctl.status(req['user_id'],job_id=req['id'])['data_erased'] is False
    first=adapter.resume(job['id'])
    assert first['state']=='waiting' and len(cloud.mutations)==1
    assert ctl.status(req['user_id'],job_id=req['id'])['state']=='waiting'
    result=finish(adapter,job)
    assert result['state']=='completed' and all(s['evidence'] for s in result['steps'])
    receipt=ctl.status(req['user_id'],job_id=req['id'])
    assert receipt['state']=='completed' and receipt['data_erased'] is True
    assert [c[1] for c in cloud.mutations]==['StopInstances','TerminateInstances','TerminateDisks','DeleteSnapshots']
    assert [c['phase'] for c in tenant.calls]==['freeze_tenant','freeze_tenant','revoke_credentials','revoke_devices','drain_actions']
    assert control.session(control.login('fixture','bob')).tenant_id=='tenant_b'
    before=deepcopy(cloud.calls); assert adapter.resume(job['id'])==result; assert cloud.calls==before
    assert adapter.prepare(req['id'])['id']==job['id']


@pytest.mark.parametrize('lost',['StopInstances','TerminateInstances','TerminateDisks','DeleteSnapshots'])
def test_response_loss_never_repeats_mutation_and_reconciles_readback(stack,lost):
    *_,cloud,tenant,adapter,a=stack
    cloud.lose=lost;job=adapter.prepare(stack[2]['id'])
    assert finish(adapter,job)['state']=='completed'
    assert sum(c[1]==lost for c in cloud.mutations)==1


def test_lost_request_without_provider_effect_stays_waiting_not_replayed(stack):
    cloud,adapter=stack[5],stack[7]; original=cloud.call
    def lost(service, action, params):
        if action=='StopInstances':
            cloud.calls.append((service,action,deepcopy(params)))
            raise DeletionError('provider_unavailable')
        return original(service,action,params)
    cloud.call=lost;job=adapter.prepare(stack[2]['id'])
    for _ in range(3): assert adapter.resume(job['id'])['state']=='waiting'
    assert len(cloud.mutations)==1
    assert stack[1].status(stack[2]['user_id'],job_id=stack[2]['id'])['data_erased'] is False


@pytest.mark.parametrize('change', ['other_account','region','attached_peer','shared_disk','new_snapshot','shared_snapshot','image','auto_backup','unknown_policy','extra_disk','truncated','prepaid'])
def test_unknown_or_shared_assets_cannot_start_cloud_mutation(stack,change):
    cloud,adapter=stack[5],stack[7]
    if change=='other_account':cloud.account='999'
    if change=='region':cloud.region='ap-beijing'
    if change=='attached_peer':cloud.disks[1]['InstanceId']='ins-zzzzzzzz'
    if change=='shared_disk':cloud.disks[1]['InstanceIdList']=['ins-zzzzzzzz']
    if change=='new_snapshot':cloud.snapshots.append(dict(cloud.snapshots[0],SnapshotId='snap-bbbbbbbb'))
    if change=='shared_snapshot':cloud.snapshots[0]['ShareReference']=1
    if change=='image':cloud.snapshots[0]['Images']=[{'ImageId':'img-aaaaaaaa'}]
    if change=='auto_backup':cloud.disks[1]['BackupDisk']=True
    if change=='unknown_policy':cloud.disks[1]['AutoSnapshotPolicyIds']=None
    if change=='extra_disk':cloud.vm['DataDisks'].append({'DiskId':'disk-cccccccc'})
    if change=='truncated':cloud.truncated=True
    if change=='prepaid':cloud.vm['InstanceChargeType']='PREPAID'
    job=adapter.prepare(stack[2]['id']);assert adapter.resume(job['id'])['state']=='waiting'
    assert cloud.mutations==[]


def test_upstream_revocation_block_preserves_vm_and_account_waiting(stack):
    stack[6].block='revoke_credentials';adapter=stack[7];job=adapter.prepare(stack[2]['id'])
    result=adapter.resume(job['id']);assert result['code']=='adapter_unconfigured'
    assert stack[5].calls==[] and stack[1].status(stack[2]['user_id'],job_id=stack[2]['id'])['data_erased'] is False


def test_unknown_registry_and_second_membership_fail_closed(stack):
    with stack[3].tx() as db:db.execute('DELETE FROM deletion_assets')
    with pytest.raises(DeletionError,match='incomplete_registry'):stack[7].prepare(stack[2]['id'])
    assert stack[5].calls==[]


def test_registry_never_reassigns_or_reuses_assets(stack):
    registry,a=stack[4],stack[8]
    for change in [{'owner_user_id':'other'},{'tenant_id':'tenant_b','instance_id':'instance_b'}]:
        with pytest.raises(DeletionError):registry.register({**a,**change})
    for key in ('complete','exclusive','indexes_on_disks','backups_only_snapshots'):
        with pytest.raises(DeletionError):checked_asset({**a,key:False})
    with pytest.raises(DeletionError):checked_asset({**a,'operator_credential_ref':'../secret.key'})
    with pytest.raises(DeletionError):checked_asset({**a,'disk_ids':[{}]})


def test_live_control_change_prevents_provider_call(stack):
    adapter=stack[7];job=adapter.prepare(stack[2]['id'])
    with stack[0].transaction(mutating=True) as db:
        db.execute(update(members).where(members.c.tenant_id=='tenant_a').values(active=True))
    result=adapter.resume(job['id']);assert result['code']=='ownership_changed'
    assert stack[5].calls==[] and stack[6].calls==[]


def test_separate_cli_denies_unlisted_actions_without_executing(monkeypatch):
    monkeypatch.setattr('shutil.which',lambda name:'/synthetic/tccli')
    client=DeletionTencentCLI('fixture','ap-hongkong')
    with pytest.raises(DeletionError):client.call('cvm','RunInstances',{})
    from wearing.cloud.tencent import READ_ACTIONS
    assert 'TerminateInstances' not in READ_ACTIONS['cvm']


def test_no_production_cli_execution_without_explicit_operator_flag(tmp_path):
    from wearing.account_deletion_cli import run
    root=tmp_path/'journal';DeletionJobs(root,initialize=True)
    with pytest.raises(DeletionError,match='explicit_operator_execution_required'):
        run(['--journal',str(root),'operator-resume','--gateway-root','/does-not-exist',
             '--job','a'*32,'--profile','fixture','--operator-keys','/does-not-exist'])


def test_tenant_http_client_requires_exact_independent_readback(tmp_path):
    import httpx
    from wearing.account_deletion_operator import TenantDeletionClient
    from wearing.profile import write_private_text
    write_private_text(tmp_path/'tenant_a.key','x'*64)
    request={'job_id':'a'*32,'plan_revision':'b'*64,'operation_id':'c'*64,'tenant_id':'tenant_a',
             'instance_id':'instance_a','phase':'freeze_tenant','owner_scope':'d'*64}
    seen=[]; wrong=[False]
    def handle(req):
        seen.append(req.method)
        assert req.url.path=='/internal/account-deletion' and req.headers['authorization']=='Bearer '+'x'*64
        value={'request':request,'state':'done','evidence':'e'*64}
        if wrong[0] and req.method=='GET':value['request']={**request,'job_id':'f'*32}
        return httpx.Response(200,json=value)
    client=TenantDeletionClient(tmp_path,transport=httpx.MockTransport(handle))
    assert client.execute(asset(),request)['state']=='done' and seen==['POST','GET']
    wrong[0]=True
    with pytest.raises(DeletionError,match='provider_unavailable'):client.execute(asset(),request)


def test_recycled_cvm_or_disk_and_snapshot_never_count_as_erased(stack):
    adapter,cloud=stack[7],stack[5];job=adapter.prepare(stack[2]['id'])
    adapter.resume(job['id']) # request stop
    adapter.resume(job['id']) # request termination
    cloud.vm={'InstanceId':'ins-aaaaaaaa','InstanceState':'SHUTDOWN','LatestOperationState':'SUCCESS',
              'InstanceChargeType':'POSTPAID_BY_HOUR','SystemDisk':{'DiskId':'disk-aaaaaaaa'},'DataDisks':[{'DiskId':'disk-bbbbbbbb'}]}
    for _ in range(2): assert adapter.resume(job['id'])['state']=='waiting'
    assert sum(c[1]=='TerminateInstances' for c in cloud.mutations)==1
    cloud.vm=None;cloud.disks[0]['DiskState']='TORECYCLE'
    assert adapter.resume(job['id'])['state']=='waiting'
    assert not any(c[1]=='TerminateDisks' for c in cloud.mutations)
    cloud.disks=[];cloud.snapshots[0]['SnapshotState']='TORECYCLE'
    result=adapter.resume(job['id'])
    assert result['code']=='backup_retained' and not any(c[1]=='DeleteSnapshots' for c in cloud.mutations)
    assert stack[1].status(stack[2]['user_id'],job_id=stack[2]['id'])['data_erased'] is False


def test_changed_inventory_after_stop_blocks_termination(stack):
    adapter,cloud=stack[7],stack[5];job=adapter.prepare(stack[2]['id'])
    adapter.resume(job['id'])
    cloud.snapshots.append(dict(cloud.snapshots[0],SnapshotId='snap-cccccccc'))
    assert adapter.resume(job['id'])['code']=='incomplete_registry'
    assert [c[1] for c in cloud.mutations]==['StopInstances']


def test_exact_cli_transport_uses_no_shell_and_sanitizes_failures(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    monkeypatch.setattr('shutil.which',lambda name:'/synthetic/tccli')
    seen=[]
    def run(command,**kwargs):
        assert kwargs=={'capture_output':True,'text':True,'timeout':30}
        assert command[:3]==['/synthetic/tccli','cvm','StopInstances']
        assert '--endpoint' in command and 'cvm.tencentcloudapi.com' in command
        from pathlib import Path
        from urllib.parse import urlparse
        path=Path(urlparse(command[-1]).path)
        assert path.stat().st_mode&0o077==0
        seen.append(json.loads(path.read_text()))
        return SimpleNamespace(returncode=0,stdout='{"Response":{"RequestId":"fixture"}}',stderr='')
    monkeypatch.setattr(subprocess,'run',run)
    cli=DeletionTencentCLI('fixture','ap-hongkong')
    p={'InstanceIds':['ins-aaaaaaaa'],'StopType':'SOFT','StoppedMode':'KEEP_CHARGING'}
    assert cli.call('cvm','StopInstances',p)=={'RequestId':'fixture'} and seen==[p]
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout='not-json PRIVATE_SECRET',stderr='PRIVATE_SECRET'))
    with pytest.raises(DeletionError) as failure:cli.call('cvm','StopInstances',p)
    assert str(failure.value)=='provider_unavailable'
