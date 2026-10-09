"""App quota admission regression: durable messages/goal/schedule truth, no provider IO."""
from datetime import datetime, timezone
import httpx
import pytest

from wearing.app import create_app
from wearing.config import Settings
from wearing.hermes import HermesClient
from wearing.schedules import ScheduleDraft
from wearing.usage import UsagePolicy
from wearing.store import Store
from test_goals import GoalWire


@pytest.fixture
async def rig(tmp_path, monkeypatch):
    monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '1')
    wire = GoalWire()
    settings = Settings(tmp_path, hermes_key='fixture')
    client = HermesClient(settings, httpx.MockTransport(wire))
    app = create_app(settings, hermes=client, engine_autostart=False, local_devices=False)
    from wearing.cloud.worker import TenantBoundary
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    # An explicitly marked fixture replaces only engine discovery, not quota guard.
    monkeypatch.setattr(app.state.runtime, 'status', lambda: {'url': settings.hermes_url, 'running': True})
    app.state.usage.configure(UsagePolicy(model_calls=0))
    yield app, wire
    await client.close()


async def test_exhausted_http_submit_keeps_original_and_does_not_claim_execution(rig):
    app, wire = rig
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver', headers={'Authorization': 'Bearer fixture-key', 'X-Wearing-Tenant': 'fixture', 'X-Pajio-Storage-Scope': 'a' * 64}) as http:
        token = (await http.get('/api/bootstrap')).json()['token']
        headers = {'X-Wearing-Token': token}
        body = {'content': 'quota fixture message', 'request_id': 'quota-request-0001'}
        first = await http.post('/api/conversation', json=body, headers=headers)
        assert first.status_code == 201
        reply = first.json()
        assert reply['delivery'] == 'saved' and reply['task']['status'] == 'draft'
        assert '额度已用完' in reply['reason']
        duplicate = (await http.post('/api/conversation', json=body, headers=headers)).json()
        assert duplicate['task']['id'] == reply['task']['id']
        assert len((await http.get('/api/conversation')).json()) == 1
        usage = await http.get('/api/usage')
        assert usage.status_code == 200 and usage.json()['resources']['model']['remaining'] == 0
    assert wire.runs == []
    await app.state.goal_coordinator.tick()
    assert wire.runs == []  # An initially saved draft does not gain queue consent.


@pytest.mark.parametrize('reason', ['exhausted', 'concurrency', 'provider'])
async def test_explicit_queue_retains_reason_backoff_then_starts_once(rig, reason, monkeypatch):
    app, wire = rig
    store, service, usage = app.state.store, app.state.service, app.state.usage
    current = store.create('occupy test execution slot', 'computer')
    store.update(current['id'], status='running', run_id='fixture-current')
    reply = await service.submit_message('keep this queued original', 'daily', 'quota-request-0002')
    queued_id = reply['task']['id']
    assert reply['queued']
    store.update(current['id'], status='stopped')
    reservation = None
    if reason == 'concurrency':
        usage.configure(UsagePolicy(model_calls=10, model_concurrency=1))
        reservation = usage.reserve('daily', 'model', 'mock-inflight')
    elif reason == 'provider':
        usage.configure(UsagePolicy(model_calls=10))
        monkeypatch.setattr(app.state.runtime, 'status', lambda: {'url': 'http://127.0.0.1:1234', 'running': True})
    await app.state.goal_coordinator.tick()
    receipt = store.message_receipt(queued_id)
    assert receipt['queued'] and receipt['queue_state'] == 'blocked'
    assert Store(store.path).message_receipt(queued_id) == receipt  # Durable across reopening the service store.
    assert ('额度已用完' if reason == 'exhausted' else '已有调用' if reason == 'concurrency' else '内置引擎') in receipt['blocked_reason']
    with store.connection() as db:
        row = db.execute('SELECT next_retry FROM message_handoffs WHERE task_id=?', (queued_id,)).fetchone()
    assert datetime.fromisoformat(row['next_retry']) > datetime.now(timezone.utc)
    assert store.get(queued_id)['status'] == 'draft' and store.get(queued_id)['run_id'] is None
    await app.state.schedule_coordinator.tick()  # Previous refusal must not escape and abort later work.
    await app.state.goal_coordinator.tick()
    assert wire.runs == []
    assert (await service.submit_message('keep this queued original', 'daily', 'quota-request-0002'))['task']['id'] == queued_id
    if reservation: usage.settle(reservation)
    usage.configure(UsagePolicy(model_calls=10))
    monkeypatch.setattr(app.state.runtime, 'status', lambda: {'url': str(service.hermes.http.base_url).rstrip('/'), 'running': True})
    with store.connection() as db: db.execute('UPDATE message_handoffs SET next_retry=NULL WHERE task_id=?', (queued_id,))
    await app.state.goal_coordinator.tick()
    await app.state.goal_coordinator.tick()
    assert len(wire.runs) == 1
    assert store.message_receipt(queued_id) == {'queued': False, 'queue_state': 'dispatched', 'blocked_reason': None}


async def test_goal_and_schedule_keep_retry_reason_without_duplicate_tasks(rig, monkeypatch):
    app, wire = rig
    store, goals = app.state.store, app.state.goals
    goal = goals.create('daily', 'quota test goal', 'fixture only', 'fixture checked', 3)
    goals.control(goal['id'], goal['revision'], 'resume')
    await app.state.goal_coordinator.tick()
    state = goals.get(goal['id'])
    assert '额度已用完' in state['reason'] and state['next_wake']
    initial_steps = goals.detail(goal['id'])['steps']
    assert len(initial_steps) == 1 and store.get(initial_steps[0]['task_id'])['status'] == 'draft'
    await app.state.goal_coordinator.tick()
    assert len(goals.detail(goal['id'])['steps']) == 1
    # Pause the goal and exercise the separate schedule coordinator path.
    goals.control(goal['id'], state['revision'], 'pause')
    clock = ['2026-10-08T00:00:00+00:00']
    monkeypatch.setattr('wearing.schedules.now', lambda: clock[0])
    schedule = app.state.schedules.create('daily', ScheduleDraft(title='quota schedule', instruction='read fixture only', kind='once', at='2026-10-08T00:01:00+00:00'), 'quota-schedule')
    clock[0] = '2026-10-08T00:02:00+00:00'
    await app.state.schedule_coordinator.tick()
    with store.connection() as db:
        rows = db.execute('SELECT * FROM schedule_occurrences WHERE schedule_id=?', (schedule['id'],)).fetchall()
    assert len(rows) == 1
    assert '额度已用完' in rows[0]['reason'] and rows[0]['retry_at'] > clock[0]
    assert store.get(rows[0]['task_id'])['status'] == 'draft'
    await app.state.schedule_coordinator.tick()
    assert wire.runs == []
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM schedule_occurrences WHERE schedule_id=?', (schedule['id'],)).fetchone()[0] == 1
