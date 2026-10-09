"""QA-only adapters exercise production routes without sockets or subprocesses."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import asyncio
import socket
import re
import httpx
import pytest

DIRECTORY = Path(__file__).resolve().parents[1] / 'docs/evidence/pajio-core-20261007'
sys.path.insert(0, str(DIRECTORY))
spec = importlib.util.spec_from_file_location('pajio_qa_server', DIRECTORY / 'qa-server.py')
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
from qa_support import APP_ID, SECRET, BOT_TOKEN, PROJECT_ID, PUSH_TOKEN

async def test_diagnostics_and_search_use_real_scoped_routes_without_external_calls(rig):
    app, client, root, manifest = rig
    diagnostics = await client.get('/api/diagnostics')
    assert diagnostics.status_code == 200
    assert diagnostics.json()['service']['deployment'] == 'synthetic'
    assert diagnostics.json()['engine_probe']['state'] == 'not_configured'
    for secret in [str(root), SECRET, BOT_TOKEN, PUSH_TOKEN]: assert secret not in diagnostics.text
    search = await client.get('/api/search', params={'q':manifest['search']['query'], 'kind':'all'})
    assert search.status_code == 200 and len(search.json()['items']) == 2
    assert 'QA_FOREIGN_SEARCH_CANARY' not in search.text and manifest['search']['foreign_record_id'] not in search.text
    assert {item['kind'] for item in search.json()['items']} == {'record','message'}
    message = await client.get('/api/search/messages/' + str(manifest['search']['message_id']))
    assert message.status_code == 200 and message.json()['task_id'] == manifest['search']['task_id']
    assert (await client.get('/api/search?q=搜索验收', headers={'X-Wearing-Identity':'daily'})).status_code == 404
    foreign = app.state.search.page('daily', '搜索验收')
    assert len(foreign['items']) == 1 and foreign['items'][0]['id'] == manifest['search']['foreign_record_id']

@pytest.fixture
async def rig(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('QA must not create an external socket or process')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    root = tmp_path / 'fixture'; root.mkdir()
    app, manifest = qa.build_app(root)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        token = (await client.get('/api/bootstrap')).json()['token']
        client.headers.update({'X-Wearing-Token': token, 'X-Wearing-Identity': 'qa'})
        yield app, client, root, manifest
    await app.state.qa_support.close()

async def test_real_skills_install_toggle_and_stale_revision(rig):
    _, client, root, _ = rig
    state = (await client.get('/api/skills')).json()
    assert state['installed'][0]['id'] == 'qa-notes'
    catalog = state['catalog'][0]
    assert catalog['installed'] is False
    r = await client.post('/api/skills/install', json={'id': catalog['id'], 'revision': catalog['revision']})
    assert r.status_code == 200
    installed = root / 'qa-runtime/skills/qa-summary/SKILL.md'
    assert installed.is_file() and '合成技能' in installed.read_text()
    state = r.json()
    r = await client.patch('/api/skills/enabled', json={'id': 'qa-summary', 'enabled': False, 'revision': state['revision']})
    assert r.status_code == 200 and not next(x for x in r.json()['installed'] if x['id'] == 'qa-summary')['enabled']
    assert (await client.patch('/api/skills/enabled', json={'id': 'qa-summary', 'enabled': True, 'revision': state['revision']})).status_code == 409
    assert (await client.get('/api/skills/detail', params={'id': '../real', 'source': 'installed'})).status_code == 422


async def test_bookmarks_are_mounted_and_share_the_real_record_lifecycle(rig):
    _, client, _, _ = rig
    saved = await client.post('/api/life', json={'request_key': 'qa-bookmark-mount-check',
        'record': {'kind': 'note', 'title': 'QA 原生收藏', 'content': '合成备注',
                   'url': 'https://example.com/pajio-bookmark-mount'}})
    assert saved.status_code == 201, saved.text
    record = saved.json()
    page = await client.get('/api/bookmarks', params={'query': 'pajio-bookmark-mount'})
    assert page.status_code == 200 and page.json()['items'] == [record]
    removed = await client.patch('/api/life/' + record['id'], json={
        'revision': record['revision'], 'action': 'archive', 'request_key': 'qa-bookmark-archive-check'})
    assert removed.status_code == 200
    assert (await client.get('/api/bookmarks')).json()['items'] == []
    assert (await client.get('/api/bookmarks?archived=true')).json()['items'][0]['id'] == record['id']
    assert (await client.get('/api/bookmarks', headers={'X-Wearing-Identity': 'daily'})).status_code == 404


async def test_conversation_source_mount_never_adopts_unproven_old_fixture_tasks(rig):
    _, client, _, manifest = rig
    page = await client.get('/api/conversation-sources')
    assert page.status_code == 200, page.text
    assert page.json()['identity_id'] == 'qa'
    assert page.json()['items'] == []
    assert manifest['task'] not in page.text
    invalid = await client.post('/api/conversation-sources/exclude', json={
        'source_id': 'source_' + 'a' * 64, 'source_revision': 'b' * 64,
        'revision': 0, 'request_key': 'qa-source-forged-owner', 'owner_scope': 'local'})
    assert invalid.status_code == 422
    assert (await client.get('/api/conversation-sources', headers={'X-Wearing-Identity': 'daily'})).status_code == 404

async def test_memory_controls_revision_add_replace_remove_and_restart_persistence(rig):
    app, client, root, _ = rig
    snapshot = (await client.get('/api/memory')).json()
    rev = snapshot['targets']['user']['revision']
    r = await client.patch('/api/memory', json={'target': 'user', 'action': 'add', 'content': 'QA 新的合成偏好', 'revision': rev})
    assert r.status_code == 200 and r.json()['targets']['user']['entries'][-1] == 'QA 新的合成偏好'
    assert (await client.patch('/api/memory', json={'target': 'user', 'action': 'remove', 'index': 0, 'revision': rev})).status_code == 409
    value = r.json()['targets']['user']
    r = await client.patch('/api/memory', json={'target': 'user', 'action': 'replace', 'index': 1, 'content': 'QA 修改后的偏好', 'revision': value['revision']})
    assert r.status_code == 200
    value = r.json()['targets']['user']
    r = await client.patch('/api/memory', json={'target': 'user', 'action': 'remove', 'index': 1, 'revision': value['revision']})
    assert r.status_code == 200 and len(r.json()['targets']['user']['entries']) == 1
    from qa_support import FixtureMemoryStore
    assert FixtureMemoryStore(root).snapshot()['targets'] == r.json()['targets']

async def test_cloud_real_authorize_exchange_read_revoke_with_no_external_url(rig):
    app, client, root, _ = rig
    state = (await client.get('/api/cloud-apps/feishu')).json()
    assert state['state'] == 'configured'
    r = await client.post('/api/cloud-apps/feishu/authorize', json={'revision': state['revision']})
    assert r.status_code == 200, r.text
    state = r.json()
    assert state['state'] == 'connected' and state['authorization'] is None and state['authorization_simulated']
    assert state['account_name'].startswith('QA ')
    files = await client.get('/api/cloud-apps/feishu/files')
    assert files.status_code == 200 and files.json()['items'][0]['token'] == 'qa_document'
    doc = await client.get('/api/cloud-apps/feishu/document', params={'document': 'qa_document'})
    assert doc.status_code == 200 and '合成资料' in doc.json()['content']
    calendar = await client.get('/api/cloud-apps/feishu/calendars')
    assert calendar.status_code == 200 and calendar.json()['items'][0]['calendar_id'] == 'qa_calendar'
    r = await client.request('DELETE', '/api/cloud-apps/feishu', json={'revision': state['revision']})
    assert r.status_code == 200 and r.json()['state'] == 'not_configured'
    assert any(call['path'] == '/oauth/v1/revoke' for call in app.state.qa_support.mock.calls)
    assert (await client.get('/api/cloud-apps/feishu/files')).status_code == 409

async def test_qa_refuses_real_or_unrecognized_credentials(rig):
    app, client, root, _ = rig
    unexpected = 'NEVER_STORE_THIS_REAL_SECRET'
    r = await client.put('/api/cloud-apps/feishu', json={'app_id': APP_ID, 'secret': unexpected, 'features': ['documents']})
    assert r.status_code == 422
    r = await client.put('/api/messaging/telegram', json={'secret': '123456:' + unexpected, 'allowed_users': ['123456789']})
    assert r.status_code == 422
    assert unexpected.encode() not in (root / 'qa.sqlite3').read_bytes()
    assert unexpected not in (root / 'requests.jsonl').read_text()
    assert not app.state.qa_support.mock.calls

async def test_messaging_true_revision_enable_disable_disconnect_use_mock_transport(rig):
    app, client, _, _ = rig
    r = await client.put('/api/messaging/telegram', json={'secret': BOT_TOKEN, 'allowed_users': ['123456789']})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()['channels'] if x['provider'] == 'telegram')
    assert row['configured'] and not row['enabled'] and BOT_TOKEN not in r.text
    r = await client.patch('/api/messaging/telegram', json={'revision': row['revision'], 'enabled': True})
    assert r.status_code == 200
    row = next(x for x in (await client.get('/api/messaging')).json()['channels'] if x['provider'] == 'telegram')
    assert row['enabled'] and row['state'] == 'listening'
    r = await client.patch('/api/messaging/telegram', json={'revision': row['revision'], 'enabled': False})
    assert r.status_code == 200
    row = next(x for x in r.json()['channels'] if x['provider'] == 'telegram')
    r = await client.request('DELETE', '/api/messaging/telegram', json={'revision': row['revision']})
    assert r.status_code == 200
    assert not next(x for x in r.json()['channels'] if x['provider'] == 'telegram')['configured']
    assert app.state.qa_support.messaging.worker is None

async def test_feishu_messaging_verifies_with_mock_and_receiver_is_inert(rig):
    app, client, _, _ = rig
    r = await client.put('/api/messaging/feishu', json={'app_id': APP_ID, 'secret': SECRET, 'allowed_users': ['ou_QASYNTHETIC']})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()['channels'] if x['provider'] == 'feishu')
    assert row['configured'] and not row['enabled'] and SECRET not in r.text
    previous = row['revision']
    r = await client.patch('/api/messaging/feishu', json={'revision': previous, 'enabled': True})
    assert r.status_code == 200, r.text
    row = next(x for x in (await client.get('/api/messaging')).json()['channels'] if x['provider'] == 'feishu')
    assert row['enabled'] and row['state'] == 'listening'
    assert (await client.patch('/api/messaging/feishu', json={'revision': previous, 'enabled': False})).status_code == 409
    r = await client.patch('/api/messaging/feishu', json={'revision': row['revision'], 'enabled': False})
    assert r.status_code == 200
    row = next(x for x in r.json()['channels'] if x['provider'] == 'feishu')
    r = await client.request('DELETE', '/api/messaging/feishu', json={'revision': row['revision']})
    assert r.status_code == 200
    assert not next(x for x in r.json()['channels'] if x['provider'] == 'feishu')['configured']
    from qa_support import SyntheticReceiver
    assert isinstance(app.state.qa_support.messaging.feishu, SyntheticReceiver)
    assert app.state.qa_support.messaging.worker is None
    assert any(call['path'] == '/open-apis/bot/v3/info' for call in app.state.qa_support.mock.calls)

async def test_push_mock_real_registration_event_ticket_receipt_disable(rig):
    app, client, _, _ = rig
    installation = 'qa-installation-001'
    body = {'installation_id': installation, 'expo_push_token': PUSH_TOKEN, 'project_id': PROJECT_ID, 'platform': 'ios'}
    r = await client.post('/api/notifications/register', json=body)
    assert r.status_code == 200 and r.json()['enabled']
    assert (await client.post('/api/conversation', json={'content': 'QA synthetic notification'})).status_code == 201
    state = (await client.get('/api/notifications/status', params={'installation_id': installation})).json()
    assert state['provider_status'] == 'ticket'
    r = await client.post('/_qa/notifications/receipts')
    assert r.status_code == 200 and r.json()['actual_device_delivery'] is False
    state = (await client.get('/api/notifications/status', params={'installation_id': installation})).json()
    assert state['provider_status'] == 'provider_accepted'
    assert (await client.post('/api/notifications/disable-installation', json={'installation_id': installation})).json()['enabled'] is False
    assert any(call['host'] == 'exp.host' for call in app.state.qa_support.mock.calls)

async def test_every_new_route_keeps_fixture_identity_csrf_and_no_secret_audit(rig):
    _, client, root, _ = rig
    assert (await client.get('/api/skills', headers={'X-Wearing-Identity': 'daily'})).status_code == 404
    assert (await client.get('/api/memory', headers={'X-Wearing-Identity': 'daily'})).status_code == 404
    assert (await client.patch('/api/memory', json={'target': 'user'}, headers={'X-Wearing-Token': 'bad'})).status_code == 403
    assert (await client.post('/_qa/notifications/receipts', headers={'X-Wearing-Token': 'bad'})).status_code == 403
    assert SECRET not in (root / 'requests.jsonl').read_text()

async def test_real_confirmation_resume_keeps_old_action_unapproved_and_is_idempotent(rig):
    app, client, _, manifest = rig
    rows = (await client.get('/api/confirmations')).json()['items']
    row = next(x for x in rows if x['id'] == manifest['confirmation']['id'])
    assert re.fullmatch(r'decision_[a-f0-9]{32}', row['id'])
    assert row['state'] == 'needs_recheck' and row['can_resume']
    path = '/api/confirmations/' + row['id'] + '/resume'
    body = {'revision': row['revision'], 'request_key': 'qa-confirmation-request-001'}
    assert (await client.post(path, json={**body, 'revision': 1})).status_code == 409
    assert (await client.post(path, json=body, headers={'X-Wearing-Identity': 'daily'})).status_code == 404
    assert (await client.post(path, json=body, headers={'X-Wearing-Token': 'bad'})).status_code == 403
    result = await client.post(path, json=body)
    assert result.status_code == 200, result.text
    result = result.json()
    assert result['created'] is True and result['authorized'] is False
    assert not {'payload', 'idempotency_key'} & result['task'].keys()
    repeat = (await client.post(path, json=body)).json()
    assert repeat['created'] is False and repeat['authorized'] is False
    assert repeat['task']['id'] == result['task']['id'] != row['task_id']
    current = (await client.get('/api/confirmations')).json()['items'][0]
    assert current['state'] == 'recovering' and current['recovery_task_id'] == result['task']['id']
    with app.state.store.connection() as db:
        recovery = db.execute('SELECT permit_id,consumed_at FROM confirmation_recovery_tasks WHERE task_id=?', (result['task']['id'],)).fetchone()
    assert recovery['permit_id'] is None and recovery['consumed_at'] is None

async def test_qa_workspace_pages_and_usage_are_real_isolated_routes(rig):
    app, client, _, _ = rig
    page = await client.get('/api/workspace/page')
    assert page.status_code == 200 and page.json()['complete']
    file = page.json()['files'][0]
    metadata = await client.get('/api/workspace/metadata', params={'path': file['path']})
    assert metadata.status_code == 200 and metadata.json() == file
    filtered = await client.get('/api/workspace/page', params={'query': '偏好'})
    assert filtered.status_code == 200 and [f['path'] for f in filtered.json()['files']] == ['关于你/偏好.md']
    assert (await client.get('/api/workspace/page', headers={'X-Wearing-Identity': 'daily'})).status_code == 404
    usage = await client.get('/api/usage')
    assert usage.status_code == 200 and usage.json()['mode'] == 'not_enabled' and usage.json()['cost'] is None
    assert not app.state.qa_support.mock.calls

async def test_qa_data_export_creates_real_synthetic_archive_without_credentials(rig):
    app, client, _, _ = rig
    request = {'request_key': 'qa-export-request-001'}
    response = await client.post('/api/data-exports', json=request)
    assert response.status_code == 201, response.text
    receipt = response.json()
    duplicate = (await client.post('/api/data-exports', json=request)).json()
    assert duplicate['id'] == receipt['id']
    blob = await client.get('/api/data-exports/' + receipt['id'] + '/file')
    assert blob.status_code == 200 and blob.headers['content-type'] == 'application/zip'
    import io, zipfile
    with zipfile.ZipFile(io.BytesIO(blob.content)) as archive:
        contents = b'\n'.join(archive.read(name) for name in archive.namelist())
    assert SECRET.encode() not in contents and BOT_TOKEN.encode() not in contents
    assert (await client.get('/api/data-exports/' + receipt['id'] + '/file', headers={'X-Wearing-Identity': 'daily'})).status_code == 404
    assert not app.state.qa_support.mock.calls

async def test_resume_preserves_synthetic_state_and_cloud_disconnect():
    with tempfile.TemporaryDirectory(prefix='pajio-core-qa-', dir='/tmp') as directory:
        root = Path(directory).resolve()
        first, _ = qa.build_app(root)
        support = first.state.qa_support
        rev = support.memory.snapshot()['targets']['user']['revision']
        from wearing.memory_controls import mutate_memory
        assert mutate_memory(support.memory, {'target': 'user', 'action': 'add', 'content': 'QA 持久记录', 'revision': rev}, lambda _: False, '\n§\n')['success']
        await support.cloud.disconnect('qa', support.cloud.snapshot('qa')['revision'])
        await support.close()
        second, _ = qa.build_app(root, resume=True)
        assert 'QA 持久记录' in second.state.qa_support.memory.snapshot()['targets']['user']['entries']
        assert second.state.qa_support.cloud.snapshot('qa')['state'] == 'not_configured'
        await second.state.qa_support.close()

async def test_task_detail_returns_exact_queue_and_artifacts_and_cancels_without_dispatch(rig):
    app, client, _, manifest = rig
    from wearing.service import ACTIVE
    queued, _ = app.state.store.accept_message('QA 可撤回的合成排队消息', 'qa', 'qa-task-detail-cancel-001', ACTIVE)
    path = '/api/tasks/' + queued['id']
    detail = (await client.get(path)).json()
    assert detail['queued'] is True and detail['status'] == 'draft'
    assert detail['events'] and detail['artifacts'] == []
    assert (await client.post(path + '/cancel-message')).status_code == 200
    detail = (await client.get(path)).json()
    assert detail['status'] == 'stopped' and detail['queue_state'] == 'cancelled' and not detail['queued']
    assert any(event['kind'] == 'message_cancelled' for event in detail['events'])
    artifact = (await client.get('/api/artifacts/' + manifest['artifact'])).json()
    source = (await client.get('/api/tasks/' + artifact['task_id'])).json()
    assert any(item['id'] == manifest['artifact'] for item in source['artifacts'])
    assert source['activity_receipt']['task_id'] == source['id']
    assert re.fullmatch(r'[a-f0-9]{64}', source['activity_receipt']['version'])
    assert (await client.get(path, headers={'X-Wearing-Identity': 'daily'})).status_code == 404
    assert not app.state.qa_support.mock.calls

async def test_brief_automation_and_record_reminder_routes_keep_real_receipts_without_sending(rig):
    app, client, _, _ = rig
    from datetime import datetime, timedelta, timezone
    from wearing.life import LifeBook, LifeDraft
    preferences = (await client.get('/api/briefings/preferences')).json()['preferences']
    state = (await client.get('/api/briefing-automation')).json()
    body = {'revision': state['revision'], 'request_key': 'qa-daily-brief-settings-001',
            'enabled': True, 'local_time': '08:00', 'timezone': 'Asia/Shanghai',
            'grace_minutes': 120, 'preferences_revision': preferences['revision']}
    response = await client.post('/api/briefing-automation', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['enabled'] and response.json()['next_run']
    assert (await client.get('/api/briefing-automation')).json()['receipts'] == []
    assert (await client.post('/api/briefing-automation', json=body)).json() == response.json()
    life = LifeBook(app.state.store)
    source = life.create('qa', LifeDraft(kind='task', title='QA 有截止时间的事项',
        due_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()), 'qa-due-record-001')
    path = '/api/record-reminders/' + source['id']
    settings = (await client.get(path)).json()
    body = {'revision': settings['revision'], 'record_revision': source['revision'],
            'request_key': 'qa-record-reminder-settings-001', 'enabled': True, 'advance_minutes': 15}
    response = await client.post(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'scheduled' and response.json()['enabled']
    assert (await client.post(path, json=body)).json() == response.json()
    life.update('qa', source['id'], source['revision'], patch={'completed': True})
    assert (await client.get(path)).json()['enabled'] is False
    for url in ['/api/briefing-automation', path]:
        assert (await client.get(url, headers={'X-Wearing-Identity': 'daily'})).status_code == 404
        assert (await client.post(url, json=body, headers={'X-Wearing-Token': 'bad'})).status_code == 403
    assert not app.state.qa_support.mock.calls
