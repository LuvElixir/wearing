"""Independent clock-boundary regression for owner-bound automatic briefings."""
import pytest
from test_briefing_automation import system, config, schedule_id, A


@pytest.mark.parametrize('before,after,local_time,expected_due,next_due', [
    ('2026-03-08T06:00:00+00:00', '2026-03-08T08:00:00+00:00', '02:30',
     '2026-03-09T06:30:00+00:00', None),
    ('2026-11-01T04:00:00+00:00', '2026-11-01T05:31:00+00:00', '01:30',
     '2026-11-01T05:30:00+00:00', '2026-11-02T06:30:00+00:00'),
])
def test_daily_briefing_dst_gap_skips_and_fold_runs_only_once(system, before, after, local_time, expected_due, next_due):
    store, schedules, _, auto, clock = system
    clock[0] = before
    saved = auto.save('daily', A, config(timezone='America/New_York', local_time=local_time))
    assert saved['next_run'] == expected_due
    clock[0] = after
    task = schedules.claim(schedule_id(auto))
    if next_due is None:
        assert task is None and store.list() == []
        assert auto.get('daily', A)['receipts'] == []
    else:
        assert task
        store.update(task['id'], status='completed_unverified', output='synthetic result')
        schedules.reconcile()
        assert auto.get('daily', A)['next_run'] == next_due
        clock[0] = '2026-11-01T06:31:00+00:00'
        assert schedules.claim(schedule_id(auto)) is None
        assert len(store.list()) == len(auto.get('daily', A)['receipts']) == 1
