"""Archive/restore acknowledgement and CAS contracts on fresh synthetic data only."""
import sqlite3
import pytest
from wearing.life import LifeBook, LifeDraft, LifeError
from wearing.store import Store


@pytest.fixture
def book(tmp_path): return LifeBook(Store(tmp_path/'synthetic.sqlite3'))


def create(book, kind='note'):
    fields = {'kind': kind, 'title': 'Synthetic', 'content': 'Preserved body'}
    if kind == 'event': fields.update(all_day=True, start_at='2026-10-08', end_at='2026-10-09')
    return book.create('daily', LifeDraft(**fields), 'synthetic-new')


@pytest.mark.parametrize('kind', ['note', 'task', 'event'])
def test_original_archive_and_restore_receipts_never_reapply_over_newer_tombstone(book, kind):
    original = create(book, kind)
    archived = book.update('daily', original['id'], 1, action='archive', request_key='archive-frozen-key')
    restored = book.update('daily', original['id'], 2, action='restore', request_key='restore-frozen-key')
    later = book.update('daily', original['id'], 3, action='archive', request_key='later-other-client')
    reopened = LifeBook(Store(book.store.path))
    assert reopened.update('daily', original['id'], 1, action='archive', request_key='archive-frozen-key') == archived
    assert reopened.update('daily', original['id'], 2, action='restore', request_key='restore-frozen-key') == restored
    assert reopened.get('daily', original['id']) == later
    with pytest.raises(LifeError) as error: reopened.update('daily', original['id'], 2, action='restore', request_key='stale-new-request')
    assert error.value.status == 409
    assert reopened.get('daily', original['id'])['deleted_at']
    acknowledged = reopened.update('daily', original['id'], 4, action='restore', request_key='explicit-revision-four')
    assert not acknowledged['deleted_at'] and acknowledged['revision'] == 5 and acknowledged['content'] == original['content']


def test_lifecycle_mutation_key_cannot_change_action_or_identity(book):
    original = create(book); other = book.store.save_identity('Other')['id']
    first = book.update('daily', original['id'], 1, action='archive', request_key='same-frozen-key')
    with pytest.raises(LifeError): book.update('daily', original['id'], 1, action='restore', request_key='same-frozen-key')
    with pytest.raises(LifeError) as error: book.update(other, original['id'], 1, action='archive', request_key='same-frozen-key')
    assert error.value.status == 404 and book.get('daily', original['id']) == first


def test_failed_archive_receipt_rolls_back_tombstone_and_list_revision(book):
    original = create(book, 'task'); catalog = book.lists.catalog('daily')
    with book.store.connection() as db:
        db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON life_mutation_requests BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    with pytest.raises(sqlite3.IntegrityError): book.update('daily', original['id'], 1, action='archive', request_key='rejected-receipt')
    assert book.get('daily', original['id']) == original and book.lists.catalog('daily') == catalog


@pytest.mark.asyncio
async def test_http_actions_require_revision_and_never_accept_deleted_at_edit_patch(book):
    import httpx
    from fastapi import FastAPI, Request
    from wearing.life_api import install_life_routes
    app = FastAPI()
    @app.middleware('http')
    async def identity(request: Request, call_next):
        request.state.identity_id = 'daily'; return await call_next(request)
    install_life_routes(app, book)
    original = create(book); path = '/api/life/' + original['id']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
        assert (await client.patch(path, json={'revision': 1, 'patch': {'deleted_at': '2026-10-08T12:00:00Z'}})).status_code == 422
        request = {'revision': 1, 'action': 'archive', 'patch': {}, 'request_key': 'archive-http-frozen'}
        first = await client.patch(path, json=request); assert first.status_code == 200
        assert (await client.patch(path, json=request)).json() == first.json()
        assert (await client.patch(path, json={'revision': 1, 'action': 'restore', 'patch': {}, 'request_key': 'bad-stale-restore'})).status_code == 409
        assert (await client.patch(path, json={'revision': 2, 'action': 'edit', 'patch': {'deleted_at': None}})).status_code == 409
        assert book.get('daily', original['id'])['deleted_at']
        good = await client.patch(path, json={'revision': 2, 'action': 'restore', 'patch': {}, 'request_key': 'restore-http-frozen'})
        assert good.status_code == 200 and good.json()['revision'] == 3 and good.json()['deleted_at'] is None
