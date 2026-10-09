"""Lost HTTP acknowledgements must not cause an offline edit to be reapplied."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from wearing.life import LifeBook, LifeDraft, LifeError
from wearing.store import Store

@pytest.fixture
def book(tmp_path):
    return LifeBook(Store(tmp_path / 'synthetic.sqlite3'))

def create(book, kind='note'):
    values = {'kind': kind, 'title': '合成记录', 'content': '仅用于回归'}
    if kind == 'event':
        values.update(all_day=True, start_at='2026-10-08', end_at='2026-10-09')
    return book.create('daily', LifeDraft(**values), 'synthetic-create')

@pytest.mark.parametrize('kind,patch', [('note', {'title': '新笔记', 'content': '完整修改'}), ('task', {'completed': True}), ('event', {'all_day': False, 'start_at': '2026-10-08T09:00:00+08:00', 'end_at': '2026-10-08T10:00:00+08:00'})])
def test_replay_after_restart_returns_original_receipt_even_if_record_later_changed(book, kind, patch):
    record = create(book, kind)
    first = book.update('daily', record['id'], 1, patch, request_key='attempt-one')
    later = book.update('daily', record['id'], first['revision'], {'title': '其他客户端的新修改'})
    reopened = LifeBook(Store(book.store.path))
    assert reopened.update('daily', record['id'], 1, patch, request_key='attempt-one') == first
    assert reopened.get('daily', record['id']) == later
    assert reopened.snapshot('daily')['version'] == 3

@pytest.mark.parametrize('changed', [{'revision': 2}, {'patch': {'content': '不能替换'}}, {'action': 'archive'}])
def test_same_key_with_different_request_is_conflict_without_changes(book, changed):
    record = create(book)
    args = dict(revision=1, patch={'content': '本机修改'}, action='edit', request_key='same-request')
    first = book.update('daily', record['id'], **args)
    with pytest.raises(LifeError) as error:
        book.update('daily', record['id'], **{**args, **changed})
    assert error.value.status == 409
    assert book.get('daily', record['id']) == first

def test_noop_receipt_is_durable_and_never_adopts_later_record_version(book):
    record = create(book)
    assert book.update('daily', record['id'], 1, {'title': record['title']}, request_key='noop') == record
    book.update('daily', record['id'], 1, {'content': '之后修改'})
    assert book.update('daily', record['id'], 1, {'title': record['title']}, request_key='noop') == record

def test_concurrent_replays_commit_only_one_revision_and_receipt(book):
    record = create(book)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: book.update('daily', record['id'], 1, {'content': '一次修改'}, request_key='concurrent'), range(8)))
    assert all(result == results[0] for result in results)
    assert book.get('daily', record['id'])['revision'] == 2
    with book.store.connection() as db:
        assert db.execute('SELECT count(*) FROM life_mutation_requests').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM life_changes').fetchone()[0] == 2

def test_identity_scope_and_failed_cas_do_not_leak_receipts_or_consume_key(book):
    record = create(book)
    other = book.store.save_identity('另一个身份')['id']
    first = book.update('daily', record['id'], 1, {'content': '新版本'}, request_key='key')
    with pytest.raises(LifeError) as error:
        book.update(other, record['id'], 1, {'content': '新版本'}, request_key='key')
    assert error.value.status == 404
    with pytest.raises(LifeError):
        book.update('daily', record['id'], 1, {'content': '本机过期稿'}, request_key='failed-cas')
    with book.store.connection() as db:
        assert db.execute("SELECT count(*) FROM life_mutation_requests WHERE request_key='failed-cas'").fetchone()[0] == 0
    applied = book.update('daily', record['id'], first['revision'], {'content': '核对后的稿'}, request_key='failed-cas')
    assert applied['revision'] == 3

@pytest.mark.asyncio
async def test_http_replay_after_discarded_response_uses_same_receipt_and_revision(tmp_path):
    import httpx
    from wearing.app import create_app
    from wearing.config import Settings
    app = create_app(Settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        created = (await client.post('/api/life', json={'record': {'kind': 'task', 'title': '合成待办'}, 'request_key': 'create-one'})).json()
        path = '/api/life/' + created['id']
        request = {'revision': 1, 'patch': {'completed': True}, 'request_key': 'lost-http-ack'}
        accepted = await client.patch(path, json=request)
        replay = await client.patch(path, json=request)
        assert accepted.status_code == replay.status_code == 200
        assert accepted.json() == replay.json()
        assert (await client.get(path)).json()['revision'] == 2
        assert (await client.patch(path, json={**request, 'patch': {'completed': False}})).status_code == 409
        assert (await client.patch(path, json={'revision': 1, 'patch': {'completed': False}})).status_code == 409
    await app.state.service.hermes.close()
