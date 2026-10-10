import copy
import hashlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from wearing.cloud.resource_reservations import RESOURCE_RESERVATIONS_SOURCE
from wearing.cloud.proxmox_devices import REMOTE
from wearing.cloud.device_provisioning import Inventory, ResourcePromise


def raw(value):
    return json.dumps(value, sort_keys=True).encode()


def fixture(tmp_path, purpose='benchmark'):
    base = tmp_path / 'resources'
    base.mkdir(mode=0o700)
    folder = base / ('a' * 32)
    folder.mkdir(mode=0o700)
    members = []
    kinds = ('linux',) if purpose == 'benchmark' else ('core', 'linux', 'android')
    for index, kind in enumerate(kinds):
        members.append(dict(kind=kind, vmid=1900 + index, request_id=str(index + 1) * 32,
                            vcpus=1, memory_mib=4096, disk_mib=32768,
                            image_sha256='b' * 64, core_reservation_sha256='c' * 64 if kind == 'core' else None))
    value = dict(version=1, reservation_id='a' * 32, node='pve01', purpose=purpose,
                 tenant_id='new_person' if purpose == 'invitation' else None,
                 created_at=1, expires_at=4102444800, members=members)
    (folder / 'reservation.json').write_bytes(raw(value))
    (folder / 'reservation.json').chmod(0o600)
    return base, folder, value


def validators():
    ns = {}
    exec(RESOURCE_RESERVATIONS_SOURCE, ns)
    lstat, fstat = Path.lstat, os.fstat
    def owned(s):
        return SimpleNamespace(st_mode=s.st_mode, st_uid=0, st_nlink=s.st_nlink, st_size=s.st_size)
    return ns, patch.object(Path, 'lstat', lambda p: owned(lstat(p))), patch.object(os, 'fstat', lambda fd: owned(fstat(fd)))


def query_result(value):
    return SimpleNamespace(returncode=0, stdout=json.dumps(value))


def totals(inv):
    source = REMOTE.split("for key in ('node','storage','vg','pool'):")[0]
    ns = {}
    exec(source.replace('p=json.load(sys.stdin)', "p={}"), ns)
    return ns['capacity_totals'](inv)


def test_expired_uncreated_and_stopped_fixture_remain_fully_charged(tmp_path):
    base, folder, value = fixture(tmp_path)
    value['expires_at'] = 2
    (folder/'reservation.json').write_bytes(raw(value))
    ns, a, b = validators()
    with a, b:
        promise = ns['resource_reservations']([], str(base), core_root=str(tmp_path/'cores'))
        assert promise[0]['owner'] is None
        inv = dict(vms=[], core_promises=[], resource_promises=promise)
        result = totals(inv)
        assert (result['vcpus'], result['memory_mib'], result['linux_slots']) == (1, 4096, 1)
        assert result['recovery_and_missing_disk_mib'] == 65540
        member = value['members'][0]
        row = dict(vmid=1900, state='stopped', template=False, owner=None,
                   vcpus=1, memory_mib=4096, disk_mib=32768, retirement_sha256=None)
        config = {'description': json.dumps({'pajio_benchmark': {'reservation_id': value['reservation_id'], 'member': member}})}
        with patch.object(ns['subprocess'], 'run', return_value=query_result(config)):
            inv['resource_promises'] = ns['resource_reservations']([row], str(base), core_root=str(tmp_path/'cores'))
        inv['vms'] = [row]
        assert totals(inv)['memory_mib'] == 4096
        assert totals(inv)['recovery_and_missing_disk_mib'] == 32768


@pytest.mark.parametrize('mutation', ['unsafe', 'hardlink', 'symlink', 'extra_flag', 'incomplete'])
def test_unsafe_and_partial_records_fail_closed(tmp_path, mutation):
    base, folder, value = fixture(tmp_path)
    path = folder/'reservation.json'
    if mutation == 'unsafe': path.chmod(0o644)
    elif mutation == 'hardlink': os.link(path, tmp_path/'alias')
    elif mutation == 'symlink': path.rename(tmp_path/'original'); path.symlink_to(tmp_path/'original')
    elif mutation == 'extra_flag': path.write_bytes(raw({**value, 'ready': True}))
    else: path.unlink()
    ns, a, b = validators()
    with a, b, pytest.raises((ValueError, OSError)):
        ns['resource_reservations']([], str(base), core_root=str(tmp_path/'cores'))


def test_released_requires_live_absence_of_every_vm_and_owned_volume(tmp_path):
    base, folder, value = fixture(tmp_path)
    receipt = dict(version=1, reservation_sha256=hashlib.sha256((folder/'reservation.json').read_bytes()).hexdigest(), removed_vmids=[1900])
    (folder/'released.json').write_bytes(raw(receipt)); (folder/'released.json').chmod(0o600)
    ns, a, b = validators()
    with a, b:
        with patch.object(ns['subprocess'], 'run', return_value=query_result([])):
            assert ns['resource_reservations']([], str(base), core_root=str(tmp_path/'cores')) == []
            with pytest.raises(ValueError): ns['resource_reservations']([{'vmid': 1900}], str(base), core_root=str(tmp_path/'cores'))
        with patch.object(ns['subprocess'], 'run', return_value=query_result([{'vmid': 1900}])):
            with pytest.raises(ValueError): ns['resource_reservations']([], str(base), core_root=str(tmp_path/'cores'))


def test_exact_core_and_bundle_dual_source_is_counted_once(tmp_path):
    base, folder, value = fixture(tmp_path, 'invitation')
    member = value['members'][0]
    core = dict(version=1, node='pve01', tenant_id='new_person', **{k: member[k] for k in ('vmid','request_id','vcpus','memory_mib','disk_mib','image_sha256')})
    corebase = tmp_path/'cores'; corebase.mkdir(mode=0o700)
    corefolder = corebase/'1900'; corefolder.mkdir(mode=0o700)
    corepath = corefolder/'reservation.json'; corepath.write_bytes(raw(core)); corepath.chmod(0o600)
    value['members'][0]['core_reservation_sha256'] = hashlib.sha256(corepath.read_bytes()).hexdigest()
    (folder/'reservation.json').write_bytes(raw(value))
    ns, a, b = validators()
    with a, b:
        promises = ns['resource_reservations']([], str(base), core_root=str(corebase))
        inv = dict(vms=[], core_promises=[{k: member[k] for k in ('vmid','vcpus','memory_mib','disk_mib')}], resource_promises=promises)
        assert totals(inv)['vcpus'] == 3
        assert totals(inv)['memory_mib'] == 12288
        assert totals(inv)['recovery_and_missing_disk_mib'] == 3*65540
        corepath.write_bytes(raw({**core, 'tenant_id': 'different'}))
        with pytest.raises(ValueError): ns['resource_reservations']([], str(base), core_root=str(corebase))
        inv['core_promises'][0]['memory_mib'] += 1
        with pytest.raises(ValueError): totals(inv)


def test_claim_is_exact_and_retired_vm_releases_compute_but_keeps_disk(tmp_path):
    base, folder, value = fixture(tmp_path, 'invitation')
    member = value['members'][1]
    owner = dict(version=1, tenant_id='new_person', identity_id='identity_real', resource_id='computer_real',
                 request_sha256='d'*64, nonce='e'*64, **{k:member[k] for k in ('request_id','kind','vcpus','memory_mib','disk_mib')})
    ns, a, b = validators()
    with a, b:
        promises = ns['resource_reservations']([], str(base), core_root=str(tmp_path/'cores'))
        ns['bind_resource_claim'](promises[1], owner, str(base))
        old = (folder/'claim-1901.json').read_bytes()
        ns['bind_resource_claim'](promises[1], owner, str(base))
        assert (folder/'claim-1901.json').read_bytes() == old
        with pytest.raises(ValueError): ns['bind_resource_claim'](promises[1], {**owner,'identity_id':'other'}, str(base))
        row = dict(vmid=1901, state='stopped', template=False, owner=owner, vcpus=1, memory_mib=4096, disk_mib=32768, retirement_sha256='f'*64)
        promises = ns['resource_reservations']([row], str(base), core_root=str(tmp_path/'cores'))
        result = totals(dict(vms=[row], core_promises=[], resource_promises=promises))
        assert result['vcpus'] == 2 and result['memory_mib'] == 8192 and result['linux_slots'] == 0
        assert result['recovery_and_missing_disk_mib'] == 2*65540+32768
        with pytest.raises(ValueError): ns['resource_reservations']([{**row,'owner':{**owner,'nonce':'1'*64}}], str(base), core_root=str(tmp_path/'cores'))


def test_benchmark_cannot_claim_a_user_owner(tmp_path):
    base, folder, value = fixture(tmp_path)
    ns, a, b = validators()
    with a, b:
        promise = ns['resource_reservations']([], str(base), core_root=str(tmp_path/'cores'))[0]
        with pytest.raises(ValueError): ns['bind_resource_claim'](promise, {}, str(base))


def test_new_record_does_not_rewrite_existing_core_or_other_reservations(tmp_path):
    base, folder, value = fixture(tmp_path)
    before = (folder/'reservation.json').read_bytes()
    other = base/('c'*32);other.mkdir(mode=0o700)
    (other/'reservation.json').write_bytes(raw({**value,'reservation_id':'c'*32}));(other/'reservation.json').chmod(0o600)
    ns, a, b = validators()
    with a, b, pytest.raises(ValueError): ns['resource_reservations']([], str(base), core_root=str(tmp_path/'cores'))
    assert (folder/'reservation.json').read_bytes() == before


def test_preclaim_and_operator_ledger_request_count_once_and_require_real_admission(tmp_path):
    from test_device_provisioning import Provider, spec, policy, SyntheticAdmission, NOW
    from wearing.cloud.device_provisioning import ProvisionBook, ProvisionError, inspect_capacity
    item = spec()
    promise = ResourcePromise(reservation_id='c'*32, reservation_sha256='d'*64,
                              purpose='invitation', expires_at=4102444800, tenant_id=item.tenant_id, kind=item.kind,
                              request_id=item.request_id, vmid=item.vmid, vcpus=item.vcpus,
                              memory_mib=item.memory_mib, disk_mib=item.disk_mib)
    provider = Provider(); provider.extra = {'resource_promises': (promise,)}
    plan = inspect_capacity(item, policy(), provider.inventory(), [], now=NOW)
    assert plan['admitted'] and plan['demand']['vcpus'] == 2
    assert plan['demand']['memory_mib'] == 4096 and plan['demand']['linux_slots'] == 1
    book = ProvisionBook(tmp_path/'no-admission', operator=True, clock=lambda: NOW)
    with pytest.raises(ProvisionError, match='account_admission_required'):
        book.plan(item, policy(), provider)
    book = ProvisionBook(tmp_path/'admitted', operator=True, clock=lambda: NOW, admission=SyntheticAdmission())
    planned = book.plan(item, policy(), provider)
    book.reserve(item, policy(), provider, plan_sha256=planned['plan_sha256'])
    assert book.plan(item, policy(), provider)['demand'] == planned['demand']
    conflict = item.model_copy(update={'tenant_id':'other'})
    refused = inspect_capacity(conflict, policy(), provider.inventory(), [], now=NOW)
    assert not refused['admitted'] and 'preclaim_binding_conflict' in refused['reasons']


def test_host_clone_records_preclaim_owner_before_single_qm_dispatch(tmp_path):
    import ast
    from test_device_provisioning import spec, policy
    from wearing.cloud.device_provisioning import Owner, fingerprint
    item=spec();owner=Owner(tenant_id=item.tenant_id,identity_id=item.identity_id,resource_id=item.resource_id,
        request_id=item.request_id,request_sha256=fingerprint(item.model_dump()),nonce='b'*64,kind=item.kind,
        vcpus=item.vcpus,memory_mib=item.memory_mib,disk_mib=item.disk_mib).model_dump()
    tree=ast.parse(REMOTE)
    branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="action == 'clone_stopped'")
    template=dict(vmid=9000,template=True,state='stopped',locked=False,owner=None,config_sha256='f'*64,disk_mib=32768)
    promise=dict(reservation_id='c'*32,reservation_sha256='d'*64,purpose='invitation',expires_at=4102444800,tenant_id=item.tenant_id,kind=item.kind,
                 request_id=item.request_id,vmid=item.vmid,vcpus=item.vcpus,memory_mib=item.memory_mib,disk_mib=item.disk_mib,owner=None)
    inv=dict(vms=[template],core_promises=[],resource_promises=[promise],physical_cores=4,memory_mib=10240,available_memory_mib=10240,committed_storage_mib=32772,storage_mib=1048576,available_storage_mib=900000)
    calls=[]
    def fail(code):raise ValueError(code)
    ns=dict(inventory=lambda:inv,capacity_totals=totals,spec=item.model_dump(),policy=policy().model_dump(),expected=owner,
            p={'storage':'local-lvm'},config=lambda _: {'onboot':0},fail=fail,json=json,time=time,
            bind_resource_claim=lambda p,o:calls.append(('claim',o)),run_change=lambda argv:calls.append(('qm',argv)),checked_target=lambda *a:None)
    exec(compile(ast.Module(body=branch.body,type_ignores=[]),'actual-clone-preclaim','exec'),ns)
    assert [c[0] for c in calls]==['claim','qm']
    calls.clear();promise['tenant_id']='foreign'
    with pytest.raises(ValueError,match='preclaim_binding_conflict'):
        exec(compile(ast.Module(body=branch.body,type_ignores=[]),'actual-clone-preclaim','exec'),ns)
    assert calls==[]


def claimed_case():
    from test_device_provisioning import spec, Provider
    from wearing.cloud.device_provisioning import Owner, fingerprint
    item = spec()
    owner = Owner(tenant_id=item.tenant_id, identity_id=item.identity_id,
                  resource_id=item.resource_id, request_id=item.request_id,
                  request_sha256=fingerprint(item.model_dump()), nonce='e'*64,
                  kind=item.kind, vcpus=item.vcpus, memory_mib=item.memory_mib, disk_mib=item.disk_mib)
    promise = ResourcePromise(reservation_id='c'*32, reservation_sha256='d'*64,
                              purpose='invitation', tenant_id=item.tenant_id, kind=item.kind,
                              request_id=item.request_id, vmid=item.vmid, vcpus=item.vcpus,
                              memory_mib=item.memory_mib, disk_mib=item.disk_mib,
                              owner=owner, expires_at=4102444800)
    provider = Provider(); provider.extra = {'resource_promises': (promise,)}
    return item, owner, promise, provider


@pytest.mark.parametrize('changes', [
    {},
    {'request_id':'b'*32,'resource_id':'computer_again','vmid':1201},
    {'request_id':'b'*32,'resource_id':'computer_a','tenant_id':'other','vmid':1201},
    {'vmid':1201},
])
def test_missing_vm_claim_survives_lost_operator_ledger_and_blocks_reclone(tmp_path, changes):
    from test_device_provisioning import policy, SyntheticAdmission, NOW
    from wearing.cloud.device_provisioning import ProvisionBook, ProvisionError
    item, owner, promise, provider = claimed_case()
    book = ProvisionBook(tmp_path/'fresh-ledger', operator=True, clock=lambda:NOW, admission=SyntheticAdmission())
    altered = item.model_copy(update=changes)
    plan = book.plan(altered, policy(), provider)
    assert not plan['admitted']
    assert set(plan['reasons']).intersection({'clone_outcome_unknown_no_replay','device_binding_conflict','idempotency_request_changed'})
    with pytest.raises(ProvisionError):book.reserve(altered, policy(), provider, plan_sha256=plan['plan_sha256'])
    assert provider.calls == []


def test_expired_first_claim_remains_charged_but_cannot_be_bound(tmp_path):
    base, folder, value = fixture(tmp_path, 'invitation')
    value['expires_at'] = 2; (folder/'reservation.json').write_bytes(raw(value))
    member = value['members'][1]
    owner = dict(version=1, tenant_id='new_person', identity_id='real_identity', resource_id='computer_real',
                 request_sha256='d'*64, nonce='e'*64, **{k:member[k] for k in ('request_id','kind','vcpus','memory_mib','disk_mib')})
    ns, a, b = validators()
    with a, b:
        promises = ns['resource_reservations']([], str(base), core_root=str(tmp_path/'cores'))
        assert totals(dict(vms=[], core_promises=[], resource_promises=promises))['vcpus'] == 3
        with pytest.raises(ValueError, match='preclaim_expired'):ns['bind_resource_claim'](promises[1], owner, str(base))
    assert not (folder/'claim-1901.json').exists()
    from test_device_provisioning import policy, NOW
    from wearing.cloud.device_provisioning import inspect_capacity
    item, _, promise, provider = claimed_case()
    provider.extra = {'resource_promises':(promise.model_copy(update={'owner':None,'expires_at':2}),)}
    result=inspect_capacity(item, policy(), provider.inventory(), [], now=NOW)
    assert not result['admitted'] and 'preclaim_expired' in result['reasons']
    assert result['demand']['vcpus']==item.vcpus


def test_inventory_rejects_duplicate_claim_owner_even_with_no_vm():
    item, owner, promise, provider = claimed_case()
    other=promise.model_copy(update={'vmid':1201,'request_id':'f'*32,'owner':owner.model_copy(update={'request_id':'f'*32,'resource_id':'computer_other'})})
    data=provider.inventory().model_dump();data['resource_promises']=[promise.model_dump(),other.model_dump()]
    with pytest.raises(ValueError, match='invalid_inventory'):Inventory.model_validate(data)


@pytest.mark.parametrize('change,code', [
    ('claimed_same','clone_outcome_unknown_no_replay'),
    ('expired','preclaim_expired'),
    ('claimed_different_vmid','preclaim_binding_conflict'),
])
def test_actual_host_clone_fence_rejects_missing_claim_and_expiry_without_dispatch(change,code):
    import ast
    from test_device_provisioning import policy
    item,owner,promise,provider=claimed_case()
    tree=ast.parse(REMOTE)
    branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="action == 'clone_stopped'")
    inv=provider.inventory().model_dump()
    if change=='expired':inv['resource_promises'][0].update(owner=None,expires_at=2)
    if change=='claimed_different_vmid':item=item.model_copy(update={'vmid':1201,'request_id':'f'*32,'resource_id':'computer_other'})
    calls=[]
    def fail(code):raise ValueError(code)
    ns=dict(inventory=lambda:inv,capacity_totals=totals,spec=item.model_dump(),policy=policy().model_dump(),expected=owner.model_dump(),
            p={'storage':'local-lvm'},config=lambda _: {'onboot':0},fail=fail,json=json,time=time,
            bind_resource_claim=lambda *a:calls.append('claim'),run_change=lambda *a:calls.append('qm'),checked_target=lambda *a:None)
    with pytest.raises(ValueError,match=code):exec(compile(ast.Module(body=branch.body,type_ignores=[]),'actual-host-fence','exec'),ns)
    assert calls==[]


def test_unclaimed_invitation_cannot_be_bypassed_by_different_vmid():
    from test_device_provisioning import policy, NOW
    from wearing.cloud.device_provisioning import inspect_capacity
    item, _, promise, provider=claimed_case()
    provider.extra={'resource_promises':(promise.model_copy(update={'owner':None}),)}
    changed=item.model_copy(update={'vmid':1201,'request_id':'f'*32,'resource_id':'computer_other'})
    result=inspect_capacity(changed,policy(),provider.inventory(),[],now=NOW)
    assert not result['admitted'] and 'preclaim_binding_conflict' in result['reasons']
