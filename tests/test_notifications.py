"""No real notifications: isolated SQLite Stores and a mock Expo transport."""
import asyncio
import json
import httpx
import pytest
from wearing.store import Store
from wearing.notifications import NotificationConfig, NotificationService, NotificationError, SEND_URL
from wearing.notifications_api import install_notification_routes
from wearing.app import create_app
from wearing.config import Settings

PROJECT = '12345678-abcd-1234-abcd-123456789abc'
INSTALL = 'synthetic-phone-001'
TOKEN = 'ExpoPushToken[syntheticToken12345]'
TOKEN2 = 'ExpoPushToken[syntheticToken67890]'
CONFIG = NotificationConfig(True, PROJECT)

class Clock:
    value = 100000.0
    def __call__(self): return self.value

@pytest.fixture
async def setup(tmp_path):
    clock, calls = Clock(), []
    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={'data': {'status': 'ok', 'id': 'ticket-1'}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    store = Store(tmp_path / 'test.db')
    service = NotificationService(store, config=CONFIG, client=client, clock=clock)
    yield service, store, calls, clock
    await client.aclose()

def result(store, text='PRIVATE salary document'):
    task = store.create(text, 'hermes')
    store.update(task['id'], status='completed_unverified', output='PRIVATE personal details')
    return task

def rows(service):
    with service.store.connection() as db:
        return [dict(r) for r in db.execute('SELECT * FROM notification_outbox')]

def register(service, token=TOKEN):
    return service.register('daily', INSTALL, token, PROJECT, 'ios')

async def test_baseline_does_not_push_historical_results(setup):
    service, store, calls, _ = setup
    result(store)
    register(service)
    await service.tick()
    assert calls == []
    assert rows(service) == []

async def test_poll_restart_and_concurrent_workers_deduplicate(setup):
    service, store, calls, _ = setup
    register(service)
    result(store)
    await asyncio.gather(service.tick(), service.tick())
    restarted = NotificationService(store, config=CONFIG, client=service.client, clock=service.clock)
    await restarted.tick()
    assert len(calls) == 1
    assert rows(service)[0]['state'] == 'ticket'
    assert restarted.server_id == service.server_id

async def test_payload_is_metadata_only_and_resolves_exact_identity_task(setup):
    service, store, calls, _ = setup
    register(service)
    task = result(store)
    await service.tick()
    payload = json.loads(calls[0].content)
    assert 'PRIVATE' not in json.dumps(payload)
    assert 'url' not in payload['data']
    assert payload['data']['task_id'] == task['id']
    assert payload['data']['identity_id'] == 'daily'
    assert service.resolve('daily', payload['data']['event_key'])['task_id'] == task['id']
    work = store.save_identity('Work')['id']
    with pytest.raises(NotificationError) as error: service.resolve(work, payload['data']['event_key'])
    assert error.value.status == 404

async def test_provider_receipt_is_distinct_from_ticket_and_device_delivery(setup):
    service, store, calls, clock = setup
    register(service); result(store)
    await service.tick()
    assert service.status('daily', INSTALL)['provider_status'] == 'ticket'
    clock.value += 900
    async def transport(request):
        return httpx.Response(200, json={'data': {'ticket-1': {'status': 'ok'}}})
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    await service.receipts()
    assert service.status('daily', INSTALL)['provider_status'] == 'provider_accepted'
    await service.client.aclose()

@pytest.mark.parametrize('stage', ['ticket', 'receipt'])
async def test_invalid_token_is_revoked(stage, setup):
    service, store, _, clock = setup
    register(service); result(store)
    if stage == 'receipt':
        await service.tick(); clock.value += 900
    async def transport(request):
        value = {'status': 'error', 'details': {'error': 'DeviceNotRegistered'}}
        return httpx.Response(200, json={'data': {'ticket-1': value} if stage == 'receipt' else value})
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    await (service.receipts() if stage == 'receipt' else service.tick())
    status = service.status('daily', INSTALL)
    assert status['enabled'] is False and status['reason'] == 'DeviceNotRegistered'
    await service.client.aclose()

async def test_old_receipt_does_not_revoke_rotated_token(setup):
    service, store, _, clock = setup
    register(service); result(store); await service.tick()
    register(service, TOKEN2); clock.value += 900
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'data': {'ticket-1': {'status': 'error', 'details': {'error': 'DeviceNotRegistered'}}}})))
    await service.receipts()
    assert service.status('daily', INSTALL)['enabled'] is True
    await service.client.aclose()

async def test_disable_cancels_pending_and_no_reenable_backfill(setup):
    service, store, calls, _ = setup
    register(service); result(store); service.collect()
    service.disable('daily', INSTALL)
    assert rows(service)[0]['state'] == 'cancelled'
    register(service); await service.tick()
    assert calls == []

@pytest.mark.parametrize('mode', ['timeout', 'malformed', 'server_error'])
async def test_uncertain_send_is_not_replayed(mode, setup):
    service, store, _, clock = setup
    count = []
    def transport(request):
        count.append(request)
        if mode == 'timeout': raise httpx.ReadTimeout('private upstream error')
        return httpx.Response(500 if mode == 'server_error' else 200, json={'data': []})
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    register(service); result(store); await service.tick()
    clock.value += 1000; await service.tick()
    assert len(count) == 1 and rows(service)[0]['state'] == 'unknown'
    assert 'private' not in json.dumps(service.status('daily', INSTALL))
    await service.client.aclose()

async def test_interrupted_claim_not_replayed_after_restart(setup):
    service, store, calls, clock = setup
    register(service); result(store); service.collect(); service._claim()
    clock.value += 121
    await service.tick()
    assert calls == [] and rows(service)[0]['error_code'] == 'InterruptedSend'

async def test_rate_limit_backoff_then_ticket(setup):
    service, store, _, clock = setup
    count = []
    def transport(request):
        count.append(request)
        return httpx.Response(429 if len(count) == 1 else 200, json={'data': {'status': 'ok', 'id': 'ticket'}})
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    register(service); result(store); await service.tick(); await service.tick()
    assert len(count) == 1 and rows(service)[0]['state'] == 'pending'
    clock.value += 60; await service.tick()
    assert len(count) == 2 and rows(service)[0]['state'] == 'ticket'
    await service.client.aclose()

async def test_unconfigured_never_sends_or_registers(setup):
    service, store, calls, _ = setup
    service.config = NotificationConfig()
    with pytest.raises(NotificationError) as error: register(service)
    assert error.value.status == 409
    result(store); await service.tick()
    assert calls == [] and service.status('daily', INSTALL)['configured'] is False

async def test_stale_approval_is_cancelled_before_send(setup):
    service, store, calls, _ = setup
    register(service)
    task = store.create('private action', 'hermes')
    store.update(task['id'], status='waiting_for_approval', approval={'request_id': 'request-1', 'kind': 'shell', 'command': 'echo hi'})
    # Real ActivityBook only creates actionable cards from a recognized approval;
    # use a result transition here too to validate the same version fence.
    store.update(task['id'], status='completed_unverified', output='one')
    service.collect()
    store.update(task['id'], status='verified', verification_note='reviewed')
    await service.tick()
    assert calls == [] and rows(service)[0]['state'] == 'cancelled'

async def test_no_notifications_for_user_verified_or_archived_status_changes(setup):
    service, store, calls, clock = setup
    register(service); task = result(store); await service.tick()
    store.update(task['id'], status='verified'); await service.tick()
    store.update(task['id'], status='closed_by_user'); await service.tick()
    assert len(calls) == 1

async def test_notification_routes_use_real_auth_csrf_and_identity_boundary(tmp_path):
    app = create_app(Settings(tmp_path))
    service = NotificationService(app.state.store, config=CONFIG)
    # The root agent may integrate these routes concurrently. Keep fixture local.
    app.router.routes = [r for r in app.router.routes if not getattr(r, 'path', '').startswith('/api/notifications/')]
    install_notification_routes(app, service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        body = {'installation_id': INSTALL, 'expo_push_token': TOKEN, 'project_id': PROJECT, 'platform': 'ios'}
        assert (await client.post('/api/notifications/register', json=body)).status_code == 403
        bootstrap = (await client.get('/api/bootstrap')).json()
        headers = {'X-Wearing-Token': bootstrap['token'], 'X-Wearing-Identity': 'daily'}
        r = await client.post('/api/notifications/register', json=body, headers=headers)
        assert r.status_code == 200 and r.json()['enabled'] is True
        assert TOKEN not in r.text
        assert (await client.post('/api/notifications/register', json={**body, 'identity_id': 'other'}, headers=headers)).status_code == 422
        assert (await client.post('/api/notifications/disable', json={'installation_id': INSTALL}, headers={**headers, 'Origin': 'https://evil.invalid'})).status_code == 403
        work = app.state.store.save_identity('Work')['id']
        r = await client.get('/api/notifications/status', params={'installation_id': INSTALL}, headers={**headers, 'X-Wearing-Identity': work})
        assert r.status_code == 200 and r.json()['enabled'] is False
    await service.close(); await app.state.service.hermes.close()

async def test_real_confirmation_card_emits_one_approval_event_per_request(setup):
    from wearing.confirmations import ConfirmationBook, MARKER
    service, store, calls, _ = setup
    register(service)
    task = store.create('synthetic action', 'hermes')
    task = store.update(task['id'], status='waiting_for_approval', run_id='test-run')
    book = ConfirmationBook(store)
    approval = {'request_id': 'request-1', 'command': MARKER + json.dumps({'title': '确认测试动作', 'action': '保存隔离测试资料', 'impact': '只修改测试资料'})}
    store.update(task['id'], approval=book.observe(task, approval))
    await service.tick(); await service.tick()
    assert len(calls) == 1
    assert '需要你确认' in json.loads(calls[0].content)['body']
    # New explicit approval request, even in the same task, gets a fresh event.
    approval['request_id'] = 'request-2'
    store.update(task['id'], approval=book.observe(store.get(task['id']), approval))
    await service.tick()
    assert len(calls) == 2
    assert len({r['event_key'] for r in rows(service)}) == 2

async def test_logout_disables_only_this_installation_across_tenant_identities(setup):
    service, store, _, _ = setup
    work = store.save_identity('Work')['id']
    register(service)
    service.register(work, INSTALL, TOKEN, PROJECT, 'ios')
    other = INSTALL + 'other'
    service.register(work, other, TOKEN2, PROJECT, 'ios')
    service.disable_installation('daily', INSTALL)
    assert not service.status('daily', INSTALL)['enabled']
    assert not service.status(work, INSTALL)['enabled']
    assert service.status(work, other)['enabled']

async def test_tenant_middleware_protects_notification_registration(tmp_path):
    from wearing.cloud.worker import TenantBoundary
    app = create_app(Settings(tmp_path))
    app.add_middleware(TenantBoundary, tenant_id='tenant_test', gateway_key='instance-key')
    service = NotificationService(app.state.store, config=CONFIG)
    app.router.routes = [r for r in app.router.routes if not getattr(r, 'path', '').startswith('/api/notifications/')]
    install_notification_routes(app, service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        body = {'installation_id': INSTALL, 'expo_push_token': TOKEN, 'project_id': PROJECT, 'platform': 'ios'}
        assert (await client.post('/api/notifications/register', json=body)).status_code == 401
        client.headers['Authorization'] = 'Bearer instance-key'
        client.headers['X-Wearing-Tenant'] = 'wrong'
        assert (await client.post('/api/notifications/register', json=body)).status_code == 403
        client.headers['X-Wearing-Tenant'] = 'tenant_test'
        csrf = (await client.get('/api/bootstrap')).json()['token']
        assert (await client.post('/api/notifications/register', json=body)).status_code == 403
        client.headers['X-Wearing-Token'] = csrf
        # The trusted gateway supplies this from its validated session; cloud
        # registrations without a finite session lease must fail closed.
        assert (await client.post('/api/notifications/register', json=body)).status_code == 401
        import time
        client.headers['X-Pajio-Session-Expires'] = str(time.time() + 3600)
        # Lease alone is insufficient: the gateway also binds the validated
        # account and tenant to a trusted owner scope.
        assert (await client.post('/api/notifications/register', json=body)).status_code == 401
        client.headers['X-Pajio-Storage-Scope'] = 'a' * 64
        assert (await client.post('/api/notifications/register', json=body)).status_code == 200
    await service.close(); await app.state.service.hermes.close()

async def test_session_expiry_holds_work_before_pending_send(setup):
    service, store, calls, clock = setup
    service.register('daily', INSTALL, TOKEN, PROJECT, 'ios', clock.value + 30)
    result(store); service.collect()
    clock.value += 31
    await service.tick()
    assert calls == []
    state = service.status('daily', INSTALL)
    assert state['enabled'] is False and state['reason'] == 'expired'
    assert rows(service)[0]['state'] == 'awaiting_registration'
    assert rows(service)[0]['error_code'] == 'RegistrationExpired'

async def test_registration_cannot_outlive_trusted_session_or_local_seven_day_lease(setup):
    service, _, _, clock = setup
    expiry = clock.value + 100
    assert service.register('daily', INSTALL, TOKEN, PROJECT, 'ios', expiry)['expires_at'] == expiry
    assert register(service)['expires_at'] == clock.value + 7 * 86400
    assert service.register('daily', INSTALL, TOKEN, PROJECT, 'ios', clock.value + 90 * 86400)['expires_at'] == clock.value + 7 * 86400
    with pytest.raises(NotificationError) as error:
        service.register('daily', INSTALL, TOKEN, PROJECT, 'ios', clock.value - 1)
    assert error.value.status == 401
