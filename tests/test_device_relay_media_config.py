"""Live operator media configuration on one relay, without a service restart."""
import json
import os

import pytest

from wearing.cloud.instance import initialize_instance
from wearing.cloud.relay import (
    ConnectionRequest, PairRequest, PollRequest, RelayError, RelayStore, instance_relay,
)

RESOURCE = 'computer_dynamic_media'
TOKEN = 'b' * 64
ACTOR = 'a' * 64
VALID = {'version': 1, 'enabled': True, 'hosts': {RESOURCE: {}}}


def save(path, value=VALID):
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def test_same_live_store_enables_then_pauses_without_restart(tmp_path):
    path = tmp_path / 'media.json'
    store = RelayStore(tmp_path / 'relay', 'tenant_dynamic',
                       human_access_ready=True, media_config=path)
    bundle = store.pair_code('daily', [{'resource_id': RESOURCE, 'name': 'Synthetic desktop',
        'kind': 'computer', 'methods': ['computer.status']}], [])
    store.pair(PairRequest(code=bundle['code'], token=TOKEN))
    connection = store.connect(TOKEN, ConnectionRequest())['connection_id']

    def poll():
        return store.poll(TOKEN, PollRequest(connection_id=connection,
            availability={RESOURCE: True}, human_access_ready=True,
            human_availability={RESOURCE: True}))

    poll()
    assert store.human_status('daily', ACTOR, RESOURCE)['supported'] is False
    with pytest.raises(RelayError, match='private_gateway_unavailable'):
        store.request_human('daily', ACTOR, RESOURCE, expected_generation=0, request_id='missing')
    save(path, {**VALID, 'hosts': {}})
    assert store.human_access_ready is False
    save(path)
    store.human_access_ready = False  # Fallback cannot override a configured file.
    assert store.human_status('daily', ACTOR, RESOURCE)['supported'] is True
    state = store.request_human('daily', ACTOR, RESOURCE,
                                expected_generation=0, request_id='first')
    assert state['state'] == 'handoff_pending'
    save(path, {**VALID, 'enabled': False})
    store.human_access_ready = True  # Nor can a flag override operator disablement.
    assert store.human_access_ready is False
    poll()
    state = store.human_status('daily', ACTOR, RESOURCE)
    assert state['supported'] is False and state['state'] == 'paused'
    with pytest.raises(RelayError, match='private_gateway_unavailable'):
        store.request_human('daily', ACTOR, RESOURCE,
                            expected_generation=state['control_generation'], request_id='disabled')
    save(path)
    restored = store.human_status('daily', ACTOR, RESOURCE)
    assert restored['supported'] is True and restored['state'] == 'paused'
    assert restored['session_id'] == state['session_id']  # No automatic new session.


@pytest.mark.parametrize('invalid', [
    None, [], 'not an object', {}, {**VALID, 'version': True},
    {**VALID, 'version': 2}, {**VALID, 'enabled': 1},
    {**VALID, 'hosts': []}, {**VALID, 'hosts': ['host']}, {**VALID, 'hosts': 'host'},
])
def test_invalid_shape_disables_current_store(tmp_path, invalid):
    path = tmp_path / 'media.json'
    save(path)
    store = RelayStore(tmp_path / 'relay', 'tenant_dynamic',
                       human_access_ready=True, media_config=path)
    assert store.human_access_ready is True
    save(path, invalid)
    assert store.human_access_ready is False


def test_corrupt_missing_unsafe_and_unreadable_config_never_use_fallback(tmp_path, monkeypatch):
    path = tmp_path / 'media.json'
    save(path)
    store = RelayStore(tmp_path / 'relay', 'tenant_dynamic',
                       human_access_ready=True, media_config=path)
    assert store.human_access_ready is True
    path.write_text('{')
    assert store.human_access_ready is False
    save(path)
    if os.name != 'nt':
        path.chmod(0o644)
        assert store.human_access_ready is False
        path.chmod(0o600)
        assert store.human_access_ready is True
    path.unlink()
    assert store.human_access_ready is False
    target = tmp_path / 'other.json'
    save(target)
    path.symlink_to(target)
    assert store.human_access_ready is False
    path.unlink()
    save(path)
    assert store.human_access_ready is True
    def denied(_):
        raise PermissionError('synthetic inaccessible operator file')
    monkeypatch.setattr('wearing.cloud.relay.read_private', denied)
    assert store.human_access_ready is False


def test_instance_keeps_media_path_before_first_device_enrollment(tmp_path):
    root = tmp_path / 'instance'
    initialize_instance(root, 'tenant_dynamic', 'http://127.0.0.1:18865')
    store = instance_relay(root)
    assert store.media_config == root / 'private-media-access.json'
    assert store.human_access_ready is False
    save(store.media_config)
    assert store.human_access_ready is True


def test_only_stores_without_operator_path_can_use_boolean_fallback(tmp_path):
    store = RelayStore(tmp_path / 'relay', 'tenant_dynamic', human_access_ready=True)
    assert store.human_access_ready is True
    store.human_access_ready = False
    assert store.human_access_ready is False
    store.human_access_ready = 'true'
    assert store.human_access_ready is False
