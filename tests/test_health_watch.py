import importlib.util
from pathlib import Path

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
