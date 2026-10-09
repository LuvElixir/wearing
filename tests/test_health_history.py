"""Temporary SQLite + ASGI only. No engine, cloud, notification or support calls."""
import asyncio
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from wearing.diagnostics import Diagnostics
from wearing.health_history import HealthError, HealthHistory, HealthMonitor, at
from wearing.health_history_api import install_health_history_routes
from wearing.store import Store

NOW = 1791399000.0
SECRET = 'PRIVATE-CANARY /Users/private/file https://secret.invalid?token=secret person@example.com'
A, B = 'a'*64, 'b'*64


@pytest.fixture
def fixture(tmp_path):
    clock = [NOW]
    store = Store(tmp_path/'test.sqlite3')
    book = HealthHistory(store, clock=lambda: clock[0])
    return store, book, clock


def snapshot(identity='daily', engine='reachable', connected=True):
    return {'identity_id': identity, 'captured_at': at(NOW), 'service': {'deployment': 'synthetic'},
        'runtime': {'state': 'observed', 'installed': True, 'running': True},
        'engine_probe': {'state': engine},
        'devices': {'state': 'observed', 'items': [{'online': connected, 'connected': connected}]},
        'tasks': {'items': []}}


def events(book, component, owner=None):
    return [row for row in book.history('daily', owner)['events'] if row['component'] == component]


def task(store, owner=None, identity='daily', phase='failed'):
    row = store.create(SECRET, 'hermes', identity)
    store.update(row['id'], status=phase)
    if owner:
        with store.connection() as db:
            store.bind_task_principal(db, row['id'], owner)
    return {'task_id': row['id'], 'phase': phase,
        'last_state_event_at': at(NOW), 'error_category': 'run_failed' if phase == 'failed' else None}


def test_fault_onset_dedup_unknown_and_readback_recovery_survive_restart(fixture):
    store, book, clock = fixture
    book.record('daily', snapshot())
    clock[0] += 300
    book.record('daily', snapshot(engine='timeout'))
    began = clock[0]
    clock[0] += 300
    book.record('daily', snapshot(engine='timeout'))
    assert len(events(book, 'engine')) == 1
    restarted = HealthHistory(store, clock=lambda: clock[0])
    clock[0] += 300
    restarted.record('daily', snapshot(engine='not_observed'))
    assert not any(row['kind'] == 'condition_cleared' for row in events(restarted, 'engine'))
    clock[0] += 300
    restarted.record('daily', snapshot())
    event = events(restarted, 'engine')[0]
    assert event['kind'] == 'condition_cleared' and event['condition_started_at'] == at(began)
    assert event['observed_at'] == at(clock[0])
    assert event['previous_code'] == 'engine_timeout'


def test_engine_device_and_collector_failures_have_distinct_evidence(fixture):
    store, book, clock = fixture
    book.record('daily', snapshot(engine='unavailable', connected=False))
    assert events(book, 'engine')[0]['code'] == 'engine_unavailable'
    assert events(book, 'devices')[0]['code'] == 'device_disconnected'
    clock[0] += 300
    book.record('daily', {}, failed=True)
    latest = book.history('daily')['samples'][0]
    assert [row['component'] for row in latest['observations']] == ['collector']
    assert latest['observations'][0]['code'] == 'collection_failed'
    assert not any(row['kind'] == 'condition_cleared' for row in events(book, 'engine'))
    clock[0] += 300
    book.record('daily', snapshot())
    assert events(book, 'collector')[0]['kind'] == 'condition_cleared'


def test_unconfigured_paused_and_truncated_are_not_fake_health(fixture):
    _, book, _ = fixture
    value = snapshot(engine='not_configured')
    value['runtime'] = {'installed': False}
    value['devices']['items'][0]['paused'] = True
    book.record('daily', value)
    rows = {row['component']: row for row in book.history('daily')['samples'][0]['observations']}
    assert rows['engine']['status'] == 'not_configured'
    assert rows['runtime']['status'] == 'not_configured'
    assert rows['devices']['status'] == 'inactive'
    value['devices']['items'][0]['paused'] = False
    value['devices']['truncated'] = True
    book.record('daily', value)
    assert book.history('daily')['samples'][0]['observations'][2]['status'] == 'unknown'


def test_cloud_task_scope_no_unowned_or_other_owner_exports(fixture):
    store, _, clock = fixture
    book = HealthHistory(store, clock=lambda: clock[0], require_owner=True)
    own, other, unowned = task(store, A), task(store, B), task(store)
    value = snapshot(); value['tasks']['items'] = [own, other, unowned]
    # An injected owner in an observation must never become authorization.
    other['owner_scope'] = A
    book.record('daily', value)
    a = json.dumps(book.history('daily', A))
    assert own['task_id'] in a and other['task_id'] not in a and unowned['task_id'] not in a
    b = json.dumps(book.history('daily', B))
    assert own['task_id'] not in b and other['task_id'] in b
    report = book.create_export('daily', A, 'request-key-00001', 'chat')
    raw, _ = book.download('daily', A, report['id'])
    assert own['task_id'].encode() in raw and other['task_id'].encode() not in raw
    assert A.encode() not in raw and B.encode() not in raw and b'owner_scope' not in raw
    with pytest.raises(HealthError, match='export_not_found'):
        book.download('daily', B, report['id'])
    for missing in (None, '', 'local', SECRET):
        with pytest.raises(HealthError, match='account_scope_required'):
            book.history('daily', missing)


def test_task_waiting_is_not_fault_and_phase_check_is_not_engine_failure(fixture):
    store, book, clock = fixture
    waiting = task(store, phase='waiting_for_approval')
    long = task(store, phase='running'); long['needs_progress_check'] = True
    value = snapshot(); value['tasks']['items'] = [waiting, long]
    book.record('daily', value)
    task_events = events(book, 'task')
    assert len(task_events) == 1 and task_events[0]['task_id'] == long['task_id']
    assert task_events[0]['code'] == 'progress_check' and task_events[0]['status'] == 'review'
    clock[0] += 300
    long.update(phase='stopped', needs_progress_check=False)
    book.record('daily', value)
    assert events(book, 'task')[0]['kind'] == 'condition_ended'
    assert events(book, 'task')[0]['previous_code'] == 'progress_check'


def test_identity_isolation_and_snapshot_identity_cannot_be_forged(fixture):
    store, book, _ = fixture
    other = store.save_identity('PRIVATE IDENTITY')['id']
    book.record('daily', snapshot(engine='timeout'))
    book.record(other, snapshot(other))
    assert not book.history(other)['events']
    with pytest.raises(HealthError, match='observation_scope_mismatch'):
        book.record(other, snapshot())
    report = book.create_export('daily', None, 'request-key-00001', 'other')
    with pytest.raises(HealthError, match='export_not_found'):
        book.download(other, None, report['id'])
    assert 'PRIVATE' not in json.dumps(book.history(other))


def test_allowlist_no_logs_names_paths_urls_tokens_in_history_tables_or_export(fixture):
    store, book, _ = fixture
    value = snapshot()
    value.update(error=SECRET, stack=SECRET, filename=SECRET)
    value['runtime'].update(error_present=True, error=SECRET, model=SECRET)
    value['devices']['items'][0].update(name=SECRET, serial=SECRET, url=SECRET)
    row = task(store); row.update(title=SECRET, run_id=SECRET, output=SECRET, error=SECRET)
    value['tasks']['items'] = [row]
    book.record('daily', value)
    metadata = book.create_export('daily', None, 'request-key-00001', 'other')
    raw, _ = book.download('daily', None, metadata['id'])
    with store.connection() as db:
        stored = '\n'.join(str(tuple(row)) for table in ('health_samples', 'health_events', 'health_conditions', 'health_exports')
            for row in db.execute('SELECT * FROM '+table))
    for canary in ('PRIVATE', '/Users/', 'secret.invalid', 'person@example.com'):
        assert canary not in stored and canary.encode() not in raw
    assert metadata['sha256'] == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw)['transmission'] == 'not_sent'


def test_expiring_immutable_export_is_idempotent_through_restart(fixture):
    store, book, clock = fixture
    book.record('daily', snapshot())
    first = book.create_export('daily', None, 'request-key-00001', 'sync')
    raw, _ = book.download('daily', None, first['id'])
    clock[0] += 300
    book.record('daily', snapshot(engine='timeout'))
    restarted = HealthHistory(store, clock=lambda: clock[0])
    assert restarted.create_export('daily', None, 'request-key-00001', 'sync') == first
    assert restarted.download('daily', None, first['id'])[0] == raw
    with pytest.raises(HealthError, match='export_request_conflict'):
        restarted.create_export('daily', None, 'request-key-00001', 'voice')
    clock[0] += 86400
    with pytest.raises(HealthError, match='export_not_found'):
        restarted.download('daily', None, first['id'])
    replacement = restarted.create_export('daily', None, 'request-key-00001', 'sync')
    assert replacement['id'] != first['id']


def test_export_limits_and_invalid_keys(fixture):
    _, book, _ = fixture
    for n in range(5):
        book.create_export('daily', None, f'request-key-{n:05}', 'sync')
    with pytest.raises(HealthError, match='export_limit'):
        book.create_export('daily', None, 'request-key-99999', 'sync')
    for key, category in [(SECRET, 'sync'), ('request-key-11111', SECRET), ('short', 'sync')]:
        with pytest.raises(HealthError, match='invalid_export'):
            book.create_export('daily', None, key, category)


def test_retention_and_size_caps_and_stale_are_not_uptime(fixture):
    store, _, clock = fixture
    book = HealthHistory(store, clock=lambda: clock[0], retention=1000, max_samples=3, max_events=2, interval=60)
    empty = book.history('daily')
    assert empty['coverage']['freshness'] == 'never_observed'
    for index in range(8):
        book.record('daily', snapshot(engine='timeout' if index%2 else 'reachable'))
        clock[0] += 10
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM health_samples').fetchone()[0] == 3
        assert db.execute('SELECT COUNT(*) FROM health_events').fetchone()[0] == 2
    assert book.history('daily', sample_limit=1, event_limit=1)['samples_truncated'] is True
    clock[0] += 121
    coverage = book.history('daily')['coverage']
    assert coverage['freshness'] == 'stale' and coverage['continuous_uptime_proven'] is False
    clock[0] += 1001
    assert not book.history('daily')['samples']
    book.record('daily', snapshot())
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM health_samples').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM health_events').fetchone()[0] <= 1


async def test_actual_diagnostics_probes_fail_timeout_and_recover_without_commands(fixture):
    store, book, clock = fixture
    state = {'engine': 'reachable', 'connected': True}
    calls = []
    def runtime(identity):
        calls.append(('status', identity))
        return SimpleNamespace(status=lambda: {'phase':'running','running':True,'installed':True})
    async def probe(identity):
        calls.append(('probe', identity))
        if state['engine'] == 'timeout':
            await asyncio.sleep(10)
        if state['engine'] == 'raise':
            raise RuntimeError(SECRET)
        return {'state': state['engine']}
    diagnostics = Diagnostics(store, runtime, probe_for=probe,
        devices_for=lambda identity: [{'kind':'computer','online':state['connected'],'connected':state['connected']}],
        clock=lambda:clock[0], probe_timeout=.01)
    monitor = HealthMonitor(book, diagnostics, minimum_interval=0)
    await monitor.collect('daily')
    state.update(engine='timeout', connected=False); clock[0] += 300
    await monitor.collect('daily')
    assert events(book, 'engine')[0]['code'] == 'engine_timeout'
    assert events(book, 'devices')[0]['code'] == 'device_disconnected'
    state.update(engine='raise'); clock[0] += 300
    await monitor.collect('daily')
    assert events(book, 'engine')[0]['code'] == 'engine_unavailable'
    state.update(engine='reachable', connected=True); clock[0] += 300
    await monitor.collect('daily')
    assert events(book, 'engine')[0]['kind'] == 'condition_cleared'
    assert calls == [('status','daily'),('probe','daily')]*4


async def test_monitor_failure_rate_limit_and_cancel_do_not_invent_healthy_rows(fixture):
    _, book, clock = fixture
    class Broken:
        async def snapshot(self, *args): raise RuntimeError(SECRET)
    monitor = HealthMonitor(book, Broken())
    assert await monitor.collect('daily') is True
    assert await monitor.collect('daily') is False
    assert book.history('daily')['samples'][0]['observations'][0]['code'] == 'collection_failed'
    class Slow:
        async def snapshot(self, *args): await asyncio.sleep(60)
    clock[0] += 20
    monitor.diagnostics = Slow()
    task = asyncio.create_task(monitor.collect('daily'))
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert len(book.history('daily')['samples']) == 1


async def test_loop_retries_inventory_failure_and_stops_without_orphans(fixture):
    _, book, _ = fixture
    book.interval = .01
    class Fake:
        async def snapshot(self, identity, deployment): return snapshot(identity)
    monitor = HealthMonitor(book, Fake(), minimum_interval=0)
    original = book.identities
    count = [0]
    def flaky():
        count[0] += 1
        if count[0] == 1: raise RuntimeError(SECRET)
        return original()
    book.identities = flaky
    stop = asyncio.Event()
    runner = asyncio.create_task(monitor.run(stop))
    for _ in range(20):
        await asyncio.sleep(.01)
        if book.history('daily')['samples']: break
    stop.set(); await runner
    assert count[0] > 1 and monitor.running is False
    assert book.history('daily')['samples']


async def test_actual_app_routes_require_auth_csrf_tenant_owner_identity_and_safe_download(tmp_path):
    from wearing.app import create_app
    from wearing.config import Settings
    from wearing.cloud.worker import TenantBoundary
    app = create_app(Settings(tmp_path))
    app.add_middleware(TenantBoundary, tenant_id='tenant_qa', gateway_key='instance-key')
    store = app.state.store
    other = store.save_identity('Private identity')['id']
    book = HealthHistory(store, clock=lambda: NOW, require_owner=True)
    class Fake:
        async def snapshot(self, identity, deployment): return snapshot(identity)
    monitor = HealthMonitor(book, Fake())
    app.router.routes = [route for route in app.router.routes if not (getattr(route, 'path', '').startswith('/api/diagnostics/') and getattr(route, 'path', '') != '/api/diagnostics')]
    install_health_history_routes(app, book, monitor)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        assert (await client.get('/api/diagnostics/history')).status_code == 401
        client.headers.update({'Authorization':'Bearer instance-key','X-Wearing-Tenant':'wrong'})
        assert (await client.get('/api/diagnostics/history')).status_code == 403
        client.headers['X-Wearing-Tenant'] = 'tenant_qa'
        assert (await client.get('/api/diagnostics/history')).status_code == 401
        client.headers['X-Pajio-Storage-Scope'] = A
        initial = await client.get('/api/diagnostics/history')
        assert initial.status_code == 200 and initial.json()['samples'] == []
        assert initial.headers['Cache-Control'] == 'no-store'
        assert (await client.post('/api/diagnostics/sample')).status_code == 403
        csrf = (await client.get('/api/bootstrap')).json()['token']
        client.headers['X-Wearing-Token'] = csrf
        assert (await client.post('/api/diagnostics/sample')).json()['sampled'] is True
        request = {'request_key':'request-key-00001','category':'devices'}
        bad = await client.post('/api/diagnostics/exports', json={**request,'error':SECRET})
        assert bad.status_code == 422
        exported = await client.post('/api/diagnostics/exports', json=request)
        assert exported.status_code == 201
        metadata = exported.json()
        response = await client.get('/api/diagnostics/exports/'+metadata['id']+'/file')
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == metadata['sha256']
        assert response.json()['transmission'] == 'not_sent'
        client.headers['X-Pajio-Storage-Scope'] = B
        assert (await client.get('/api/diagnostics/exports/'+metadata['id']+'/file')).status_code == 404
        client.headers['X-Wearing-Identity'] = other
        assert (await client.get('/api/diagnostics/history')).json()['samples'] == []
        assert (await client.get('/api/diagnostics/history?identity=daily')).status_code == 409
        client.headers['X-Wearing-Identity'] = 'missing'
        assert (await client.get('/api/diagnostics/history')).status_code == 404
    await app.state.service.hermes.close()


def test_paging_is_stable_while_new_samples_arrive_and_never_crosses_identity(fixture):
    store, book, clock = fixture
    other = store.save_identity('other')['id']
    ids = []
    for index in range(5):
        ids.append(book.record('daily', snapshot(engine='timeout' if index%2 else 'reachable')))
        book.record(other, snapshot(other))
        clock[0] += 300
    first = book.history('daily', sample_limit=2, event_limit=2)
    book.record('daily', snapshot(engine='timeout'))
    second = book.history('daily', sample_limit=2, event_limit=2,
        before_sample=first['next_before_sample'], before_event=first['next_before_event'])
    assert [row['id'] for row in first['samples']] == ids[-2:][::-1]
    assert [row['id'] for row in second['samples']] == ids[-4:-2][::-1]
    assert second['coverage']['latest_observed_at'] == at(clock[0])
    assert not {row['id'] for row in first['events']} & {row['id'] for row in second['events']}
    assert not book.history(other)['events']
    for invalid in (True, -1, 2**64, SECRET):
        with pytest.raises(HealthError, match='invalid_cursor'):
            book.history('daily', before_sample=invalid)


def test_large_export_is_capped_and_records_truncation_and_immutable_checksum(fixture):
    store, book, clock = fixture
    from wearing.health_history import MAX_EXPORT_BYTES
    value = snapshot()
    value['tasks']['items'] = [task(store) for _ in range(30)]
    for row in value['tasks']['items']:
        row['run_id'] = 'run_'+row['task_id']; row['attempt'] = 100000
    for _ in range(288):
        book.record('daily', value)
        clock[0] += 300
    metadata = book.create_export('daily', None, 'request-key-large', 'performance')
    raw, read = book.download('daily', None, metadata['id'])
    assert len(raw) <= MAX_EXPORT_BYTES and read['sha256'] == hashlib.sha256(raw).hexdigest()
    exported = json.loads(raw)
    assert exported['contents']['samples_truncated'] is True
    assert 0 < len(exported['contents']['samples']) < 288
    assert exported['contents']['next_before_sample'] == exported['contents']['samples'][-1]['id']


async def test_real_hermes_probe_only_reads_capabilities_and_never_mutates_task_rows(fixture, tmp_path):
    from wearing.config import Settings
    from wearing.hermes import HermesClient
    store, book, _ = fixture
    task(store, phase='running')
    def original():
        with store.connection() as db:
            return [tuple(row) for row in db.execute('SELECT * FROM tasks')], [tuple(row) for row in db.execute('SELECT * FROM events')]
    before = original(); calls = []
    async def transport(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={'features': {'secret': SECRET}, 'message': SECRET})
    client = HermesClient(Settings(tmp_path, 'https://synthetic.invalid', 'synthetic-key'), transport=httpx.MockTransport(transport))
    diagnostics = Diagnostics(store, lambda identity: SimpleNamespace(status=lambda: {'running':True}), probe_for=lambda identity:client.probe())
    try:
        await HealthMonitor(book, diagnostics).collect('daily')
    finally:
        await client.close()
    assert calls == [('GET', '/v1/capabilities')] and original() == before
    assert 'PRIVATE' not in json.dumps(book.history('daily'))
