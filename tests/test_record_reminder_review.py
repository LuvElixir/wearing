"""Independent adversarial reminder lifecycle regressions; synthetic fixtures only."""
from datetime import datetime, timezone
import pytest
from test_record_reminders import env, register, make, save, OWNER


@pytest.mark.parametrize('change', ['complete', 'archive'])
async def test_transient_source_retirement_between_observations_stays_disabled(env, change):
    service, life, clock, calls = env
    register(service)
    record = make(life, clock)
    save(service, record)
    clock.value += 2700
    service.collect()
    claimed = service._claim()
    assert claimed
    # No reminder collector/get occurs between these two legitimate writes.
    life.update('daily', record['id'], 1, action='archive' if change == 'archive' else 'edit',
                patch={} if change == 'archive' else {'completed': True})
    life.update('daily', record['id'], 2, action='restore' if change == 'archive' else 'edit',
                patch={} if change == 'archive' else {'completed': False})
    assert not service._delivery_authorized(claimed)
    await service.tick()
    assert not calls
    assert not service.reminders.get('daily', record['id'], owner_scope=OWNER)['enabled']


async def test_series_cancel_then_reset_between_observations_does_not_reenable(env):
    from wearing.calendar_series import CalendarSeriesBook
    service, _, clock, calls = env
    register(service)
    book = CalendarSeriesBook(service.store)
    draft = {'template': {'title': 'synthetic series', 'content': '', 'timezone': 'UTC', 'all_day': False,
                         'start_local': '2026-10-08T05:00', 'end_local': '2026-10-08T06:00'},
             'rule': {'frequency': 'daily', 'interval': 1, 'weekdays': [], 'count': 5, 'until': None}}
    series = book.mutate('daily', 'create-fixture', 'create', draft=draft)
    selected = book.get('daily', series['id'], '2026-10-08')['selected']
    save(service, selected)
    clock.value += 2700; service.collect(); claimed = service._claim()
    assert claimed
    book.mutate('daily', 'cancel-fixture', 'cancel', series_id=series['id'], revision=1, occurrence_key='2026-10-08')
    book.mutate('daily', 'reset-fixture', 'reset', series_id=series['id'], revision=2, occurrence_key='2026-10-08')
    assert not service._delivery_authorized(claimed)
    await service.tick()
    assert not calls
    assert not service.reminders.get('daily', selected['id'], owner_scope=OWNER)['enabled']


async def test_due_moved_away_and_back_invalidates_old_claim_but_title_change_does_not(env):
    service, life, clock, calls = env
    register(service); record = make(life, clock); save(service, record)
    clock.value += 2700; service.collect(); claimed = service._claim()
    life.update('daily', record['id'], 1, patch={'title': 'renamed fixture'})
    assert service._delivery_authorized(claimed)
    later = datetime.fromtimestamp(clock.value + 7200, timezone.utc).isoformat()
    life.update('daily', record['id'], 2, patch={'due_at': later})
    life.update('daily', record['id'], 3, patch={'due_at': record['due_at']})
    assert not service._delivery_authorized(claimed)
    with service.store.connection() as db:
        current = db.execute('SELECT * FROM record_reminders').fetchone()
        assert current['activation'] == 3 and current['enabled']
        assert db.execute('SELECT state FROM notification_outbox').fetchone()[0] == 'cancelled'


async def test_native_import_complete_then_reopen_also_invalidates_old_claim(env):
    from wearing.native_sync import NativeSyncBook
    service, life, clock, calls = env
    register(service)
    sync = NativeSyncBook(service.store)
    phone = 'e' * 32
    source = {'kind': 'reminder', 'id': 'native-fixture-reminders', 'title': 'fixture'}
    sync.configure('daily', OWNER, phone, 0, True, [source], 'enable-import')
    due = datetime.fromtimestamp(clock.value + 3600, timezone.utc).isoformat()
    def upload(key, completed):
        return sync.upload('daily', OWNER, phone, 1, key, datetime.fromtimestamp(clock.value, timezone.utc).isoformat(),
            [{'source': source, 'complete': True,
              'items': [{'external_id': 'os-fixture-reminder', 'occurrence_id': '',
                         'record': {'kind': 'task', 'title': 'fixture', 'content': '', 'timezone': 'UTC',
                                    'due_at': due, 'completed': completed}}]}])
    first = upload('first-import', False); record = life.get('daily', first['record_ids'][0])
    save(service, record); clock.value += 2700; service.collect(); claimed = service._claim()
    assert claimed
    upload('completed-import', True); clock.value += 1; upload('reopened-import', False)
    assert not service._delivery_authorized(claimed)
    assert not service.reminders.get('daily', record['id'], owner_scope=OWNER)['enabled']


def test_reminder_settings_export_only_current_owner_without_delivery_or_request_journals(env):
    from wearing.identity_export import IdentityExports
    service, life, clock, _ = env
    record = make(life, clock); save(service, record)
    other = 'b' * 64 if OWNER != 'b' * 64 else 'c' * 64
    service.reminders.save('daily', record['id'], 0, 1, True, 30, 'other-owner-config-01', owner_scope=other)
    data, _, _ = IdentityExports(service.store)._snapshot('daily', owner_scope=OWNER)
    assert len(data['record_reminders']) == 1
    assert data['record_reminders'][0]['advance_minutes'] == 15
    assert set(data['record_reminders'][0]) == {'target_id', 'revision', 'enabled', 'advance_minutes', 'anchor_at', 'reason', 'updated_at'}
    assert 'record_reminder_events' not in data and 'record_reminder_requests' not in data
