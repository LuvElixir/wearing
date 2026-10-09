"""X11 desktop adapter, behind the existing DesktopFrames/ownership gates.

The OS helper runs with Ubuntu's Python so GI/AT-SPI never leaks into the managed
model interpreter. Input travels on stdin, never in process arguments or logs.
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading


SESSION_ENV = frozenset({
    'HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'DISPLAY',
    'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR', 'XDG_SESSION_TYPE',
})
INPUT_ACTIONS = frozenset({'click', 'set_value', 'type', 'key', 'scroll'})


class LinuxComputerError(ValueError):
    pass


def run_helper(argv, *, input, timeout, env, **_):
    """Terminate the entire helper group before releasing the ownership lock."""
    with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, env=env,
                          start_new_session=True) as process:
        try:
            stdout, _ = process.communicate(input, timeout=timeout)
        except BaseException:
            # A timeout must not leave xdotool/ImageMagick alive after takeover.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        return subprocess.CompletedProcess(argv, process.returncode, stdout, '')


class LinuxComputerBackend:
    """Use one instance per MCP session and wrap dispatch with DesktopFrames.

``capture`` returns a PNG under ``screenshot``. The MCP transport must remove
that field from text and emit it as an image block. There is no screenshot or
input endpoint listening on the network. The host must wrap *every* dispatch
with DeviceGateway.native_lock(resource_id) and validate the admission permit
before and after dispatch; DesktopFrames supplies its separate frame/approval
gate. Do not take that OS lock again inside the helper.
    """
    def __init__(self, *, python='/usr/bin/python3', environment=None, runner=None):
        self.python = python
        self.environment = dict(os.environ if environment is None else environment)
        self.runner = runner or run_helper
        self._approval = None
        self._capture = None
        self._lock = threading.RLock()

    def set_approval_callback(self, callback):
        with self._lock:
            self._approval = callback

    def _request(self, payload):
        env = {k: v for k, v in self.environment.items() if k in SESSION_ENV}
        env.update(PYTHONIOENCODING='utf-8', NO_AT_BRIDGE='0')
        try:
            result = self.runner(
                [self.python, str(Path(__file__).with_name('linux_computer_helper.py'))],
                input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                text=True, timeout=18, env=env,
            )
            if result.returncode or len(result.stdout) > 12 * 1024 * 1024:
                raise LinuxComputerError('linux_desktop_helper_unavailable')
            response = json.loads(result.stdout)
            if not isinstance(response, dict):
                raise LinuxComputerError('linux_desktop_invalid_response')
            if response.get('ok') is False or response.get('error'):
                # Native exceptions, captured text and command stderr never escape.
                error = response.get('error', 'linux_desktop_unavailable')
                if not isinstance(error, str) or not re.fullmatch(r'linux_[a-z0-9_]{1,84}', error):
                    error = 'linux_desktop_unavailable'
                raise LinuxComputerError(error)
            return response
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            raise LinuxComputerError('linux_desktop_helper_unavailable') from error

    def status(self):
        try:
            return self._request({'action': 'status'})
        except LinuxComputerError as error:
            return {'installed': False, 'ready': False, 'backend': 'linux-x11-atspi',
                    'error': str(error)}

    def dispatch(self, args):
        with self._lock:
            action = args.get('action')
            if action not in INPUT_ACTIONS | {'status', 'capture', 'list_apps', 'list_windows'}:
                raise LinuxComputerError('linux_action_not_allowed')
            if action == 'status':
                return json.dumps(self.status())
            if action in INPUT_ACTIONS:
                captured, self._capture = self._capture, None
                if not captured or args.get('app') != captured['app']:
                    raise LinuxComputerError('linux_capture_required')
                callback = self._approval
                if callback is None or callback('linux-desktop', action) != 'once':
                    raise LinuxComputerError('linux_input_approval_required')
                payload = {**args, 'target': captured['target'], 'snapshot_id': captured['snapshot_id']}
            else:
                self._capture = None
                payload = dict(args)
            response = self._request(payload)
            if action == 'capture' and response.get('snapshot_id') and args.get('app'):
                self._capture = {'app': args['app'], 'target': response['target'],
                                 'snapshot_id': response['snapshot_id']}
            return json.dumps(response, ensure_ascii=False)


def linux_computer_status():
    if not sys.platform.startswith('linux'):
        return {'installed': False, 'ready': False, 'backend': 'linux-x11-atspi',
                'error': 'linux_platform_required'}
    return LinuxComputerBackend().status()
