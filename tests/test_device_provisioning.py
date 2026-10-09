import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

import pytest

from wearing.cloud.device_provisioning import (DeviceSpec, Inventory, Owner, Policy, ProvisionBook,
                                               ProvisionError, Template, VM, inspect_capacity)
from wearing.cloud.proxmox_devices import ProxmoxDevices
from wearing.cloud.device_admission import AccountProof

NOW = 1000.0


class SyntheticAdmission:
    def __init__(self, clock=lambda: NOW): self.clock = clock
    def check(self, item):
        return AccountProof(tenant_id=item.tenant_id, identity_id=item.identity_id,
                            instance_id='instance_fixture', owner_user_id='user_fixture',
                            ownership_revision=1, member_digest='1' * 64,
                            source_sha256='2' * 64, observed_at=self.clock())


def spec(**changes):
    return DeviceSpec(request_id='a' * 32, tenant_id='tenant_a', identity_id='daily',
                      resource_id='computer_a', kind='linux', vmid=1200).model_copy(update=changes)


def policy(**changes):
    return Policy(node='pve01', storage='local-lvm',
                  templates={'linux': Template(vmid=9000, config_sha256='f' * 64,
                                              clean_review_ref='clean_fixture', disk_mib=32768),
                             'android': Template(vmid=9000, config_sha256='f' * 64,
                                                clean_review_ref='clean_fixture', disk_mib=32768)}).model_copy(update=changes)


class Provider:
    def __init__(self):
        self.calls = []
        self.clock = NOW
        self.vms = [VM(vmid=9000, state='stopped', vcpus=2, memory_mib=4096,
                       disk_mib=32768, template=True, config_sha256='f' * 64)]
        self.extra = {}
        self.clone_error = None
        self.prepare_error = None
        self.clone_created = True
        self.foreign_after_clone = False

    def inventory(self):
        return Inventory(node='pve01', storage='local-lvm', observed_at=self.clock,
                         physical_cores=16, memory_mib=65536, available_memory_mib=60000,
                         storage_mib=1024 * 1024, available_storage_mib=900000,
                         committed_storage_mib=sum(v.disk_mib + 4 for v in self.vms),
                         vms=tuple(self.vms)).model_copy(update=self.extra)

    def inspect_vm(self, vmid):
        return next((v for v in self.vms if v.vmid == vmid), None)

    def clone_stopped(self, item, limits, owner):
        self.calls.append('clone')
        if self.clone_created:
            if self.foreign_after_clone:
                owner = owner.model_copy(update={'tenant_id': 'foreign'})
            self.vms.append(VM(vmid=item.vmid, state='stopped', vcpus=2, memory_mib=4096,
                               disk_mib=32768, owner=owner, config_sha256='e' * 64))
        if self.clone_error:
            raise self.clone_error

    def prepare_stopped(self, item, limits, owner, config):
        self.calls.append('prepare')
        current = self.inspect_vm(item.vmid)
        assert current.owner == owner and current.config_sha256 == config
        self.vms[self.vms.index(current)] = current.model_copy(update={
            'vcpus': item.vcpus, 'memory_mib': item.memory_mib, 'prepared': True,
            'config_sha256': 'd' * 64})
        if self.prepare_error:
            raise self.prepare_error


@pytest.fixture
def setup(tmp_path):
    return ProvisionBook(tmp_path / 'ops', operator=True, clock=lambda: NOW,
                         admission=SyntheticAdmission()), Provider()


def reserve(book, provider, item=None, limits=None):
    item, limits = item or spec(), limits or policy()
    plan = book.plan(item, limits, provider)
    assert plan['admitted'], plan
    result = book.reserve(item, limits, provider, plan_sha256=plan['plan_sha256'])
    return result['plan_sha256']


def test_preview_and_reserve_do_not_create_and_apply_only_stages_owned_vm(setup):
    book, provider = setup
    revision = reserve(book, provider)
    assert provider.calls == []
    result = book.apply(spec().request_id, provider, plan_sha256=revision)
    assert result['state'] == 'staged' and not result['product_ready']
    assert provider.calls == ['clone', 'prepare']
    current = provider.inspect_vm(1200)
    assert current.state == 'stopped' and current.prepared
    assert current.owner.tenant_id == 'tenant_a'
    assert 'nonce' not in json.dumps(result)
    assert book.path.stat().st_mode & 0o077 == 0
    assert book.apply(spec().request_id, provider, plan_sha256=revision) == result
    assert provider.calls == ['clone', 'prepare']


@pytest.mark.parametrize('change,reason', [
    ({'physical_cores': 3}, 'capacity_vcpus'),
    ({'memory_mib': 8000, 'available_memory_mib': 7000}, 'capacity_memory_mib'),
    ({'available_memory_mib': 8000}, 'host_memory_pressure'),
    ({'committed_storage_mib': 820000}, 'capacity_disk_mib'),
    ({'available_storage_mib': 20000}, 'storage_free_space_low'),
])
def test_full_commitments_and_headroom_not_idle_rss_gate_capacity(setup, change, reason):
    book, provider = setup
    provider.extra = change
    plan = book.plan(spec(), policy(), provider)
    assert not plan['admitted'] and reason in plan['reasons']
    with pytest.raises(ProvisionError, match=reason):
        book.reserve(spec(), policy(), provider, plan_sha256=plan['plan_sha256'])
    assert provider.calls == []


@pytest.mark.parametrize('change', [{'observed_at': 900.0}, {'observed_at': 1001.0}, {'node': 'other'}])
def test_stale_future_or_wrong_host_inventory_fails_closed(setup, change):
    book, provider = setup
    provider.extra = change
    with pytest.raises(ProvisionError, match='inventory_stale_or_wrong_host'):
        book.plan(spec(), policy(), provider)


def test_unreviewed_or_changed_template_never_applies(setup):
    book, provider = setup
    assert 'reviewed_clean_template_required' in book.plan(spec(), policy(templates={}), provider)['reasons']
    revision = reserve(book, provider)
    provider.vms[0] = provider.vms[0].model_copy(update={'config_sha256': '0' * 64})
    with pytest.raises(ProvisionError, match='reviewed_clean_template_required'):
        book.apply(spec().request_id, provider, plan_sha256=revision)
    assert provider.calls == []


def test_binding_and_request_are_unique_across_identities_and_retries(setup):
    book, provider = setup
    revision = reserve(book, provider, limits=policy(linux_slots=3))
    same = book.reserve(spec(), policy(linux_slots=3), provider, plan_sha256=revision)
    assert same['state'] == 'reserved'
    other = spec(request_id='b' * 32, identity_id='work', resource_id='computer_b', vmid=1201)
    plan = book.plan(other, policy(linux_slots=3), provider)
    with pytest.raises(ProvisionError, match='device_binding_conflict'):
        book.reserve(other, policy(linux_slots=3), provider, plan_sha256=plan['plan_sha256'])
    changed = spec(memory_mib=8192)
    changed_plan = book.plan(changed, policy(linux_slots=3), provider)
    with pytest.raises(ProvisionError, match='idempotency_request_changed'):
        book.reserve(changed, policy(linux_slots=3), provider, plan_sha256=changed_plan['plan_sha256'])


def test_concurrent_reservations_cannot_overbook_one_slot(setup):
    book, provider = setup
    a, b = spec(), spec(request_id='b' * 32, tenant_id='tenant_b', vmid=1201, resource_id='computer_b')
    revisions = [book.plan(item, policy(), provider)['plan_sha256'] for item in (a, b)]
    def attempt(item, revision):
        try:
            book.reserve(item, policy(), provider, plan_sha256=revision)
            return 'reserved'
        except ProvisionError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(attempt, item, rev) for item, rev in zip((a, b), revisions)]
        results = [job.result() for job in jobs]
    assert results.count('reserved') == 1
    assert any('capacity_linux_slots' in item for item in results)


def test_running_allocation_and_matching_staged_binding_are_not_double_counted(setup):
    book, provider = setup
    revision = reserve(book, provider)
    book.apply(spec().request_id, provider, plan_sha256=revision)
    vm = provider.inspect_vm(1200)
    provider.vms[1] = vm.model_copy(update={'state': 'running'})
    with book._tx() as db:
        rows = book._rows(db)
    plan = inspect_capacity(spec(), policy(), provider.inventory(), rows, now=NOW)
    assert plan['demand']['memory_mib'] == 4096 and plan['demand']['vcpus'] == 2
    # Existing signed ownership markers also reserve resources if another
    # operator process does not have this ledger's reservation rows.
    plan = inspect_capacity(spec(request_id='b' * 32, tenant_id='tenant_b', vmid=1201,
                                 resource_id='computer_b'), policy(linux_slots=2), provider.inventory(), [], now=NOW)
    assert plan['demand']['memory_mib'] == 8192 and plan['demand']['linux_slots'] == 2


def test_ambiguous_clone_absent_is_not_replayed_or_released(setup):
    book, provider = setup
    revision = reserve(book, provider)
    provider.clone_created = False
    provider.clone_error = TimeoutError('secret provider content')
    with pytest.raises(ProvisionError, match='provider_outcome_unknown'):
        book.apply(spec().request_id, provider, plan_sha256=revision)
    assert 'secret' not in json.dumps(book.status(spec().request_id))
    provider.clone_error = None
    with pytest.raises(ProvisionError, match='clone_outcome_unknown_no_replay'):
        book.apply(spec().request_id, provider, plan_sha256=revision)
    with pytest.raises(ProvisionError, match='reservation_cannot_cancel'):
        book.cancel_unattempted(spec().request_id, provider)
    assert provider.calls == ['clone']


def test_lost_clone_response_recovers_existing_exact_owner_without_duplicate_create(setup):
    book, provider = setup
    revision = reserve(book, provider)
    provider.clone_error = TimeoutError()
    with pytest.raises(ProvisionError):
        book.apply(spec().request_id, provider, plan_sha256=revision)
    # Reopen ledger: pending intent and unique owner must survive process death.
    recovered = ProvisionBook(book.root, operator=True, clock=lambda: NOW, admission=book.admission)
    provider.clone_error = None
    assert recovered.apply(spec().request_id, provider, plan_sha256=revision)['state'] == 'staged'
    assert provider.calls == ['clone', 'prepare']


@pytest.mark.parametrize('change', [{'owner': None}, {'state': 'running'}, {'locked': True}, {'template': True}])
def test_changed_existing_vm_is_never_configured_or_deleted(setup, change):
    book, provider = setup
    revision = reserve(book, provider)
    provider.clone_error = TimeoutError()
    with pytest.raises(ProvisionError):
        book.apply(spec().request_id, provider, plan_sha256=revision)
    provider.vms[1] = provider.vms[1].model_copy(update=change)
    with pytest.raises(ProvisionError, match='vm_owner_or_state_conflict'):
        book.apply(spec().request_id, provider, plan_sha256=revision)
    assert provider.calls == ['clone']


def test_foreign_vmid_preexisting_or_created_during_clone_is_never_touched(setup):
    book, provider = setup
    revision = reserve(book, provider)
    provider.foreign_after_clone = True
    with pytest.raises(ProvisionError, match='clone_not_confirmed'):
        book.apply(spec().request_id, provider, plan_sha256=revision)
    assert provider.calls == ['clone']


def test_expiry_only_releases_never_attempted_reservations(setup):
    book, provider = setup
    revision = reserve(book, provider)
    book.clock = lambda: NOW + 1000
    provider.clock = NOW + 1000
    with pytest.raises(ProvisionError, match='reservation_expired_or_cancelled'):
        book.apply(spec().request_id, provider, plan_sha256=revision)
    assert provider.calls == []


def test_cancel_never_touches_vms_and_unattempted_capacity_can_be_reused(setup):
    book, provider = setup
    reserve(book, provider)
    assert book.cancel_unattempted(spec().request_id, provider)['state'] == 'cancelled'
    other = spec(request_id='b' * 32, vmid=1201, resource_id='computer_b')
    reserve(book, provider, item=other)
    assert provider.calls == []


def test_operator_gate_and_unsafe_path(tmp_path):
    with pytest.raises(ProvisionError, match='operator_required'):
        ProvisionBook(tmp_path / 'book')
    (tmp_path / 'link').symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ProvisionError, match='unsafe_operator_ledger'):
        ProvisionBook(tmp_path / 'link', operator=True)


def test_transport_read_only_by_default_and_no_shell_or_host_key_bypass(tmp_path):
    config = tmp_path / 'ssh-config';config.write_text('')
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps(Provider().inventory().model_dump()), '')
    adapter = ProxmoxDevices(ssh_config=config, host='pve-lab', node='pve01', runner=run)
    assert adapter.inventory().physical_cores == 16
    argv, kwargs = calls[0]
    assert 'StrictHostKeyChecking=yes' in argv and 'BatchMode=yes' in argv
    assert not kwargs.get('shell') and json.loads(kwargs['input'])['action'] == 'inventory'
    with pytest.raises(ProvisionError, match='operator_apply_required'):
        adapter._call('clone_stopped')
    with pytest.raises(ProvisionError, match='proxmox_action_not_allowed'):
        adapter._call('delete')
    assert len(calls) == 1


def test_lost_prepare_response_recovers_by_observation_without_reapplying(setup):
    book, provider = setup
    revision = reserve(book, provider)
    provider.prepare_error = TimeoutError()
    with pytest.raises(ProvisionError, match='provider_outcome_unknown'):
        book.apply(spec().request_id, provider, plan_sha256=revision)
    provider.prepare_error = None
    assert book.apply(spec().request_id, provider, plan_sha256=revision)['state'] == 'staged'
    assert provider.calls == ['clone', 'prepare']


def test_second_process_sees_stopped_owned_vm_reservation_without_local_rows(setup):
    book, provider = setup
    revision = reserve(book, provider)
    book.apply(spec().request_id, provider, plan_sha256=revision)
    other = spec(request_id='b' * 32, tenant_id='tenant_b', resource_id='computer_b', vmid=1201)
    result = inspect_capacity(other, policy(), provider.inventory(), [], now=NOW)
    assert not result['admitted'] and 'capacity_linux_slots' in result['reasons']
    assert result['demand']['memory_mib'] == 8192


def test_owner_proofs_cannot_appear_on_two_different_vms(setup):
    book, provider = setup
    revision = reserve(book, provider)
    book.apply(spec().request_id, provider, plan_sha256=revision)
    provider.vms.append(provider.vms[1].model_copy(update={'vmid': 1202}))
    with pytest.raises(ValueError, match='invalid_inventory'):
        provider.inventory()


@pytest.mark.parametrize('changes', [
    {'tenant_id': 'tenant_a', 'resource_id': 'computer_b'},
    {'tenant_id': 'tenant_b', 'resource_id': 'computer_a'},
])
def test_host_ownership_prevents_duplicate_binding_without_local_ledger(setup, changes):
    book, provider = setup
    revision = reserve(book, provider)
    book.apply(spec().request_id, provider, plan_sha256=revision)
    other = spec(request_id='b' * 32, vmid=1201, **changes)
    result = inspect_capacity(other, policy(linux_slots=5), provider.inventory(), [], now=NOW)
    assert 'device_binding_conflict' in result['reasons']


def test_host_request_id_cannot_be_reused_with_changed_spec(setup):
    book, provider = setup
    revision = reserve(book, provider)
    book.apply(spec().request_id, provider, plan_sha256=revision)
    result = inspect_capacity(spec(vmid=1201), policy(), provider.inventory(), [], now=NOW)
    assert 'idempotency_request_changed' in result['reasons']


def test_stopped_owned_vm_larger_than_reserved_is_fully_counted(setup):
    book, provider = setup
    revision = reserve(book, provider)
    book.apply(spec().request_id, provider, plan_sha256=revision)
    provider.vms[1] = provider.vms[1].model_copy(update={'memory_mib': 8192, 'vcpus': 4})
    result = inspect_capacity(spec(), policy(), provider.inventory(), [], now=NOW)
    assert result['demand']['memory_mib'] == 8192 and result['demand']['vcpus'] == 4
