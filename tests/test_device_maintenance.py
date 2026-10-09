import pytest

from wearing.cloud.device_maintenance import DeviceMaintenance, guard
from wearing.cloud.relay import RelayError, PollRequest, ResourceControl
from test_device_relay import paired, queue, claim, TOKEN

OP = 'a' * 32
OWNER = 'b' * 64


def maint(fixture):
    return DeviceMaintenance(fixture[1], operator=True)


def args(): return ('daily', 'phone_test', OP, OWNER)


def test_freeze_denies_new_actions_pause_and_human_takeover_without_erasing_history(paired):
    _, relay, _, connection = paired
    m = maint(paired)
    before = m.begin(*args())
    assert before['phase'] == 'freezing'
    for fn in (lambda: queue(relay), lambda: relay.control('daily', ResourceControl(
        resource_id='phone_test', expected_generation=0, paused=False)),
        lambda: relay.request_human('daily', 'user_a', 'phone_test', expected_generation=0, request_id='test')):
        with pytest.raises(RelayError, match='device_maintenance_waiting'): fn()
    assert m.freeze(*args())['phase'] == 'frozen'
    with pytest.raises(RelayError, match='maintenance_ack_pending'): m.assert_drained(*args())
    relay.poll(TOKEN, PollRequest(connection_id=connection, availability={'phone_test': False}, control_acks={'phone_test': 1}))
    assert m.assert_drained(*args())['acknowledged']
    assert m.begin(*args())['phase'] == 'frozen'
    with relay.tx() as db:
        assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM human_access').fetchone()[0] == 0


@pytest.mark.parametrize('state', ['queued', 'executing', 'unknown', 'device_error'])
def test_busy_and_unresolved_work_cannot_be_relabelled_to_make_sleep_possible(paired, state):
    _, relay, _, connection = paired
    command = queue(relay)
    if state == 'executing': claim(relay, command, connection)
    else:
        with relay.tx() as db: db.execute('UPDATE commands SET state=? WHERE id=?', (state, command.command_id))
    with pytest.raises(RelayError, match='device_maintenance_busy'): maint(paired).begin(*args())
    with relay.tx() as db:
        assert db.execute('SELECT state FROM commands').fetchone()[0] == state
        assert db.execute('SELECT COUNT(*) FROM controls').fetchone()[0] == 0


@pytest.mark.parametrize('state,resolved', [('completed', 0), ('blocked', 0), ('unknown', 1), ('device_error', 1)])
def test_terminal_or_explicitly_reviewed_history_does_not_block_idle_device(paired, state, resolved):
    _, relay, *_ = paired
    command = queue(relay)
    with relay.tx() as db: db.execute('UPDATE commands SET state=?,resolved=? WHERE id=?', (state, resolved, command.command_id))
    assert maint(paired).begin(*args())['phase'] == 'freezing'


def test_durable_fence_survives_operator_restart_and_needs_current_wake_ack(paired):
    _, relay, _, connection = paired
    m = maint(paired);m.begin(*args());m.freeze(*args())
    relay.poll(TOKEN, PollRequest(connection_id=connection, availability={'phone_test': False}, control_acks={'phone_test': 1}))
    m = maint(paired)
    assert m.assert_drained(*args())['acknowledged']
    assert m.wake(*args())['phase'] == 'waking'
    with pytest.raises(RelayError, match='device_maintenance_waiting'): queue(relay)
    with pytest.raises(RelayError, match='wake_readiness_pending'): m.finish_wake(*args())
    relay.poll(TOKEN, PollRequest(connection_id=connection, availability={'phone_test': True}, control_acks={'phone_test': 2},
                                 human_access_ready=True, human_availability={'phone_test': True}))
    assert m.finish_wake(*args())['phase'] == 'awake'
    assert queue(relay)


def test_wrong_scope_operation_and_owner_never_release_fence(paired):
    m = maint(paired);m.begin(*args());m.freeze(*args())
    for changed in [('other', 'phone_test', OP, OWNER), ('daily', 'phone_test', 'c'*32, OWNER),
                    ('daily', 'phone_test', OP, 'd'*64)]:
        with pytest.raises(RelayError): m.wake(*changed)
    assert m.status(*args())['phase'] == 'frozen'


def test_existing_user_pause_remains_user_owned(paired):
    paired[1].control('daily', ResourceControl(resource_id='phone_test', paused=True, expected_generation=0))
    with pytest.raises(RelayError, match='device_not_agent_ready'): maint(paired).begin(*args())


def test_operator_requirement(paired):
    with pytest.raises(ValueError, match='operator_required'): DeviceMaintenance(paired[1])
