import asyncio
from contextlib import contextmanager
import hashlib
import io
import json
import os
import zipfile

from fastapi import FastAPI, Request
import httpx
import pytest

from wearing.artifacts import ArtifactBook
from wearing.capture import CaptureBook
from wearing.goals import GoalBook
from wearing.identity_export import IdentityExports, ExportError, MAX_EXPORT_BYTES
from wearing.identity_export_api import install_identity_export_routes
from wearing.life import LifeBook
from wearing.schedules import ScheduleBook
from wearing.store import Store, now


@pytest.fixture
def book(tmp_path):
    store = Store(tmp_path / 'wearing.sqlite3')
    life = LifeBook(store)
    GoalBook(store); ScheduleBook(store); CaptureBook(life); ArtifactBook(store)
    return IdentityExports(store)


def unzip(book, identity, receipt):
    raw, _ = book.download(identity, receipt['id'])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def asset(book, identity='daily', number='a', raw=b'media fixture', suffix='.wav'):
    aid = 'asset_' + number * 32
    with book.store.connection() as db:
        db.execute('INSERT INTO life_assets VALUES(?,?,?,?,?,?,?,?,?,?)', (aid, identity, 'test.wav', 'audio/wav', len(raw), hashlib.sha256(raw).hexdigest(), suffix, 'key-' + aid, 'hash', now()))
    (book.store.path.parent / 'media' / (aid + suffix)).write_bytes(raw)
    return aid


def test_identity_whitelist_files_receipts_and_restart(book):
    other = book.store.save_identity('Work')['id']
    task = book.store.create_message('my conversation')
    book.store.update(task['id'], output='my result', payload={'api_key': 'PAYLOAD-SECRET'})
    book.store.create_message('OTHER-PRIVATE-DATA', other)
    with book.store.connection() as db:
        db.execute('INSERT INTO settings VALUES(?,?)', ('provider-key', 'SETTINGS-SECRET'))
    root = book.store.path.parent
    memory = root / 'hermes' / 'memories'; memory.mkdir(parents=True)
    (memory / 'USER.md').write_text('User memory fixture')
    (memory / 'MEMORY.md').write_text('Memory fixture')
    (root / 'hermes' / 'config.yaml').write_text('key: CONFIG-SECRET')
    workspace = root / 'workspace'; workspace.mkdir()
    (workspace / 'report.txt').write_text('workspace body is intentionally separate')
    (workspace / '.env').write_text('WORKSPACE-SECRET')
    (workspace / 'api.key').write_text('PRIVATE-KEY')
    (workspace / 'bad-link.txt').symlink_to(root / 'hermes' / 'config.yaml')
    own = asset(book)
    asset(book, other, 'b', b'OTHER-MEDIA')
    receipt = book.create('daily', 'test_request_key_001')
    assert book.create('daily', 'test_request_key_001') == receipt
    assert IdentityExports(book.store).metadata('daily', receipt['id']) == receipt
    files = unzip(book, 'daily', receipt)
    joined = b'\n'.join(files.values())
    assert all(secret not in joined for secret in (b'OTHER-PRIVATE-DATA', b'OTHER-MEDIA', b'PAYLOAD-SECRET', b'SETTINGS-SECRET', b'CONFIG-SECRET', b'WORKSPACE-SECRET'))
    data = json.loads(files['records.json'])
    assert data['tasks'][0]['output'] == 'my result'
    assert files['memory/USER.md'] == b'User memory fixture'
    assert files['media/' + own + '.wav'] == b'media fixture'
    manifest = json.loads(files['manifest.json'])
    assert [row['path'] for row in manifest['workspace']] == ['report.txt']
    assert manifest['omitted'][0]['reason'] == '符号链接未导出'
    assert len(files) >= 5
    assert os.stat(book.root / (receipt['id'] + '.zip')).st_mode & 0o777 == 0o600
    with pytest.raises(ExportError) as err: book.download(other, receipt['id'])
    assert err.value.status == 404


def test_links_changes_size_and_expiry_are_explicit(book, monkeypatch):
    root = book.store.path.parent
    memory = root / 'hermes' / 'memories'; memory.mkdir(parents=True)
    secret = root / 'credential.txt'; secret.write_text('SECRET')
    (memory / 'USER.md').symlink_to(secret)
    aid = asset(book)
    (root / 'media' / (aid + '.wav')).write_bytes(b'changed contents')
    receipt = book.create('daily', 'test_request_key_001')
    files = unzip(book, 'daily', receipt)
    assert 'memory/USER.md' not in files and 'media/' + aid + '.wav' not in files
    assert any(row['section'] == 'media' for row in receipt['omitted'])
    assert b'SECRET' not in b''.join(files.values())
    monkeypatch.setattr(book, 'clock', lambda: receipt['expires_at'] + 1)
    with pytest.raises(ExportError) as error: book.download('daily', receipt['id'])
    assert error.value.status == 410
    book.purge_expired()
    assert not (book.root / (receipt['id'] + '.zip')).exists()
    monkeypatch.setattr('wearing.identity_export.MAX_DATA_BYTES', 50)
    book.store.create_message('large message' * 30)
    with pytest.raises(ExportError) as error: book.create('daily', 'test_request_key_002')
    assert error.value.status == 413
    assert not list(book.root.glob('*.zip'))


def test_hard_links_and_oversized_originals_never_read(book):
    root = book.store.path.parent
    aid = asset(book)
    source = root / 'media' / (aid + '.wav')
    os.link(source, root / 'alias')
    receipt = book.create('daily', 'test_request_key_001')
    assert not any(name.startswith('media/') for name in unzip(book, 'daily', receipt))
    with book.store.connection() as db:
        db.execute('UPDATE life_assets SET size=? WHERE id=?', (MAX_EXPORT_BYTES + 1, aid))
    receipt = book.create('daily', 'test_request_key_002')
    assert any(row['section'] == 'media' for row in receipt['omitted'])


def test_record_snapshot_stays_consistent_during_concurrent_write(book, monkeypatch):
    task = book.store.create_message('old message')
    with book.store.connection() as db: db.execute('PRAGMA journal_mode=WAL')
    original = book.store.connection
    changed = False
    @contextmanager
    def connection():
        nonlocal changed
        with original() as db:
            def trace(sql):
                nonlocal changed
                if not changed and 'SELECT m.id,m.content' in sql:
                    changed = True
                    with original() as writer:
                        writer.execute('UPDATE tasks SET prompt=? WHERE id=?', ('new message', task['id']))
                        writer.execute('UPDATE messages SET content=? WHERE task_id=?', ('new message', task['id']))
            db.set_trace_callback(trace)
            yield db
    monkeypatch.setattr(book.store, 'connection', connection)
    data, _, _ = book._snapshot('daily')
    assert changed
    assert data['tasks'][0]['prompt'] == data['conversation'][0]['content'] == 'old message'
    assert book.store.get(task['id'])['prompt'] == 'new message'


def test_export_routes_enforce_identity_and_safe_download_headers(book):
    app = FastAPI()
    @app.middleware('http')
    async def scope(request: Request, next):
        request.state.identity_id = request.headers.get('X-Wearing-Identity', 'daily')
        return await next(request)
    install_identity_export_routes(app, book)
    other = book.store.save_identity('Other')['id']
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/data-exports', json={'request_key': 'test_request_key_001'})
            assert response.status_code == 201
            receipt = response.json()
            denied = await client.get('/api/data-exports/' + receipt['id'] + '/file', headers={'X-Wearing-Identity': other})
            assert denied.status_code == 404
            file = await client.get('/api/data-exports/' + receipt['id'] + '/file')
            assert file.headers['cache-control'] == 'no-store'
            assert file.headers['content-type'] == 'application/zip'
            assert hashlib.sha256(file.content).hexdigest() == receipt['sha256']
            bad = await client.post('/api/data-exports', json={'request_key': '../bad'})
            assert bad.status_code == 422
    asyncio.run(check())


def test_nondefault_memory_workspace_are_isolated_and_result_bodies_verified(book):
    root = book.store.path.parent
    other = book.store.save_identity('Project')['id']
    home = root / 'identities' / other / 'hermes' / 'memories'; home.mkdir(parents=True)
    (home / 'USER.md').write_text('other own memory')
    daily = root / 'hermes' / 'memories'; daily.mkdir(parents=True)
    (daily / 'USER.md').write_text('DAILY-MEMORY')
    own_workspace = root / 'identities' / other / 'workspace'; own_workspace.mkdir()
    (own_workspace / 'project.txt').write_text('project')
    task = book.store.create_message('project chat', other)
    raw = b'<html>project result</html>'
    aid = 'art_' + 'c' * 32
    with book.store.connection() as db:
        db.execute('INSERT INTO artifacts(id,identity_id,task_id,run_id,request_key,fingerprint,metadata,html,sha256,previous_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (aid, other, task['id'], 'run', 'request', 'fp', json.dumps({'title': 'project result'}), raw, hashlib.sha256(raw).hexdigest(), None, now()))
    receipt = book.create(other, 'test_request_key_001')
    files = unzip(book, other, receipt)
    assert files['memory/USER.md'] == b'other own memory'
    assert files['results/' + aid + '.html'] == raw
    assert b'DAILY-MEMORY' not in b''.join(files.values())
    assert json.loads(files['manifest.json'])['workspace'][0]['path'] == 'project.txt'


def test_package_is_bounded_and_same_key_still_works_at_receipt_limit(book):
    # Compressible fixture still must respect the uncompressed memory/read budget.
    first = asset(book, number='a', raw=b'x' * (8 * 1024 * 1024))
    second = asset(book, number='b', raw=b'y' * (8 * 1024 * 1024))
    receipt = book.create('daily', 'test_request_key_001')
    files = unzip(book, 'daily', receipt)
    assert 'media/' + first + '.wav' in files
    assert 'media/' + second + '.wav' not in files
    assert any('上限' in row['reason'] for row in receipt['omitted'])
    assert receipt['size'] <= MAX_EXPORT_BYTES
    book.create('daily', 'test_request_key_002'); book.create('daily', 'test_request_key_003')
    assert book.create('daily', 'test_request_key_001') == receipt
    with pytest.raises(ExportError) as error: book.create('daily', 'test_request_key_004')
    assert error.value.status == 429
