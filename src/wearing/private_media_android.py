"""Continuous Android video from a pinned official scrcpy server.

This is an independent client of scrcpy's documented H264 wire interface, not a
copy of another agent's implementation. The server binary is provisioned by the
operator, checked against its official release digest, and runs only while a
human owns the device. No recordings or clipboard synchronization are enabled.
"""
import hashlib
from pathlib import Path
import re
import secrets
import socket
import struct
import subprocess
import threading
import time

from .private_media_sources import AndroidScreencapSource, CapturedFrame, SourceError, _run


SCRCPY_VERSION = '5.0.1'
SCRCPY_SHA256 = '764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536'
IME = 'io.pajio.privateinput/.PrivateInputMethod'
IME_SOCKET = 'pajio.privateinput.v1'
PRIVATE_IME_SHA256 = '80960fcaa86936abdf20de79660ea63cbc10f024b3f43b3a6ee53e92c1037c27'


class AndroidScrcpySource(AndroidScreencapSource):
    name = 'scrcpy-h264'

    def __init__(self, *, serial, server, adb='adb', max_fps=24, max_size=0,
                 bitrate=4_000_000, unicode_ime=False):
        super().__init__(serial=serial,adb=adb,max_fps=2)
        self.max_fps = min(30,max(5,float(max_fps)))
        self.max_size = int(max_size)
        if not 0 <= self.max_size <= 8192:
            raise SourceError('invalid_video_configuration')
        self.bitrate = min(12_000_000,max(500_000,int(bitrate)))
        self.server = Path(server)
        self.unicode_ime = unicode_ime is True
        self.capabilities = {**super().capabilities,'text':'unicode' if self.unicode_ime else 'unavailable'}
        self.guard = None
        self.process = None
        self.sock = None
        self.port = None
        self.thread = None
        self.condition = threading.Condition()
        self.latest = None
        self.static_refresh = None
        self.static_refresh_count = 0
        self.last_capture_mode = self.name
        self.closed = False
        self.failed = False
        self.previous_ime = None
        self.ime_apk = None
        self.ime_uid = None
        self.ime_nonce = bytearray(secrets.token_bytes(32))
        self.cleanup_errors = []
        self.ime_release_ack = None
        self.remote_installed = False
        self.geometry_token = 0
        self.scid = secrets.token_hex(4)
        # scrcpy restricts scid to a positive signed 31-bit integer.
        self.scid = f'{int(self.scid,16)&0x7fffffff:08x}'
        self.remote_path = '/data/local/tmp/pajio-scrcpy-'+self.scid+'.jar'

    def set_guard(self, guard):
        self.guard = guard

    def available(self):
        return (super().available() and self.server.is_file() and self.server.stat().st_size<=2*1024*1024 and
                hashlib.sha256(self.server.read_bytes()).hexdigest()==SCRCPY_SHA256)

    def _check(self):
        if self.closed or not callable(self.guard):
            raise SourceError('private_capture_not_authorized')
        self.guard()

    def _adb(self,*args,capture=False,stdin=None,timeout=5):
        return _run([self.adb,'-s',self.serial,*args],capture=capture,stdin=stdin,timeout=timeout)

    def _start(self):
        self._check()
        if self.process is not None:
            return
        if not self.server.is_file() or self.server.stat().st_size>2*1024*1024:
            raise SourceError('scrcpy_server_missing')
        if hashlib.sha256(self.server.read_bytes()).hexdigest()!=SCRCPY_SHA256:
            raise SourceError('scrcpy_server_digest_mismatch')
        self.remote_installed = True  # Also clean up a partially failed push.
        self._adb('push',str(self.server),self.remote_path,timeout=10)
        port = self._adb('forward','tcp:0','localabstract:scrcpy_'+self.scid,capture=True)
        try:
            self.port = int(port.strip())
            if not 1024 <= self.port <= 65535:
                raise ValueError()
        except (ValueError,TypeError):
            raise SourceError('scrcpy_tunnel_failed') from None
        args = [self.adb,'-s',self.serial,'shell',
                'CLASSPATH='+self.remote_path,'app_process','/','com.genymobile.scrcpy.Server',SCRCPY_VERSION,
                'scid='+self.scid,'tunnel_forward=true','audio=false','control=false','cleanup=false',
                'send_device_meta=false','send_dummy_byte=false','send_stream_meta=true',
                'send_frame_meta=true','video_codec=h264','max_size='+str(self.max_size),
                'max_fps='+str(self.max_fps),'video_bit_rate='+str(self.bitrate),
                'clipboard_autosync=false','log_level=error']
        self.process = subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        # adb forward may accept the TCP connection before app_process starts
        # listening. Verify actual H264 data; do not trust TCP connect alone.
        deadline = time.monotonic()+6
        first = b''
        while time.monotonic()<deadline:
            self._check()
            if self.process.poll() is not None:
                break
            candidate = None
            try:
                candidate = socket.create_connection(('127.0.0.1',self.port),timeout=.5)
                candidate.settimeout(.5)
                first = candidate.recv(65536)
                if first:
                    self.sock = candidate
                    break
            except OSError:
                pass
            if candidate:
                candidate.close()
            time.sleep(.05)
        if self.sock is None:
            raise SourceError('scrcpy_stream_unavailable')
        self.sock.settimeout(.5)
        self.thread = threading.Thread(target=self._decode,args=(first,),daemon=True,name='pajio-private-video')
        self.thread.start()

    def _decode(self, first):
        import av
        decoder = av.CodecContext.create('h264','r')
        decoder.thread_count = 1
        buffered = bytearray(first)
        configuration = b''
        def read(count):
            while len(buffered)<count:
                self._check()
                try:
                    chunk = self.sock.recv(min(65536,count-len(buffered)))
                except socket.timeout:
                    continue
                if not chunk:
                    raise SourceError('scrcpy_stream_closed')
                buffered.extend(chunk)
            value = bytes(buffered[:count])
            del buffered[:count]
            return value
        try:
            if read(4)!=b'h264':
                raise SourceError('scrcpy_codec_mismatch')
            while not self.closed:
                self._check()
                header = read(12)
                flags,size = struct.unpack('>QI',header)
                if flags & (1<<63):
                    _,width,height = struct.unpack('>III',header)
                    if not 0<width<=8192 or not 0<height<=8192 or width*height>16_000_000:
                        raise SourceError('screen_capture_too_large')
                    # Captures restart on rotation, including 180 degrees with
                    # unchanged dimensions. Invalidate all prior input frames.
                    self.geometry_token += 1
                    configuration = b''
                    decoder = av.CodecContext.create('h264','r')
                    decoder.thread_count = 1
                    with self.condition:
                        self.latest = None
                    continue
                if not 0<size<=8*1024*1024:
                    raise SourceError('scrcpy_packet_invalid')
                payload = read(size)
                if flags & (1<<62):
                    configuration = payload
                    continue
                for image in decoder.decode(av.Packet(configuration+payload)):
                    self._check()
                    if image.width*image.height>16_000_000:
                        raise SourceError('screen_capture_too_large')
                    value = CapturedFrame(image.to_image(),time.monotonic(),self.geometry_token)
                    self._check()
                    with self.condition:
                        self.latest = value  # One newest frame; never an unbounded video queue.
                        self.condition.notify_all()
                configuration = b''
        except Exception:
            self.failed = True
        finally:
            # Drop parser and decoded picture references before acknowledging a
            # private-media clear. Never flush delayed frames into another lease.
            decoder = None
            buffered.clear()
            configuration = b''
            with self.condition:
                self.latest = None
                self.condition.notify_all()

    def capture(self):
        self._check()
        self._start()
        deadline = time.monotonic()+3
        with self.condition:
            while not self.closed and not self.failed and self.latest is None and time.monotonic()<deadline:
                self.condition.wait(.1)
            self._check()
            if self.failed or self.latest is None:
                raise SourceError('scrcpy_frame_unavailable')
            encoded = self.latest
            refresh = self.static_refresh
            # Some Android encoders stop emitting after an unchanged screen.
            # Never update an old image's timestamp to pass the freshness gate.
            if refresh and (refresh.geometry_token != encoded.geometry_token or
                            refresh.image.size != encoded.image.size):
                self.static_refresh = refresh = None
            newest = refresh if refresh and refresh.captured_at > encoded.captured_at else encoded
            if time.monotonic()-newest.captured_at <= .75:
                self.last_capture_mode = 'adb-static-refresh' if newest is refresh else self.name
                return newest
        self._check()
        fresh = super().capture()
        self._check()
        # A refresh must represent the same geometry as the encoded session.
        # For operator-configured downsizing, preserve aspect ratio explicitly.
        if self.max_size and fresh.image.size != encoded.image.size:
            w,h = encoded.image.size
            fw,fh = fresh.image.size
            if (w>h)!=(fw>fh) or abs(w/h-fw/fh) > .02:
                raise SourceError('android_geometry_changed')
            fresh = CapturedFrame(fresh.image.resize((w,h)),fresh.captured_at,encoded.geometry_token)
        with self.condition:
            if (self.failed or self.latest is None or
                    self.latest.geometry_token != encoded.geometry_token or
                    fresh.image.size != encoded.image.size):
                raise SourceError('android_geometry_changed')
            self.static_refresh = CapturedFrame(fresh.image,fresh.captured_at,encoded.geometry_token)
            self.static_refresh_count += 1
            self.last_capture_mode = 'adb-static-refresh'
            return self.static_refresh

    def geometry(self):
        # scrcpy's newest decoded dimensions track rotation. Native taps below
        # also verify the actual device dimensions before scaling coordinates.
        return self.capture().image.size

    def _native_geometry(self):
        return super().capture().image.size

    def _verify_ime_apk(self, apk):
        # Verify the installed bytes, not just a package name or recyclable UID.
        # Android package install paths are immutable to ordinary application UIDs.
        if not isinstance(apk,str) or not re.fullmatch(r'/data/app/[A-Za-z0-9_./~+=-]+/base\.apk',apk):
            raise SourceError('android_private_input_identity_unknown')
        try:
            digest = self._adb('shell','sha256sum',apk,capture=True).decode('ascii').strip()
        except (UnicodeError,SourceError):
            raise SourceError('android_private_input_digest_mismatch') from None
        if digest != PRIVATE_IME_SHA256+'  '+apk:
            raise SourceError('android_private_input_digest_mismatch')

    def _ime_request(self, operation, text=''):
        # All payload bytes travel inside a local socket to a kernel-UID checked
        # IME. Never put text in Android argv, broadcasts, clipboard or files.
        self._verify_ime_apk(self.ime_apk)
        if operation == 1:
            # Digest I/O can outlive the human lease. Recheck immediately before
            # sending any input; release operation 2 must also work after close.
            self._check()
        payload = bytearray(text.encode('utf-8'))
        request = bytearray(b'PIM1') + self.ime_nonce + bytearray(struct.pack('>BI', operation, len(payload)))
        request.extend(payload)
        try:
            reply = self._adb('shell','-T','env','CLASSPATH='+self.ime_apk,'app_process','/',
                              'io.pajio.privateinput.SocketClient',str(self.ime_uid),
                              capture=True,stdin=request,timeout=3)
            expected = b'\x03' if operation == 1 and not payload else b'\x00'
            if reply != expected:
                raise SourceError('android_text_delivery_uncertain')
        finally:
            payload[:] = b'\x00' * len(payload)
            request[:] = b'\x00' * len(request)

    def _unicode_text(self,text):
        if self.previous_ime is None:
            previous = self._adb('shell','settings','get','secure','default_input_method',capture=True).decode().strip()
            if not re.fullmatch(r'[A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+',previous) or previous == IME:
                raise SourceError('android_ime_state_unknown')
            installed = self._adb('shell','ime','list','-a','-s',capture=True).decode().splitlines()
            if IME not in installed:
                raise SourceError('android_unicode_ime_missing')
            apk = self._adb('shell','pm','path','io.pajio.privateinput',capture=True).decode().strip()
            uid = self._adb('shell','cmd','package','list','packages','-U','io.pajio.privateinput',capture=True).decode().strip()
            if not re.fullmatch(r'package:/data/app/[A-Za-z0-9_./~+=-]+/base\.apk',apk):
                raise SourceError('android_private_input_identity_unknown')
            match = re.fullmatch(r'package:io\.pajio\.privateinput uid:(\d+)',uid)
            if not match or not 10000 <= int(match[1]) < 200000:
                raise SourceError('android_private_input_identity_unknown')
            self._verify_ime_apk(apk[len('package:'):])
            self.ime_apk = apk[len('package:'):]
            self.ime_uid = int(match[1])
            self.previous_ime = previous
            self._adb('shell','ime','enable',IME)
            self._adb('shell','ime','set',IME)
            # Only empty probes can retry while Android starts the IME. The
            # SocketClient verifies the server UID before sending even a nonce.
            deadline = time.monotonic()+3
            while time.monotonic()<deadline:
                self._check()
                try:
                    self._ime_request(1)
                    break
                except SourceError:
                    time.sleep(.05)
            else:
                raise SourceError('android_private_input_unavailable')
        self._check()
        self._ime_request(1,text)

    def apply(self,event):
        self._check()
        if event['action']=='text' and self.unicode_ime:
            self._unicode_text(event['text'])
            return
        if event['action'] in ('tap','swipe'):
            current = self.geometry()
            native = self._native_geometry()
            # A rotation between the stream frame and this input is rejected.
            if (current[0]>current[1]) != (native[0]>native[1]):
                raise SourceError('android_geometry_changed')
            event = dict(event)
            for x,y in (('x','y'),('to_x','to_y')):
                if x in event:
                    event[x] = min(native[0]-1,round(event[x]*native[0]/current[0]))
                    event[y] = min(native[1]-1,round(event[y]*native[1]/current[1]))
        super().apply(event)

    def release_all(self):
        self.closed = True
        errors = []
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                errors.append('socket_not_closed')
            else:
                self.sock = None
        if self.process:
            try:
                # poll handles a child that exited between disconnect and clear.
                if self.process.poll() is None:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                # Keep the handle for a later explicit cleanup attempt, but do
                # not skip IME restoration, nonce clearing or other resources.
                errors.append('server_process_not_stopped')
            else:
                self.process = None
        if self.thread:
            try:
                self.thread.join(timeout=4)
                if self.thread.is_alive():
                    errors.append('decoder_not_stopped')
                else:
                    self.thread = None
            except RuntimeError:
                errors.append('decoder_not_stopped')
        if self.port:
            try:
                self._adb('forward','--remove','tcp:'+str(self.port))
                self.port = None
            except SourceError:
                # An already removed forward is an idempotent success only
                # after querying the real list, never based on an error alone.
                try:
                    forwards=self._adb('forward','--list',capture=True).decode().splitlines()
                    if any(line.split()[:2]==[self.serial,'tcp:'+str(self.port)] for line in forwards):
                        errors.append('forward_not_removed')
                    else:self.port=None
                except (SourceError,UnicodeError):errors.append('forward_not_removed')
        if self.remote_installed:
            try:
                # No broad pkill: scope cleanup to this random server path.
                self._adb('shell','rm','-f',self.remote_path)
                self.remote_installed = False
            except SourceError:
                errors.append('server_file_not_removed')
        if self.ime_apk:
            try:
                self._ime_request(2)
                self.ime_release_ack = True
            except SourceError:
                # Android may already have destroyed the input-method service.
                # Missing socket ACK is not proof of failure or successful clear;
                # establish the postconditions below even when an ACK was seen.
                self.ime_release_ack = False
        if self.previous_ime:
            try:
                self._verify_ime_apk(self.ime_apk)
                self._adb('shell','ime','set',self.previous_ime)
                self._adb('shell','am','force-stop','io.pajio.privateinput')
                actual=self._adb('shell','settings','get','secure','default_input_method',capture=True).decode().strip()
                names=self._adb('shell','ps','-A','-o','NAME',capture=True).decode().splitlines()
                if not names or names[0].strip()!='NAME' or actual != self.previous_ime or any(name.strip()=='io.pajio.privateinput' or
                        name.strip().startswith('io.pajio.privateinput:') for name in names):
                    raise SourceError('ime_postcondition_failed')
            except (SourceError,UnicodeError):
                errors.append('ime_cleanup_unconfirmed')
            else:
                self.previous_ime = None
                self.ime_apk = self.ime_uid = None
        elif self.ime_apk:
            errors.append('ime_restore_identity_missing')
        self.ime_nonce[:] = b'\x00' * len(self.ime_nonce)
        with self.condition:
            self.latest = None
            self.static_refresh = None
        self.cleanup_errors = errors
        if errors:
            raise SourceError('private_android_cleanup_failed')
