"""Synthetic support snapshots: state evidence, strict privacy, tenant isolation."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
import httpx
import pytest
from wearing.app import create_app
from wearing.config import Settings
from wearing.diagnostics import Diagnostics, reference
from wearing.diagnostics_api import install_diagnostic_routes
from wearing.store import Store

NOW = 1791399000.0
CANARY = 'PRIVATE-secret-token /Users/person/private.txt https://secret.invalid?token=hidden'
def at(value): return datetime.fromtimestamp(value, timezone.utc).isoformat()
def runtime(identity):
    return SimpleNamespace(status=lambda: {'phase': 'running', 'running': True, 'installed': True, 'error': CANARY,
        'url': CANARY, 'model': {'key': CANARY}, 'model_setup_command': CANARY,
        'files': {'phase': 'ready', 'active': True, 'path': CANARY},
        'phone': {'phase': 'failed', 'active': False, 'error': CANARY}})

def seed(store, state='running', identity='daily', age=1800):
    task = store.create(CANARY, 'hermes', identity)
    store.update(task['id'], status=state, run_id='run_' + task['id'], output=CANARY, error=CANARY)
    with store.connection() as db:
        db.execute('UPDATE tasks SET created_at=?,updated_at=? WHERE id=?', (at(NOW-age), at(NOW), task['id']))
        db.execute('UPDATE events SET created_at=? WHERE task_id=?', (at(NOW-age), task['id']))
    return task

async def test_snapshot_projects_only_metadata_and_never_reads_message_columns(tmp_path):
    store = Store(tmp_path/'test.db'); task = seed(store)
    async def probe(identity): return {'state':'reachable', 'features':{CANARY: CANARY}, 'message':CANARY}
    devices = lambda identity: [{'kind':'computer', 'connected':False, 'online':False, 'paused':False, 'control_pending':False,
        'needs_review':True, 'last_seen_at':at(NOW-100), 'serial':CANARY, 'name':CANARY, 'resource_id':CANARY, 'token':CANARY}]
    snapshot = await Diagnostics(store, runtime, probe_for=probe, devices_for=devices, clock=lambda:NOW).snapshot('daily')
    text = json.dumps(snapshot)
    assert 'PRIVATE' not in text and '/Users/' not in text and 'secret.invalid' not in text
    assert snapshot['tasks']['items'][0]['task_id'] == task['id']
    assert snapshot['tasks']['items'][0]['run_id'] == 'run_' + task['id']
    assert snapshot['engine_probe'] == {'state':'reachable', 'observed_at':at(NOW)}
    assert snapshot['runtime']['connectors']['files']['active'] is True
    assert snapshot['devices']['items'][0]['last_seen_at'] == at(NOW-100)
    assert snapshot['devices']['items'][0]['connected'] is False

async def test_polling_updated_at_is_not_progress_and_waiting_is_not_stalled(tmp_path):
    store = Store(tmp_path/'test.db')
    running = seed(store); waiting = seed(store, 'waiting_for_approval'); recent = seed(store, age=10)
    snapshot = await Diagnostics(store, runtime, clock=lambda:NOW).snapshot('daily')
    rows = {row['task_id']: row for row in snapshot['tasks']['items']}
    assert rows[running['id']]['record_updated_at'] == at(NOW)
    assert rows[running['id']]['last_state_event_at'] == at(NOW-1800)
    assert rows[running['id']]['needs_progress_check'] is True
    assert rows[waiting['id']]['needs_progress_check'] is False
    assert rows[recent['id']]['needs_progress_check'] is False
    assert snapshot['engine_probe'] == {'state':'not_observed', 'observed_at':None}
    assert snapshot['devices']['state'] == 'not_observed'

async def test_explicit_new_state_event_resets_check_age_without_error_text(tmp_path):
    store = Store(tmp_path/'test.db'); task = seed(store)
    store.event(task['id'], 'approval_answered', CANARY)
    with store.connection() as db: db.execute('UPDATE events SET created_at=? WHERE task_id=? AND kind=?', (at(NOW-20), task['id'], 'approval_answered'))
    snapshot = await Diagnostics(store, runtime, clock=lambda:NOW).snapshot('daily')
    assert snapshot['tasks']['items'][0]['seconds_without_state_change'] == 20
    assert snapshot['tasks']['items'][0]['needs_progress_check'] is False

async def test_error_categories_and_unknown_ids_do_not_echo_upstream(tmp_path):
    store = Store(tmp_path/'test.db'); task = seed(store, 'connection_lost')
    store.update(task['id'], run_id=CANARY)
    snapshot = await Diagnostics(store, runtime, clock=lambda:NOW).snapshot('daily')
    row = snapshot['tasks']['items'][0]
    assert row['error_category'] == 'engine_connection_lost'
    assert row['run_id'].startswith('ref_') and 'PRIVATE' not in row['run_id']
    assert reference(CANARY) == row['run_id']

async def test_timeout_failed_runtime_and_devices_remain_partial_and_do_not_start(tmp_path):
    store = Store(tmp_path/'test.db'); calls = []
    def unavailable(identity): calls.append(('runtime',identity)); raise RuntimeError(CANARY)
    async def probe(identity): calls.append(('probe',identity)); await asyncio.sleep(60)
    def devices(identity): raise RuntimeError(CANARY)
    snapshot = await Diagnostics(store, unavailable, probe_for=probe, devices_for=devices, clock=lambda:NOW, probe_timeout=.01).snapshot('daily')
    assert snapshot['runtime']['state'] == 'unavailable' and snapshot['runtime']['running'] is None
    assert snapshot['engine_probe']['state'] == 'timeout'
    assert snapshot['devices']['state'] == 'unavailable'
    assert calls == [('runtime','daily'),('probe','daily')]
    assert 'PRIVATE' not in json.dumps(snapshot)

async def test_recent_limit_and_identity_do_not_leak_older_or_other_tasks(tmp_path):
    store = Store(tmp_path/'test.db'); other = store.save_identity('Private name')['id']
    hidden = seed(store, identity=other)
    for _ in range(35): seed(store)
    snapshot = await Diagnostics(store, runtime, clock=lambda:NOW).snapshot('daily')
    assert len(snapshot['tasks']['items']) == 30 and snapshot['tasks']['truncated']
    assert hidden['id'] not in json.dumps(snapshot) and 'Private name' not in json.dumps(snapshot)
    snapshot = await Diagnostics(store, runtime, clock=lambda:NOW).snapshot(other)
    assert [row['task_id'] for row in snapshot['tasks']['items']] == [hidden['id']]

async def test_real_app_tenant_and_identity_middleware_protect_diagnostic_route(tmp_path):
    from wearing.cloud.worker import TenantBoundary
    app = create_app(Settings(tmp_path))
    app.add_middleware(TenantBoundary, tenant_id='tenant_qa', gateway_key='instance-key')
    # Explicit isolated adapters replace any production mount; no engine starts.
    app.router.routes = [route for route in app.router.routes if getattr(route,'path',None) != '/api/diagnostics']
    store = app.state.store; other = store.save_identity('Private name')['id']
    own = seed(store); hidden = seed(store, identity=other)
    install_diagnostic_routes(app, store, runtime)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        assert (await client.get('/api/diagnostics')).status_code == 401
        client.headers.update({'Authorization':'Bearer instance-key', 'X-Wearing-Tenant':'wrong'})
        assert (await client.get('/api/diagnostics')).status_code == 403
        client.headers['X-Wearing-Tenant'] = 'tenant_qa'
        response = await client.get('/api/diagnostics')
        assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
        assert own['id'] in response.text and hidden['id'] not in response.text and 'PRIVATE' not in response.text
        assert (await client.get('/api/diagnostics', headers={'X-Wearing-Identity':other})).json()['tasks']['items'][0]['task_id'] == hidden['id']
        assert (await client.get('/api/diagnostics?identity=daily', headers={'X-Wearing-Identity':other})).status_code == 409
        assert (await client.get('/api/diagnostics', headers={'X-Wearing-Identity':'missing'})).status_code == 404
    await app.state.service.hermes.close()

async def test_get_does_not_mutate_task_or_event_rows(tmp_path):
    store = Store(tmp_path/'test.db'); seed(store)
    def rows():
        with store.connection() as db: return [tuple(r) for r in db.execute('SELECT * FROM tasks')], [tuple(r) for r in db.execute('SELECT * FROM events')]
    before = rows(); diagnostics = Diagnostics(store, runtime, clock=lambda:NOW)
    await diagnostics.snapshot('daily'); await diagnostics.snapshot('daily')
    assert before == rows()


def bind_owner(store, task, owner):
    with store.connection() as db:
        db.execute('INSERT INTO task_principals(task_id,owner_scope) VALUES(?,?)', (task['id'], owner))


async def test_owner_filter_precedes_task_limit_and_omits_unowned_tasks(tmp_path):
    store = Store(tmp_path/'test.db')
    owner_a, owner_b = 'a'*64, 'b'*64
    own = seed(store, age=10000); bind_owner(store, own, owner_a)
    unowned = seed(store)
    for _ in range(35):
        hidden = seed(store); bind_owner(store, hidden, owner_b)
    diagnostics = Diagnostics(store, runtime, clock=lambda: NOW, require_owner=True)
    snapshot = await diagnostics.snapshot('daily', owner_scope=diagnostics.owner(owner_a))
    assert [row['task_id'] for row in snapshot['tasks']['items']] == [own['id']]
    assert not snapshot['tasks']['truncated']
    assert unowned['id'] not in json.dumps(snapshot)
    assert owner_a not in json.dumps(snapshot) and owner_b not in json.dumps(snapshot)
    for missing in (None, '', 'local', owner_a+'a', 'A'*64):
        with pytest.raises(PermissionError):
            diagnostics.owner(missing)


async def test_actual_cloud_app_snapshot_and_history_scope_each_owner(tmp_path):
    from wearing.cloud.worker import TenantBoundary
    app = create_app(Settings(tmp_path), local_devices=False, engine_autostart=False)
    app.add_middleware(TenantBoundary, tenant_id='tenant_qa', gateway_key='instance-key')
    store = app.state.store
    owner_a, owner_b = 'a'*64, 'b'*64
    own = seed(store); bind_owner(store, own, owner_a)
    foreign = seed(store); bind_owner(store, foreign, owner_b)
    unowned = seed(store)
    other_identity = store.save_identity('Private identity')['id']
    other = seed(store, identity=other_identity); bind_owner(store, other, owner_a)
    # Keep the production route and require_owner mount. Only I/O adapters are
    # synthetic, so this cannot contact an engine or inspect a real device.
    diagnostics = app.state.diagnostics
    diagnostics.runtime_for = runtime
    diagnostics.devices_for = None
    async def probe(identity): return {'state': 'reachable'}
    diagnostics.probe_for = probe
    assert diagnostics.require_owner is True
    # Internal health collection still observes both principals. Each public
    # history projects its own tasks instead of inheriting the last reader.
    assert await app.state.health_monitor.collect('daily')
    with store.connection() as db:
        captured = db.execute('SELECT payload FROM health_samples WHERE identity_id=?', ('daily',)).fetchone()[0]
    assert own['id'] in captured and foreign['id'] in captured and unowned['id'] not in captured
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            assert (await client.get('/api/diagnostics')).status_code == 401
            client.headers.update({'Authorization': 'Bearer instance-key', 'X-Wearing-Tenant': 'tenant_qa'})
            assert (await client.get('/api/diagnostics')).status_code == 401
            assert (await client.get('/api/diagnostics?owner_scope='+owner_a)).status_code == 401
            for principal, visible, invisible in ((owner_a, own, foreign), (owner_b, foreign, own)):
                client.headers['X-Pajio-Storage-Scope'] = principal
                response = await client.get('/api/diagnostics?owner_scope='+invisible['id'])
                assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
                assert [row['task_id'] for row in response.json()['tasks']['items']] == [visible['id']]
                history = await client.get('/api/diagnostics/history')
                assert history.status_code == 200 and visible['id'] in history.text
                for hidden in (invisible, unowned, other):
                    assert hidden['id'] not in response.text and hidden['id'] not in history.text
                assert 'PRIVATE' not in response.text and principal not in response.text
            client.headers['X-Pajio-Storage-Scope'] = owner_a
            response = await client.get('/api/diagnostics', headers={'X-Wearing-Identity': other_identity})
            assert response.status_code == 200
            assert [row['task_id'] for row in response.json()['tasks']['items']] == [other['id']]
            assert (await client.get('/api/diagnostics', headers={'X-Wearing-Tenant': 'foreign'})).status_code == 403
    finally:
        await app.state.service.hermes.close()
