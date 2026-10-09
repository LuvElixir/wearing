import pytest

from wearing.cloud.device_queue import DeviceQueue
from wearing.cloud.device_provisioning import ProvisionError
from test_device_provisioning import setup, spec, policy, SyntheticAdmission


def test_capacity_waiting_owns_no_resources_then_promotes_without_creating_vm(setup):
    book, provider = setup
    queue = DeviceQueue(book)
    assert queue.enqueue(spec(), policy())['state'] == 'queued'
    provider.extra = {'physical_cores': 3}
    waiting = queue.tick(provider)
    assert waiting['state'] == 'queued' and 'capacity_vcpus' in waiting['code']
    assert not waiting['resources_reserved']
    with book._tx() as db: assert db.execute('SELECT COUNT(*) FROM devices').fetchone()[0] == 0
    provider.extra = {}
    assert queue.tick(provider)['state'] == 'reserved'
    assert provider.calls == []
    assert queue.tick(provider)['state'] == 'empty'


def test_fifo_and_crash_after_reservation_reconcile_exact_request(setup):
    book, provider = setup;queue = DeviceQueue(book)
    queue.enqueue(spec(), policy())
    queue.enqueue(spec(request_id='b'*32, tenant_id='tenant_b', resource_id='computer_b', vmid=1201), policy())
    first = queue.tick(provider)
    queue._set(spec().request_id, 'promoting')
    assert queue.tick(provider) == first
    assert queue.tick(provider)['state'] == 'queued'
    assert provider.calls == []


def test_changed_account_blocks_one_request_without_allocating(setup):
    book, provider = setup;queue = DeviceQueue(book)
    queue.enqueue(spec(), policy())
    class Changed(SyntheticAdmission):
        def check(self, item): return super().check(item).model_copy(update={'ownership_revision': 2})
    book.admission = Changed()
    assert queue.tick(provider)['code'] == 'account_binding_changed'
    with book._tx() as db: assert db.execute('SELECT COUNT(*) FROM devices').fetchone()[0] == 0


def test_idempotency_cancellation_and_one_tenant_kind(setup):
    book, provider = setup;queue=DeviceQueue(book)
    first=queue.enqueue(spec(),policy())
    assert queue.enqueue(spec(),policy())==first
    with pytest.raises(ProvisionError,match='idempotency_request_changed'): queue.enqueue(spec(memory_mib=8192),policy())
    with pytest.raises(ProvisionError,match='device_binding_conflict'): queue.enqueue(spec(request_id='c'*32,vmid=1202,resource_id='other'),policy())
    assert queue.cancel(spec().request_id)['state']=='cancelled'
    other=spec(request_id='c'*32,vmid=1202,resource_id='other')
    queue.enqueue(other,policy());queue.tick(provider)
    with pytest.raises(ProvisionError,match='queue_cannot_cancel_reserved'): queue.cancel(other.request_id)
