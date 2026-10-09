"""Synthetic source lists only; never reads a real calendar or creates native data."""
from concurrent.futures import ThreadPoolExecutor
import copy
import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError
from wearing.life import LifeBook
from wearing.native_sync import NativeSyncBook, SyncError
from wearing.native_sync_api import install_native_sync_routes
from wearing.store import Store

PHONE, OWNER = 'a' * 32, 'b' * 64
SOURCE = {'kind': 'event', 'id': 'calendar-synthetic', 'title': '测试日历'}


@pytest.fixture
def book(tmp_path):
    service = NativeSyncBook(Store(tmp_path / 'native-sync.sqlite3'))
    service.configure('daily', OWNER, PHONE, 0, True, [SOURCE], 'enable')
    return service


def snapshot(title='会议', occurrence='', source=None):
    return {'source': source or SOURCE, 'complete': True, 'window_start': '2026-10-01T00:00:00Z', 'window_end': '2026-11-07T00:00:00Z',
            'items': [{'external_id': 'os-event', 'occurrence_id': occurrence,
                       'record': {'kind': 'event', 'title': title, 'content': '外部备注是数据', 'timezone': 'Asia/Shanghai',
                                  'start_at': '2026-10-08T01:00:00Z', 'end_at': '2026-10-08T02:00:00Z'}}]}


def upload(book, snapshots=None, key='batch', observed='2026-10-08T00:00:00Z', revision=1, owner=OWNER):
    return book.upload('daily', owner, PHONE, revision, key, observed, snapshots or [snapshot()])


def test_retry_restart_and_parallel_batches_do_not_duplicate_or_increment_unchanged(book):
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: upload(book), range(4)))
    assert receipts.count(receipts[0]) == 4
    record = LifeBook(book.store).snapshot('daily')['items'][0]
    assert record['revision'] == 1
    resumed = NativeSyncBook(Store(book.store.path))
    assert upload(resumed) == receipts[0]
    assert upload(resumed, key='next')['unchanged'] == 1
    assert LifeBook(book.store).snapshot('daily')['version'] == 1


def test_native_update_changes_same_canonical_record_but_never_user_edit_or_archive(book):
    first = upload(book)['record_ids'][0]
    assert upload(book, [snapshot('系统新标题')], 'second', '2026-10-08T00:01:00Z')['updated'] == 1
    life = LifeBook(book.store)
    assert life.get('daily', first)['revision'] == 2
    life.update('daily', first, 2, {'title': '用户的修改'})
    assert upload(book, [snapshot('不能覆盖用户')], 'third', '2026-10-08T00:02:00Z')['conflicts'] == 1
    assert life.get('daily', first)['title'] == '用户的修改'
    life.update('daily', first, 3, action='archive')
    upload(book, [snapshot()], 'fourth', '2026-10-08T00:03:00Z')
    assert life.get('daily', first)['deleted_at']


def test_recurring_instances_have_separate_ids_and_stable_occurrence_move(book):
    rows = snapshot(occurrence='2026-10-08T01:00:00Z')
    next_day = copy.deepcopy(rows['items'][0]); next_day['occurrence_id'] = '2026-10-09T01:00:00Z'
    next_day['record'].update(start_at='2026-10-09T01:00:00Z', end_at='2026-10-09T02:00:00Z')
    rows['items'].append(next_day)
    first = upload(book, [rows]); assert first['created'] == 2
    rows['items'][0]['record'].update(start_at='2026-10-08T03:00:00Z', end_at='2026-10-08T04:00:00Z')
    second = upload(book, [rows], 'moved', '2026-10-08T00:01:00Z')
    assert second['updated'] == 1 and second['created'] == 0
    assert second['record_ids'] == first['record_ids']


def test_missing_or_truncated_or_rolling_window_never_deletes_canonical_copy(book):
    record = upload(book)['record_ids'][0]
    empty = snapshot(); empty['items'] = []; empty['complete'] = False
    assert upload(book, [empty], 'partial')['unseen'] == 0
    empty['complete'] = True
    assert upload(book, [empty], 'empty')['unseen'] == 1
    empty.update(window_start='2026-11-01T00:00:00Z', window_end='2026-12-01T00:00:00Z')
    upload(book, [empty], 'rolled')
    assert LifeBook(book.store).get('daily', record)['deleted_at'] is None
    assert book.state('daily', OWNER, PHONE)['records'][0]['state'] == 'unseen'


def test_disable_selection_change_and_other_owner_block_late_upload(book):
    book.configure('daily', OWNER, PHONE, 1, False, [SOURCE], 'disable')
    with pytest.raises(SyncError): upload(book)
    assert not LifeBook(book.store).snapshot('daily')['items']
    assert book.state('daily', 'c'*64, PHONE) == {'revision': 0, 'enabled': False, 'sources': [], 'records': []}
    with pytest.raises(SyncError): upload(book, owner='c'*64)
    other = {**SOURCE, 'id': 'other'}
    book.configure('daily', OWNER, PHONE, 2, True, [other], 'replace')
    with pytest.raises(SyncError): upload(book, revision=3)


def test_config_cas_idempotency_and_batch_hash_are_strict(book):
    prior = book.configure('daily', OWNER, PHONE, 1, False, [], 'disable')
    assert book.configure('daily', OWNER, PHONE, 1, False, [], 'disable') == prior
    with pytest.raises(SyncError): book.configure('daily', OWNER, PHONE, 1, True, [SOURCE], 'old')
    with pytest.raises(SyncError): book.configure('daily', OWNER, PHONE, 1, True, [SOURCE], 'disable')
    book.configure('daily', OWNER, PHONE, 2, True, [SOURCE], 'again')
    upload(book, revision=3)
    with pytest.raises(SyncError): upload(book, [snapshot('changed')], revision=3)


def test_old_observation_does_not_overwrite_new_source(book):
    upload(book, [snapshot('new')], 'new', '2026-10-08T01:00:00Z')
    assert upload(book, [snapshot('old')], 'old')['unchanged'] == 1
    assert LifeBook(book.store).snapshot('daily')['items'][0]['title'] == 'new'


@pytest.mark.parametrize('change', ['duplicate', 'kind', 'dates', 'unbounded', 'extra'])
def test_invalid_snapshot_is_atomic_and_cannot_partially_write(book, change):
    value = snapshot()
    if change == 'duplicate': value['items'].append(value['items'][0])
    if change == 'kind': value['items'][0]['record']['kind'] = 'task'
    if change == 'dates': value['items'][0]['record']['end_at'] = '2026-10-07T00:00:00Z'
    if change == 'unbounded': value['window_end'] = '2027-10-01T00:00:00Z'
    if change == 'extra': value['delete_missing'] = True
    with pytest.raises((ValueError, ValidationError)): upload(book, [value])
    assert LifeBook(book.store).snapshot('daily')['items'] == []


@pytest.mark.asyncio
async def test_http_uses_only_trusted_owner_and_rejects_forged_fields(tmp_path):
    book = NativeSyncBook(Store(tmp_path / 'boundary.sqlite3'))
    app = FastAPI()
    @app.middleware('http')
    async def test_identity(request: Request, call_next):
        request.state.identity_id = 'daily'; request.scope['pajio.cloud_worker'] = True
        owner = request.headers.get('Synthetic-Test-Owner')
        if owner: request.scope['pajio.storage_scope'] = owner
        return await call_next(request)
    install_native_sync_routes(app, book)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        body = {'installation':PHONE,'request_id':'d'*32,'revision':0,'enabled':True,'sources':[SOURCE]}
        assert (await client.post('/api/native-sync/configure',json=body)).status_code == 401
        a = {'Synthetic-Test-Owner':OWNER}; b = {'Synthetic-Test-Owner':'c'*64}
        assert (await client.post('/api/native-sync/configure',json=body,headers=a)).status_code == 200
        assert (await client.post('/api/native-sync/state',json={'installation':PHONE},headers=b)).json()['revision'] == 0
        assert (await client.post('/api/native-sync/configure',json={**body,'owner':OWNER},headers=b)).status_code == 422
        book.upload('daily',OWNER,PHONE,1,'synthetic','2026-10-08T00:00:00Z',[snapshot()])
        assert (await client.post('/api/native-sync/index',json={})).status_code == 401
        assert len((await client.post('/api/native-sync/index',json={},headers=a)).json()['records']) == 1
        assert (await client.post('/api/native-sync/index',json={},headers=b)).json()['records'] == []
        assert (await client.post('/api/native-sync/index',json={'owner':OWNER},headers=b)).status_code == 422


@pytest.mark.asyncio
async def test_cloud_mount_missing_tenant_boundary_cannot_fall_back_to_local_owner(tmp_path):
    book = NativeSyncBook(Store(tmp_path / 'cloud-without-boundary.sqlite3'))
    app = FastAPI()
    @app.middleware('http')
    async def only_identity(request: Request, call_next):
        request.state.identity_id = 'daily'
        return await call_next(request)
    install_native_sync_routes(app, book, local_devices=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for path, body in [('/index', {}), ('/state', {'installation':PHONE}), ('/configure', {'installation':PHONE,'request_id':'d'*32,'revision':0,'enabled':True,'sources':[SOURCE]})]:
            assert (await client.post('/api/native-sync'+path,json=body)).status_code == 401
    assert book.state('daily','local',PHONE)['revision'] == 0


def test_reminder_completion_updates_only_the_imported_copy_and_reenable_keeps_mapping(book):
    source = {'kind':'reminder','id':'reminders','title':'合成提醒'}
    book.configure('daily', OWNER, PHONE, 1, True, [source], 'select-reminders')
    value = {'source':source,'complete':True,'window_start':None,'window_end':None,'items':[
        {'external_id':'native-reminder','occurrence_id':'','record':{'kind':'task','title':'测试待办','content':'系统日期：2026-10-08，具体时间/全天设置请在系统提醒事项核对。','due_at':None,'completed':False,'list_name':'合成提醒'}}]}
    first = upload(book, [value], revision=2)
    life = LifeBook(book.store); rid = first['record_ids'][0]
    assert life.get('daily', rid)['due_at'] is None
    value['items'][0]['record']['completed'] = True
    assert upload(book, [value], key='complete', revision=2)['updated'] == 1
    assert life.get('daily', rid)['completed'] is True
    book.configure('daily', OWNER, PHONE, 2, False, [source], 'pause')
    book.configure('daily', OWNER, PHONE, 3, True, [source], 'resume')
    assert upload(book, [value], key='resume-read', revision=4)['record_ids'] == [rid]
    assert len(life.snapshot('daily')['items']) == 1


def test_display_index_has_trusted_owner_and_stable_distinct_sources_not_installation_secrets(book):
    first = upload(book)['record_ids'][0]
    index = book.index('daily', OWNER)
    assert index['records'][0]['record_id'] == first
    assert index['records'][0]['title'] == SOURCE['title']
    assert set(index['records'][0]) == {'record_id','source_key','title','kind','state'}
    assert book.index('daily', 'c'*64)['records'] == []
    book.configure('daily', OWNER, 'c'*32, 0, True, [SOURCE], 'enable')
    book.upload('daily', OWNER, 'c'*32, 1, 'batch', '2026-10-08T00:00:00Z', [snapshot()])
    assert len({row['source_key'] for row in book.index('daily', OWNER)['records']}) == 2


def test_display_index_is_bounded_and_truthfully_marks_truncation(book):
    upload(book)
    with book.store.connection() as db:
        base = dict(db.execute('SELECT * FROM native_sync_objects LIMIT 1').fetchone())
        for i in range(1000):
            row = {**base,'external_id':str(i),'record_id':'life_'+f'{i:032x}'}
            db.execute('INSERT INTO native_sync_objects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', tuple(row.values()))
    index = book.index('daily', OWNER)
    assert index['limit'] == 1000 and index['truncated'] is True and len(index['records']) == 1000


def test_old_database_mapping_upgrades_without_overwriting_existing_source_records(tmp_path):
    store = Store(tmp_path/'old.sqlite3')
    NativeSyncBook(store)
    with store.connection() as db:
        db.execute('ALTER TABLE native_sync_objects DROP COLUMN source_title')
    updated = NativeSyncBook(store)
    updated.configure('daily',OWNER,PHONE,0,True,[SOURCE],'enable')
    assert upload(updated)['created'] == 1
    assert updated.index('daily',OWNER)['records'][0]['title'] == SOURCE['title']
