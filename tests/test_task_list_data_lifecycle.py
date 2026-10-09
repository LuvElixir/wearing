"""Synthetic list/recurrence export and whole-instance erasure coverage."""
import io
import json
import shutil
import zipfile

import pytest

from wearing.account_deletion import DeletionJobs, digest
from wearing.account_deletion_fixture import SyntheticDeletionAdapter
from wearing.calendar_series import CalendarSeriesBook
from wearing.identity_export import IdentityExports, ExportError
from wearing.life import LifeBook, LifeDraft
from wearing.store import Store, now
from wearing.task_lists import ListChange


def populate(path):
    store = Store(path); life = LifeBook(store); CalendarSeriesBook(store)
    other = store.save_identity('Work')['id']
    own = life.create('daily', LifeDraft(kind='task', title='MY_TASK', list_name='MY_LIST'), 'own-task')
    foreign = life.create(other, LifeDraft(kind='task', title='OTHER_TASK', list_name='OTHER_LIST'), 'other-task')
    catalog = life.lists.catalog('daily')
    life.lists.change('daily', ListChange(action='archive', revision=catalog['revision'], list_id=catalog['lists'][0]['id'], request_key='private-operation-key'))
    with store.connection() as db:
        for identity, identifier, title in [('daily', 'series_own', 'MY_SERIES'), (other, 'series_other', 'OTHER_SERIES')]:
            body = json.dumps({'template': {'title': title}, 'rule': {'frequency': 'weekly'}})
            db.execute('INSERT INTO calendar_series VALUES(?,?,1,?,NULL,?,?)', (identifier, identity, body, now(), now()))
            db.execute('INSERT INTO calendar_exceptions VALUES(?,?,?,0,1)', (identifier, '2026-10-08', json.dumps({'title': title + '_EXCEPTION'})))
            db.execute('INSERT INTO calendar_exceptions VALUES(?,?,NULL,1,2)', (identifier, '2026-10-15'))
            db.execute('INSERT INTO calendar_series_requests VALUES(?,?,?,?,?)', (identity, 'PRIVATE_REQUEST_SECRET', 'INTERNAL_HASH_SECRET', 'INTERNAL_RECEIPT_SECRET', now()))
        # Corrupt membership may not grant a foreign record to the exporting identity.
        db.execute('UPDATE task_list_members SET identity_id=?,list_id=? WHERE record_id=?', ('daily', catalog['lists'][0]['id'], foreign['id']))
    return store, own, other


def contents(exporter):
    receipt = exporter.create('daily', 'export-list-fixture-001')
    raw, _ = exporter.download('daily', receipt['id'])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return json.loads(archive.read('records.json')), b'\n'.join(archive.read(name) for name in archive.namelist())


def test_export_has_real_lists_members_and_series_with_no_foreign_or_internal_journals(tmp_path):
    store, task, other = populate(tmp_path/'state.sqlite3')
    data, raw = contents(IdentityExports(store))
    assert len(data['task_lists']) == 1 and data['task_lists'][0]['name'] == 'MY_LIST'
    assert data['task_lists'][0]['archived_at']
    assert data['task_list_members'] == [{'record_id': task['id'], 'list_id': data['task_lists'][0]['id'], 'position': 1}]
    assert data['calendar_series'][0]['body']['template']['title'] == 'MY_SERIES'
    assert len(data['calendar_exceptions']) == 2
    assert data['calendar_exceptions'][0]['body']['title'] == 'MY_SERIES_EXCEPTION'
    assert data['calendar_exceptions'][1]['body'] is None and data['calendar_exceptions'][1]['cancelled'] == 1
    for value in [b'OTHER_TASK', b'OTHER_LIST', b'OTHER_SERIES', b'PRIVATE_REQUEST_SECRET', b'INTERNAL_HASH_SECRET', b'INTERNAL_RECEIPT_SECRET', b'private-operation-key']:
        assert value not in raw
    assert all(key not in data for key in ['task_list_boards', 'task_list_requests', 'calendar_series_requests'])


def test_new_export_sections_obey_global_row_limit_without_partial_file(tmp_path, monkeypatch):
    store, _, _ = populate(tmp_path/'state.sqlite3')
    exporter = IdentityExports(store)
    monkeypatch.setattr('wearing.identity_export.MAX_ROWS', 4)
    with pytest.raises(ExportError) as error: contents(exporter)
    assert error.value.status == 413
    assert not list(exporter.root.glob('*.zip'))


def test_whole_private_tenant_erasure_covers_new_tables_without_touching_another_owner(tmp_path):
    rows = [dict(tenant_id=tenant, classification='private', owner_user_id=owner, member_ids=[owner], instance_id='instance_' + tenant) for tenant, owner in [('one', 'user_one'), ('two', 'user_two')]]
    jobs = DeletionJobs(tmp_path/'journal', initialize=True, mode='synthetic')
    for row in rows: jobs.register(row['tenant_id'], row['classification'], row['member_ids'], owner_user_id=row['owner_user_id'], instance_id=row['instance_id'])
    adapter = SyntheticDeletionAdapter.create(rows)
    try:
        for tenant in ['one', 'two']:
            for area in ['primary', 'indexes', 'backups']:
                # Brand-new fixtures, never existing application paths.
                path = adapter.root/digest(tenant)/area/'synthetic.sqlite3'
                store, _, _ = populate(path)
                with store.connection() as db:
                    assert {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {'task_lists', 'task_list_members', 'task_list_requests', 'task_list_boards', 'calendar_series', 'calendar_exceptions', 'calendar_series_requests'}
        plan = jobs.preview('user_one')
        request = jobs.request('user_one', 'delete-list-fixture-001', plan['revision'])
        state = jobs.run(request['id'], adapter, max_steps=50)
        assert state['state'] == 'completed'
        assert not list((adapter.root/digest('one')).iterdir())
        for area in ['primary', 'indexes', 'backups']:
            assert (adapter.root/digest('two')/area/'synthetic.sqlite3').is_file()
    finally: shutil.rmtree(adapter.root)
