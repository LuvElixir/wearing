"""Synthetic record times and a mock push transport only; no real notifications."""
import asyncio
import json
from datetime import datetime, timezone
import httpx
import pytest
from wearing.store import Store
from wearing.life import LifeBook, LifeDraft
from wearing.calendar_series import CalendarSeriesBook
from wearing.notifications import NotificationConfig, NotificationService, NotificationError
from wearing.record_reminders import ReminderError, WINDOW

PROJECT = '12345678-abcd-1234-abcd-123456789abc'
INSTALL = 'reminder-fixture-001'
OWNER = 'a' * 64
OTHER = 'b' * 64


class Clock:
    value = datetime(2026, 10, 8, 4, tzinfo=timezone.utc).timestamp()
    def __call__(self): return self.value
    def iso(self, seconds=0): return datetime.fromtimestamp(self.value + seconds, timezone.utc).isoformat()


@pytest.fixture
async def env(tmp_path):
    clock, calls = Clock(), []
    def send(request):
        calls.append(request)
        return httpx.Response(200, json={'data': {'status': 'ok', 'id': 'fixture-ticket'}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    store = Store(tmp_path / 'synthetic.sqlite3')
    life = LifeBook(store)
    service = NotificationService(store, config=NotificationConfig(True, PROJECT), client=client, clock=clock)
    yield service, life, clock, calls
    await client.aclose()


def register(service, scope=OWNER, installation=INSTALL):
    service.register('daily', installation, 'ExpoPushToken[reminderFixtureToken]', PROJECT, 'ios', service.clock() + 8 * 3600, owner_scope=scope)
    service.update_preferences('daily', installation, 0, False, 1320, 480, 'Asia/Shanghai', owner_scope=scope)


def make(life, clock, kind='task'):
    return life.create('daily', LifeDraft(kind=kind, title='PRIVATE reminder source', **({'due_at': clock.iso(3600)} if kind == 'task' else {'start_at': clock.iso(3600), 'end_at': clock.iso(7200)})), 'new-' + kind)


def save(service, record, **overrides):
    args = dict(revision=0, record_revision=record['revision'], enabled=True, advance_minutes=15, request_key='fixture-request-0001')
    args.update(overrides)
    scope = args.pop('owner_scope', OWNER)
    return service.reminders.save('daily', record['id'], **args, owner_scope=scope)


def outbox(service):
    with service.store.connection() as db: return [dict(row) for row in db.execute('SELECT * FROM notification_outbox')]


@pytest.mark.parametrize('kind', ['task', 'event'])
async def test_exact_owner_due_receipt_and_restart_deduplication(env, kind):
    service, life, clock, calls = env
    register(service); register(service, OTHER, 'other-owner-fixture')
    record = make(life, clock, kind)
    settings = save(service, record)
    await service.tick(); assert calls == []
    clock.value += 2700
    await asyncio.gather(service.tick(), service.tick())
    restarted = NotificationService(service.store, config=service.config, client=service.client, clock=clock)
    await restarted.tick()
    assert len(calls) == 1 and outbox(service)[0]['owner_scope'] == OWNER
    payload = json.loads(calls[0].content)
    assert payload['data']['type'] == 'pajio.record' and payload['data']['record_id'] == record['id']
    assert 'PRIVATE' not in json.dumps(payload) and 'owner_scope' not in payload['data']
    key = payload['data']['event_key']
    resolved = service.resolve('daily', key, owner_scope=OWNER)
    assert resolved['record_id'] == record['id'] and resolved['series_id'] is None
    with pytest.raises(NotificationError) as error: service.resolve('daily', key, owner_scope=OTHER)
    assert error.value.status == 404
    assert save(service, record) == settings  # Lost settings reply is historical, not a fresh alarm.
    assert service.reminders.get('daily', record['id'], owner_scope=OTHER)['enabled'] is False


async def test_no_time_all_day_past_and_foreign_identity_fail_closed(env):
    service, life, clock, _ = env
    untimed = life.create('daily', LifeDraft(kind='task', title='No due'), 'untimed')
    all_day = life.create('daily', LifeDraft(kind='event', title='All day', all_day=True, start_at='2026-10-09', end_at='2026-10-10'), 'all-day')
    for record in [untimed, all_day]:
        assert service.reminders.get('daily', record['id'], owner_scope=OWNER)['status'] == 'unavailable'
        with pytest.raises(ReminderError): save(service, record)
    record = make(life, clock)
    with pytest.raises(ReminderError): save(service, record, advance_minutes=1440)
    other = service.store.save_identity('Other')['id']
    with pytest.raises(ReminderError): service.reminders.get(other, record['id'], owner_scope=OWNER)
    with pytest.raises(ReminderError): save(service, record, owner_scope='injected')


async def test_time_edit_cancels_old_alarm_and_reschedules_current_anchor(env):
    service, life, clock, calls = env
    register(service); record = make(life, clock); save(service, record)
    clock.value += 2700; service.collect()
    old_key = outbox(service)[0]['event_key']
    changed = life.update('daily', record['id'], 1, patch={'due_at': clock.iso(5400)})
    assert not service._claim()  # Check current source even before next collect.
    await service.tick()
    state = service.reminders.get('daily', record['id'], owner_scope=OWNER)
    assert state['revision'] == 2 and state['record_revision'] == changed['revision'] and state['enabled']
    assert calls == [] and outbox(service)[0]['state'] == 'cancelled'
    clock.value += 4500; await service.tick()
    assert len(calls) == 1 and json.loads(calls[0].content)['data']['event_key'] != old_key


@pytest.mark.parametrize('change', ['archive', 'complete'])
async def test_delete_or_complete_between_claim_and_handoff_never_sends(env, change):
    service, life, clock, calls = env
    register(service); record = make(life, clock); save(service, record)
    clock.value += 2700; service.collect(); claimed = service._claim(); assert claimed
    life.update('daily', record['id'], 1, action='archive' if change == 'archive' else 'edit', patch={} if change == 'archive' else {'completed': True})
    assert not service._delivery_authorized(claimed)
    await service.tick(); assert not calls
    state = service.reminders.get('daily', record['id'], owner_scope=OWNER)
    assert not state['enabled'] and state['reason'] in {'removed', 'completed'}
    life.update('daily', record['id'], 2, action='restore' if change == 'archive' else 'edit', patch={} if change == 'archive' else {'completed': False})
    await service.tick(); assert not calls and not service.reminders.get('daily', record['id'], owner_scope=OWNER)['enabled']


async def test_quiet_expired_registration_is_recovered_once_or_expires_without_stale_alert(env):
    service, life, clock, calls = env
    register(service); record = make(life, clock); save(service, record)
    with service.store.connection() as db: db.execute('UPDATE notification_devices SET expires_at=?', (clock.value + 1000,))
    clock.value += 2700; await service.tick()
    assert outbox(service)[0]['state'] == 'awaiting_registration' and not calls
    service.register('daily', INSTALL, 'ExpoPushToken[reminderFixtureToken]', PROJECT, 'ios', clock() + 10000, owner_scope=OWNER)
    await service.tick(); assert len(calls) == 1
    clock.value += WINDOW + 3600
    await service.tick(); assert len(calls) == 2  # Existing ticket receipt check only, no second send.
    assert sum('push/send' in str(call.url) for call in calls) == 1


async def test_unknown_send_and_optout_never_replay(env):
    service, life, clock, calls = env
    register(service); record = make(life, clock); save(service, record)
    old = service.client
    def timeout(request): calls.append(request); raise httpx.ReadTimeout('synthetic')
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    clock.value += 2700; await service.tick(); assert outbox(service)[0]['state'] == 'unknown'
    service.disable('daily', INSTALL, owner_scope=OWNER)
    service.register('daily', INSTALL, 'ExpoPushToken[reminderFixtureToken]', PROJECT, 'ios', clock() + 10000, owner_scope=OWNER)
    await service.tick(); assert len(calls) == 1
    await service.client.aclose(); service.client = old


async def test_series_override_uses_same_occurrence_real_time_and_cancel_invalidates(env):
    service, _, clock, calls = env
    register(service); book = CalendarSeriesBook(service.store)
    draft = {'template': {'title': 'PRIVATE series', 'content': '', 'timezone': 'UTC', 'all_day': False, 'start_local': '2026-10-08T05:00', 'end_local': '2026-10-08T06:00'}, 'rule': {'frequency': 'daily', 'interval': 1, 'weekdays': [], 'count': 5, 'until': None}}
    series = book.mutate('daily', 'series-initial', 'create', draft=draft)
    selected = book.get('daily', series['id'], '2026-10-08')['selected']; save(service, selected)
    clock.value += 2700; service.collect()
    template = {**draft['template'], 'start_local': '2026-10-08T07:00', 'end_local': '2026-10-08T08:00'}
    book.mutate('daily', 'move-this-one', 'override', series_id=series['id'], revision=1, occurrence_key='2026-10-08', template=template)
    await service.tick(); assert not calls and outbox(service)[0]['state'] == 'cancelled'
    state = service.reminders.get('daily', selected['id'], owner_scope=OWNER)
    assert state['anchor_at'] == '2026-10-08T07:00:00+00:00' and state['record_revision'] == 2
    book.mutate('daily', 'cancel-this-one', 'cancel', series_id=series['id'], revision=2, occurrence_key='2026-10-08')
    await service.tick(); assert not calls
    assert service.reminders.get('daily', selected['id'], owner_scope=OWNER)['status'] == 'unavailable'


async def test_settings_cas_frozen_key_and_atomic_receipt(env):
    service, life, clock, _ = env; record = make(life, clock)
    result = save(service, record)
    with pytest.raises(ReminderError): save(service, record, enabled=False)
    with pytest.raises(ReminderError): save(service, record, request_key='another-request-001')
    with service.store.connection() as db: db.execute("CREATE TRIGGER reject_reminder BEFORE INSERT ON record_reminder_requests BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(Exception): save(service, record, revision=1, enabled=False, request_key='disable-request-001')
    current = service.reminders.get('daily', record['id'], owner_scope=OWNER)
    assert current['revision'] == result['revision'] and current['enabled']


async def test_http_owner_only_from_trusted_scope_and_strict_fields(env):
    from fastapi import FastAPI, Request
    from wearing.record_reminders_api import install_record_reminder_routes
    service, life, clock, _ = env; record = make(life, clock)
    app = FastAPI()
    @app.middleware('http')
    async def identity(request: Request, call_next):
        request.state.identity_id = 'daily'
        if request.headers.get('fixture-trusted') == 'yes': request.scope['pajio.storage_scope'] = OWNER
        return await call_next(request)
    install_record_reminder_routes(app, service.reminders, local_devices=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
        path = '/api/record-reminders/' + record['id']
        assert (await client.get(path, headers={'x-pajio-storage-scope': OWNER})).status_code == 401
        payload = {'revision': 0, 'record_revision': 1, 'enabled': True, 'advance_minutes': 15, 'request_key': 'http-reminder-fixture'}
        assert (await client.post(path, headers={'fixture-trusted': 'yes'}, json={**payload, 'owner_scope': OTHER})).status_code == 422
        first = await client.post(path, headers={'fixture-trusted': 'yes'}, json=payload)
        assert first.status_code == 200
        assert (await client.post(path, headers={'fixture-trusted': 'yes'}, json=payload)).json() == first.json()


async def test_quiet_hours_expire_old_reminders_and_late_handoff_bounds_provider_ttl(env):
    service, life, clock, calls = env
    register(service); record = make(life, clock); save(service, record)
    # Noon in Shanghai; a quiet window through 15:00 is beyond the 13:00 + 1h deadline.
    service.update_preferences('daily', INSTALL, 1, True, 11 * 60, 15 * 60, 'Asia/Shanghai', owner_scope=OWNER)
    clock.value += 2700; await service.tick(); assert not calls and outbox(service)[0]['error_code'] == 'QuietHours'
    clock.value += 3 * 3600; await service.tick(); assert not calls and outbox(service)[0]['state'] == 'cancelled'
    # A different future record is handed off near its expiry, with only remaining TTL.
    service.update_preferences('daily', INSTALL, 2, False, 11 * 60, 15 * 60, 'Asia/Shanghai', owner_scope=OWNER)
    other = life.create('daily', LifeDraft(kind='task', title='Late fixture', due_at=clock.iso(3600)), 'late-task')
    save(service, other, request_key='late-reminder-request')
    clock.value += 3600 + WINDOW - 10; await service.tick()
    assert len(calls) == 1 and json.loads(calls[0].content)['ttl'] == 10


async def test_due_time_out_and_back_invalidates_claim_but_text_only_does_not_repeat(env):
    service, life, clock, calls = env
    register(service); record = make(life, clock); save(service, record)
    clock.value += 2700; service.collect(); old = service._claim(); assert old
    life.update('daily', record['id'], 1, patch={'due_at': clock.iso(7200)})
    life.update('daily', record['id'], 2, patch={'due_at': record['due_at']})
    assert not service._delivery_authorized(old)
    await service.tick(); assert len(calls) == 1
    life.update('daily', record['id'], 3, patch={'title': 'Changed title'})
    await service.tick(); assert len(calls) == 1


async def test_source_transaction_rolls_back_reminder_invalidation_with_record(env):
    service, life, clock, calls = env
    register(service); record = make(life, clock); save(service, record)
    clock.value += 2700; service.collect(); old = service._claim(); assert old
    with service.store.connection() as db:
        db.execute("CREATE TRIGGER reject_life_receipt BEFORE INSERT ON life_mutation_requests BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    with pytest.raises(Exception): life.update('daily', record['id'], 1, action='archive', request_key='rollback-original-key')
    assert service.reminders.get('daily', record['id'], owner_scope=OWNER)['enabled']
    assert service._delivery_authorized(old)


async def test_absolute_times_preserve_offsets_without_server_timezone_guessing(env):
    service, life, clock, _ = env
    first = life.create('daily', LifeDraft(kind='event', title='DST first', start_at='2026-11-01T01:30:00-04:00', end_at='2026-11-01T02:30:00-04:00', timezone='America/New_York'), 'first-dst')
    second = life.create('daily', LifeDraft(kind='event', title='DST second', start_at='2026-11-01T01:30:00-05:00', end_at='2026-11-01T02:30:00-05:00', timezone='America/New_York'), 'second-dst')
    a = save(service, first, request_key='dst-first-reminder')
    b = save(service, second, request_key='dst-second-reminder')
    assert datetime.fromisoformat(b['fire_at']).timestamp() - datetime.fromisoformat(a['fire_at']).timestamp() == 3600
