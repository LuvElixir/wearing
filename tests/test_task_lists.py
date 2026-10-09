import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

from fastapi import FastAPI, Request
import httpx
import pytest
from pydantic import ValidationError

from wearing.life import LifeBook, LifeDraft, LifeError
from wearing.life_api import install_life_routes
from wearing.store import Store
from wearing.task_lists import ListChange, install_task_list_routes
from wearing.task_list_tools import dispatch


@pytest.fixture
def life(tmp_path):
    return LifeBook(Store(tmp_path/'state.sqlite3'))


def change(life, action, *, key='task-list-request-001', revision=None, identity='daily', **fields):
    body = ListChange(action=action, revision=life.lists.catalog(identity)['revision'] if revision is None else revision, request_key=key, **fields)
    return life.lists.change(identity, body)


def task(life, title='Paper', name='Shopping', key='record-one'):
    return life.create('daily', LifeDraft(kind='task', title=title, list_name=name), key)


def test_existing_tasks_keep_ids_and_revisions_during_additive_migration(life):
    one = task(life)
    two = task(life, title='Milk', key='record-two')
    with life.store.connection() as db:
        db.execute('DELETE FROM task_list_members'); db.execute('DELETE FROM task_lists'); db.execute('DELETE FROM task_list_boards')
    reopened = LifeBook(Store(life.store.path))
    catalog = reopened.lists.catalog('daily')
    assert len(catalog['lists']) == 1 and catalog['lists'][0]['name'] == 'Shopping'
    page = reopened.lists.items('daily', catalog['lists'][0]['id'])
    assert {row['id'] for row in page['items']} == {one['id'], two['id']}
    assert all(row['revision'] == 1 for row in page['items'])
    assert reopened.lists.catalog('daily') == catalog


def test_create_rename_archive_restore_preserves_canonical_tasks(life):
    created = change(life, 'create', name='Travel')
    identifier = created['lists'][0]['id']
    added = change(life, 'add', list_id=identifier, title='Passport', content='bring original', key='task-list-request-002')
    item = added['record']
    renamed = change(life, 'rename', list_id=identifier, name='Packing', key='task-list-request-003')
    saved = life.get('daily', item['id'])
    assert saved['id'] == item['id'] and saved['revision'] == 2 and saved['list_name'] == 'Packing'
    assert renamed['changed_records'] == 1
    archived = change(life, 'archive', list_id=identifier, key='task-list-request-004')
    assert archived['lists'][0]['archived_at'] and not life.get('daily', item['id'])['deleted_at']
    with pytest.raises(LifeError): change(life, 'add', list_id=identifier, title='Invalid', key='task-list-request-005')
    with pytest.raises(LifeError): task(life, name='Packing', key='legacy-create')
    restored = change(life, 'restore', list_id=identifier, key='task-list-request-006')
    assert not restored['lists'][0]['archived_at'] and restored['lists'][0]['open'] == 1
    assert life.lists.items('daily', identifier)['items'][0]['content'] == 'bring original'


def test_renaming_updates_deleted_record_label_without_resurrecting(life):
    item = task(life)
    life.update('daily', item['id'], item['revision'], action='archive')
    identifier = life.lists.catalog('daily')['lists'][0]['id']
    change(life, 'rename', list_id=identifier, name='New label')
    current = life.get('daily', item['id'])
    assert current['deleted_at'] and current['list_name'] == 'New label' and current['revision'] == 3
    assert not life.lists.items('daily', identifier)['items']
    life.update('daily', item['id'], current['revision'], action='restore')
    assert life.lists.items('daily', identifier)['items'][0]['id'] == item['id']


def test_move_and_stable_order_do_not_clone_tasks(life):
    one, two, three = [task(life, title=str(i), key=f'record-{i}') for i in range(3)]
    old = life.lists.catalog('daily')['lists'][0]['id']
    destination = change(life, 'create', name='Trip')['lists'][0]['id']
    moved = change(life, 'move', list_id=old, record_id=two['id'], record_revision=1, target_list_id=destination, key='task-list-request-002')
    assert moved['record']['id'] == two['id'] and moved['record']['list_name'] == 'Trip'
    reordered = change(life, 'reorder', list_id=old, record_id=three['id'], record_revision=1, before_id=one['id'], key='task-list-request-003')
    assert reordered['record']['revision'] == 1
    assert [row['id'] for row in life.lists.items('daily', old)['items']] == [three['id'], one['id']]
    change(life, 'reorder', list_id=old, record_id=three['id'], record_revision=1, key='task-list-request-004')
    assert [row['id'] for row in life.lists.items('daily', old)['items']] == [one['id'], three['id']]
    assert len(life.snapshot('daily')['items']) == 3
    assert LifeBook(Store(life.store.path)).lists.items('daily', old)['items'] == life.lists.items('daily', old)['items']


def test_legacy_record_change_moves_list_membership_and_invalidates_page(life):
    item = task(life)
    before = life.lists.catalog('daily')
    updated = life.update('daily', item['id'], 1, {'list_name': 'Weekend'})
    after = life.lists.catalog('daily')
    target = next(row for row in after['lists'] if row['name'] == 'Weekend')
    assert life.lists.items('daily', target['id'])['items'][0]['id'] == updated['id']
    with pytest.raises(LifeError) as error: life.lists.items('daily', before['lists'][0]['id'], revision=before['revision'])
    assert error.value.status == 409


def test_more_than_ten_tasks_are_all_accessible_with_version_bound_pagination(life):
    for index in range(117): task(life, title=str(index), key=f'record-{index}')
    identifier = life.lists.catalog('daily')['lists'][0]['id']
    page = life.lists.items('daily', identifier)
    assert len(page['items']) == 100 and page['next_offset'] == 100 and page['list']['total'] == 117
    tail = life.lists.items('daily', identifier, offset=100, revision=page['revision'])
    assert len(tail['items']) == 17 and tail['next_offset'] is None
    assert len({row['id'] for row in page['items'] + tail['items']}) == 117
    life.update('daily', page['items'][0]['id'], 1, {'completed': True})
    with pytest.raises(LifeError): life.lists.items('daily', identifier, offset=100, revision=page['revision'])
    with pytest.raises(LifeError): life.lists.items('daily', identifier, offset=100)


def test_exact_retry_survives_restart_and_later_changes(life):
    body = ListChange(action='create', name='First', revision=0, request_key='task-list-request-001')
    receipt = life.lists.change('daily', body)
    identifier = receipt['lists'][0]['id']
    change(life, 'rename', list_id=identifier, name='Second', key='task-list-request-002')
    assert LifeBook(Store(life.store.path)).lists.change('daily', body) == receipt
    with pytest.raises(LifeError): life.lists.change('daily', body.model_copy(update={'name': 'different'}))
    assert life.lists.catalog('daily')['lists'][0]['name'] == 'Second'


def test_stale_catalog_and_record_revision_cannot_overwrite(life):
    item = task(life)
    catalog = life.lists.catalog('daily'); identifier = catalog['lists'][0]['id']
    life.update('daily', item['id'], 1, {'title': 'edited'})
    with pytest.raises(LifeError): change(life, 'rename', list_id=identifier, name='stale', revision=catalog['revision'])
    with pytest.raises(LifeError): change(life, 'reorder', list_id=identifier, record_id=item['id'], record_revision=1)
    assert life.get('daily', item['id'])['title'] == 'edited'


def test_concurrent_operations_share_one_compare_and_swap(life):
    def create(number):
        try: return change(life, 'create', name=f'List {number}', revision=0, key=f'task-list-request-{number:03}')
        except LifeError as error: return error.status
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(create, [1, 2]))
    assert sum(isinstance(result, dict) for result in results) == 1 and 409 in results
    assert len(life.lists.catalog('daily')['lists']) == 1


def test_receipt_failure_rolls_back_list_record_and_order(life):
    item = task(life); before = life.lists.catalog('daily')
    with life.store.connection() as db:
        db.execute("CREATE TRIGGER deny_list_receipt BEFORE INSERT ON task_list_requests BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    with pytest.raises(sqlite3.IntegrityError): change(life, 'rename', list_id=before['lists'][0]['id'], name='Not saved')
    assert life.get('daily', item['id']) == item
    assert life.lists.catalog('daily') == before


def test_move_failed_before_reference_rolls_back_record_and_membership(life):
    item = task(life); source = life.lists.catalog('daily')['lists'][0]['id']
    target = change(life, 'create', name='New')['lists'][0]['id']
    before = life.lists.catalog('daily')
    with pytest.raises(LifeError): change(life, 'move', key='task-list-request-002', list_id=source, record_id=item['id'], record_revision=1, target_list_id=target, before_id='life_'+'f'*32)
    assert life.get('daily', item['id']) == item and life.lists.catalog('daily') == before


def test_foreign_lists_records_and_same_keys_stay_in_own_identity(life):
    one = task(life); source = life.lists.catalog('daily')['lists'][0]['id']
    other = life.store.save_identity('Work')['id']
    target = change(life, 'create', identity=other, name='Shopping')['lists'][0]['id']
    with pytest.raises(LifeError) as error: life.lists.items(other, source)
    assert error.value.status == 404
    with pytest.raises(LifeError): change(life, 'move', list_id=source, record_id=one['id'], record_revision=1, target_list_id=target)
    with pytest.raises(LifeError): change(life, 'rename', identity=other, list_id=source, name='bad', key='task-list-request-002')
    assert not life.lists.items(other, target)['items']


def test_name_limits_duplicates_and_field_allowlist(life, monkeypatch):
    change(life, 'create', name='Shopping')
    with pytest.raises(LifeError): change(life, 'create', name='shopping', key='task-list-request-002')
    monkeypatch.setattr('wearing.task_lists.MAX_LISTS', 1)
    with pytest.raises(LifeError) as error: change(life, 'create', name='Other', key='task-list-request-003')
    assert error.value.status == 413
    for fields in [{'action': 'create', 'name': ''}, {'action': 'create', 'name': 'x', 'identity_id': 'other'}, {'action': 'archive', 'list_id': 'list_'+'a'*32, 'title': 'bad'}, {'action': 'move', 'record_id': 'life_'+'a'*32}]:
        with pytest.raises(ValidationError): ListChange(revision=1, request_key='task-list-request-001', **fields)


def test_agent_uses_same_canonical_records_and_provenance(life):
    result = dispatch(life, 'daily', 'task_list_change', {'action': 'create', 'name': 'Trips', 'revision': 0, 'request_key': 'task-list-request-001'})
    created = dispatch(life, 'daily', 'task_list_change', {'action': 'add', 'list_id': result['lists'][0]['id'], 'title': 'Ticket', 'revision': result['revision'], 'request_key': 'task-list-request-002'})
    assert life.get('daily', created['record']['id'])['title'] == 'Ticket'
    with life.store.connection() as db:
        assert db.execute('SELECT actor FROM life_changes').fetchone()[0] == 'agent'
    assert dispatch(life, 'daily', 'task_lists', {})['lists'][0]['total'] == 1


def test_routes_use_existing_identity_gate_and_strict_body(life):
    app = FastAPI()
    @app.middleware('http')
    async def identity(request: Request, next):
        request.state.identity_id = request.headers.get('X-Wearing-Identity', 'daily')
        return await next(request)
    install_life_routes(app, life); install_task_list_routes(app, life)
    other = life.store.save_identity('Other')['id']
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/task-lists/change', json={'action': 'create', 'revision': 0, 'name': 'Shopping', 'request_key': 'task-list-request-001'})
            assert response.status_code == 200
            identifier = response.json()['lists'][0]['id']
            assert (await client.get('/api/task-lists/'+identifier+'/items', headers={'X-Wearing-Identity': other})).status_code == 404
            assert (await client.get('/api/task-lists/'+identifier+'/items?offset=100')).status_code == 422
            assert (await client.post('/api/task-lists/change', json={'action':'create','revision':0,'name':'x','request_key':'task-list-request-002','identity_id':other})).status_code == 422
    asyncio.run(run())


def test_list_add_key_cannot_collide_with_legacy_creation_protocol(life):
    key = 'task-list-request-001'
    original = task(life, title='Paper', key=key)
    catalog = life.lists.catalog('daily'); identifier = catalog['lists'][0]['id']
    added = change(life, 'add', list_id=identifier, title='Paper', key=key)
    assert added['record']['id'] != original['id']
    assert len(life.snapshot('daily')['items']) == 2
    assert life.lists.change('daily', ListChange(action='add', list_id=identifier, title='Paper', request_key=key, revision=catalog['revision'])) == added


def test_large_rename_limit_rolls_back_without_partial_labels(life, monkeypatch):
    items = [task(life, key=f'fixture-{i}') for i in range(2)]
    catalog = life.lists.catalog('daily')
    monkeypatch.setattr('wearing.task_lists.MAX_RENAME_ITEMS', 1)
    with pytest.raises(LifeError) as error: change(life, 'rename', list_id=catalog['lists'][0]['id'], name='Later')
    assert error.value.status == 413
    assert life.lists.catalog('daily') == catalog
    assert [life.get('daily', item['id']) for item in items] == items
