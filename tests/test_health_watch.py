import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'deploy/on-prem'))

spec = importlib.util.spec_from_file_location('health_watch', Path(__file__).parents[1] / 'deploy/on-prem/health-watch.py')
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def rows(*items):
    return [{'at': at, 'healthy': healthy} for at, healthy in items]


def test_continuity_needs_actual_elapsed_samples():
    assert watch.uninterrupted_seconds(rows((100, True))) == 0
    assert watch.uninterrupted_seconds(rows((100, True), (220, True), (340, True))) == 240


def test_failure_and_missed_timer_break_continuity():
    assert watch.uninterrupted_seconds(rows((100, True), (220, False), (340, True), (460, True))) == 120
    assert watch.uninterrupted_seconds(rows((100, True), (320, True))) == 0
    assert watch.uninterrupted_seconds(rows((100, True), (220, False))) == 0


def test_backward_clock_cannot_fabricate_elapsed_time():
    assert watch.uninterrupted_seconds(rows((100, True), (220, True), (90, True), (210, True))) == 120


def test_expanding_the_monitored_fleet_starts_a_new_window():
    history = rows((100, True), (220, True), (340, True), (460, True))
    history[2]['scope_sha256'] = history[3]['scope_sha256'] = 'new-fleet'
    assert watch.uninterrupted_seconds(history) == 120


def test_reused_vm_is_not_probed_or_reported_healthy():
    scope = {'version': 1, 'guests': {'1411': {'config_sha256': 'a'*64, 'services': ['nginx']}}}
    with patch.object(watch.subprocess, 'check_output', return_value='{"name":"different-owner"}'), \
            patch.object(watch.subprocess, 'run') as run:
        assert watch.guest('1411', scope)['code'] == 'guest_scope_changed'
        run.assert_not_called()


def test_missing_scope_records_failure_and_breaks_old_health_window(tmp_path):
    with patch.object(watch, 'STATE', tmp_path), \
            patch.object(watch, 'load_scope', side_effect=FileNotFoundError), \
            patch.object(watch, 'oidc') as oidc:
        assert watch.main() == 1
        result = watch.json.loads((tmp_path / 'latest.json').read_text())
        assert result['healthy'] is False
        assert result['continuous_healthy_seconds'] == 0
        assert result['infrastructure_48h_observed'] is False
        oidc.assert_not_called()
