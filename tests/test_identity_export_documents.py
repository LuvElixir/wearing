"""Synthetic stores only: product document export and trusted-owner receipts."""
import asyncio
from contextlib import contextmanager
import hashlib
import io
import json
from types import SimpleNamespace
import zipfile

from fastapi import FastAPI, Request
import httpx
import pytest

from wearing.briefing_preferences import BriefingPreferences, SavePreferences
from wearing.identity_export import IdentityExports, ExportError, MAX_TEXT_BYTES
from wearing.identity_export_api import install_identity_export_routes
from wearing.store import Store, now
from wearing.workspace_text import WorkspaceText, TextSave


def setup(root):
    store = Store(root / 'state.sqlite3')
    def runtime(identity):
        base = root if identity == 'daily' else root / 'identities' / identity
        path = base / 'workspace'
        path.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(workspace=path)
    return IdentityExports(store), BriefingPreferences(store), WorkspaceText(store, runtime)


def unpack(book, identity='daily', key='export-documents-001', **kwargs):
    receipt = book.create(identity, key, **kwargs)
    raw, _ = book.download(identity, receipt['id'], **kwargs)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    return json.loads(files['records.json']), json.loads(files['manifest.json']), files


def preference(prefs, identity='daily', interests=None):
    return prefs.save(identity, SavePreferences(revision=0, request_key='preference-save-key-001',
        interests=interests or ['中文阅读'], priorities='关注项目进展', sources=['task', 'files'], max_items=2))


def edit(editor, identity='daily', path='report.md', before='原文\n', after='新文\n', key='document-save-key-001'):
    source = editor.root(identity) / path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(before, encoding='utf-8')
    base = editor.read(identity, path)
    return editor.save(identity, TextSave(path=path, text=after, request_key=key,
        base_revision=base['revision'], base_sha256=base['sha256']))


def fixture_version(book, *, key='document-save-key-001', old=b'old body', new=b'new body', path='report.md', identity='daily', completed=True, receipt_updates=None):
    stamp = now()
    receipt = {'identity_id': identity, 'path': path, 'source_path': path,
               'request_key': key, 'recovery_id': key, 'save_mode': 'replace', 'saved_at': stamp,
               'sha256': hashlib.sha256(new).hexdigest(), 'size': len(new)}
    receipt.update(receipt_updates or {})
    with book.store.connection() as db:
        db.execute('INSERT INTO workspace_text_versions VALUES(?,?,?,?,?,?,?,?,?,?)',
            (identity, key, 'INTERNAL-SPEC-SECRET', path, path, 'INTERNAL-REVISION', old, new, stamp,
             json.dumps(receipt) if completed else None))


def test_real_preferences_and_completed_recovery_are_closed_product_records(tmp_path):
    book, prefs, editor = setup(tmp_path)
    preference(prefs)
    saved = edit(editor)
    fixture_version(book, key='document-pending-002', old=b'PENDING-OLD-SECRET', new=b'PENDING-NEW-SECRET', completed=False)
    with book.store.connection() as db:
        db.execute('UPDATE briefing_preference_requests SET spec=?,receipt=?', ('REQUEST-SECRET', 'REQUEST-RECEIPT-SECRET'))
        value = json.loads(db.execute('SELECT receipt FROM workspace_text_versions WHERE request_key=?', (saved['request_key'],)).fetchone()[0])
        value['future_private_field'] = 'RECEIPT-SECRET'
        db.execute('UPDATE workspace_text_versions SET receipt=? WHERE request_key=?', (json.dumps(value), saved['request_key']))
    data, manifest, files = unpack(book)
    assert data['briefing_preferences'] == [{'revision': 1, 'interests': ['中文阅读'], 'priorities': '关注项目进展', 'sources': ['task', 'files'], 'max_items': 2, 'updated_at': data['briefing_preferences'][0]['updated_at']}]
    row = data['workspace_text_versions'][0]
    assert set(row) == {'id', 'source_path', 'path', 'created_at', 'saved_at', 'save_mode', 'size', 'sha256', 'text_included', 'text'}
    assert row['text'] == '原文\n' and row['text_included'] is True
    assert row['sha256'] == hashlib.sha256('原文\n'.encode()).hexdigest()
    assert row['size'] == len('原文\n'.encode())
    assert manifest['counts']['workspace_text_versions'] == 1
    assert manifest['limits']['workspace_text_version_bytes'] == MAX_TEXT_BYTES
    joined = b'\n'.join(files.values())
    assert all(secret not in joined for secret in [b'PENDING-', b'REQUEST-SECRET', b'REQUEST-RECEIPT-SECRET', b'RECEIPT-SECRET', b'INTERNAL-SPEC-SECRET', b'document-save-key-001'])
    # No filesystem read of the former body: the current file has newer bytes.
    assert (editor.root('daily') / 'report.md').read_text() == '新文\n'


def test_two_identities_and_two_tenant_stores_never_share_content(tmp_path):
    first, prefs, editor = setup(tmp_path / 'tenant-one')
    other = first.store.save_identity('Work')['id']
    preference(prefs, interests=['FIRST-DAILY'])
    preference(prefs, other, interests=['FIRST-WORK'])
    edit(editor, before='FIRST-DAILY-BODY')
    edit(editor, other, before='FIRST-WORK-BODY')
    second, prefs_two, editor_two = setup(tmp_path / 'tenant-two')
    preference(prefs_two, interests=['SECOND-DAILY'])
    edit(editor_two, before='SECOND-DAILY-BODY')
    a, _, _ = unpack(first)
    b, _, _ = unpack(first, other)
    c, _, _ = unpack(second)
    assert [x['briefing_preferences'][0]['interests'] for x in [a, b, c]] == [['FIRST-DAILY'], ['FIRST-WORK'], ['SECOND-DAILY']]
    assert [x['workspace_text_versions'][0]['text'] for x in [a, b, c]] == ['FIRST-DAILY-BODY', 'FIRST-WORK-BODY', 'SECOND-DAILY-BODY']


def test_import_copy_recovery_exports_original_even_if_file_later_removed(tmp_path):
    book, _, editor = setup(tmp_path)
    saved = edit(editor, path='imports/import-key-0001/source.txt')
    (editor.root('daily') / saved['path']).unlink()
    data, _, _ = unpack(book)
    row = data['workspace_text_versions'][0]
    assert row['source_path'] == 'imports/import-key-0001/source.txt'
    assert row['path'] == saved['path'] and row['save_mode'] == 'copy' and row['text'] == '原文\n'


@pytest.mark.parametrize('path', ['../outside.txt', '/private/report.md', 'skills/tool/SKILL.md', 'documents/.env.txt', 'credentials/secret.txt', 'USER.md', 'settings.json'])
def test_recovery_rejects_unsafe_or_non_document_paths_without_dereferencing(tmp_path, path):
    book, _, _ = setup(tmp_path)
    fixture_version(book, path=path, old=b'UNSAFE-BODY')
    data, manifest, files = unpack(book)
    assert data['workspace_text_versions'] == []
    assert any(row['section'] == 'workspace_text_versions' for row in manifest['omitted'])
    assert b'UNSAFE-BODY' not in b''.join(files.values())


@pytest.mark.parametrize('updates', [{'identity_id': 'other'}, {'path': 'other.md'}, {'source_path': 'other.md'}, {'recovery_id': 'wrong'}, {'save_mode': 'copy'}, {'sha256': '0' * 64}, {'size': 123}])
def test_recovery_receipt_must_match_actual_identity_path_and_bytes(tmp_path, updates):
    book, _, _ = setup(tmp_path)
    fixture_version(book, receipt_updates=updates)
    data, manifest, _ = unpack(book)
    assert data['workspace_text_versions'] == []
    assert any('回执' in row['reason'] for row in manifest['omitted'])


@pytest.mark.parametrize('raw', [b'x' * (MAX_TEXT_BYTES + 1), b'\xff', b'bad\x00content', b'-----BEGIN PRIVATE KEY-----\nsecret'])
def test_recovery_invalid_or_oversized_body_omits_whole_version(tmp_path, raw):
    book, _, _ = setup(tmp_path)
    fixture_version(book, old=raw)
    data, manifest, _ = unpack(book)
    assert data['workspace_text_versions'] == []
    assert any(row['section'] == 'workspace_text_versions' for row in manifest['omitted'])


def test_recovery_budgets_are_declared_no_partial_text_or_unbounded_history(tmp_path, monkeypatch):
    book, _, _ = setup(tmp_path)
    monkeypatch.setattr('wearing.identity_export.MAX_TEXT_VERSIONS', 3)
    monkeypatch.setattr('wearing.identity_export.MAX_RECOVERY_BYTES', 5)
    for index in range(4):
        fixture_version(book, key=f'document-save-{index:04}', old='中文'.encode())
    data, manifest, _ = unpack(book)
    versions = data['workspace_text_versions']
    assert len(versions) == 3 and all(row['text'] is None and not row['text_included'] for row in versions)
    assert all(row['size'] == 6 and row['sha256'] == hashlib.sha256('中文'.encode()).hexdigest() for row in versions)
    reasons = [row['reason'] for row in manifest['omitted']]
    assert any('最近 3' in reason for reason in reasons) and any('3 份恢复正文' in reason for reason in reasons)
    assert manifest['limits']['workspace_recovery_text_bytes'] == 5
    assert manifest['limits']['workspace_text_versions_rows'] == 3


@pytest.mark.parametrize('value', [json.dumps({'extra_secret': 'NEVER-EXPORT'}), json.dumps({'priorities': 'x' * 9000}), 'not-json'])
def test_preferences_are_validated_with_bounded_closed_fields(tmp_path, value):
    book, prefs, _ = setup(tmp_path)
    preference(prefs)
    with book.store.connection() as db:
        db.execute('UPDATE briefing_preferences SET value=?', (value,))
    data, manifest, files = unpack(book)
    assert data['briefing_preferences'] == []
    assert any(row['section'] == 'briefing_preferences' for row in manifest['omitted'])
    assert b'NEVER-EXPORT' not in b''.join(files.values())


def test_new_records_still_obey_global_record_limit(tmp_path, monkeypatch):
    book, prefs, _ = setup(tmp_path)
    preference(prefs)
    monkeypatch.setattr('wearing.identity_export.MAX_ROWS', 0)
    with pytest.raises(ExportError) as error:
        book.create('daily', 'export-documents-001')
    assert error.value.status == 413 and not list(book.root.glob('*.zip'))


def test_version_body_and_receipt_remain_in_one_database_snapshot(tmp_path, monkeypatch):
    book, prefs, _ = setup(tmp_path)
    preference(prefs)
    fixture_version(book, old=b'original recovery')
    with book.store.connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
    original = book.store.connection
    changed = False
    @contextmanager
    def connection():
        nonlocal changed
        with original() as db:
            def trace(sql):
                nonlocal changed
                if not changed and 'SELECT old_bytes,new_bytes,receipt' in sql:
                    changed = True
                    with original() as writer:
                        writer.execute('UPDATE workspace_text_versions SET old_bytes=?,receipt=NULL', (b'changed after snapshot',))
                        writer.execute('DELETE FROM briefing_preferences')
            db.set_trace_callback(trace)
            yield db
    monkeypatch.setattr(book.store, 'connection', connection)
    data, _, _ = unpack(book)
    assert changed and data['briefing_preferences'][0]['interests'] == ['中文阅读']
    assert data['workspace_text_versions'][0]['text'] == 'original recovery'


def test_owner_bound_receipts_idempotency_restart_and_local_legacy(tmp_path):
    book, _, _ = setup(tmp_path)
    local = book.create('daily', 'export-documents-001')
    metadata_path = book.root / (local['id'] + '.json')
    value = json.loads(metadata_path.read_text())
    value.pop('owner_scope')  # Existing local receipts remain retrievable locally only.
    metadata_path.write_text(json.dumps(value))
    a, b = 'a' * 64, 'b' * 64
    one = book.create('daily', 'export-documents-001', owner_scope=a)
    two = book.create('daily', 'export-documents-001', owner_scope=b)
    assert len({local['id'], one['id'], two['id']}) == 3
    restarted = IdentityExports(book.store)
    assert restarted.create('daily', 'export-documents-001', owner_scope=a) == one
    assert restarted.list('daily', owner_scope=a) == [one]
    assert restarted.list('daily', owner_scope=b) == [two]
    assert restarted.list('daily') == [local]
    for target, owner in [(one, b), (one, 'local'), (local, a)]:
        with pytest.raises(ExportError) as error:
            restarted.download('daily', target['id'], owner_scope=owner)
        assert error.value.status == 404
    assert 'owner_scope' not in one and 'request_hash' not in one
    with pytest.raises(ExportError) as error:
        book.list('daily', owner_scope='public-client-value')
    assert error.value.status == 401


def test_cloud_export_owner_only_from_trusted_asgi_and_missing_scope_fails_closed(tmp_path):
    book, _, _ = setup(tmp_path)
    app = FastAPI()
    trusted = {'cloud': True, 'owner': 'a' * 64}
    @app.middleware('http')
    async def scope(request: Request, next):
        request.state.identity_id = 'daily'
        request.scope['pajio.cloud_worker'] = trusted['cloud']
        if trusted['owner'] is not None:
            request.scope['pajio.storage_scope'] = trusted['owner']
        return await next(request)
    install_identity_export_routes(app, book)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/data-exports', json={'request_key': 'export-documents-001'})
            assert response.status_code == 201
            identifier = response.json()['id']
            trusted['owner'] = 'b' * 64
            forged = {'X-Pajio-Storage-Scope': 'a' * 64}
            assert (await client.get('/api/data-exports', headers=forged)).json() == {'exports': []}
            for suffix in ['', '/file']:
                assert (await client.get('/api/data-exports/' + identifier + suffix, headers=forged)).status_code == 404
            assert (await client.post('/api/data-exports', json={'request_key': 'export-documents-002', 'owner_scope': 'a' * 64})).status_code == 422
            trusted['owner'] = None
            for path in ['/api/data-exports', '/api/data-exports/' + identifier, '/api/data-exports/' + identifier + '/file']:
                assert (await client.get(path, headers=forged)).status_code == 401
            assert (await client.post('/api/data-exports', headers=forged, json={'request_key': 'export-documents-002'})).status_code == 401
            trusted.update(cloud=False, owner='a' * 64)
            assert (await client.get('/api/data-exports', headers=forged)).json() == {'exports': []}
    asyncio.run(check())
