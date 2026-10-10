"""Activation lease and user-visible completion boundaries, with no real guests."""
from copy import deepcopy
from types import SimpleNamespace
import time

import pytest

from wearing.cloud.bundle_activation import ActivationError, public_progress
from wearing.cloud.bundle_activation_worker import ActivationWorker, Lease, LeaseLost


def progress(state='pending'):
    return {kind: {'state': state} for kind in ('core', 'linux', 'android')}


class Store:
    def __init__(self):
        self.event = {'id': 'a' * 32, 'generation': 1, 'state': 'reserved', 'step': 'planned',
                      'members_json': progress(), 'updated_at': 100}
        self.valid = True
        self.calls = []

    def claim(self, worker):
        if self.event['state'] in ('ready', 'needs_review'):
            return None
        return deepcopy(self.event)

    def heartbeat(self, *args):
        self.calls.append(('heartbeat', args))
        return deepcopy(self.event) if self.valid else None

    def update(self, *args, **values):
        self.calls.append(('update', values))
        if not self.valid:
            return None
        self.event.update(values)
        return deepcopy(self.event)

    def release(self, *args):
        self.calls.append(('release', args))
        return deepcopy(self.event) if self.valid else None


def test_lost_lease_never_starts_provider_action():
    store = Store()
    store.valid = False
    calls = []
    worker = ActivationWorker(store, SimpleNamespace(advance=lambda *v: calls.append(v)))
    assert worker.tick() == {'state': 'lease_lost'}
    assert calls == []
    assert not any(action == 'update' for action, _ in store.calls)


def test_lost_generation_after_action_cannot_publish_ready():
    store = Store()
    def action(event, guard):
        guard()
        store.valid = False
        return {'state': 'ready', 'step': 'complete', 'members': progress('ready'), 'evidence': {'ok': True}}
    worker = ActivationWorker(store, SimpleNamespace(advance=action))
    assert worker.tick()['state'] == 'lease_lost'
    assert store.event['state'] == 'reserved'
    assert not any(action == 'update' for action, _ in store.calls)


def test_unknown_action_is_held_and_not_replayed_on_next_tick():
    store, actions = Store(), []
    def action(event, guard):
        guard()
        actions.append('dispatched')
        raise RuntimeError('ssh secret password=do-not-log')
    worker = ActivationWorker(store, SimpleNamespace(advance=action))
    assert worker.tick() == {'state': 'needs_review', 'step': 'review'}
    assert worker.tick() == {'state': 'idle'}
    assert actions == ['dispatched']
    assert store.event['reason'] == 'provisioning_requires_review'
    assert 'do-not-log' not in repr(store.calls)


def test_owner_change_stops_before_a_following_stage():
    store, actions = Store(), []
    def action(event, guard):
        guard()
        raise ActivationError('activation_owner_changed')
    worker = ActivationWorker(store, SimpleNamespace(advance=action))
    assert worker.tick()['state'] == 'needs_review'
    assert actions == []
    assert all(v['state'] == 'needs_review' for v in store.event['members'].values())


def test_live_lease_heartbeat_continues_while_provider_blocks():
    store = Store()
    event = deepcopy(store.event)
    with Lease(store, event, 'b' * 32, interval=.01):
        time.sleep(.045)
    assert len([v for v in store.calls if v[0] == 'heartbeat']) >= 3


def test_ready_rejects_partial_delivery_and_strips_internal_scope():
    value = {'state': 'ready', 'members': progress('ready'), 'updated_at': 100,
             'host': 'private-host', 'vmid': 999, 'receipt_sha256': 'c' * 64}
    assert set(public_progress(value)) == {'state', 'members', 'updated_at', 'reason', 'retry_after'}
    value['members']['android']['state'] = 'preparing'
    with pytest.raises(ActivationError):
        public_progress(value)


@pytest.mark.parametrize('members', [[], [{'kind': 'core', 'state': 'ready'}] * 3,
    {'core': {'state': 'ready'}, 'linux': {'state': 'ready'}}, progress('unknown')])
def test_malformed_progress_cannot_become_ready(members):
    with pytest.raises(ActivationError):
        public_progress({'state': 'ready', 'members': members, 'updated_at': 100})
