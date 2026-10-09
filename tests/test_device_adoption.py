import json
import pytest
from wearing.cloud.device_adoption import AdoptionBook
from wearing.cloud.device_adoption_ssh import HOST,GUEST
from wearing.cloud.device_provisioning import VM,ProvisionError,fingerprint
from test_device_provisioning import setup,spec,policy

@pytest.fixture
def adopted_setup(setup):
    book,provider=setup;item=spec()
    provider.vms.append(VM(vmid=item.vmid,state='running',vcpus=2,memory_mib=4096,disk_mib=32768,config_sha256='9'*64))
    def probe(item,owner):
        vm=provider.inspect_vm(item.vmid)
        return {'vmid':item.vmid,'resource_id':item.resource_id,'scope_matches':True,'guest_matches_vm':True,'paired_ready':True,
                'connector_id':'fixture','machine_sha256':'8'*64,'config_sha256':vm.config_sha256,
                'owner_sha256':fingerprint(vm.owner.model_dump()) if vm.owner else None}
    def apply(item,owner,before):
        provider.calls.append('adopt_metadata')
        vm=provider.inspect_vm(item.vmid)
        assert vm.owner in (None,owner) and vm.config_sha256 in (before['config_sha256'],'7'*64)
        provider.vms[provider.vms.index(vm)]=vm.model_copy(update={'owner':owner,'config_sha256':'7'*64})
    provider.adoption_probe=probe;provider.adopt_existing=apply
    return AdoptionBook(book),book,provider

def test_adopt_existing_is_metadata_only_with_explicit_provenance(adopted_setup):
    adoption,book,provider=adopted_setup
    planned=adoption.plan(spec(),policy(),provider)
    assert planned['admitted'] and not planned['creates_resources']
    assert planned['demand']['vcpus']==2 and planned['demand']['memory_mib']==4096
    result=adoption.apply(spec().request_id,provider,reviewed_sha256=planned['reviewed_sha256'])
    assert result['state']=='adopted' and result['provenance']=='manual_adoption'
    assert provider.calls==['adopt_metadata'] and provider.inspect_vm(1200).state=='running'
    assert adoption.apply(spec().request_id,provider,reviewed_sha256=planned['reviewed_sha256'])==result
    assert provider.calls==['adopt_metadata']
    with pytest.raises(ProvisionError,match='manual_adoption_cannot_clone_or_prepare'):
        book.apply(spec().request_id,provider,plan_sha256=planned['reviewed_sha256'])
    assert provider.calls==['adopt_metadata']

def test_scope_or_config_change_rejected_before_stamp(adopted_setup):
    a,book,p=adopted_setup;plan=a.plan(spec(),policy(),p)
    vm=p.inspect_vm(1200);p.vms[p.vms.index(vm)]=vm.model_copy(update={'config_sha256':'6'*64})
    with pytest.raises(ProvisionError,match='adoption_evidence_changed'):a.apply(spec().request_id,p,reviewed_sha256=plan['reviewed_sha256'])
    assert not p.calls

def test_capacity_and_existing_external_slots_not_silently_ignored(adopted_setup):
    a,book,p=adopted_setup;plan=a.plan(spec(),policy(external_linux_slots=1),p)
    assert not plan['admitted'] and 'capacity_linux_slots' in plan['reasons']
    with pytest.raises(ProvisionError,match='capacity_linux_slots'):a.apply(spec().request_id,p,reviewed_sha256=plan['reviewed_sha256'])
    assert not p.calls

def test_lost_metadata_reply_observes_same_vm_and_preserves_provenance(adopted_setup):
    a,book,p=adopted_setup;plan=a.plan(spec(),policy(),p);original=p.adopt_existing
    def lost(*args):original(*args);raise TimeoutError()
    p.adopt_existing=lost
    with pytest.raises(TimeoutError):a.apply(spec().request_id,p,reviewed_sha256=plan['reviewed_sha256'])
    assert a.status(spec().request_id)['state']=='applying'
    p.adopt_existing=original
    assert a.apply(spec().request_id,p,reviewed_sha256=plan['reviewed_sha256'])['state']=='adopted'
    assert p.calls==['adopt_metadata','adopt_metadata']

def test_exact_host_guest_helpers_have_no_power_or_network_mutation():
    compile(HOST,'<adoption-host>','exec');compile(GUEST,'<adoption-guest>','exec')
    assert "'--description',description" in HOST and "'--digest',c['digest']" in HOST
    assert "'guest','exec'" in HOST and "'/usr/bin/cat','/etc/machine-id'" in HOST
    assert "['qm','start'" not in HOST and "['qm','stop'" not in HOST and '--net' not in HOST
    assert 'manual_adoption' in HOST
