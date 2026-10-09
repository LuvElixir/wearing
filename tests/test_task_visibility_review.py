"""Synthetic full-ASGI reads agree on owner, identity, and legacy semantics."""
import io
import json
import zipfile
import httpx
import pytest
from wearing.app import create_app
from wearing.artifacts import ArtifactDraft
from wearing.cloud.worker import TenantBoundary
from wearing.config import Settings
from wearing.identity_export import IdentityExports, ExportError
from wearing.service import ACTIVE

A, B = 'a' * 64, 'b' * 64


def fixture(app, owner, label, identity='daily'):
    store, book = app.state.store, app.state.artifacts
    task = store.accept_message('synthetic-' + label, identity, 'request-' + label, ACTIVE, owner_scope=owner)[0]
    store.update(task['id'], status='running', run_id='run-' + label)
    workspace = book.workspace(identity); workspace.mkdir(parents=True, exist_ok=True)
    (workspace / (label + '.html')).write_text('<html>synthetic-private-' + label + '</html>')
    result = book.publish(identity, ArtifactDraft(path=label + '.html', title='result ' + label, summary='synthetic-private-' + label), 'publish-' + label)
    store.update(task['id'], status='completed_unverified', output='synthetic-private-' + label)
    message = next(m for m in store.conversation(identity) if m['task_id'] == task['id'])
    return task['id'], result['id'], message['id']


async def test_same_identity_owner_reads_search_results_and_export(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    aa, bb, legacy = fixture(app, A, 'A'), fixture(app, B, 'B'), fixture(app, None, 'legacy')
    other = app.state.store.save_identity('Other')['id']
    foreign = fixture(app, A, 'foreign', other)
    headers = {'Authorization': 'Bearer fixture-key', 'X-Wearing-Tenant': 'fixture', 'X-Pajio-Storage-Scope': A}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers=headers) as client:
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        cursor = (await client.get('/api/search', params={'q': 'synthetic', 'limit': 1})).json()['next_cursor']
        for owner, own, denied, label, secret in [(A, aa, bb, 'A', 'B'), (B, bb, aa, 'B', 'A')]:
            client.headers['X-Pajio-Storage-Scope'] = owner
            for url in ['/api/tasks', '/api/conversation', '/api/search?q=synthetic', '/api/artifacts']:
                response = await client.get(url)
                assert response.status_code == 200, response.text
                assert own[0] in response.text and legacy[0] in response.text
                assert denied[0] not in response.text and foreign[0] not in response.text
                assert 'synthetic-private-' + secret not in response.text
            for target in [denied, foreign]:
                for url in [f'/api/tasks/{target[0]}', f'/api/search/messages/{target[2]}'] + [f'/api/artifacts/{target[1]}' + suffix for suffix in ['', '/preview', '/download', '/choices']]:
                    assert (await client.get(url)).status_code == 404, url
            detail = await client.get(f'/api/tasks/{own[0]}')
            assert own[1] in detail.text and 'queue_state' in detail.json()
            assert (await client.get(f'/api/artifacts/{own[1]}/preview')).status_code == 200
            response = await client.post('/api/data-exports', json={'request_key': 'fixture-export-key-001'})
            assert response.status_code == 201, response.text
            receipt = response.json()
            raw = (await client.get(f'/api/data-exports/{receipt["id"]}/file')).content
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                data = json.loads(archive.read('records.json'))
                assert {t['id'] for t in data['tasks']} == {own[0], legacy[0]}
                assert {a['task_id'] for a in data['artifacts']} == {own[0], legacy[0]}
                assert f'results/{denied[1]}.html' not in archive.namelist()
                assert 'synthetic-private-' + secret not in archive.read('records.json').decode()
                assert 'owner_conversations' not in data and 'task_conversation_sessions' not in data
            if owner == A: first_export = receipt['id']
            else: assert (await client.get(f'/api/data-exports/{first_export}/file')).status_code == 404
        assert (await client.get('/api/search', params={'q': 'synthetic', 'limit': 1, 'cursor': cursor})).status_code == 409
    await app.state.service.hermes.close()


@pytest.mark.parametrize('boundary', [False, True])
async def test_cloud_missing_trusted_scope_fails_closed(tmp_path, boundary):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    legacy = fixture(app, None, 'legacy')
    headers = {'X-Pajio-Storage-Scope': A}
    if boundary:
        app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
        headers = {'Authorization': 'Bearer fixture-key', 'X-Wearing-Tenant': 'fixture'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers=headers) as client:
        for url in ['/api/tasks', '/api/conversation', '/api/search?q=synthetic', '/api/artifacts', '/api/data-exports', f'/api/tasks/{legacy[0]}', f'/api/artifacts/{legacy[1]}/download']:
            assert (await client.get(url)).status_code == 401, url
    await app.state.service.hermes.close()


def test_pre_projection_archive_receipt_is_not_reused_or_downloadable(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False)
    book = IdentityExports(app.state.store)
    receipt = book.create('daily', 'fixture-export-key-001', owner_scope=A)
    path = book.root / (receipt['id'] + '.json')
    value = json.loads(path.read_text()); value.pop('task_visibility_version'); path.write_text(json.dumps(value))
    assert book.list('daily', owner_scope=A) == []
    with pytest.raises(ExportError) as error: book.download('daily', receipt['id'], owner_scope=A)
    assert error.value.status == 404
    replacement = book.create('daily', 'fixture-export-key-001', owner_scope=A)
    assert replacement['id'] != receipt['id']


async def test_owned_background_reports_never_enter_other_owners_model_or_views(tmp_path):
    from wearing.goals import GoalBook, GoalError
    from wearing.schedules import ScheduleBook, ScheduleDraft
    from wearing.life import LifeBook
    from wearing.life_proxy import dispatch
    from wearing.store import now
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    store = app.state.store
    goals, schedules = GoalBook(store), ScheduleBook(store)
    ga = goals.create('daily', 'synthetic goal A', 'safe fixture', 'fixture result', owner_scope=A)
    gl = goals.create('daily', 'legacy shared goal', 'safe fixture', 'fixture result')
    goals.control(ga['id'], 1, 'resume', owner_scope=A)
    child = goals.claim(ga['id'])
    from test_goals import report
    store.update(child['id'], status='completed_unverified', output=report('synthetic-private-goal-A'))
    goals.reconcile()
    update = goals.updates('daily', owner_scope=A)['items'][0]
    sa = schedules.create('daily', ScheduleDraft(title='synthetic schedule A', instruction='read fixture', kind='cron', cron='0 9 * * *'), 'fixture-schedule', owner_scope=A)
    # Existing completed occurrence, created without executing an engine.
    with store.connection() as db:
        db.execute('INSERT INTO schedule_occurrences(schedule_id,revision,due_at,spec,task_id,status,created_at) VALUES(?,?,?,?,?,?,?)',
                   (sa['id'], 1, now(), json.dumps(sa['schedule']), child['id'], 'completed_unverified', now()))
    actor = store.accept_message('ordinary B', 'daily', None, ACTIVE, owner_scope=B)[0]
    store.update(actor['id'], status='running', run_id='synthetic-B')
    context = goals.context(store.get(actor['id']))
    assert 'synthetic-private-goal-A' not in context and ga['id'] not in context
    assert gl['id'] in context
    assert ga['id'] not in str(dispatch(LifeBook(store), 'daily', 'goal_list', {}))
    assert sa['id'] not in str(dispatch(LifeBook(store), 'daily', 'schedule_list', {}))
    with pytest.raises(GoalError): dispatch(LifeBook(store), 'daily', 'goal_list', {'goal_id': ga['id']})
    headers = {'Authorization': 'Bearer fixture-key', 'X-Wearing-Tenant': 'fixture', 'X-Pajio-Storage-Scope': B}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers=headers) as client:
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        for url in ['/api/goals', '/api/goal-updates', '/api/schedules', '/api/conversation']:
            response = await client.get(url)
            assert response.status_code == 200 and 'synthetic-private-goal-A' not in response.text and ga['id'] not in response.text
        assert (await client.get('/api/goals/' + ga['id'])).status_code == 409
        assert (await client.get('/api/schedules/' + sa['id'])).status_code == 404
        assert (await client.post('/api/goal-updates/seen', json={'ids': [update['id']]})).status_code == 409
        assert goals.updates('daily', owner_scope=A)['unread'] == 1
        client.headers['X-Pajio-Storage-Scope'] = A
        assert 'synthetic-private-goal-A' in (await client.get('/api/goals/' + ga['id'])).text
        assert 'synthetic-private-goal-A' in (await client.get('/api/schedules/' + sa['id'])).text
    package, _ = IdentityExports(store)._build('daily', owner_scope=B)
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        data = archive.read('records.json').decode()
        assert ga['id'] not in data and sa['id'] not in data and 'synthetic-private-goal-A' not in data
    await app.state.service.hermes.close()
