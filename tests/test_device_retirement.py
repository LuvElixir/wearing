import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from wearing.cloud.device_provisioning import VM, Owner, fingerprint, inspect_capacity
from wearing.cloud.device_retirement import RETENTION_SOURCE
from wearing.cloud.proxmox_devices import REMOTE
from test_device_provisioning import NOW, Provider, spec, policy, reserve, setup


def retained_vm(provider, *, retired):
    item=spec()
    owner=Owner(**{k:getattr(item,k) for k in ('tenant_id','identity_id','resource_id','request_id','kind','vcpus','memory_mib','disk_mib')},request_sha256=fingerprint(item.model_dump()),nonce='d'*64)
    vm=VM(vmid=item.vmid,state='stopped',vcpus=item.vcpus,memory_mib=item.memory_mib,disk_mib=item.disk_mib,locked=retired,owner=owner,config_sha256='a'*64,retirement_sha256='b'*64 if retired else None)
    provider.vms.append(vm)
    return item,owner


def test_stopped_is_reserved_but_verified_retention_releases_only_compute_slots():
    other=spec(request_id='b'*32,tenant_id='new_person',vmid=1401,resource_id='new_computer')
    p=Provider();old,owner=retained_vm(p,retired=False)
    before=inspect_capacity(other,policy(),p.inventory(),[],now=NOW)
    assert not before['admitted'] and 'capacity_linux_slots' in before['reasons']
    p.vms[-1]=p.vms[-1].model_copy(update={'locked':True,'retirement_sha256':'b'*64})
    after=inspect_capacity(other,policy(),p.inventory(),[],now=NOW)
    assert after['admitted'] and after['demand']['linux_slots']==1
    assert after['demand']['vcpus']==other.vcpus and after['demand']['memory_mib']==other.memory_mib
    assert after['demand']['disk_mib']==before['demand']['disk_mib']
    assert after['demand']['disk_mib']>=old.disk_mib*2+other.disk_mib*2


@pytest.mark.parametrize('reuse', ['vmid','resource_id','tenant_id'])
def test_archived_ownership_still_excludes_reuse_after_local_ledger_loss(reuse):
    p=Provider();old,owner=retained_vm(p,retired=True)
    values={'request_id':'b'*32,'tenant_id':'new_person','vmid':1401,'resource_id':'new_computer'}
    values[reuse]=getattr(old,reuse)
    result=inspect_capacity(spec(**values),policy(linux_slots=5),p.inventory(),[],now=NOW)
    assert not result['admitted'] and 'device_binding_conflict' in result['reasons']


def test_existing_retired_ledger_row_is_preserved_and_not_double_reserved(setup):
    book,p=setup;plan=reserve(book,p);book.apply(spec().request_id,p,plan_sha256=plan)
    p.vms[-1]=p.vms[-1].model_copy(update={'locked':True,'retirement_sha256':'b'*64})
    new=spec(request_id='b'*32,tenant_id='new_person',vmid=1401,resource_id='new_computer')
    result=book.plan(new,policy(),p)
    assert result['admitted'] and result['demand']['vcpus']==new.vcpus
    assert book.status(spec().request_id)['state']=='staged'
    with pytest.raises(Exception,match='vm_owner_or_state_conflict'):book.apply(spec().request_id,p,plan_sha256=plan)


@pytest.mark.parametrize('changes',[{'state':'running'},{'locked':False},{'template':True},{'owner':None}])
def test_inventory_cannot_mark_unlocked_running_unowned_or_template_retired(changes):
    p=Provider();retained_vm(p,retired=True);data=p.vms[-1].model_dump();data.update(changes)
    with pytest.raises(ValueError,match='retained_vm_state_invalid'):VM.model_validate(data)


@pytest.fixture
def archive(tmp_path,monkeypatch):
    ns={};exec(RETENTION_SOURCE,ns)
    # These are real filesystem/inode/no-follow operations. Only root UID is
    # simulated so the same tests run under an unprivileged developer account.
    class RootStat:
        def __init__(self,value):self.value=value
        st_uid=0
        def __getattr__(self,key):return getattr(self.value,key)
    real_lstat=Path.lstat
    monkeypatch.setattr(Path,'lstat',lambda self:RootStat(real_lstat(self)))
    ns['os']=SimpleNamespace(**{key:getattr(os,key) for key in ('open','close','read','O_RDONLY','O_NOFOLLOW')},fstat=lambda fd:RootStat(os.fstat(fd)))
    root=tmp_path/'archives';root.mkdir(mode=0o700);directory=root/'1200';directory.mkdir(mode=0o700)
    p=Provider();item,owner=retained_vm(p,retired=True)
    config={'description':json.dumps({'pajio_provisioning':owner.model_dump()}),'onboot':0,'lock':'backup','memory':4096}
    data=directory/'retained.vma.zst';data.write_bytes(b'synthetic archive');data.chmod(0o600)
    backup={'version':1,'vmid':1200,'operation':'c'*32,'owner_sha256':fingerprint(owner.model_dump()),'zstd_verified':True,'vma_verified':True,'archive_sha256':hashlib.sha256(data.read_bytes()).hexdigest(),'archive_bytes':data.stat().st_size,'archive_mtime_ns':data.stat().st_mtime_ns}
    raw=json.dumps(backup).encode();(directory/'backup-proof.json').write_bytes(raw);(directory/'backup-proof.json').chmod(0o600)
    proof={'version':1,'kind':'execution','vmid':1200,'node':'pve01','operation':'c'*32,'owner_sha256':fingerprint(owner.model_dump()),'locked_config_sha256':fingerprint(config),'backup_proof_sha256':hashlib.sha256(raw).hexdigest(),'membership_fence_sha256':'1'*64,'maintenance_proof_sha256':'2'*64,'compute_released':True,'disks_retained':True}
    receipt=directory/'receipt.json';receipt.write_text(json.dumps(proof));receipt.chmod(0o600)
    return ns,root,directory,config,proof


def verify(a,state='stopped'):
    ns,root,directory,config,proof=a
    return ns['retained_archive_sha'](1200,config,state,'pve01',str(root))


def test_host_verifies_exact_proof_real_files_and_missing_receipt_reserves(archive):
    assert verify(archive)==hashlib.sha256((archive[2]/'receipt.json').read_bytes()).hexdigest()
    (archive[2]/'receipt.json').unlink()
    assert verify(archive) is None


@pytest.mark.parametrize('fault',['running','onboot','unlock','owner','receipt_public','archive_public','changed_archive','link','wrong_fence','wrong_backup'])
def test_invalid_host_archive_never_releases_compute(archive,fault):
    ns,root,directory,config,proof=archive
    if fault=='onboot':config['onboot']=1
    if fault=='unlock':config.pop('lock')
    if fault=='owner':config['description']=config['description'].replace('tenant_a','wrong_tenant')
    if fault=='receipt_public':(directory/'receipt.json').chmod(0o644)
    if fault=='archive_public':(directory/'retained.vma.zst').chmod(0o644)
    if fault=='changed_archive':(directory/'retained.vma.zst').write_bytes(b'corrupt')
    if fault=='link':
        (directory/'receipt.json').rename(directory/'actual.json');(directory/'receipt.json').symlink_to(directory/'actual.json')
    if fault=='wrong_fence':
        proof['membership_fence_sha256']='';(directory/'receipt.json').write_text(json.dumps(proof))
    if fault=='wrong_backup':(directory/'backup-proof.json').write_text('{}')
    with pytest.raises((ValueError,OSError)):verify(archive,state='running' if fault=='running' else 'stopped')


def test_provider_embeds_same_validator_for_preview_and_locked_final_admission():
    compile(REMOTE,'<proxmox remote>','exec')
    assert REMOTE.startswith(RETENTION_SOURCE)
    assert "retained_archive_sha(row['vmid'],c,row['status'],p['node'])" in REMOTE
    assert "if not item['retirement_sha256']:" in REMOTE
    assert REMOTE.index("backup+=o['disk_mib']+")<REMOTE.index("if not item['retirement_sha256']:")
    assert "assert_group_restores_complete(observed,p['node'])" in REMOTE


def test_unknown_group_restore_blocks_inventory_until_durable_done_and_live_core(archive):
    ns,root,*_=archive
    directory=root/'b-restore';directory.mkdir(mode=0o700)
    vms=[{'vmid':1102,'state':'stopped','template':False,'owner':None,'config_sha256':'9'*64}]
    check=lambda:ns['assert_group_restores_complete'](vms,'pve01',str(root))
    check()  # Only an empty directory; no mutation intent has begun.
    journal=directory/'journal.json'
    proof={'version':1,'node':'pve01','operation':'a'*32,'manifest_sha256':'b'*64,'core_vmid':1102,'core_config_sha256':'9'*64,'state':'started','phase':'core_start_sent'}
    def write():journal.write_text(json.dumps(proof));journal.chmod(0o600)
    write()
    with pytest.raises(ValueError,match='group_restore_capacity_unconfirmed'):check()
    # Even a running VM does not turn an unknown start into an acknowledged one.
    vms[0]['state']='running'
    with pytest.raises(ValueError,match='group_restore_capacity_unconfirmed'):check()
    proof.update(state='done',phase='core_running_devices_reserved');write();check()
    vms[0]['state']='stopped'
    with pytest.raises(ValueError,match='group_restore_capacity_unconfirmed'):check()
    vms[0]['state']='running';vms[0]['config_sha256']='8'*64
    with pytest.raises(ValueError,match='group_restore_capacity_unconfirmed'):check()


@pytest.mark.parametrize('fault',['symlink','public','hardlink','wrong_node','boolean_vmid'])
def test_group_restore_evidence_unsafe_is_never_ignored(archive,fault):
    ns,root,*_=archive;directory=root/'b-restore';directory.mkdir(mode=0o700)
    journal=directory/'journal.json'
    proof={'version':1,'node':'pve01','operation':'a'*32,'manifest_sha256':'b'*64,'core_vmid':1102,'core_config_sha256':'9'*64,'state':'done','phase':'core_running_devices_reserved'}
    if fault=='wrong_node':proof['node']='foreign'
    if fault=='boolean_vmid':proof['core_vmid']=True
    journal.write_text(json.dumps(proof));journal.chmod(0o600)
    if fault=='public':journal.chmod(0o644)
    if fault=='hardlink':os.link(journal,directory/'copy')
    if fault=='symlink':journal.rename(directory/'actual');journal.symlink_to(directory/'actual')
    vms=[{'vmid':1102,'state':'running','template':False,'owner':None,'config_sha256':'9'*64}]
    with pytest.raises((ValueError,OSError)):
        ns['assert_group_restores_complete'](vms,'pve01',str(root))


def test_real_power_start_trailer_skips_only_trusted_retired_commitments():
    from wearing.cloud.device_power_ssh import POWER_REMOTE
    source=POWER_REMOTE.split("if p['action']=='start':",1)[1]
    source="if p['action']=='start':"+source
    class Refused(Exception):pass
    def fail(code):raise Refused(code)
    target={'vmid':1401,'template':False,'owner':{'vcpus':1,'memory_mib':4096,'disk_mib':32768,'kind':'linux'},'state':'stopped','vcpus':1,'memory_mib':4096,'retirement_sha256':None,'disk_mib':32768}
    archived={'vmid':1211,'template':False,'owner':{'vcpus':2,'memory_mib':4096,'disk_mib':32768,'kind':'linux'},'state':'stopped','vcpus':2,'memory_mib':4096,'retirement_sha256':'b'*64,'disk_mib':32768}
    live={'vmid':1100,'template':False,'owner':None,'state':'running','vcpus':1,'memory_mib':3072,'retirement_sha256':None}
    inv={'core_promises':[],'vms':[target,archived,live],'physical_cores':4,'memory_mib':16384,'available_memory_mib':15000}
    head=REMOTE[REMOTE.index('def capacity_totals(inv):'):REMOTE.index('def checked_target(spec,expected):')]
    helpers={};exec(head,helpers)
    calls=[];ns={'capacity_totals':helpers['capacity_totals'],'p':{'action':'start','host_cores':2,'host_memory_mib':6144},'spec':{'vmid':1401,'memory_mib':4096},'inventory':lambda:inv,'fail':fail,'run_change':calls.append,'json':json}
    exec(source,ns);assert calls==[['qm','start','1401']]
    calls.clear();archived['retirement_sha256']=None
    with pytest.raises(Refused,match='wake_capacity_unavailable'):exec(source,ns)
    assert calls==[]
    archived['retirement_sha256']='b'*64;target['owner']['vcpus']=2
    with pytest.raises(Refused,match='wake_capacity_unavailable'):exec(source,ns)


def test_host_and_python_capacity_match_core_staged_running_and_retired():
    from wearing.cloud.device_provisioning import CorePromise
    p=Provider();retained_vm(p,retired=True)
    p.vms.append(VM(vmid=1401,state='running',vcpus=1,memory_mib=2048,disk_mib=32768,config_sha256='c'*64))
    core=CorePromise(vmid=1401,vcpus=2,memory_mib=4096,disk_mib=32768)
    missing=CorePromise(vmid=1402,vcpus=1,memory_mib=2048,disk_mib=32768)
    inv=p.inventory().model_copy(update={'core_promises':(core,missing)})
    head=REMOTE[REMOTE.index('def capacity_totals(inv):'):REMOTE.index('def checked_target(spec,expected):')]
    ns={};exec(head,ns);host=ns['capacity_totals'](inv.model_dump(mode='json'))
    assert host['vcpus']==3 and host['memory_mib']==6144 and host['linux_slots']==0
    new=spec(request_id='b'*32,tenant_id='new_person',vmid=1411,resource_id='new_computer')
    result=inspect_capacity(new,policy(),inv,[],now=NOW)
    assert result['demand']['vcpus']==host['vcpus']+new.vcpus
    assert result['demand']['memory_mib']==host['memory_mib']+new.memory_mib
    assert result['demand']['disk_mib']==inv.committed_storage_mib+host['recovery_and_missing_disk_mib']+new.disk_mib*2+4
    collision=inspect_capacity(new.model_copy(update={'vmid':1402}),policy(),inv,[],now=NOW)
    assert not collision['admitted'] and 'core_vm_binding_conflict' in collision['reasons']
