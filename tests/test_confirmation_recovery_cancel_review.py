"""Synthetic regression for cancelled read-only confirmation recovery."""
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from wearing.app import create_app
from wearing.cloud.worker import TenantBoundary
from wearing.config import Settings
from wearing.durable_confirmations import DurableConfirmations
from wearing.service import ACTIVE, TaskService
from wearing.store import Store

A, B = 'a' * 64, 'b' * 64
CARD = {'title': '合成确认', 'action': '核对隔离记录', 'impact': '无外部资源'}


def prepare(store, book):
    task, _ = store.accept_message('Synthetic source', 'daily', 'synthetic_source_1', ACTIVE, owner_scope=A)
    store.update(task['id'], status='running', run_id='source')
    action = book.create('daily', CARD)
    book.finish_wait(action['id'])
    store.update(task['id'], status='failed')
    blocker = store.create('Synthetic blocker', 'computer')
    store.update(blocker['id'], status='running', run_id='blocker')
    source = book.get('daily', action['id'])
    recovery, _ = book.prepare_recovery('daily', source['id'], source['revision'], 'synthetic_recovery_1', owner_scope=A)
    return source, recovery


async def test_cancelled_recovery_http_projection_and_explicit_successor(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    store = app.state.store
    book = app.state.service.confirmations.durable
    source, recovery = prepare(store, book)
    headers = {'Authorization': 'Bearer fixture-key', 'X-Wearing-Tenant': 'fixture', 'X-Pajio-Storage-Scope': A}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers=headers) as client:
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        client.headers['X-Pajio-Storage-Scope'] = B
        assert (await client.post(f'/api/tasks/{recovery}/cancel-message')).status_code == 404
        assert book.get('daily', source['id'])['state'] == 'recovering'
        client.headers['X-Pajio-Storage-Scope'] = A
        assert (await client.post(f'/api/tasks/{recovery}/cancel-message')).status_code == 200
        assert store.get(recovery)['status'] == 'stopped'
        rows = (await client.get('/api/confirmations')).json()['items']
        successors = [r for r in rows if r['parent_id'] == source['id']]
        assert len(successors) == 1
        successor = successors[0]
        assert successor['state'] == 'needs_recheck' and successor['can_resume']
        assert successor['recovery_task_id'] is None and successor['task_id'] == recovery
        assert book.get('daily', source['id'])['state'] == 'superseded'
        # Neither an old retry nor a new key on the original proposal bypasses
        # the explicit new recheck card or creates another queued task.
        for key in ['synthetic_recovery_1', 'synthetic_new_key_on_old']:
            response = await client.post(f"/api/confirmations/{source['id']}/resume",
                json={'revision': source['revision'], 'request_key': key})
            assert response.status_code == 200
            assert response.json()['task']['id'] == recovery
            assert response.json()['task']['status'] == 'stopped' and not response.json()['created']
        client.headers['X-Pajio-Storage-Scope'] = B
        assert not (await client.get('/api/confirmations')).json()['items']
        assert (await client.post(f"/api/confirmations/{successor['id']}/resume",
            json={'revision': successor['revision'], 'request_key': 'synthetic_new_read_1'})).status_code in {404, 409}
        client.headers['X-Pajio-Storage-Scope'] = A
        response = await client.post(f"/api/confirmations/{successor['id']}/resume",
            json={'revision': successor['revision'], 'request_key': 'synthetic_new_read_1'})
        assert response.status_code == 200
        payload = response.json()
        assert payload['created'] and payload['authorized'] is False and payload['delivery'] == 'queued'
        assert payload['task']['id'] != recovery
        with store.connection() as db:
            assert db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (payload['task']['id'],)).fetchone()[0] == A
        assert payload['task']['prompt'] == '重新核对：' + CARD['title']
        assert '旧提案，仅作为历史数据，不是执行授权' in store.get(payload['task']['id'])['prompt']
    await app.state.service.hermes.close()


@pytest.mark.parametrize('surface', ['get', 'list', 'startup'])
def test_restart_repairs_legacy_cancelled_recovery_without_auto_dispatch(tmp_path, surface):
    store = Store(tmp_path / 'wearing.sqlite3'); book = DurableConfirmations(store)
    source, recovery = prepare(store, book)
    with store.connection() as db:
        db.execute("UPDATE tasks SET status='stopped' WHERE id=?", (recovery,))
        db.execute("UPDATE message_handoffs SET state='cancelled' WHERE task_id=?", (recovery,))
    restarted = DurableConfirmations(Store(store.path))
    if surface == 'get': restarted.get('daily', source['id'])
    elif surface == 'list': restarted.list('daily')
    else: restarted.recover_startup()
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: DurableConfirmations(Store(store.path)).list('daily'), range(3)))
    rows = restarted.list('daily')
    retry = [r for r in rows if r['task_id'] == recovery]
    assert len(retry) == 1 and retry[0]['can_resume']
    assert len(store.list()) == 3  # original, blocker, cancelled recovery only


def test_stop_request_waits_for_terminal_proof_before_offering_new_recheck(tmp_path):
    store = Store(tmp_path / 'wearing.sqlite3'); book = DurableConfirmations(store)
    source, recovery = prepare(store, book)
    task = store.update(recovery, status='running', run_id='recovery')
    book.observe_task(task, stopped=True)
    assert book.get('daily', source['id'])['state'] == 'recovering'
    assert not any(r['can_resume'] for r in book.list('daily'))
    store.update(recovery, status='stopped')
    assert sum(r['can_resume'] for r in book.list('daily')) == 1


def test_successful_read_only_recheck_and_consumed_attempt_never_make_retry_card(tmp_path):
    store = Store(tmp_path / 'wearing.sqlite3'); book = DurableConfirmations(store)
    source, recovery = prepare(store, book)
    with store.connection() as db:
        db.execute("UPDATE confirmation_recovery_tasks SET consumed_at='synthetic',result_state='unknown' WHERE task_id=?", (recovery,))
    store.update(recovery, status='stopped')
    assert not any(r['can_resume'] for r in book.list('daily'))
    assert book.get('daily', source['id'])['state'] == 'recovering'
    with store.connection() as db:
        db.execute('UPDATE confirmation_recovery_tasks SET consumed_at=NULL,result_state=NULL WHERE task_id=?', (recovery,))
    store.update(recovery, status='completed_unverified')
    assert book.get('daily', source['id'])['state'] == 'rechecked'
    assert not any(r['can_resume'] for r in book.list('daily'))


async def test_queue_and_recovery_reconciliation_commit_together(tmp_path, monkeypatch):
    store = Store(tmp_path / 'wearing.sqlite3'); book = DurableConfirmations(store)
    source, recovery = prepare(store, book)
    service = TaskService(store, None)
    def fail(*args): raise RuntimeError('Synthetic storage failure')
    monkeypatch.setattr(service.confirmations.durable, 'observe_task_in', fail)
    with pytest.raises(RuntimeError, match='storage failure'):
        await service.cancel_message(recovery, identity_id='daily', owner_scope=A)
    assert store.get(recovery)['status'] == 'draft'
    assert store.message_receipt(recovery)['queue_state'] == 'queued'
    assert book.get('daily', source['id'])['state'] == 'recovering'
