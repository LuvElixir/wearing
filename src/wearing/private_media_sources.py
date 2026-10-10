"""Host-local capture/input drivers for the private WebRTC channel.

No source accepts commands, paths or device identifiers from the viewer. Input
text travels over subprocess stdin and is never returned in exceptions or logs.
The caller supplies the ownership guard around every operation.
"""
from dataclasses import dataclass
from io import BytesIO
import os
import shlex
import shutil
import subprocess
import time

from PIL import Image

from .linux_computer_helper import Refused, text_input_command


class SourceError(RuntimeError):
    pass


@dataclass
class CapturedFrame:
    image: Image.Image
    captured_at: float
    geometry_token: int | None = None


def _run(args, *, stdin=None, env=None, capture=False, timeout=4):
    try:
        result = subprocess.run(args, input=stdin, env=env,
                                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        if result.returncode:
            raise SourceError('native_operation_failed')
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        raise SourceError('native_operation_unavailable') from None


X11_KEYS = {
    'Enter':'Return', 'Backspace':'BackSpace', 'Tab':'Tab', 'Escape':'Escape',
    'ArrowLeft':'Left', 'ArrowRight':'Right', 'ArrowUp':'Up', 'ArrowDown':'Down',
    'Home':'Home', 'End':'End', 'PageUp':'Prior', 'PageDown':'Next',
    'Delete':'Delete', 'Insert':'Insert', 'Control':'Control_L', 'Alt':'Alt_L',
    'Shift':'Shift_L', 'Meta':'Super_L', 'CapsLock':'Caps_Lock', ' ':'space',
    **{f'F{i}':f'F{i}' for i in range(1,13)},
}
ANDROID_KEYS = {
    'Back':4, 'Home':3, 'Recents':187, 'Enter':66, 'Backspace':67, 'Tab':61,
    'Escape':111, 'ArrowLeft':21, 'ArrowRight':22, 'ArrowUp':19, 'ArrowDown':20,
    'Delete':112, 'PageUp':92, 'PageDown':93,
}


class X11Source:
    name = 'x11'
    capabilities = {'pointer':True, 'scroll':True, 'keyboard':True, 'text':'unicode', 'touch':True,
                    'text_max_chars':32, 'text_max_bytes':4096, 'text_disallow_controls':True}

    def __init__(self, *, display=':0', xauthority=None, max_fps=15, xdotool='xdotool'):
        self.max_fps = min(30, max(1, float(max_fps)))
        self.env = {**os.environ, 'DISPLAY':display}
        if xauthority:
            self.env['XAUTHORITY'] = xauthority
        self.display = display
        self.xdotool = xdotool
        self.keys = set()
        self.buttons = set()

    def _x(self, *args, stdin=None):
        return _run([self.xdotool, *map(str,args)], stdin=stdin, env=self.env)

    def capture(self):
        import mss
        try:
            # mss's X11 connection is thread-local. Never reuse it across a
            # to_thread worker or share one user's display connection.
            with mss.mss(display=self.display) as screen:
                shot = screen.grab(screen.monitors[0])
                frame = Image.frombytes('RGB', shot.size, shot.rgb)
            return CapturedFrame(frame, time.monotonic())
        except Exception:
            raise SourceError('screen_capture_unavailable') from None

    def geometry(self):
        import mss
        try:
            with mss.mss(display=self.display) as screen:
                monitor = screen.monitors[0]
                return monitor['width'],monitor['height']
        except Exception:
            raise SourceError('screen_geometry_unavailable') from None

    def available(self):
        return bool(shutil.which(self.xdotool) and self.geometry())

    def apply(self, event):
        action = event['action']
        if action == 'pointer':
            # xdotool's --sync waits for a position *change*, not an X11
            # ordering barrier. Older builds wait even at the current point,
            # starving capture under the shared native fence until timeout.
            # Plain mousemove flushes XWarpPointer; process exit closes/syncs
            # that X connection before the following button command starts.
            self._x('mousemove', event['x'], event['y'])
            button = event.get('button', 0) + 1
            if event['phase'] == 'down':
                self.buttons.add(button)
                self._x('mousedown', button)
            elif event['phase'] == 'up':
                self._x('mouseup', button)
                self.buttons.discard(button)
        elif action == 'tap':
            # One X connection preserves move-before-click request ordering.
            self._x('mousemove', event['x'], event['y'], 'click', '1')
        elif action == 'swipe':
            self.buttons.add(1)
            self._x('mousemove', event['x'], event['y'], 'mousedown', '1')
            try:
                steps = min(30, max(2, event['duration_ms']//25))
                for index in range(1, steps+1):
                    self._x('mousemove', round(event['x']+(event['to_x']-event['x'])*index/steps),
                            round(event['y']+(event['to_y']-event['y'])*index/steps))
                    time.sleep(event['duration_ms']/1000/steps)
            finally:
                self._x('mouseup', '1')
                self.buttons.discard(1)
        elif action == 'scroll':
            for value, negative, positive in ((event['delta_y'],4,5),(event['delta_x'],6,7)):
                if value:
                    self._x('click', '--repeat', min(10,max(1,round(abs(value)/80))),
                            '--delay', '10', positive if value>0 else negative)
        elif action == 'key':
            key = event['key']
            mapped = X11_KEYS.get(key)
            if mapped is None and len(key)==1 and key.isascii() and key.isalnum():
                mapped = key
            if mapped is None:
                raise SourceError('unsupported_key')
            if event['phase']=='down':
                self.keys.add(mapped)
            self._x('keydown' if event['phase']=='down' else 'keyup', mapped)
            if event['phase']!='down':
                self.keys.discard(mapped)
        elif action == 'text':
            text = event.get('text')
            # Bounded before any keystroke. Longer typing would starve capture
            # under the native guard and exceed the viewer's input ACK budget.
            # Share the measured Unicode cadence with the ordinary driver, but
            # never read private field contents back to validate delivery.
            try:
                command = text_input_command(text, maximum=self.capabilities['text_max_chars'],
                                             xdotool=self.xdotool)
            except Refused:
                code = ('text_too_long' if isinstance(text, str) and
                        len(text) > self.capabilities['text_max_chars'] else 'text_invalid')
                raise SourceError(code) from None
            _run(command, stdin=text.encode('utf-8'), env=self.env)
        else:
            raise SourceError('unsupported_input')

    def release_all(self):
        # Do not leave a held modifier or mouse button on a disconnected user.
        failed = False
        # A crashed host loses its in-memory held-key set. Reset the supported
        # keys as well, on this dedicated virtual display, before safe return.
        keys = self.keys | set(X11_KEYS.values()) | set('abcdefghijklmnopqrstuvwxyz0123456789')
        try:
            self._x('keyup',*sorted(keys))
            self.keys.clear()
        except SourceError:
            failed = True
        for button in self.buttons | {1,2,3}:
            try:
                self._x('mouseup', button)
                self.buttons.discard(button)
            except SourceError:
                failed = True
        if failed:
            raise SourceError('input_release_failed')


class AndroidScreencapSource:
    """Explicit low-frame-rate fallback; replace this driver with scrcpy later."""
    name = 'adb-screencap'
    capabilities = {'pointer':False, 'scroll':False, 'keyboard':True, 'text':'unavailable', 'touch':True,
                    'text_max_chars':4096, 'text_max_bytes':4096}

    def __init__(self, *, serial, adb='adb', max_fps=2):
        self.serial, self.adb = serial, adb
        self.max_fps = min(3, max(0.25, float(max_fps)))

    def capture(self):
        raw = _run([self.adb,'-s',self.serial,'exec-out','screencap','-p'], capture=True, timeout=5)
        if len(raw) > 32*1024*1024:
            raise SourceError('screen_capture_too_large')
        try:
            with Image.open(BytesIO(raw)) as image:
                if image.width*image.height > 16_000_000:
                    raise SourceError('screen_capture_too_large')
                result = image.convert('RGB')
            return CapturedFrame(result, time.monotonic())
        except (OSError, ValueError):
            raise SourceError('screen_capture_unavailable') from None

    def available(self):
        return _run([self.adb,'-s',self.serial,'get-state'],capture=True,timeout=2).strip()==b'device'

    def geometry(self):
        # The fallback deliberately trades latency for correct rotation. `wm
        # size` alone reports natural dimensions and misses current orientation.
        return self.capture().image.size

    def _input(self, *parts):
        # The shell script is sent over stdin, not command arguments. Never
        # expose password text through the connector tool or subprocess logs.
        script = ('input '+shlex.join(map(str, parts))+'\n').encode('utf-8')
        _run([self.adb,'-s',self.serial,'shell'], stdin=script)

    def apply(self, event):
        action = event['action']
        if action == 'tap':
            self._input('tap',event['x'],event['y'])
        elif action == 'swipe':
            self._input('swipe',event['x'],event['y'],event['to_x'],event['to_y'],event['duration_ms'])
        elif action == 'key':
            code = ANDROID_KEYS.get(event['key'])
            if code is None:
                raise SourceError('unsupported_key')
            if event['phase']=='down':
                self._input('keyevent',code)
        elif action == 'text':
            # `adb shell input text` exposes text in the device-side process
            # arguments even when adb itself receives its script over stdin.
            raise SourceError('android_private_input_unavailable')
        else:
            raise SourceError('unsupported_input')

    def release_all(self):
        pass


def configured_source(binding):
    if binding['kind']=='computer':
        return X11Source(display=binding.get('display',':0'), xauthority=binding.get('xauthority'),
                         max_fps=binding.get('max_fps',15), xdotool=binding.get('xdotool','xdotool'))
    if binding['kind']=='android':
        if binding.get('video_source')=='scrcpy':
            from .private_media_android import AndroidScrcpySource
            return AndroidScrcpySource(serial=binding['serial'],server=binding['scrcpy_server'],
                adb=binding.get('adb','adb'),max_fps=binding.get('max_fps',24),
                max_size=binding.get('max_size',0),bitrate=binding.get('bitrate',4_000_000),
                unicode_ime=binding.get('unicode_ime') is True)
        return AndroidScreencapSource(serial=binding['serial'], adb=binding.get('adb','adb'),
                                      max_fps=binding.get('max_fps',2))
    raise SourceError('unsupported_device_kind')
