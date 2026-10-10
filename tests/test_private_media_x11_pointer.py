"""Same-position input must not wait for a cursor change while capture is fenced."""
import subprocess

import pytest

from wearing.private_media_sources import SourceError, X11Source


class LegacyPointerBackend:
    """Model the installed xdotool's movement wait, including stationary steps."""

    def __init__(self):
        self.position = (30, 40)
        self.pressed = set()
        self.events = []
        self.timeouts = []

    def __call__(self, argv, **options):
        self.timeouts.append(options['timeout'])
        commands = list(argv[1:])
        while commands:
            command = commands.pop(0)
            if command == 'mousemove':
                sync = commands[0] == '--sync'
                if sync:
                    commands.pop(0)
                target = (int(commands.pop(0)), int(commands.pop(0)))
                if sync and target == self.position:
                    raise subprocess.TimeoutExpired(argv, options['timeout'])
                self.position = target
                self.events.append(('move', target))
            elif command in ('mousedown', 'mouseup', 'click'):
                button = int(commands.pop(0))
                if command in ('mousedown', 'click'):
                    self.pressed.add(button)
                    self.events.append(('down', self.position))
                if command in ('mouseup', 'click'):
                    self.pressed.discard(button)
                    self.events.append(('up', self.position))
            else:
                raise AssertionError('unexpected test command')
        return subprocess.CompletedProcess(argv, 0)


@pytest.fixture
def pointer_backend(monkeypatch):
    backend = LegacyPointerBackend()
    monkeypatch.setattr('wearing.private_media_sources.subprocess.run', backend)
    return backend


def test_legacy_backend_reproduces_same_position_movement_wait(pointer_backend):
    source = X11Source()
    with pytest.raises(SourceError, match='native_operation_unavailable'):
        source._x('mousemove', '--sync', 30, 40)
    assert not pointer_backend.events


def test_same_position_pointer_down_and_up_deliver_and_release(pointer_backend):
    source = X11Source()
    for _ in range(2):
        for phase in ('down', 'up'):
            source.apply({'action': 'pointer', 'phase': phase, 'x': 30, 'y': 40, 'button': 0})
    assert [kind for kind, _ in pointer_backend.events] == ['move', 'down', 'move', 'up'] * 2
    assert not pointer_backend.pressed and not source.buttons
    assert set(pointer_backend.timeouts) == {4}


def test_repeated_tap_at_current_position_keeps_move_before_click(pointer_backend):
    source = X11Source()
    for _ in range(2):
        source.apply({'action': 'tap', 'x': 30, 'y': 40})
    assert [kind for kind, _ in pointer_backend.events] == ['move', 'down', 'up'] * 2
    assert not pointer_backend.pressed
    assert all(position == (30, 40) for _, position in pointer_backend.events)


@pytest.mark.parametrize('target', [(30, 40), (31, 41), (50, 60)])
def test_swipe_allows_stationary_or_rounded_duplicate_steps(pointer_backend, monkeypatch, target):
    monkeypatch.setattr('wearing.private_media_sources.time.sleep', lambda _: None)
    source = X11Source()
    source.apply({'action': 'swipe', 'x': 30, 'y': 40, 'to_x': target[0], 'to_y': target[1], 'duration_ms': 150})
    assert pointer_backend.events[0] == ('move', (30, 40))
    assert pointer_backend.events[1] == ('down', (30, 40))
    assert pointer_backend.events[-1] == ('up', target)
    assert not pointer_backend.pressed and not source.buttons
    assert set(pointer_backend.timeouts) == {4}
