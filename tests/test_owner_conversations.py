"""Engine histories are private by trusted owner, independently of read filters."""
import httpx
from wearing.config import Settings
from wearing.hermes import HermesClient
from wearing.service import TaskService, ACTIVE
from wearing.store import Store
from test_goals import GoalWire

A, B = 'a' * 64, 'b' * 64


def accept(store, owner, label):
    return store.accept_message(label, 'daily', 'request-' + label, ACTIVE, owner_scope=owner)[0]


async def test_two_owners_turns_drafts_and_service_restart(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    wire = GoalWire()
    client = HermesClient(Settings(tmp_path, hermes_key='fixture'), httpx.MockTransport(wire))
    service = TaskService(store, client)
    a = accept(store, A, 'a1')
    await service.start(a['id'])
    a2, b = accept(store, A, 'a2'), accept(store, B, 'b1')
    legacy = store.create_message('legacy')
    assert len({a['session_id'], b['session_id'], legacy['session_id']}) == 3
    store.sync_conversation_session(a['id'], 'synthetic-canonical-A')
    assert store.get(a2['id'])['session_id'] == 'synthetic-canonical-A'
    assert store.get(b['id'])['session_id'] == b['session_id']
    assert store.get(legacy['id'])['session_id'] == legacy['session_id']
    store.update(a['id'], status='completed_unverified')
    reopened = Store(store.path)
    restarted = TaskService(reopened, client)
    await restarted.start(a2['id'])
    assert wire.runs[-1]['session_id'] == 'synthetic-canonical-A'
    reopened.update(a2['id'], status='completed_unverified')
    await restarted.start(b['id'])
    assert wire.runs[-1]['session_id'] == b['session_id']
    reopened.sync_conversation_session(b['id'], 'synthetic-canonical-B')
    reopened.update(b['id'], status='completed_unverified')
    a3, b2 = accept(reopened, A, 'a3'), accept(reopened, B, 'b2')
    assert a3['session_id'] == 'synthetic-canonical-A'
    assert b2['session_id'] == 'synthetic-canonical-B'
    assert reopened.create_message('legacy2')['session_id'] == legacy['session_id']
    await client.close()


def test_preupgrade_owned_draft_and_late_run_do_not_adopt_shared_history(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    old_running, old_draft = store.create_message('old running'), store.create_message('old draft')
    with store.connection() as db:
        db.execute('INSERT INTO task_principals VALUES(?,?)', (old_running['id'], A))
        db.execute('INSERT INTO task_principals VALUES(?,?)', (old_draft['id'], A))
    store.update(old_running['id'], status='running', run_id='preupgrade')
    store.sync_conversation_session(old_running['id'], 'preupgrade-shared-remote')
    fresh = accept(store, A, 'fresh')
    assert fresh['session_id'] not in {old_running['session_id'], 'preupgrade-shared-remote'}
    store.update(old_running['id'], status='completed_unverified')
    payload = {'session_id': old_draft['session_id'], 'input': 'test'}
    assert store.reserve_start(old_draft['id'], payload, 'fixture-admission', ACTIVE)
    assert payload['session_id'] == fresh['session_id']
    store.sync_conversation_session(old_draft['id'], 'owned-remote')
    assert store.get(fresh['id'])['session_id'] == 'owned-remote'
    store.sync_conversation_session(old_running['id'], 'another-late-legacy-session')
    assert accept(Store(store.path), A, 'fresh2')['session_id'] == 'owned-remote'


def test_legacy_sync_does_not_update_owned_drafts(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    legacy = store.create_message('legacy')
    owned = accept(store, A, 'owned')
    store.sync_conversation_session(legacy['id'], 'legacy-resumed')
    assert store.get(owned['id'])['session_id'] == owned['session_id']
    assert store.create_message('legacy next')['session_id'] == 'legacy-resumed'


def test_confirmation_recovery_inherits_original_owner_and_denies_foreign_replay(tmp_path):
    import pytest
    from wearing.durable_confirmations import DurableConfirmations, ConfirmationError
    from test_durable_confirmations import CARD
    store = Store(tmp_path / 'test.sqlite3')
    source = accept(store, A, 'approval-source')
    store.update(source['id'], status='running', run_id='fixture-source')
    book = DurableConfirmations(store)
    action = book.create('daily', CARD)
    book.finish_wait(action['id'])
    store.update(source['id'], status='failed')
    revision = book.get('daily', action['id'])['revision']
    assert book.list('daily', owner_scope=B) == []
    with pytest.raises(ConfirmationError):
        book.prepare_recovery('daily', action['id'], revision, 'fixture-recovery-key', owner_scope=B)
    task_id, created = book.prepare_recovery('daily', action['id'], revision, 'fixture-recovery-key', owner_scope=A)
    assert created and store.get(task_id)['session_id'] == source['session_id']
    with store.connection() as db:
        assert db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (task_id,)).fetchone()[0] == A
    with pytest.raises(ConfirmationError):
        book.prepare_recovery('daily', action['id'], revision, 'fixture-recovery-key', owner_scope=B)
    assert book.prepare_recovery('daily', action['id'], revision, 'fixture-recovery-key', owner_scope=A) == (task_id, False)
