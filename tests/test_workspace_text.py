import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import threading
from types import SimpleNamespace

import httpx
import pytest

from wearing.app import create_app
from wearing.config import Settings
from wearing.store import Store
from wearing.workspace_text import WorkspaceText, TextEditError, TextSave, MAX_TEXT_BYTES, install_workspace_text_routes


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *_: pytest.fail('external calls forbidden'))


def setup(tmp_path):
    store = Store(tmp_path/'state.sqlite3')
    roots = {}
    def runtime(identity):
        root = roots.setdefault(identity, tmp_path/identity/'workspace')
        root.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(workspace=root)
    return store, WorkspaceText(store, runtime), runtime('daily').workspace


def request(editor, path='note.md', key='text-save-request-001', text='Updated synthetic text'):
    current = editor.read('daily', path)
    return TextSave(path=path, text=text, request_key=key, base_revision=current['revision'], base_sha256=current['sha256'])


def test_atomic_save_restart_receipt_and_recovery(tmp_path):
    store, editor, root = setup(tmp_path)
    (root/'note.md').write_text('原文\n', encoding='utf-8')
    draft = request(editor)
    receipt = editor.save('daily', draft)
    assert (root/'note.md').read_text() == draft.text
    assert receipt['sha256'] == hashlib.sha256(draft.text.encode()).hexdigest()
    assert receipt['save_mode'] == 'replace'
    assert editor.recovery('daily', 'note.md', receipt['recovery_id'])['text'] == '原文\n'
    before = (root/'note.md').stat().st_mtime_ns
    reopened = WorkspaceText(Store(store.path), editor.runtime_for)
    assert reopened.save('daily', draft) == receipt
    assert (root/'note.md').stat().st_mtime_ns == before
    assert editor.read('daily', 'note.md')['history'][0]['id'] == draft.request_key
    assert list(root.iterdir()) == [root/'note.md']  # Recovery is private, outside browsing.
    with pytest.raises(TextEditError): editor.save('daily', draft.model_copy(update={'text': 'different'}))


def test_import_original_immutable_and_copy_has_its_own_edit_history(tmp_path):
    from wearing.workspace_upload import WorkspaceImports
    store, editor, root = setup(tmp_path)
    path = 'imports/original-import-001/材料.txt'
    imports = WorkspaceImports(store)
    imported = imports.upload('daily', root, 'original-import-001', '材料.txt', b'source-original')
    original = root/path
    before = original.stat()
    receipt = editor.save('daily', request(editor, path))
    assert receipt['path'] == 'documents/text-save-request-001/材料.txt'
    assert receipt['save_mode'] == 'copy' and original.read_text() == 'source-original'
    assert original.stat().st_ino == before.st_ino and original.stat().st_mtime_ns == before.st_mtime_ns
    assert editor.read('daily', receipt['path'])['save_mode'] == 'replace'
    assert editor.recovery('daily', receipt['path'], receipt['recovery_id'])['text'] == 'source-original'
    assert imports.upload('daily', root, 'original-import-001', '材料.txt', b'source-original')['sha256'] == imported['sha256']


def test_conflict_does_not_overwrite_and_concurrent_edits_have_one_winner(tmp_path):
    _, editor, root = setup(tmp_path)
    (root/'note.md').write_text('base')
    one = request(editor); two = request(editor, key='text-save-request-002', text='other')
    def save(draft):
        try: return editor.save('daily', draft)
        except TextEditError as error: return error.status
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(save, [one, two]))
    assert sum(isinstance(result, dict) for result in results) == 1 and 409 in results
    stale = request(editor, key='text-save-request-003')
    (root/'note.md').write_text('updated elsewhere')
    with pytest.raises(TextEditError): editor.save('daily', stale)
    assert (root/'note.md').read_text() == 'updated elsewhere'


def test_unknown_receipt_after_publication_recovers_without_rewriting(tmp_path):
    store, editor, root = setup(tmp_path)
    (root/'note.md').write_text('prior')
    draft = request(editor)
    with store.connection() as db:
        db.execute("CREATE TRIGGER fail_receipt BEFORE UPDATE OF receipt ON workspace_text_versions BEGIN SELECT RAISE(ABORT,'synthetic receipt failure'); END")
    with pytest.raises(sqlite3.IntegrityError): editor.save('daily', draft)
    assert (root/'note.md').read_text() == draft.text
    with store.connection() as db:
        assert bytes(db.execute('SELECT old_bytes FROM workspace_text_versions').fetchone()[0]) == b'prior'
        db.execute('DROP TRIGGER fail_receipt')
    before = (root/'note.md').stat().st_ino
    receipt = WorkspaceText(Store(store.path), editor.runtime_for).save('daily', draft)
    assert receipt['request_key'] == draft.request_key and (root/'note.md').stat().st_ino == before


def test_failed_recovery_commit_cannot_write_the_file(tmp_path):
    store, editor, root = setup(tmp_path)
    (root/'note.md').write_text('must remain')
    draft = request(editor)
    with store.connection() as db:
        db.execute("CREATE TRIGGER fail_prepare BEFORE INSERT ON workspace_text_versions BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END")
    with pytest.raises(sqlite3.IntegrityError): editor.save('daily', draft)
    assert (root/'note.md').read_text() == 'must remain'


def test_external_change_during_preparation_is_not_overwritten(tmp_path, monkeypatch):
    _, editor, root = setup(tmp_path)
    (root/'note.md').write_text('base')
    draft = request(editor)
    publish = editor._publish
    def changed(*args):
        (root/'note.md').write_text('external update')
        return publish(*args)
    monkeypatch.setattr(editor, '_publish', changed)
    with pytest.raises(TextEditError): editor.save('daily', draft)
    assert (root/'note.md').read_text() == 'external update'
    assert not list(root.glob('.edit-*'))


def test_task_guard_blocks_saves_and_same_identity_only(tmp_path):
    store, editor, root = setup(tmp_path)
    (root/'note.md').write_text('base')
    draft = request(editor)
    task = store.create('Synthetic', 'Do not execute')
    store.update(task['id'], status='running')
    assert not editor.read('daily', 'note.md')['editable']
    with pytest.raises(TextEditError) as caught: editor.save('daily', draft)
    assert caught.value.status == 423 and (root/'note.md').read_text() == 'base'
    store.update(task['id'], status='stopped')
    assert editor.save('daily', draft)['path'] == 'note.md'


def test_task_start_waits_until_atomic_publication_releases_database_lock(tmp_path, monkeypatch):
    store, editor, root = setup(tmp_path)
    (root/'note.md').write_text('base')
    draft = request(editor)
    task = store.create('Synthetic', 'No external engine')
    at_publish, allow_publish, task_attempted = threading.Event(), threading.Event(), threading.Event()
    publish = editor._publish
    def guarded(*args):
        at_publish.set()
        assert allow_publish.wait(5)
        return publish(*args)
    monkeypatch.setattr(editor, '_publish', guarded)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(editor.save, 'daily', draft)
        assert at_publish.wait(5)
        def start():
            task_attempted.set()
            return store.reserve_start(task['id'], {}, 'synthetic-start', {'running', 'starting'})
        starting = pool.submit(start)
        assert task_attempted.wait(5) and not starting.done()
        allow_publish.set()
        assert saving.result()['sha256'] == hashlib.sha256(draft.text.encode()).hexdigest()
        assert starting.result() is True
    assert (root/'note.md').read_text() == draft.text and store.get(task['id'])['status'] == 'starting'


def test_identity_scoped_versions_and_request_keys(tmp_path):
    store, editor, root = setup(tmp_path)
    (root/'note.md').write_text('one')
    receipt = editor.save('daily', request(editor))
    other = store.save_identity('Other synthetic')['id']
    other_root = editor.runtime_for(other).workspace; (other_root/'note.md').write_text('other')
    with pytest.raises(TextEditError): editor.recovery(other, 'note.md', receipt['recovery_id'])
    assert editor.read(other, 'note.md')['history'] == []
    current = editor.read(other, 'note.md')
    other_save = TextSave(path='note.md', text='changed other', request_key=receipt['request_key'], base_revision=current['revision'], base_sha256=current['sha256'])
    assert editor.save(other, other_save)['identity_id'] == other
    assert (root/'note.md').read_text() == 'Updated synthetic text'


@pytest.mark.parametrize('path', ['../escape.md', '/absolute.txt', 'a//b.md', 'a\\b.md', '.hidden.md', 'skills/demo/notes.md', 'config/notes.txt', 'credentials/token.txt', 'SOUL.md', 'SKILL.md', 'MEMORY.md', 'settings.json', 'code.py', 'report.html', 'secret.pem'])
def test_protected_paths_not_read_or_changed(tmp_path, path):
    _, editor, _ = setup(tmp_path)
    with pytest.raises(TextEditError): editor.read('daily', path)


@pytest.mark.parametrize('kind', ['file', 'parent', 'root', 'hardlink', 'fifo'])
def test_symlinks_hardlinks_and_special_files_rejected(tmp_path, kind):
    _, editor, root = setup(tmp_path)
    outside = tmp_path/'outside'; outside.mkdir(); (outside/'note.md').write_text('private')
    path = 'note.md'
    if kind == 'file': (root/path).symlink_to(outside/path)
    if kind == 'parent': (root/'linked').symlink_to(outside, target_is_directory=True); path = 'linked/note.md'
    if kind == 'root': root.rmdir(); root.symlink_to(outside, target_is_directory=True)
    if kind == 'hardlink': os.link(outside/path, root/path)
    if kind == 'fifo': os.mkfifo(root/path)
    with pytest.raises(TextEditError): editor.read('daily', path)
    assert (outside/'note.md').read_text() == 'private'


@pytest.mark.parametrize('raw', [b'\xff', b'binary\x00data', b'a'*(MAX_TEXT_BYTES+1), b'-----BEGIN RSA PRIVATE KEY-----\nprivate'])
def test_size_encoding_and_private_key_guards(tmp_path, raw):
    _, editor, root = setup(tmp_path); (root/'note.md').write_bytes(raw)
    with pytest.raises(TextEditError): editor.read('daily', 'note.md')


def test_empty_unicode_content_and_newline_preservation(tmp_path):
    _, editor, root = setup(tmp_path); (root/'note.md').write_bytes(b'old\r\n')
    saved = editor.save('daily', request(editor, text='  首行\r\n次行\n'))
    assert (root/'note.md').read_bytes() == '  首行\r\n次行\n'.encode()
    assert saved['size'] == len('  首行\r\n次行\n'.encode())
    editor.save('daily', request(editor, key='text-save-empty-002', text=''))
    assert (root/'note.md').read_bytes() == b''


async def test_real_app_routes_auth_csrf_and_extra_owner_rejected(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    editor = install_workspace_text_routes(app, app.state.store, lambda identity: app.state.runtime)
    root = app.state.runtime.workspace; root.mkdir(parents=True); (root/'note.md').write_text('test data')
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as http:
            response = await http.get('/api/workspace/text', params={'path': 'note.md'})
            assert response.status_code == 200 and response.json()['identity_id'] == 'daily'
            body = request(editor).model_dump()
            assert (await http.post('/api/workspace/text', json=body)).status_code == 403
            token = (await http.get('/api/bootstrap')).json()['token']; headers = {'X-Wearing-Token': token}
            assert (await http.post('/api/workspace/text', json={**body, 'identity_id': 'foreign'}, headers=headers)).status_code == 422
            assert (await http.post('/api/workspace/text', json=body, headers={**headers, 'Origin': 'null'})).status_code == 403
            assert (await http.post('/api/workspace/text', json=body, headers=headers)).status_code == 200
            assert not app.state.store.list()
    finally: await app.state.service.hermes.close()
