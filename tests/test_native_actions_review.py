"""Independent phone-receipt boundary regression checks; all data is synthetic."""
from datetime import datetime, timezone

import pytest

from wearing.native_actions import NativeActions, NativeActionError
from wearing.store import Store

PHONE, SECRET, SESSION = "a" * 32, "b" * 64, "c" * 32


def admitted(tmp_path, method, params, *, claim_it=True):
    store = Store(tmp_path / "synthetic-native-review.sqlite3")
    book = NativeActions(store, lambda: datetime(2026, 10, 8, tzinfo=timezone.utc))
    policy = {
        "calendars": [{"id": "cal", "title": "Synthetic calendar", "writable": True}],
        "reminders": [{"id": "rem", "title": "Synthetic reminders", "writable": True}],
        "calendar_create": True, "reminder_create": True, "location": False,
    }
    book.configure("daily", PHONE, SECRET, 0, True, policy)
    book.connect("daily", PHONE, SECRET, 1, SESSION, [method])
    task = store.create("Synthetic receipt review", "general")
    with store.connection() as db:
        db.execute("UPDATE tasks SET status='running',run_id='synthetic-review-run' WHERE id=?", (task["id"],))
    command = book.request("daily", PHONE, method, params, "synthetic-once")
    if claim_it:
        book.claim("daily", PHONE, SECRET, SESSION, command["id"], command["fingerprint"], True)
    return book, command


def finish(book, command, data):
    return book.finish("daily", PHONE, SECRET, SESSION, command["id"], command["fingerprint"],
                       {"status": "succeeded", "code": "ok", "data": data})


def packet(item, returned=1):
    return {"items": [item], "returned": returned, "has_more": False, "text_may_be_truncated": True}


@pytest.mark.parametrize("dates", [
    {"start": None, "end": "2026-10-08T01:00:00Z"},
    {"start": "not-a-date", "end": "2026-10-08T01:00:00Z"},
    {"start": "2026-10-08T00:00:00", "end": "2026-10-08T01:00:00Z"},
    {"start": "2026-10-08T02:00:00Z", "end": "2026-10-08T01:00:00Z"},
])
def test_calendar_read_cannot_claim_success_with_malformed_native_dates(tmp_path, dates):
    book, command = admitted(tmp_path, "calendar.read", {
        "calendar_ids": ["cal"], "start": "2026-10-08T00:00:00Z", "end": "2026-10-09T00:00:00Z",
    })
    item = {"id": "synthetic-event", "calendar_id": "cal", "title": "Synthetic", "notes": "", "all_day": False, **dates}
    with pytest.raises(NativeActionError):
        finish(book, command, packet(item))
    assert book.get("daily", command["id"])["result"] is None


@pytest.mark.parametrize("patch", [{"completed": "false"}, {"completed": 0}, {"due": "tomorrow"}, {"due": {"date": "2026-10-08"}}])
def test_reminder_read_cannot_claim_success_with_untyped_fields(tmp_path, patch):
    book, command = admitted(tmp_path, "reminders.read", {"calendar_ids": ["rem"]})
    item = {"id": "synthetic-reminder", "calendar_id": "rem", "title": "Synthetic", "notes": "", "all_day": False, "due": None, "completed": False, **patch}
    with pytest.raises(NativeActionError):
        finish(book, command, packet(item))
    assert book.get("daily", command["id"])["result"] is None


def test_read_count_requires_integer_not_boolean(tmp_path):
    book, command = admitted(tmp_path, "reminders.read", {"calendar_ids": ["rem"]})
    item = {"id": "synthetic-reminder", "calendar_id": "rem", "title": "Synthetic", "notes": "", "all_day": False, "due": None, "completed": False}
    with pytest.raises(NativeActionError):
        finish(book, command, packet(item, returned=True))


def test_cancelled_task_does_not_accept_pending_read_receipt(tmp_path):
    book, command = admitted(tmp_path, "reminders.read", {"calendar_ids": ["rem"]})
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET status='stopping' WHERE id=?", (command["task_id"],))
    with pytest.raises(NativeActionError):
        finish(book, command, {"items": [], "returned": 0, "has_more": False, "text_may_be_truncated": False})
    assert book.get("daily", command["id"])["state"] == "expired"


def test_new_run_cannot_claim_an_old_run_native_request(tmp_path):
    book, command = admitted(tmp_path, "reminders.read", {"calendar_ids": ["rem"]})
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET run_id='new-synthetic-run' WHERE id=?", (command["task_id"],))
    with pytest.raises(NativeActionError):
        finish(book, command, {"items": [], "returned": 0, "has_more": False, "text_may_be_truncated": False})


@pytest.fixture
def cloud_api(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from wearing.native_actions_api import install_native_action_routes

    book = NativeActions(Store(tmp_path / 'synthetic-cloud-native.sqlite3'))
    app = FastAPI()

    @app.middleware('http')
    async def trusted_test_gateway(request, call_next):
        # This fixture supplies authenticated ASGI scope, not production headers.
        request.state.identity_id = 'daily'
        request.scope['pajio.cloud_worker'] = True
        owner = request.headers.get('x-test-authenticated-owner')
        if owner:
            request.scope['pajio.storage_scope'] = owner
        return await call_next(request)

    install_native_action_routes(app, book)
    with TestClient(app) as client:
        yield client, book


def config_body():
    return {'installation_id': PHONE, 'secret': SECRET, 'revision': 0, 'enabled': True,
            'policy': {'calendars': [{'id': 'private-calendar', 'title': 'Private calendar', 'writable': True}]}}


def test_cloud_requires_authenticated_account_scope_not_legacy_local_default(cloud_api):
    client, _ = cloud_api
    assert client.get('/api/native-actions/devices').status_code == 401
    assert client.post('/api/native-actions/configure', json=config_body()).status_code == 401


def test_same_tenant_identity_other_account_cannot_discover_or_use_phone(cloud_api):
    client, _ = cloud_api
    owner_a = {'x-test-authenticated-owner': 'a' * 64}
    owner_b = {'x-test-authenticated-owner': 'f' * 64}
    configured = client.post('/api/native-actions/configure', headers=owner_a, json=config_body())
    assert configured.status_code == 200
    assert len(client.get('/api/native-actions/devices', headers=owner_a).json()['items']) == 1
    assert client.get('/api/native-actions/devices', headers=owner_b).json()['items'] == []
    # Use even the exact phone credential to prove the account boundary itself.
    phone = {'installation_id': PHONE, 'secret': SECRET}
    assert client.post('/api/native-actions/history', headers=owner_b, json=phone).status_code in {403, 404}
    assert client.post('/api/native-actions/connect', headers=owner_b, json={**phone, 'connection_id': SESSION, 'revision': 1, 'capabilities': ['calendar.read']}).status_code in {403, 404}
    assert client.post('/api/native-actions/configure', headers=owner_b, json={**config_body(), 'revision': 1, 'enabled': False}).status_code in {403, 404}
    assert client.get('/api/native-actions/devices', headers=owner_a).json()['items'][0]['enabled'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('claim_it,expected_state', [(False, 'cancelled'), (True, 'unknown')])
async def test_tool_cancellation_retires_request_without_replaying_admitted_write(tmp_path, monkeypatch, claim_it, expected_state):
    import asyncio
    from wearing.native_actions_tools import dispatch

    params = {'calendar_id': 'rem', 'title': 'Synthetic cancellation'}
    book, command = admitted(tmp_path, 'reminders.create', params, claim_it=claim_it)
    monkeypatch.setattr('wearing.native_actions_tools.NativeActions', lambda _store: book)
    job = asyncio.create_task(dispatch(book.store, 'daily', 'native_request', {
        'installation_id': PHONE, 'method': 'reminders.create', 'params': params, 'request_key': 'synthetic-once',
    }))
    await asyncio.sleep(0)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    # Use a fresh object to prove retirement is durable, not only a UI update.
    renewed = NativeActions(Store(book.store.path), book.clock)
    assert renewed.get('daily', command['id'])['state'] == expected_state
    assert renewed.get('daily', command['id'])['result'] is None


@pytest.fixture
def owned_cloud(tmp_path):
    from wearing.native_actions import ACTIVE

    book = NativeActions(Store(tmp_path / 'owned-cloud-review.sqlite3'), require_task_owner=True)
    owner = 'a' * 64
    policy = {'reminders': [{'id': 'rem', 'title': 'Private reminders', 'writable': True}], 'reminder_create': True}
    book.configure('daily', PHONE, SECRET, 0, True, policy, owner_scope=owner)
    book.connect('daily', PHONE, SECRET, 1, SESSION, ['reminders.read', 'reminders.create'], owner_scope=owner)
    task, _ = book.store.accept_message('Synthetic owner A message', 'daily', 'owner-A-request', ACTIVE, owner_scope=owner)
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET status='running',run_id='owner-A-run' WHERE id=?", (task['id'],))
    return book, task, owner


@pytest.mark.asyncio
async def test_agent_uses_trusted_task_owner_for_device_discovery_and_receipts(owned_cloud):
    from wearing.native_actions import ACTIVE
    from wearing.native_actions_tools import dispatch

    book, task, owner = owned_cloud
    assert len((await dispatch(book.store, 'daily', 'native_devices', {}))['items']) == 1
    original = book.request('daily', PHONE, 'reminders.read', {'calendar_ids': ['rem']}, 'original-read')
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET status='stopped' WHERE id=?", (task['id'],))
    other, _ = book.store.accept_message('Synthetic owner B message', 'daily', 'owner-B-request', ACTIVE, owner_scope='f' * 64)
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET status='running',run_id='owner-B-run' WHERE id=?", (other['id'],))
    assert (await dispatch(book.store, 'daily', 'native_devices', {}))['items'] == []
    with pytest.raises(NativeActionError):
        await dispatch(book.store, 'daily', 'native_receipt', {'command_id': original['id']})
    with pytest.raises(NativeActionError):
        book.request('daily', PHONE, 'reminders.read', {'calendar_ids': ['rem']}, 'new-owner-attempt')
    assert len(book.devices('daily', owner_scope=owner)) == 1


def test_message_idempotency_cannot_reassign_existing_task_owner(owned_cloud):
    from wearing.native_actions import ACTIVE
    from wearing.store import MessageConflict

    book, task, owner = owned_cloud
    with pytest.raises(MessageConflict):
        book.store.accept_message('Synthetic owner A message', 'daily', 'owner-A-request', ACTIVE, owner_scope='f' * 64)
    original, created = book.store.accept_message('Synthetic owner A message', 'daily', 'owner-A-request', ACTIVE, owner_scope=owner)
    assert original['id'] == task['id'] and created is False
    with book.store.connection() as db:
        assert db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (task['id'],)).fetchone()[0] == owner


@pytest.mark.asyncio
async def test_unknown_cloud_task_owner_remains_closed_after_mcp_reconstruction(owned_cloud):
    from wearing.native_actions_tools import dispatch

    book, task, _ = owned_cloud
    with book.store.connection() as db:
        db.execute('DELETE FROM task_principals WHERE task_id=?', (task['id'],))
    fresh = NativeActions(Store(book.store.path))
    assert fresh.require_task_owner is True
    with pytest.raises(NativeActionError):
        fresh.request('daily', PHONE, 'reminders.read', {'calendar_ids': ['rem']}, 'owner-missing')
    with pytest.raises(NativeActionError):
        await dispatch(fresh.store, 'daily', 'native_devices', {})


def test_same_identity_other_account_cannot_admit_or_finish_original_command(owned_cloud):
    book, _, owner = owned_cloud
    command = book.request('daily', PHONE, 'reminders.read', {'calendar_ids': ['rem']}, 'private-read')
    args = ('daily', PHONE, SECRET, SESSION, command['id'], command['fingerprint'])
    with pytest.raises(NativeActionError):
        book.claim(*args, True, owner_scope='f' * 64)
    book.claim(*args, True, owner_scope=owner)
    with pytest.raises(NativeActionError):
        book.finish(*args, {'status':'succeeded','code':'ok','data':{'items':[],'returned':0,'has_more':False,'text_may_be_truncated':False}}, owner_scope='f' * 64)
    assert book.get('daily', command['id'], owner_scope=owner)['state'] == 'executing'


def test_legacy_local_device_is_not_inherited_by_cloud_account(tmp_path):
    from wearing.native_actions import ACTIVE

    store = Store(tmp_path / 'legacy-local-device.sqlite3')
    local = NativeActions(store)
    local.configure('daily', PHONE, SECRET, 0, True, {'location': True})
    local.connect('daily', PHONE, SECRET, 1, SESSION, ['location.read'])
    cloud = NativeActions(store, require_task_owner=True)
    owner = 'a' * 64
    task, _ = store.accept_message('Synthetic cloud message', 'daily', 'cloud-owner', ACTIVE, owner_scope=owner)
    with store.connection() as db:
        db.execute("UPDATE tasks SET status='running',run_id='cloud-run' WHERE id=?", (task['id'],))
    assert cloud.devices('daily', owner_scope=owner) == []
    with pytest.raises(NativeActionError):
        cloud.request('daily', PHONE, 'location.read', {}, 'inherit-local')
    with pytest.raises(NativeActionError):
        cloud.configure('daily', PHONE, SECRET, 1, True, {'location': True}, owner_scope=owner)


@pytest.mark.asyncio
async def test_actual_app_binds_chat_owner_and_blocks_other_account_task_controls(tmp_path):
    import httpx
    from wearing.app import create_app
    from wearing.config import Settings
    from wearing.hermes import HermesClient

    wire_calls = []
    def no_engine(request):
        wire_calls.append(str(request.url))
        return httpx.Response(503, json={'error': 'Synthetic: engine must not be reached'})

    settings = Settings(tmp_path / 'actual-app-fixture', hermes_key='synthetic')
    hermes = HermesClient(settings, httpx.MockTransport(no_engine))
    app = create_app(settings, hermes=hermes, local_devices=False, engine_autostart=False)

    @app.middleware('http')
    async def authenticated_fixture(request, call_next):
        request.scope['pajio.cloud_worker'] = True
        owner = request.headers.get('x-test-authenticated-owner')
        if owner:
            request.scope['pajio.storage_scope'] = owner
        return await call_next(request)

    # Occupy the single-run lane so this actual HTTP submission remains queued.
    occupied = app.state.store.create('Synthetic occupied run', 'computer')
    app.state.store.update(occupied['id'], status='running', run_id='occupied-run')
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as http:
            token = (await http.get('/api/bootstrap')).json()['token']
            owner_a = {'X-Wearing-Token': token, 'x-test-authenticated-owner': 'a' * 64}
            owner_b = {'X-Wearing-Token': token, 'x-test-authenticated-owner': 'f' * 64}
            body = {'content': 'Synthetic phone task owner A', 'request_id': 'synthetic-owner-request-0001'}
            missing = await http.post('/api/conversation', json={'content': 'Synthetic private preview', 'request_id': 'synthetic-preview-request-0001'}, headers={'X-Wearing-Token': token})
            assert missing.status_code == 201
            preview_id = missing.json()['task']['id']
            with app.state.store.connection() as db:
                assert db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (preview_id,)).fetchone() is None
                db.execute("UPDATE tasks SET status='running',run_id='synthetic-preview-run' WHERE id=?", (preview_id,))
            try:
                with pytest.raises(NativeActionError):
                    NativeActions(app.state.store).task_owner('daily')
            finally:
                app.state.store.update(preview_id, status='draft', run_id=None)
            malformed = await http.post('/api/conversation', json={'content': 'Synthetic malformed owner', 'request_id': 'synthetic-malformed-request-0001'}, headers={'X-Wearing-Token': token, 'x-test-authenticated-owner': 'invalid'})
            assert malformed.status_code == 401
            created = await http.post('/api/conversation', json=body, headers=owner_a)
            assert created.status_code == 201
            task_id = created.json()['task']['id']
            assert created.json()['queued'] is True
            with app.state.store.connection() as db:
                assert db.execute('SELECT owner_scope FROM task_principals WHERE task_id=?', (task_id,)).fetchone()[0] == 'a' * 64
            assert (await http.get('/api/tasks/' + task_id, headers=owner_a)).status_code == 200
            assert (await http.get('/api/tasks/' + task_id, headers=owner_b)).status_code == 404
            for action, payload in [('start', {}), ('approval', {'request_id': 'synthetic', 'choice': 'once'}), ('stop', {}), ('cancel-message', {})]:
                denied = await http.post(f'/api/tasks/{task_id}/{action}', json=payload, headers=owner_b)
                assert denied.status_code == 404, action
            assert (await http.post('/api/conversation', json=body, headers=owner_b)).status_code == 409
            assert app.state.store.get(task_id)['status'] == 'draft'
            assert wire_calls == []
    finally:
        await hermes.close()
