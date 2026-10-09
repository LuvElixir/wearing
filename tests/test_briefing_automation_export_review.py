"""Independent portability checks using temporary owner-bound automation fixtures."""
import io
import json
import zipfile

from wearing.identity_export import IdentityExports
from test_briefing_automation import system, config, schedule_id, A, B


def test_daily_automation_export_is_owner_filtered_and_excludes_internal_columns(system):
    store, schedules, _, auto, clock = system
    auto.save('daily', A, config())
    auto.save('daily', B, config(local_time='08:01'))
    other = store.save_identity('Other')['id']
    auto.save(other, A, config())
    clock[0] = '2026-10-08T00:02:00+00:00'
    with store.connection() as db:
        schedules_to_claim = [row[0] for row in db.execute('SELECT schedule_id FROM briefing_automations')]
    for sid in schedules_to_claim:
        assert schedules.claim(sid)
    with store.connection() as db:
        db.execute("ALTER TABLE briefing_automations ADD COLUMN secret TEXT DEFAULT 'NEVER-EXPORT-EXTRA'")
        db.execute("ALTER TABLE briefing_automation_days ADD COLUMN secret TEXT DEFAULT 'NEVER-EXPORT-EXTRA'")
    exports = IdentityExports(store)
    for actor, minute in [(A, '08:00'), (B, '08:01')]:
        receipt = exports.create('daily', 'automation-export-review-001', owner_scope=actor)
        raw, _ = exports.download('daily', receipt['id'], owner_scope=actor)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            data = json.loads(archive.read('records.json'))
        settings = data['briefing_automations']; days = data['briefing_automation_days']
        assert len(settings) == len(days) == 1
        assert settings[0]['local_time'] == minute
        assert isinstance(settings[0]['preferences'], dict)
        assert settings[0]['schedule_id'] == schedule_id(auto, actor)
        assert days[0]['task_id'] in {task['id'] for task in data['tasks']}
        assert set(settings[0]) == {'revision', 'enabled', 'local_time', 'timezone', 'grace_minutes',
                                  'preferences', 'schedule_id', 'schedule_revision', 'updated_at'}
        assert set(days[0]) == {'local_date', 'timezone', 'revision', 'due_at', 'state',
                              'briefing_id', 'task_id', 'created_at'}
        serialized = json.dumps(data)
        assert 'NEVER-EXPORT-EXTRA' not in serialized
        assert 'briefing_automation_requests' not in data and 'owner_scope' not in serialized


def test_automation_export_enforces_derived_task_and_schedule_visibility(system):
    store, schedules, _, auto, clock = system
    auto.save('daily', A, config()); clock[0] = '2026-10-08T00:02:00+00:00'
    sid = schedule_id(auto); task = schedules.claim(sid)
    # A corrupt/mismatched source reference must not bypass the shared predicate.
    with store.connection() as db:
        db.execute('UPDATE task_principals SET owner_scope=? WHERE task_id=?', (B, task['id']))
        db.execute('UPDATE background_principals SET owner_scope=? WHERE source_id=?', (B, sid))
    data, _, _ = IdentityExports(store)._snapshot('daily', owner_scope=A)
    assert data['briefing_automations'] == data['briefing_automation_days'] == []


def test_hidden_automation_preferences_do_not_consume_export_budget(system, monkeypatch):
    store, _, _, auto, _ = system
    auto.save('daily', A, config()); auto.save('daily', B, config())
    with store.connection() as db:
        db.execute('UPDATE briefing_automations SET preferences=? WHERE owner_scope=?',
                   (json.dumps({'hidden': 'b' * 20000}), B))
    monkeypatch.setattr('wearing.identity_export.MAX_DATA_BYTES', 10000)
    data, _, _ = IdentityExports(store)._snapshot('daily', owner_scope=A)
    assert len(data['briefing_automations']) == 1
