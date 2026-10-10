"""Exercise only the explicitly opened, synthetic Linux acceptance page.

Run as the dedicated desktop user. The one-use decision is local provisioning
acceptance, not an agent endpoint or a substitute for relay/media acceptance.
Every dispatch has the installed connector's device ownership fence. Do not wrap
this process in a second native_lock for that resource (flock is not reentrant).
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import time

from wearing.cloud.instance import read_private
from wearing.device_gateway import DeviceGateway
from wearing.linux_computer import LinuxComputerBackend
from wearing.linux_computer_helper import accessible_input_text


TITLE = 'Pajio Desktop Native Probe'
WINDOW_TITLES = {TITLE, TITLE + ' — Mozilla Firefox'}
FIXTURE_URL = 'file:///opt/pajio-native/linux-native-probe.html'
EDIT_SAMPLE = '中文验收 café 🙂，Pajio 42'
TYPE_SAMPLE = '中文键盘 é 🙂！Pajio 43'


def note_field(frame):
    matches = [e for e in frame['elements']
               if e['label'] == 'Test note' and e['role'] in {'entry', 'text'}]
    if len(matches) != 1 or matches[0].get('password'):
        raise ValueError('synthetic_fixture_entry_not_available')
    return matches[0]


def saved_count(frame):
    # Read the dedicated result's exact text. A string elsewhere in a page
    # must not make a failed click pass; duplicate AX text is also ambiguous.
    counts = {0 if e.get('text') == 'Not saved' else int(e['text'][6:])
              for e in frame['elements']
              if e.get('text') == 'Not saved' or re.fullmatch(r'Saved [0-9]+', e.get('text', ''))}
    if len(counts) != 1:
        raise ValueError('synthetic_fixture_save_state_ambiguous')
    return counts.pop()


def fenced_dispatch(backend, gateway, resource_id, args):
    with gateway.native_lock(resource_id):
        permit = gateway.permit_agent(resource_id)
        gateway.validate_agent(permit)
        result = backend.dispatch(args)
        gateway.validate_agent(permit)
        return json.loads(result)


def exercise(backend, gateway, resource_id, output, *, sleep=time.sleep):
    def dispatch(args):
        return fenced_dispatch(backend, gateway, resource_id, args)

    ready = dispatch({'action': 'status'})
    if not ready.get('ready'):
        raise ValueError('desktop_not_ready')
    windows = dispatch({'action': 'list_windows'})['windows']
    matches = [w for w in windows if w['window_title'] in WINDOW_TITLES and 'firefox' in w['app'].lower()]
    if len(matches) != 1:
        raise ValueError('open_exact_synthetic_fixture_first')
    target = {k: matches[0][k] for k in ('app', 'window_id', 'pid')}
    report = {'ready': ready, 'target': target, 'checks': [],
              'scope': 'synthetic_native_fixture_only', 'profile_persistence_verified': False}

    def capture(name=None):
        frame = dispatch({'action': 'capture', **target})
        if frame['window_title'] != matches[0]['window_title'] or frame['target'] != target:
            raise ValueError('probe_window_changed')
        documents = [e for e in frame['elements'] if e['role'] == 'document web' and e['label'] == TITLE]
        addresses = [e for e in frame['elements'] if e['role'] == 'combo box' and e.get('text') == FIXTURE_URL]
        if len(documents) != 1 or len(addresses) != 1:
            raise ValueError('probe_document_or_url_changed')
        if name:
            image = base64.b64decode(frame['screenshot']['data'], validate=True)
            path = output / (name + '.png')
            path.write_bytes(image)
            path.chmod(0o600)
            report[name] = {'sha256': hashlib.sha256(image).hexdigest(),
                            'width': frame['width'], 'height': frame['height'],
                            'origin': frame['origin'], 'elements': len(frame['elements'])}
        return frame

    def wait_for(check, error):
        for attempt in range(6):
            frame = capture()
            if check(frame):
                return frame
            if attempt < 5:
                sleep(.1)
        raise ValueError(error)

    def submit(**args):
        used = False

        def once(*_):
            nonlocal used
            if used:
                return 'deny'
            used = True
            return 'once'

        backend.set_approval_callback(once)
        try:
            result = dispatch({'app': target['app'], **args})
        finally:
            backend.set_approval_callback(None)
        if not result.get('ok'):
            raise ValueError('native_action_not_submitted')
        # Only observation may retry. Never repeat unknown/failed input.

    initial = capture('initial')
    note = note_field(initial)
    if not note.get('focused'):
        raise ValueError('focus_synthetic_fixture_entry_first')
    submit(action='set_value', element=note['index'], value=EDIT_SAMPLE)
    wait_for(lambda f: note_field(f)['text'] == accessible_input_text(EDIT_SAMPLE, target['app']),
             'editable_text_not_observed')
    report['checks'].append('exact_unicode_replacement_observed')

    submit(action='key', keys='ctrl+a')
    wait_for(lambda f: note_field(f).get('text_selections') ==
             [[0, len(accessible_input_text(EDIT_SAMPLE, target['app']))]],
             'full_text_selection_not_observed')
    submit(action='type', text=TYPE_SAMPLE)
    wait_for(lambda f: note_field(f)['text'] == accessible_input_text(TYPE_SAMPLE, target['app']),
             'typed_text_not_observed')
    typed = capture('typed')
    report['checks'].append('exact_unicode_xtest_keyboard_observed')

    count = saved_count(typed)
    buttons = [e for e in typed['elements'] if e['label'] == 'Save note' and 'button' in e['role']]
    if len(buttons) != 1:
        raise ValueError('synthetic_fixture_button_not_available')
    submit(action='click', element=buttons[0]['index'])
    clicked = wait_for(lambda f: saved_count(f) == count + 1, 'button_effect_not_observed')
    report['checks'].append('atspi_click_increment_observed')
    anchors = [e for e in clicked['elements'] if e['label'] == 'Scroll section 1' and e['role'] == 'heading']
    if len(anchors) != 1 or len(anchors[0].get('bounds', [])) != 4:
        raise ValueError('synthetic_scroll_anchor_unavailable')
    before_y = anchors[0]['bounds'][1]
    submit(action='scroll', direction='down', amount=5)

    def scrolled_down(frame):
        first = [e for e in frame['elements'] if e['label'] == 'Scroll section 1' and e['role'] == 'heading']
        second = [e for e in frame['elements'] if e['label'] == 'Scroll section 2' and e['role'] == 'heading']
        # SHOWING filtering legitimately omits section 2 before scrolling and
        # may omit section 1 afterwards. Require revealed content plus upward
        # movement/disappearance, not an initially offscreen AX node.
        moved = not first or (len(first) == 1 and len(first[0].get('bounds', [])) == 4
                              and first[0]['bounds'][1] < before_y)
        return frame['screenshot']['data'] != clicked['screenshot']['data'] and len(second) == 1 and moved

    wait_for(scrolled_down, 'scroll_pixels_and_geometry_unchanged')
    capture('scrolled')
    report['checks'].append('scroll_pixels_and_accessibility_geometry_observed')
    report['ok'] = True
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resource-id', required=True)
    parser.add_argument('--data', type=Path, default=Path.home() / '.pajio')
    options = parser.parse_args()
    binding = json.loads(read_private(options.data / 'runtime/computer/connector-id.json'))
    if binding.get('resource_id') != options.resource_id:
        raise ValueError('probe_resource_binding_mismatch')
    output = options.output
    if output.is_symlink():
        raise ValueError('unsafe_probe_directory')
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    report = exercise(LinuxComputerBackend(), DeviceGateway(), options.resource_id, output)
    result = output / 'report.json'
    result.write_text(json.dumps(report, indent=2))
    result.chmod(0o600)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
