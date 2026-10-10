"""Acceptance probe must verify effects, not merely successful submissions."""
import base64
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('linux_native_probe',
    Path(__file__).resolve().parents[1] / 'deploy/on-prem/probe-linux-native.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class Gateway:
    def __init__(self):
        self.locked = False
        self.epoch = 0
        self.dispatches = 0

    @contextmanager
    def native_lock(self, resource):
        assert resource == 'computer_test' and not self.locked
        self.locked = True
        self.dispatches += 1
        try:
            yield
        finally:
            self.locked = False

    def permit_agent(self, resource):
        assert self.locked
        return self.epoch

    def validate_agent(self, permit):
        assert self.locked
        if permit != self.epoch:
            raise ValueError('device_epoch_changed')


class Backend:
    def __init__(self, gateway, *, drop_text=False, duplicate=False):
        self.gateway, self.drop_text, self.duplicate = gateway, drop_text, duplicate
        self.value, self.selected, self.saves, self.scroll = 'old', [], 4, 0
        self.inputs = []
        self.approval = None
        self.target = {'app': 'firefox', 'window_id': 10, 'pid': 22}

    def set_approval_callback(self, callback):
        self.approval = callback

    def dispatch(self, args):
        assert self.gateway.locked
        action = args['action']
        if action == 'status':
            return json.dumps({'ready': True})
        if action == 'list_windows':
            windows = [{**self.target, 'window_title': probe.TITLE + ' — Mozilla Firefox'}]
            return json.dumps({'windows': windows * (2 if self.duplicate else 1)})
        if action == 'capture':
            return json.dumps({**self.target, 'target': self.target,
                'window_title': probe.TITLE + ' — Mozilla Firefox',
                'width': 1280, 'height': 800, 'origin': [0, 0],
                'screenshot': {'data': base64.b64encode(str(self.scroll).encode()).decode()},
                # Deliberately includes both samples even when the actual field
                # is unchanged. A substring-in-whole-AX test would falsely pass.
                'accessibility_text': probe.EDIT_SAMPLE + '\n' + probe.TYPE_SAMPLE,
                'elements': [
                    {'label': 'Test note', 'role': 'entry', 'index': 0,
                     'text': self.value, 'focused': True, 'text_selections': self.selected},
                    {'label': 'Save note', 'role': 'push button', 'index': 1, 'text': ''},
                    {'label': 'result', 'role': 'text', 'index': 2, 'text': 'Saved ' + str(self.saves)},
                    {'label': probe.TITLE, 'role': 'document web', 'index': 3, 'text': ''},
                    {'label': 'address', 'role': 'combo box', 'index': 4, 'text': probe.FIXTURE_URL},
                    {'label': 'Scroll section 1', 'role': 'heading', 'index': 5,
                     'text': '', 'bounds': [10, 500 - self.scroll * 100, 300, 30]}] +
                    ([{'label': 'Scroll section 2', 'role': 'heading', 'index': 6,
                       'text': '', 'bounds': [10, 700, 300, 30]}] if self.scroll else [])})
        assert self.approval and self.approval() == 'once'
        self.inputs.append(args)
        if action in {'set_value', 'type'} and not self.drop_text:
            self.value = probe.accessible_input_text(args.get('value', args.get('text')), 'firefox')
            self.selected = []
        elif action == 'key':
            assert args['keys'] == 'ctrl+a'
            self.selected = [[0, len(self.value)]]
        elif action == 'click':
            self.saves += 1
        elif action == 'scroll':
            self.scroll += 1
        return json.dumps({'ok': True})


def test_probe_checks_exact_unicode_field_and_relative_click_count(tmp_path):
    gateway = Gateway()
    backend = Backend(gateway)
    result = probe.exercise(backend, gateway, 'computer_test', tmp_path, sleep=lambda _: None)
    assert result['ok'] and result['profile_persistence_verified'] is False
    assert backend.saves == 5
    assert [v['action'] for v in backend.inputs] == ['set_value', 'key', 'type', 'click', 'scroll']
    assert gateway.dispatches > len(backend.inputs) and not gateway.locked
    assert backend.approval is None


def test_probe_does_not_accept_text_elsewhere_or_replay_failed_replacement(tmp_path):
    gateway = Gateway()
    backend = Backend(gateway, drop_text=True)
    with pytest.raises(ValueError, match='editable_text_not_observed'):
        probe.exercise(backend, gateway, 'computer_test', tmp_path, sleep=lambda _: None)
    assert [v['action'] for v in backend.inputs] == ['set_value']
    assert backend.approval is None


def test_probe_ambiguous_windows_do_not_receive_input(tmp_path):
    gateway = Gateway()
    backend = Backend(gateway, duplicate=True)
    with pytest.raises(ValueError, match='open_exact_synthetic_fixture_first'):
        probe.exercise(backend, gateway, 'computer_test', tmp_path, sleep=lambda _: None)
    assert not backend.inputs


def test_probe_fence_discards_result_if_epoch_changes_during_dispatch():
    gateway = Gateway()
    class ChangedBackend:
        def dispatch(self, _):
            gateway.epoch += 1
            return '{"private_result":true}'
    with pytest.raises(ValueError, match='device_epoch_changed'):
        probe.fenced_dispatch(ChangedBackend(), gateway, 'computer_test', {'action': 'capture'})
    assert not gateway.locked
