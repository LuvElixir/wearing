"""Recovery presentation and saved withdrawal; isolated SQLite and wire fixtures."""
import asyncio
import json

import httpx
import pytest

from wearing.activity import ActivityBook
from wearing.app import create_app, public_task
from wearing.cloud.worker import TenantBoundary
from wearing.config import Settings
from wearing.durable_confirmations import DurableConfirmations
from wearing.identity_export import IdentityExports
from wearing.search import SearchBook
from wearing.service import ACTIVE, TaskService, TaskError
from wearing.store import Store
from wearing.task_presentation import present_messages, recovery_label, EXECUTION_LIMIT_MESSAGE

A, B = 'a' * 64, 'b' * 64
CARD = {'title': 'QA 保存这份测试笔记？', 'action': '只修改合成记录。', 'impact': '无真实服务。'}
LABEL = '重新核对：' + CARD['title']


class SyntheticClient:
    def __init__(self, capable=False):
        self.capable, self.calls = capable, []
        self.entered, self.release = None, None

    async def probe(self):
        if self.entered:
            self.entered.set()
            await self.release.wait()
        return {'state': 'reachable', 'wearing': {'confirmation_guard': 'durable-v1'} if self.capable else {}}

    async def start(self, payload, request_key):
        self.calls.append((payload, request_key))
        return {'run_id': 'synthetic-recovery-run'}


def original(store, book, owner=A):
    task, _ = store.accept_message('Synthetic source', 'daily', 'source_request_fixture', ACTIVE, owner_scope=owner)
    store.update(task['id'], status='running', run_id='synthetic-source')
    source = book.create('daily', CARD)
    book.finish_wait(source['id'])
    store.update(task['id'], status='failed')
    return book.get('daily', source['id'])


def prepare(store, owner=A):
    book = DurableConfirmations(store)
    source = original(store, book, owner)
    task, _ = book.prepare_recovery('daily', source['id'], source['revision'], 'recovery_request_fixture')
    return book, source, task


def legacy_text(store, task):
    with store.connection() as db:
        prompt = db.execute('SELECT prompt FROM tasks WHERE id=?', (task,)).fetchone()[0]
        db.execute('UPDATE messages SET content=? WHERE task_id=?', (prompt, task))
        db.execute('UPDATE tasks SET title=? WHERE id=?', (prompt[:64], task))
    return prompt


def test_new_message_and_existing_recovery_projection_do_not_change_execution_or_plain_history(tmp_path):
    store = Store(tmp_path / 'fixture.sqlite3')
    _, _, task = prepare(store)
    assert store.conversation()[-1]['content'] == LABEL
    prompt = legacy_text(store, task)
    plain = store.create_message('请解释 request_confirmation；这是一段用户原文。')
    projected = public_task(store.get(task), store=store)
    assert projected['title'] == projected['prompt'] == LABEL
    assert projected['message_kind'] == 'confirmation_recovery'
    assert '旧提案' in prompt and 'request_confirmation' in store.get(task)['prompt']
    messages = present_messages(store, store.conversation())
    assert next(m for m in messages if m['task_id'] == task)['content'] == LABEL
    assert messages[-1]['content'] == plain['prompt']
    assert public_task(plain, store=store)['prompt'] == plain['prompt']
    assert store.conversation()[-2]['content'] == prompt  # Read projection, no migration.


async def test_http_activity_search_and_export_hide_legacy_recovery_internals_and_foreign_owner(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    store = app.state.store
    _, _, task = prepare(store)
    prompt = legacy_text(store, task)
    message = next(m for m in store.conversation() if m['task_id'] == task)
    headers = {'Authorization': 'Bearer fixture-key', 'X-Wearing-Tenant': 'fixture', 'X-Pajio-Storage-Scope': A}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers=headers) as client:
        detail = (await client.get('/api/tasks/' + task)).json()
        assert detail['title'] == detail['prompt'] == LABEL and detail['can_retry'] and detail['can_cancel']
        conversation = (await client.get('/api/conversation')).json()
        row = next(m for m in conversation if m['task_id'] == task)
        assert row['content'] == row['turn']['prompt'] == LABEL
        assert 'request_confirmation' not in json.dumps(row, ensure_ascii=False)
        client.headers['X-Pajio-Storage-Scope'] = B
        assert (await client.get('/api/tasks/' + task)).status_code == 404
        assert not (await client.get('/api/conversation')).json()
    activity = ActivityBook(store).snapshot(owner_scope=A)
    assert next(i for i in activity['items'] if i['task_id'] == task)['title'] == LABEL
    search = SearchBook(store)
    assert search.message('daily', message['id'], owner_scope=A)['content'] == LABEL
    assert not search.page('daily', 'request_confirmation', owner_scope=A)['items']
    matches = search.page('daily', '重新核对', owner_scope=A)['items']
    assert len(matches) == 1 and matches[0]['title'] == LABEL
    data, *_ = IdentityExports(store)._snapshot('daily', owner_scope=A)
    assert next(t for t in data['tasks'] if t['id'] == task)['prompt'] == LABEL
    assert next(m for m in data['conversation'] if m['task_id'] == task)['content'] == LABEL
    assert store.get(task)['prompt'] == prompt
    await app.state.service.hermes.close()


async def test_refusal_reason_survives_restart_then_explicit_retry_preserves_internal_prompt(tmp_path):
    store = Store(tmp_path / 'fixture.sqlite3'); client = SyntheticClient()
    service = TaskService(store, client)
    source = original(store, service.confirmations.durable)
    response = await service.resume_confirmation('daily', source['id'], source['revision'], 'recovery_request_fixture', owner_scope=A)
    task = response['task']['id']
    assert response['delivery'] == 'saved' and not client.calls
    assert '安全恢复' in response['reason']
    restarted = TaskService(Store(store.path), client)
    detail = public_task(restarted.require(task), store=restarted.store)
    assert detail['can_retry'] and detail['can_cancel'] and '安全恢复' in detail['blocked_reason']
    assert not await restarted.dispatch_message() and not client.calls
    with pytest.raises(TaskError, match='安全恢复'):
        await restarted.start(task)
    assert '安全恢复' in store.message_receipt(task)['blocked_reason']
    client.capable = True
    assert (await restarted.start(task))['status'] == 'running'
    assert len(client.calls) == 1 and client.calls[0][0]['input'] == store.get(task)['prompt']
    assert 'request_confirmation' in client.calls[0][0]['input']
    current = public_task(store.get(task), store=store)
    assert not current['can_retry'] and not current['can_cancel'] and not current['blocked_reason']


async def test_only_owner_saved_withdrawal_is_idempotent_and_old_resume_cannot_revive(tmp_path):
    store = Store(tmp_path / 'fixture.sqlite3'); book, source, task = prepare(store)
    service = TaskService(store, SyntheticClient(True))
    before = store.get(task), store.events(task)
    for identity, owner in [('daily', B), ('other', A)]:
        with pytest.raises(TaskError):
            await service.cancel_message(task, identity_id=identity, owner_scope=owner)
    assert (store.get(task), store.events(task)) == before
    assert (await service.cancel_message(task, identity_id='daily', owner_scope=A))['status'] == 'stopped'
    events, proposals = store.events(task), book.list('daily', owner_scope=A)
    restarted = TaskService(Store(store.path), service.hermes)
    assert (await restarted.cancel_message(task, identity_id='daily', owner_scope=A))['status'] == 'stopped'
    assert store.events(task) == events and book.list('daily', owner_scope=A) == proposals
    reply = await restarted.resume_confirmation('daily', source['id'], source['revision'], 'recovery_request_fixture', owner_scope=A)
    assert reply['task']['id'] == task and reply['task']['status'] == 'stopped' and not reply['created']
    assert sum(p['can_resume'] for p in proposals) == 1 and not service.hermes.calls


async def test_unowned_saved_draft_cannot_be_adopted_by_cloud_owner(tmp_path):
    store = Store(tmp_path / 'fixture.sqlite3'); _, _, task = prepare(store, owner=None)
    service = TaskService(store, None)
    assert not public_task(store.get(task), store=store)['can_cancel']
    with pytest.raises(TaskError):
        await service.cancel_message(task, identity_id='daily', owner_scope=A)
    assert public_task(store.get(task), store=store, local_devices=True)['can_cancel']
    assert (await service.cancel_message(task, identity_id='daily', owner_scope='local'))['status'] == 'stopped'


async def test_withdrawal_during_another_worker_probe_prevents_any_dispatch(tmp_path):
    store = Store(tmp_path / 'fixture.sqlite3'); _, _, task = prepare(store)
    client = SyntheticClient(True); client.entered, client.release = asyncio.Event(), asyncio.Event()
    first, second = TaskService(store, client), TaskService(Store(store.path), client)
    pending = asyncio.create_task(first.start(task))
    await client.entered.wait()
    await second.cancel_message(task, identity_id='daily', owner_scope=A)
    client.release.set()
    with pytest.raises(TaskError): await pending
    assert not client.calls and store.get(task)['status'] == 'stopped'


@pytest.mark.parametrize('change', [{'status':'starting'}, {'status':'running','run_id':'fixture'}, {'payload':{'input':'claimed'}}, {'idempotency_key':'already-admitted'}, {'idempotency_key':''}])
async def test_claimed_or_ambiguous_draft_is_not_withdrawable(tmp_path, change):
    store = Store(tmp_path / 'fixture.sqlite3'); _, _, task = prepare(store)
    store.update(task, **change)
    before = store.get(task)
    assert not public_task(before, store=store)['can_cancel']
    with pytest.raises(TaskError):
        await TaskService(store, None).cancel_message(task, identity_id='daily', owner_scope=A)
    assert store.get(task) == before


def test_missing_or_foreign_source_never_falls_back_to_internal_prompt(tmp_path):
    store = Store(tmp_path / 'fixture.sqlite3'); _, source, task = prepare(store)
    legacy_text(store, task)
    with store.connection() as db:
        for body in ['invalid json', '{}', '{"title":1}']:
            db.execute('UPDATE durable_confirmations SET card=? WHERE id=?', (body, source['id']))
            assert recovery_label(db, task) == '重新核对之前暂停的事情'
        db.execute('UPDATE durable_confirmations SET card=?,identity_id=? WHERE id=?', (json.dumps(CARD), 'another', source['id']))
        assert recovery_label(db, task) == '重新核对之前暂停的事情'


def test_public_failure_reason_is_a_known_enum_not_raw_provider_text(tmp_path):
    store = Store(tmp_path / 'fixture.sqlite3')
    task = store.create('合成任务', 'computer')
    for error, code in [(EXECUTION_LIMIT_MESSAGE, 'execution_limit'), ('request_confirmation JSON private trace', None)]:
        failed = store.update(task['id'], status='failed', error=error)
        visible = public_task(failed, store=store)
        assert visible['failure_code'] == code and 'error' not in visible
        assert store.get(task['id'])['error'] == error
    visible = public_task(store.update(task['id'], status='running', error=EXECUTION_LIMIT_MESSAGE), store=store)
    assert visible['failure_code'] is None
