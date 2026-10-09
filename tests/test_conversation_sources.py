"""Synthetic source-control receipts, fences and real guard entry regressions."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi import FastAPI, Request
from wearing.conversation_sources import ConversationSources, SourceError, generation
from wearing.conversation_sources_api import install_conversation_source_routes
from wearing.session_recall_guard import RecallConfig, RecallGuard
from wearing.service import ACTIVE, TaskError, TaskService
from wearing.store import Store
from wearing.hermes import HermesClient
from wearing.config import Settings
from test_session_recall_guard import A, B, case, admit
from test_lifecycle import HermesStub


@pytest.fixture
def sources(case):
    store, _, old, foreign, current, path = case
    store.update(current['id'], status='completed')
    return ConversationSources(store), case


def selected(book, owner=A, task=None):
    page = book.page('daily', owner_scope=owner)
    row = next((r for r in page['items'] if r['source_task_id'] == task), page['items'][0])
    return {'source_id': row['source_id'], 'source_revision': row['source_revision'], 'revision': page['revision'], 'request_key': 'exclude-fixture-0001'}


def exclude(book, task=None, owner=A):
    return book.exclude('daily', owner_scope=owner, **selected(book, owner, task))


def test_receipt_restart_private_export_and_history_retained(sources):
    book, (store, _, old, foreign, current, path) = sources
    before = path.read_bytes()
    page = book.page('daily', owner_scope=A)
    assert len(page['items']) == 2
    assert foreign['id'] not in json.dumps(page)
    request = selected(book, task=old['id'])
    receipt = book.exclude('daily', owner_scope=A, **request)
    assert receipt['history_retained'] and receipt['continuation_reset']
    assert path.read_bytes() == before and len(store.conversation()) == 3
    restarted = ConversationSources(Store(store.path))
    assert restarted.exclude('daily', owner_scope=A, **request) == receipt
    assert len(restarted.page('daily', owner_scope=B)['items']) == 1
    assert restarted.page('daily', owner_scope=B)['revision'] == 0
    with pytest.raises(SourceError): restarted.exclude('daily', owner_scope=A, **{**request, 'revision': 1})
    from wearing.identity_export import IdentityExports
    data, _, _ = IdentityExports(store)._snapshot('daily', owner_scope=A)
    assert len(data['conversation_source_exclusions']) == 1
    assert set(data['conversation_source_exclusions'][0]) == {'source_id', 'source_task_id', 'revision', 'created_at'}
    assert not data.get('conversation_source_requests') and not data.get('conversation_source_tasks')
    other, _, _ = IdentityExports(store)._snapshot('daily', owner_scope=B)
    assert not other['conversation_source_exclusions']


@pytest.mark.parametrize('status', sorted(ACTIVE))
def test_live_stopping_and_unknown_runs_block_only_own_scope(sources, status):
    book, (store, _, old, foreign, current, _) = sources
    request = selected(book)
    store.update(current['id'], status=status)
    with pytest.raises(SourceError, match='停止'): book.exclude('daily', owner_scope=A, **request)
    assert book.page('daily', owner_scope=A)['revision'] == 0
    # Another owner's state neither prevents their source control nor leaks its details.
    exclude(book, task=foreign['id'], owner=B)


def test_queue_rebind_and_old_receipt_cannot_resurrect_context(sources):
    book, (store, _, old, _, current, _) = sources
    queued, _ = store.accept_message('queued synthetic', 'daily', 'queued-key', ACTIVE, owner_scope=A)
    exclude(book, task=old['id'])
    new = store.get(queued['id'])['session_id']
    assert new != current['session_id']
    store.sync_conversation_session(current['id'], 'late-compaction')
    payload = {'session_id': current['session_id']}
    assert store.reserve_start(queued['id'], payload, 'new-admission', ACTIVE)
    assert payload['session_id'] == new
    with store.connection() as db:
        stamp = db.execute('SELECT generation FROM conversation_source_tasks WHERE task_id=?', (queued['id'],)).fetchone()[0]
        assert stamp == generation(db, 'daily', A) == 1
        assert db.execute('SELECT session_id FROM task_conversation_sessions WHERE task_id=?', (queued['id'],)).fetchone()[0] == new
    store.sync_conversation_session(queued['id'], 'new-compaction')
    with store.connection() as db:
        assert db.execute('SELECT session_id FROM owner_conversations WHERE owner_scope=?', (A,)).fetchone()[0] == 'new-compaction'


@pytest.mark.parametrize('mode', ['search', 'read', 'scroll', 'browse'])
def test_all_recall_modes_exclude_descendants_even_added_later(sources, mode):
    book, (store, _, old, _, current, path) = sources
    exclude(book, task=old['id'])
    task = admit(store, 'new-session', A, run='new-run'); store.update(task['id'], status='running')
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO sessions VALUES(?,NULL,\'fresh\',\'api_server\',\'fixture\',1,1,0)', (task['session_id'],))
        db.execute('INSERT INTO sessions VALUES(?,?,\'later compression\',\'api_server\',\'fixture\',1,1,1)', ('later-child', old['session_id']))
        db.execute('INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(5,\'later-child\',\'user\',\'excludedfixture\',5)')
        db.execute('INSERT INTO messages_fts(rowid,content) VALUES(5,\'excludedfixture\')')
    guard = RecallGuard(RecallConfig(store.path.parent, 'daily'), lambda: 'new-run')
    args = {'query': 'excludedfixture'} if mode == 'search' else {'session_id': 'later-child', 'around_message_id': 5} if mode == 'scroll' else {'session_id': 'later-child'} if mode == 'read' else {}
    result = json.loads(guard.search(current_session_id=task['session_id'], **args))
    assert 'excludedfixture' not in json.dumps(result) and 'later-child' not in json.dumps(result)
    assert old['session_id'] not in json.dumps(result)
    assert json.loads(guard.search(current_session_id=task['session_id'], session_id=current['session_id']))['success']
    # A stale old run row cannot revive its generation even if later marked running.
    store.update(task['id'], status='completed'); store.update(current['id'], status='running')
    assert not json.loads(RecallGuard(RecallConfig(store.path.parent, 'daily'), lambda: 'run-current').search(current_session_id=current['session_id']))['success']


def test_compression_group_membership_cas_and_parallel_exclusion(sources):
    book, (store, _, old, _, current, path) = sources
    before = selected(book, task=current['id'])
    child = 'compressed-current'
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO sessions VALUES(?,?,\'compressed\',\'api_server\',\'fixture\',1,1,0)', (child, current['session_id']))
    store.sync_conversation_session(current['id'], child)
    with pytest.raises(SourceError, match='范围'): book.exclude('daily', owner_scope=A, **before)
    new = selected(book, task=current['id'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: book.exclude('daily', owner_scope=A, **new), range(2)))
    assert receipts[0] == receipts[1]
    assert len(book.page('daily', owner_scope=A)['items']) == 2


def test_foreign_legacy_and_wrong_identity_fail_closed(sources):
    book, (store, _, old, foreign, _, _) = sources
    request = selected(book, owner=B)
    with pytest.raises(SourceError) as error: book.exclude('daily', owner_scope=A, **request)
    assert error.value.status == 404
    second = store.save_identity('Synthetic second')['id']
    with pytest.raises(SourceError) as error: book.exclude(second, owner_scope=A, **selected(book))
    assert error.value.status == 404
    with store.connection() as db:
        db.execute('DELETE FROM task_conversation_sessions WHERE task_id=?', (old['id'],))
    assert old['id'] not in json.dumps(book.page('daily', owner_scope=A))


def test_catalog_pagination_snapshot_and_bounded_journal(sources, monkeypatch):
    book, (store, _, _, _, current, path) = sources
    for index in range(12):
        with store.connection() as db: db.execute('UPDATE owner_conversations SET session_id=? WHERE owner_scope=?', (f'page-{index}', A))
        admit(store, f'page-{index}', A)
    first = book.page('daily', owner_scope=A, limit=10)
    second = book.page('daily', owner_scope=A, limit=10, offset=first['next_offset'], snapshot=first['snapshot'])
    assert len(first['items']) == 10 and len(second['items']) == 4 and second['next_offset'] is None
    exclude(book)
    with pytest.raises(SourceError, match='列表已变化'): book.page('daily', owner_scope=A, offset=10, snapshot=first['snapshot'])
    monkeypatch.setattr('wearing.conversation_sources.MAX_SESSIONS', 1)
    with pytest.raises(SourceError): exclude(book, task=current['id'])


async def test_api_only_trusted_owner_and_closed_schema(sources):
    book, _ = sources
    app = FastAPI(); principal = [None]
    @app.middleware('http')
    async def trusted(request: Request, call_next):
        request.state.identity_id = 'daily'
        if principal[0]: request.scope['pajio.storage_scope'] = principal[0]
        return await call_next(request)
    install_conversation_source_routes(app, book, local_devices=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
        assert (await client.get('/api/conversation-sources', headers={'X-Owner-Scope': A})).status_code == 401
        principal[0] = A
        assert (await client.get('/api/conversation-sources')).status_code == 200
        request = selected(book)
        assert (await client.post('/api/conversation-sources/exclude', json={**request, 'owner_scope': B})).status_code == 422
        assert (await client.post('/api/conversation-sources/exclude', json=request)).status_code == 200


@pytest.mark.parametrize('capability', ['owner-v1', 'sources-v1'])
async def test_start_capability_gate_preserves_draft_before_dispatch(sources, capability):
    book, (store, _, old, _, _, _) = sources
    exclude(book, task=old['id'])
    stub = HermesStub()
    async def transport(request):
        response = await stub(request)
        if request.url.path == '/v1/capabilities':
            data = response.json(); data['wearing']['session_recall_guard'] = capability
            return httpx.Response(200, json=data)
        return response
    client = HermesClient(Settings(store.path.parent, hermes_key='fixture-key'), httpx.MockTransport(transport))
    service = TaskService(store, client)
    task, _ = store.accept_message('new synthetic', 'daily', 'gate-draft', ACTIVE, owner_scope=A)
    try:
        if capability == 'owner-v1':
            with pytest.raises(TaskError, match='来源控制'): await service.start(task['id'])
            assert store.get(task['id'])['status'] == 'draft'
            assert not any(r[0] == 'POST' for r in stub.calls)
        else:
            await service.start(task['id'])
            posts = [r for r in stub.calls if r[:2] == ('POST', '/v1/runs')]
            assert len(posts) == 1 and posts[0][2]['session_id'] == task['session_id']
    finally:
        await client.close()


def test_admission_rejects_context_prepared_before_source_boundary(sources):
    book, (store, _, old, _, current, _) = sources
    queued, _ = store.accept_message('queued synthetic', 'daily', 'queued-race', ACTIVE, owner_scope=A)
    exclude(book, task=old['id'])
    payload = {'session_id': current['session_id'], 'instructions': 'stale synthetic context'}
    assert not store.reserve_start(queued['id'], payload, 'stale-start', ACTIVE, source_generation=0)
    assert store.get(queued['id'])['status'] == 'draft'
    with store.connection() as db:
        assert db.execute('SELECT 1 FROM task_conversation_sessions WHERE task_id=?', (queued['id'],)).fetchone() is None
    assert store.reserve_start(queued['id'], {'instructions': 'fresh context'}, 'fresh-start', ACTIVE, source_generation=1)


def test_goal_raw_source_is_omitted_but_saved_objective_is_kept(sources):
    from wearing.goals import GoalBook
    book, (store, _, old, _, _, _) = sources
    goals = GoalBook(store)
    goal = goals.create('daily', 'Saved product objective', 'Synthetic scope', 'Synthetic evidence', 1, old['id'], owner_scope=A)
    goals.control(goal['id'], goal['revision'], 'resume', owner_scope=A)
    task = goals.claim(goal['id'])
    before = goals.context(task)
    assert 'source_conversation' in before and old['prompt'] in before
    exclude(book, task=old['id'])
    after = goals.context(task)
    assert 'source_conversation' not in after and old['prompt'] not in after
    assert 'Saved product objective' in after


async def test_service_context_race_never_submits_pre_exclusion_payload(sources):
    book, (store, _, old, _, _, _) = sources
    stub = HermesStub()
    client = HermesClient(Settings(store.path.parent, hermes_key='fixture-key'), httpx.MockTransport(stub))
    service = TaskService(store, client)
    task, _ = store.accept_message('new synthetic', 'daily', 'context-race', ACTIVE, owner_scope=A)
    def old_context(_task):
        exclude(book, task=old['id'])
        return 'synthetic stale source context'
    service.context_provider = old_context
    try:
        with pytest.raises(TaskError): await service.start(task['id'])
        assert store.get(task['id'])['status'] == 'draft' and store.get(task['id'])['payload'] is None
        assert not any(r[0] == 'POST' for r in stub.calls)
    finally:
        await client.close()


def test_explicit_local_sources_and_symlink_rejection(sources):
    book, (store, _, _, _, _, path) = sources
    task = admit(store, 'local-conversation', 'local')
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO sessions VALUES(?,NULL,\'local\',\'api_server\',\'fixture\',1,1,0)', (task['session_id'],))
    page = book.page('daily', owner_scope='local')
    assert len(page['items']) == 1
    old = path.with_suffix('.fixture-backup'); path.rename(old); path.symlink_to(old)
    with pytest.raises(SourceError): exclude(book, owner='local')
    path.unlink(); old.rename(path)
    assert exclude(book, owner='local')['excluded']
    assert book.page('daily', owner_scope=A)['revision'] == 0


def test_qa_seed_targets_only_qa_identity_directory(tmp_path, monkeypatch):
    import source_controls_qa_seed as helper
    from wearing.store import now
    store = Store(tmp_path / 'qa.sqlite3')
    with pytest.raises(ValueError): helper.seed(store)
    with store.connection() as db:
        db.execute('INSERT INTO identities VALUES(?,?,?,?,?,?)', ('qa', 'QA synthetic', '', 'CN', now(), now()))
        db.execute('INSERT INTO identity_conversations VALUES(?,?)', ('qa', 'qa-synthetic-session'))
    # Only the unit fixture swaps this constant; shipped helper remains exact-root restricted.
    monkeypatch.setattr(helper, 'QA_ROOT', tmp_path)
    home = tmp_path / 'hermes'; home.mkdir(); (home / 'state.db').write_bytes(b'daily sentinel: not a sqlite db')
    page = helper.seed(store)
    assert page['identity_id'] == 'qa' and len(page['items']) == 2
    assert helper.seed(store) == page
    assert (home / 'state.db').read_bytes() == b'daily sentinel: not a sqlite db'
    assert (tmp_path / 'identities' / 'qa' / 'hermes' / 'state.db').is_file()
    assert not store.conversation('daily') and len(store.conversation('qa')) == 2


def test_background_missing_receipt_is_not_adopted_through_another_owner(sources):
    book, (store, _, old, _, current, path) = sources
    task = store.create('foreign background fixture', 'computer', owner_scope=B)
    with store.connection() as db:
        db.execute('UPDATE tasks SET session_id=? WHERE id=?', ('foreign-background', task['id']))
    assert store.reserve_start(task['id'], {'session_id': 'foreign-background'}, 'foreign-standalone', ACTIVE)
    store.update(task['id'], status='completed')
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO sessions VALUES(?,?,\'foreign\',\'api_server\',\'fixture\',1,1,0)', ('foreign-background', old['session_id']))
    with store.connection() as db:
        db.execute('DELETE FROM conversation_source_tasks WHERE task_id=?', (task['id'],))
    store.update(current['id'], status='running')
    guard = RecallGuard(RecallConfig(store.path.parent, 'daily'), lambda: 'run-current')
    assert not json.loads(guard.search(current_session_id=current['session_id'], session_id='foreign-background'))['success']
