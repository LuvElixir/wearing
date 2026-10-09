"""Bounded Ubuntu X11/AT-SPI operations. Executed with system Python, JSON stdin.

Only this process imports pyatspi. It has no model keys, relay credentials,
HTTP server or command-evaluation action. Diagnostics are fixed error codes.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time


MAX_NODES = 750
MAX_IMAGE = 8 * 1024 * 1024
INPUTS = {'click', 'set_value', 'type', 'key', 'scroll'}


class Refused(ValueError):
    pass


def run(argv, *, stdin=None, binary=False, timeout=5):
    try:
        value = subprocess.run(argv, input=stdin, capture_output=True,
                               text=not binary, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused('linux_native_operation_unavailable') from error
    if value.returncode:
        raise Refused('linux_native_operation_unavailable')
    if len(value.stdout) > (MAX_IMAGE if binary else 256 * 1024):
        raise Refused('linux_native_output_too_large')
    return value.stdout


def integer(value, *, minimum=0, maximum=2**32 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Refused('linux_invalid_target')
    return value


def geometry(text):
    # xdotool 3.20160805 double-counts decoration offsets on Xfce reparented
    # windows. xwininfo's absolute client coordinates are the canonical origin.
    names={'Absolute upper-left X':'X','Absolute upper-left Y':'Y','Width':'WIDTH','Height':'HEIGHT'}
    values={names[key]:value for key,value in re.findall(
        r'^\s*(Absolute upper-left X|Absolute upper-left Y|Width|Height):\s*(-?\d+)\s*$',text,re.M)}
    if set(values) != {'X', 'Y', 'WIDTH', 'HEIGHT'}:
        raise Refused('linux_window_geometry_unavailable')
    x, y, width, height = (int(values[key]) for key in ('X', 'Y', 'WIDTH', 'HEIGHT'))
    if x < 0 or y < 0 or width < 1 or height < 1 or width * height > 8_000_000:
        raise Refused('linux_window_geometry_unsupported')
    return x, y, width, height


def key_chord(value):
    aliases = {'ctrl': 'ctrl', 'control': 'ctrl', 'alt': 'alt', 'shift': 'shift',
               'super': 'super', 'meta': 'super', 'win': 'super',
               'enter': 'Return', 'return': 'Return', 'esc': 'Escape', 'escape': 'Escape',
               'backspace': 'BackSpace', 'delete': 'Delete', 'tab': 'Tab', 'space': 'space',
               'home': 'Home', 'end': 'End', 'up': 'Up', 'down': 'Down',
               'left': 'Left', 'right': 'Right', 'pageup': 'Page_Up', 'pagedown': 'Page_Down'}
    if not isinstance(value, str) or len(value) > 100:
        raise Refused('linux_invalid_key')
    pieces = value.split('+')
    if not 1 <= len(pieces) <= 5:
        raise Refused('linux_invalid_key')
    out = []
    for piece in pieces:
        low = piece.lower()
        if low in aliases:
            out.append(aliases[low])
        elif re.fullmatch(r'[a-zA-Z0-9]', piece) or re.fullmatch(r'F(?:[1-9]|1[0-9]|2[0-4])', piece):
            out.append(piece)
        else:
            raise Refused('linux_invalid_key')
    return '+'.join(out)


def png_size(data):
    if len(data) < 24 or not data.startswith(b'\x89PNG\r\n\x1a\n') or data[12:16] != b'IHDR':
        raise Refused('linux_invalid_capture')
    return struct.unpack('>II', data[16:24])


def view_id(frame):
    view = {key: frame[key] for key in ('target', 'window_title', 'width', 'height',
                                       'origin', 'elements', 'accessibility_text')}
    return hashlib.sha256(json.dumps(view, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class LinuxDesktop:
    def __init__(self, *, native=run, atspi=None):
        self.native = native
        self.atspi = atspi

    def status(self):
        missing = [name for name in ('xdotool', 'xprop', 'xwininfo', 'import') if not shutil.which(name)]
        display = os.environ.get('DISPLAY', '')
        wayland = os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland'
        if not sys.platform.startswith('linux'):
            raise Refused('linux_platform_required')
        if wayland or not re.fullmatch(r':\d+(?:\.\d+)?', display):
            raise Refused('linux_local_x11_session_required')
        if not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
            raise Refused('linux_accessibility_bus_required')
        if missing:
            return {'installed': False, 'ready': False, 'backend': 'linux-x11-atspi',
                    'missing_packages': missing}
        self.load_atspi()
        size = self.native(['xdotool', 'getdisplaygeometry']).strip().split()
        if len(size) != 2 or not all(re.fullmatch(r'\d+', part) and int(part) > 0 for part in size):
            raise Refused('linux_display_unavailable')
        self.atspi.Registry.getDesktop(0)
        return {'installed': True, 'ready': True, 'backend': 'linux-x11-atspi',
                'display': display, 'width': int(size[0]), 'height': int(size[1]),
                'scope': 'foreground_window', 'accessibility': True}

    def load_atspi(self):
        if self.atspi is None:
            try:
                import pyatspi
                self.atspi = pyatspi
            except ImportError as error:
                raise Refused('linux_atspi_package_required') from error

    def active_window(self):
        value = self.native(['xdotool', 'getactivewindow']).strip()
        if not value.isdigit():
            raise Refused('linux_active_window_unavailable')
        return int(value)

    def windows(self):
        raw = self.native(['xprop', '-root', '_NET_CLIENT_LIST_STACKING'])
        ids = re.findall(r'0x[0-9a-fA-F]+', raw)[:80]
        records = []
        for value in reversed(ids):
            try:
                pid = int(self.native(['xdotool', 'getwindowpid', value]).strip())
                title = self.native(['xdotool', 'getwindowname', value]).strip()[:500]
                classes = re.findall(r'"([^"\n]*)"', self.native(['xprop', '-id', value, 'WM_CLASS']))
                if not classes or not classes[-1] or pid < 1:
                    continue
                records.append({'app': classes[-1][:200], 'window_id': int(value, 16),
                                'pid': pid, 'window_title': title})
            except (Refused, ValueError):
                continue
        return records

    def select_window(self, args):
        app = args.get('app')
        if not isinstance(app, str) or not 1 <= len(app) <= 200 or any(ord(c) < 32 for c in app):
            raise Refused('linux_app_required')
        windows = [window for window in self.windows() if window['app'] == app]
        if ('window_id' in args) != ('pid' in args):
            raise Refused('linux_invalid_target')
        if 'window_id' in args:
            wid, pid = integer(args['window_id']), integer(args['pid'], minimum=1)
            windows = [window for window in windows if window['window_id'] == wid and window['pid'] == pid]
        if len(windows) != 1:
            raise Refused('linux_window_ambiguous_or_missing')
        window = windows[0]
        # X11 screenshots and keystrokes must refer to the same foreground view.
        # Switching a foreground window is a separate human action in this MVP.
        if self.active_window() != window['window_id']:
            raise Refused('linux_target_not_foreground')
        return window

    def accessible_window(self, window):
        self.load_atspi()
        roots = []
        desktop = self.atspi.Registry.getDesktop(0)
        for application in desktop:
            try:
                if application.get_process_id() != window['pid']:
                    continue
                roots.extend(child for child in application if child.getRole() in
                             (self.atspi.ROLE_FRAME, self.atspi.ROLE_DIALOG, self.atspi.ROLE_WINDOW))
            except Exception:
                continue
        exact = [root for root in roots if str(root.name or '') == window['window_title']]
        if len(exact) == 1:
            return exact[0]
        if len(roots) == 1:
            return roots[0]
        raise Refused('linux_accessible_window_ambiguous_or_missing')

    def tree(self, root, origin, bounds):
        atspi = self.atspi
        deadline = time.monotonic() + 4
        nodes, elements, lines = {}, [], []
        queue = [(root, 0)]
        while queue:
            if len(elements) >= MAX_NODES or time.monotonic() >= deadline:
                raise Refused('linux_accessibility_tree_too_large')
            node, depth = queue.pop()
            if depth > 32:
                raise Refused('linux_accessibility_tree_too_deep')
            try:
                state = node.getState()
                if state.contains(atspi.STATE_DEFUNCT):
                    raise Refused('linux_accessibility_target_changed')
                if not state.contains(atspi.STATE_SHOWING):
                    continue
                role = node.getRoleName()
                password = node.getRole() == atspi.ROLE_PASSWORD_TEXT
                focused = state.contains(atspi.STATE_FOCUSED)
                if password and focused:
                    raise Refused('linux_sensitive_focus_handoff_required')
                label = 'Private field' if password else str(node.name or '')[:1000]
                text = ''
                if not password:
                    try:
                        text_iface = node.queryText()
                        text = str(text_iface.getText(0, min(text_iface.characterCount, 1000)))[:1000]
                    except Exception:
                        pass
                actions = []
                try:
                    iface = node.queryAction()
                    actions = [iface.getName(index) for index in range(min(iface.nActions, 20))]
                except Exception:
                    pass
                index = len(elements)
                element = {'index': index, 'label': label or text[:200] or role,
                           'role': role, 'text': '[private]' if password else text,
                           'focused': focused, 'enabled': state.contains(atspi.STATE_ENABLED),
                           'password': password, 'actions': actions}
                try:
                    rect = node.queryComponent().getExtents(atspi.DESKTOP_COORDS)
                    x, y, w, h = (int(part) for part in rect)
                    element['bounds'] = [x - origin[0], y - origin[1], w, h]
                except Exception:
                    pass
                nodes[index] = node
                elements.append(element)
                lines.append('  ' * min(depth, 8) + f"[{index}] {role} {element['label']}" +
                             (f" = {element['text']}" if element['text'] else ''))
                if node.childCount > MAX_NODES:
                    raise Refused('linux_accessibility_tree_too_large')
                queue.extend((node.getChildAtIndex(index), depth + 1)
                             for index in reversed(range(node.childCount)))
            except Refused:
                raise
            except Exception as error:
                raise Refused('linux_accessibility_target_changed') from error
        if not elements:
            raise Refused('linux_accessibility_tree_unavailable')
        return nodes, elements, '\n'.join(lines)

    def snapshot(self, args, *, image=True):
        window = self.select_window(args)
        x, y, width, height = geometry(self.native(
            ['xwininfo', '-id', str(window['window_id']), '-stats']))
        root = self.accessible_window(window)
        nodes, elements, text = self.tree(root, (x, y), (width, height))
        target = {key: window[key] for key in ('app', 'window_id', 'pid')}
        result = {**window, 'ok': True, 'target': target, 'origin': [x, y],
                  'width': width, 'height': height, 'elements': elements, 'accessibility_text': text}
        result['snapshot_id'] = view_id(result)
        if image:
            png = self.native(['import', '-window', 'root', '-crop', f'{width}x{height}+{x}+{y}',
                               '+repage', '-silent', 'png:-'], binary=True, timeout=8)
            if png_size(png) != (width, height):
                raise Refused('linux_capture_geometry_changed')
            if self.active_window() != window['window_id']:
                raise Refused('linux_target_changed_during_capture')
            current_geometry = geometry(self.native(
                ['xwininfo', '-id', str(window['window_id']), '-stats']))
            if current_geometry != (x, y, width, height) or self.select_window(target) != window:
                raise Refused('linux_target_changed_during_capture')
            # Re-read semantics after pixels; a frame from a changing window never
            # becomes authority for an action on an earlier tree.
            _, after, after_text = self.tree(root, (x, y), (width, height))
            if after != elements or after_text != text:
                raise Refused('linux_target_changed_during_capture')
            result['screenshot'] = {'mime_type': 'image/png', 'data': base64.b64encode(png).decode('ascii')}
        return result, nodes

    def act(self, args):
        target = args.get('target')
        if not isinstance(target, dict) or set(target) != {'app', 'window_id', 'pid'} or target['app'] != args.get('app'):
            raise Refused('linux_invalid_target')
        if not re.fullmatch(r'[a-f0-9]{64}', str(args.get('snapshot_id', ''))):
            raise Refused('linux_capture_required')
        frame, nodes = self.snapshot(target, image=False)
        if frame['snapshot_id'] != args['snapshot_id']:
            raise Refused('linux_view_changed')
        if self.active_window() != target['window_id']:
            raise Refused('linux_target_not_foreground')
        action = args['action']
        if action in {'click', 'set_value'}:
            index = integer(args.get('element'), maximum=MAX_NODES - 1)
            if index not in nodes or not frame['elements'][index]['enabled']:
                raise Refused('linux_element_not_actionable')
            node = nodes[index]
            if action == 'set_value':
                if frame['elements'][index]['password']:
                    raise Refused('linux_sensitive_focus_handoff_required')
                value = args.get('value')
                if not isinstance(value, str) or len(value) > 2000:
                    raise Refused('linux_invalid_input')
                try:
                    if node.queryEditableText().setTextContents(value) is False:
                        raise Refused('linux_element_input_failed')
                except Refused:
                    raise
                except Exception as error:
                    raise Refused('linux_element_not_editable') from error
            else:
                try:
                    iface = node.queryAction()
                    names = [str(iface.getName(i)).lower() for i in range(min(iface.nActions, 20))]
                    selected = next((names.index(name) for name in ('click', 'press', 'activate', 'toggle', 'open') if name in names), None)
                    if selected is None or not iface.doAction(selected):
                        raise Refused('linux_element_not_actionable')
                except Refused:
                    raise
                except Exception as error:
                    raise Refused('linux_element_not_actionable') from error
        elif action == 'type':
            text = args.get('text')
            if not isinstance(text, str) or len(text) > 2000:
                raise Refused('linux_invalid_input')
            # XTEST to the verified foreground; --window uses synthetic
            # XSendEvent which Chromium and many GTK apps discard.
            self.native(['xdotool', 'type', '--clearmodifiers', '--delay', '0', '--file', '-'], stdin=text)
        elif action == 'key':
            self.native(['xdotool', 'key', '--clearmodifiers', key_chord(args.get('keys'))])
        elif action == 'scroll':
            button = {'up': '4', 'down': '5', 'left': '6', 'right': '7'}.get(args.get('direction'))
            amount = integer(args.get('amount'), minimum=1, maximum=5)
            if button is None:
                raise Refused('linux_invalid_input')
            self.native(['xdotool', 'mousemove',
                         str(frame['origin'][0] + frame['width'] // 2),
                         str(frame['origin'][1] + frame['height'] // 2),
                         'click', '--clearmodifiers', '--repeat', str(amount), '--delay', '35', button])
        else:
            raise Refused('linux_action_not_allowed')
        return {'ok': True, 'action': action, 'app': target['app'],
                'note': 'Action submitted to the target application; observe again to verify its result.'}

    def dispatch(self, args):
        action = args.get('action')
        if action == 'status':
            return self.status()
        if action == 'list_windows':
            return {'ok': True, 'windows': self.windows()}
        if action == 'list_apps':
            names = sorted({window['app'] for window in self.windows()})
            return {'ok': True, 'apps': [{'app': name} for name in names]}
        if action == 'capture':
            return self.snapshot(args)[0]
        if action in INPUTS:
            return self.act(args)
        raise Refused('linux_action_not_allowed')


def main():
    try:
        request = sys.stdin.read(32769)
        if len(request) > 32768:
            raise Refused('linux_request_too_large')
        args = json.loads(request)
        if not isinstance(args, dict):
            raise Refused('linux_invalid_request')
        host = LinuxDesktop()
        # Verify X11 rather than quietly controlling an XWayland or other display.
        ready = host.status()
        if args.get('action') != 'status' and not ready.get('ready'):
            raise Refused('linux_desktop_not_ready')
        value = ready if args.get('action') == 'status' else host.dispatch(args)
    except Refused as error:
        value = {'ok': False, 'error': str(error)}
    except Exception:
        value = {'ok': False, 'error': 'linux_desktop_unavailable'}
    sys.stdout.write(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    main()
