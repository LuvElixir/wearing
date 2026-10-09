"""Private, device-terminated WebRTC media and human input.

Run behind the operator's authenticated TLS proxy on the execution VM. The
public relay forwards only offer/answer and fixed ownership metadata. Video is
DTLS-SRTP; input is a reliable DTLS/SCTP data channel terminating here. No video,
input text, SDP, or ICE credentials are persisted or sent to the agent runtime.
"""
import argparse
import asyncio
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from fractions import Fraction
import hmac
import json
import math
from pathlib import Path
import secrets
import time

from .cloud.instance import read_private
from .device_gateway import DeviceGateway, GatewayError, GatewayScope, identifier
from .private_media_sources import SourceError, configured_source


class MediaError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _integer(value, low=0, high=2**53-1):
    if type(value) is not int or not low <= value <= high:
        raise MediaError('invalid_input')
    return value


def _number(value, low, high):
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
        raise MediaError('invalid_input')
    return value


def parse_input(value, width, height):
    """Build an allowlisted event; never forward viewer-supplied native args."""
    action = value.get('action')
    out = {'action':action}
    if action in ('pointer','tap','swipe'):
        out.update(x=round(_number(value.get('x'),0,width-1)),
                   y=round(_number(value.get('y'),0,height-1)))
    if action == 'pointer':
        if value.get('phase') not in ('move','down','up'):
            raise MediaError('invalid_input')
        out.update(phase=value['phase'],button=_integer(value.get('button',0),0,2))
    elif action == 'swipe':
        out.update(to_x=round(_number(value.get('to_x'),0,width-1)),
                   to_y=round(_number(value.get('to_y'),0,height-1)),
                   duration_ms=_integer(value.get('duration_ms',300),50,1000))
    elif action == 'scroll':
        out.update(delta_x=_number(value.get('delta_x',0),-2000,2000),
                   delta_y=_number(value.get('delta_y',0),-2000,2000))
    elif action == 'key':
        if value.get('phase') not in ('down','up') or not isinstance(value.get('key'),str) or not 1 <= len(value['key']) <= 20:
            raise MediaError('invalid_input')
        out.update(key=value['key'],phase=value['phase'])
    elif action == 'text':
        text = value.get('text')
        if not isinstance(text,str) or not text or '\0' in text:
            raise MediaError('invalid_text')
        try:
            if len(text.encode('utf-8')) > 4096:
                raise MediaError('text_too_large')
        except UnicodeEncodeError:
            raise MediaError('invalid_text') from None
        out['text'] = text
    elif action != 'tap':
        raise MediaError('unsupported_input')
    return out


class InputGate:
    """Session binding, replay and stale geometry checks independent of WebRTC."""
    def __init__(self, scope, session_id, epoch, gateway_epoch, *, clock=time.monotonic):
        self.scope, self.session_id = scope, identifier(session_id)
        self.epoch, self.gateway_epoch = _integer(epoch,1), _integer(gateway_epoch,1)
        self.clock = clock
        self.last_seq = 0
        self.frames = OrderedDict()
        self.geometry = None
        self.source_geometry_token = None
        self.geometry_revision = 0

    def frame(self, width, height, geometry_token=None):
        _integer(width,1,8192); _integer(height,1,8192)
        if self.geometry != (width,height) or self.source_geometry_token != geometry_token:
            self.geometry = (width,height)
            self.source_geometry_token = geometry_token
            self.geometry_revision += 1
            self.frames.clear()
        frame_id = secrets.token_hex(12)
        self.frames[frame_id] = (self.clock(),self.geometry,self.geometry_revision)
        while len(self.frames)>64:
            self.frames.popitem(last=False)
        return {'type':'frame','frame_id':frame_id,'width':width,'height':height,
                'geometry_revision':self.geometry_revision,'gateway_epoch':self.gateway_epoch}

    def decode(self, raw):
        if not isinstance(raw,str) or len(raw)>20*1024:
            raise MediaError('invalid_message')
        try:
            if len(raw.encode('utf-8'))>20*1024:
                raise MediaError('message_too_large')
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise MediaError('invalid_message') from None
        if not isinstance(value,dict):
            raise MediaError('invalid_message')
        if (value.get('session_id') != self.session_id or type(value.get('epoch')) is not int or
                value['epoch'] != self.epoch or type(value.get('gateway_epoch')) is not int or
                value['gateway_epoch'] != self.gateway_epoch):
            raise MediaError('private_session_mismatch')
        if value.get('type') == 'heartbeat':
            return 'heartbeat',None,None
        if value.get('type') != 'input':
            raise MediaError('unsupported_message')
        seq = _integer(value.get('seq'),1)
        if seq <= self.last_seq:
            raise MediaError('input_replayed')
        self.last_seq = seq
        frame_id = value.get('frame_id')
        if not isinstance(frame_id,str):
            raise MediaError('frame_required')
        frame = self.frames.get(frame_id)
        if not frame or self.clock()-frame[0]>2 or frame[1]!=self.geometry:
            raise MediaError('stale_frame')
        return frame_id,seq,parse_input(value,*frame[1])

    def validate_frame(self, frame_id):
        frame = self.frames.get(frame_id)
        if not frame or self.clock()-frame[0]>2 or frame[1]!=self.geometry:
            raise MediaError('stale_frame')

    def clear(self):
        self.frames.clear()


def validated_ice(value):
    """Only the authenticated worker supplies ephemeral TURN configuration."""
    if not isinstance(value,list) or len(value)>8:
        raise MediaError('invalid_ice_configuration')
    result = []
    for server in value:
        if not isinstance(server,dict) or set(server)-{'urls','username','credential'}:
            raise MediaError('invalid_ice_configuration')
        urls = server.get('urls')
        if isinstance(urls,str):
            urls = [urls]
        if (not isinstance(urls,list) or not 1 <= len(urls) <= 8 or
                any(not isinstance(url,str) or len(url)>512 or not url.startswith(('stun:','stuns:','turn:','turns:'))
                    or any(ord(c)<33 for c in url) for url in urls)):
            raise MediaError('invalid_ice_configuration')
        if any(not isinstance(server.get(key,''),str) or len(server.get(key,''))>1024
               for key in ('username','credential')):
            raise MediaError('invalid_ice_configuration')
        result.append({**server,'urls':urls})
    return result


class PrivateSession:
    def __init__(self, gateway, scope, session_id, epoch, gateway_epoch, source, pc):
        self.gateway, self.scope, self.source, self.pc = gateway,scope,source,pc
        self.input_gate = InputGate(scope,session_id,epoch,gateway_epoch)
        self.channel = None
        self.closed = False
        self.cleared = False
        self.cleanup_attempts = 0
        self.cleanup_code = None
        self.last_heartbeat = time.monotonic()
        self.started = time.monotonic()
        self.capture_times = deque(maxlen=30)
        self.pending_native = set()
        self.native_lock = asyncio.Lock()
        self.close_lock = asyncio.Lock()
        self.inputs = asyncio.Queue(maxsize=32)
        self.input_task = None
        self.watchdog_task = None
        self.track = None
        if callable(getattr(source,'set_guard',None)):
            source.set_guard(lambda:self.gateway.validate_human(*self.binding))

    @property
    def binding(self):
        gate = self.input_gate
        return (gate.scope,gate.session_id,gate.gateway_epoch)

    def send(self, value):
        if self.closed or not self.channel or self.channel.readyState!='open':
            return False
        if self.channel.bufferedAmount>64*1024:
            self.schedule_close()
            return False
        self.channel.send(json.dumps(value,separators=(',',':')))
        return True

    def schedule_close(self):
        asyncio.create_task(self.close())

    def bind_channel(self, channel):
        if self.channel is not None or channel.label!='pajio-control' or not channel.ordered or channel.maxRetransmits is not None or channel.maxPacketLifeTime is not None:
            channel.close()
            self.schedule_close()
            return
        self.channel = channel

        @channel.on('open')
        def opened():
            self.ready()

        @channel.on('message')
        def message(raw):
            self.message(raw)

        @channel.on('close')
        def closed():
            if not self.closed:
                self.schedule_close()

        if channel.readyState=='open':
            self.ready()

    def ready(self):
        try:
            self.gateway.validate_human(*self.binding)
        except GatewayError:
            self.schedule_close()
            return
        gate = self.input_gate
        self.send({'type':'ready','session_id':gate.session_id,'epoch':gate.epoch,
                   'gateway_epoch':gate.gateway_epoch,'heartbeat_ms':5000,
                   'source':self.source.name,'max_fps':self.source.max_fps,
                   'capabilities':self.source.capabilities})

    def message(self, raw):
        if self.closed:
            return
        try:
            self.gateway.validate_human(*self.binding)
            frame_id,seq,event = self.input_gate.decode(raw)
            if frame_id == 'heartbeat':
                self.last_heartbeat = time.monotonic()
                self.send({'type':'heartbeat_ack','gateway_epoch':self.input_gate.gateway_epoch})
                return
            if self.inputs.full():
                raise MediaError('input_backpressure')
            self.inputs.put_nowait((frame_id,seq,event))
        except (GatewayError,MediaError) as error:
            self.send({'type':'error','code':error.code})
            if isinstance(error,GatewayError) or error.code in ('private_session_mismatch','input_backpressure'):
                self.schedule_close()

    async def native(self, fn):
        # Shield the native call. Cancellation must not drop the OS fence while
        # a subprocess/thread can still read a frame or enter a secret.
        async with self.native_lock:
            if self.closed:
                raise MediaError('private_session_closed')
            def guarded():
                with self.gateway.human_guard(*self.binding):
                    if self.closed:
                        raise MediaError('private_session_closed')
                    return fn()
            task = asyncio.create_task(asyncio.to_thread(guarded))
            self.pending_native.add(task)
            task.add_done_callback(self.pending_native.discard)
            return await asyncio.shield(task)

    async def capture(self):
        frame = await self.native(self.source.capture)
        if self.closed:
            raise MediaError('private_session_closed')
        self.gateway.validate_human(*self.binding)
        # A scrcpy source may return the same newest decoded frame on several
        # WebRTC ticks; do not mislabel those retransmissions as capture FPS.
        if not self.capture_times or frame.captured_at > self.capture_times[-1]:
            self.capture_times.append(frame.captured_at)
        times = self.capture_times
        fps = (len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0
        metadata = self.input_gate.frame(frame.image.width,frame.image.height,frame.geometry_token)
        self.send({**metadata,'source':self.source.name,'capture_fps':round(fps,2),
                   'capture_mode':getattr(self.source,'last_capture_mode',self.source.name),
                   'max_fps':self.source.max_fps})
        return frame

    async def process_inputs(self):
        while not self.closed:
            item = await self.inputs.get()
            if item is None or self.closed:
                break
            frame_id,seq,event = item
            try:
                def apply():
                    self.input_gate.validate_frame(frame_id)
                    geometry = getattr(self.source,'geometry',None)
                    if callable(geometry) and tuple(geometry()) != self.input_gate.geometry:
                        raise MediaError('stale_frame')
                    if getattr(self.source,'geometry_token',None) != self.input_gate.source_geometry_token:
                        raise MediaError('stale_frame')
                    self.input_gate.validate_frame(frame_id)
                    self.source.apply(event)
                await self.native(apply)
                self.send({'type':'input_ack','seq':seq})
            except (MediaError,GatewayError,SourceError) as error:
                code = getattr(error,'code',str(error))
                self.send({'type':'error','code':code,'seq':seq})
                if isinstance(error,GatewayError) or (isinstance(error,SourceError) and
                        str(error) not in ('unsupported_input','unsupported_key','android_text_ascii_only')):
                    self.schedule_close()
            except Exception:
                self.send({'type':'error','code':'native_input_failed','seq':seq})
                self.schedule_close()
            finally:
                # Drop all references to text after delivery; no retry journal.
                event.clear()

    async def watch(self):
        while not self.closed:
            await asyncio.sleep(1)
            try:
                # Lease renewal belongs to authenticated connector polling,
                # not to a viewer that might outlive revoked server authority.
                state = self.gateway.snapshot(self.scope.resource_id)
                if (state['session_id']==self.input_gate.session_id and
                        state['epoch']==self.input_gate.gateway_epoch and state['state']=='awaiting_scope'):
                    await self.close(pause=False)
                    return
                self.gateway.validate_human(*self.binding)
                if time.monotonic()-self.last_heartbeat>15:
                    raise MediaError('private_heartbeat_timeout')
            except (GatewayError,MediaError):
                await self.close()
                return

    async def close(self, *, pause=True):
        async with self.close_lock:
            if self.closed:
                if self.cleared:
                    return True
                # Only re-run cleanup; never revive a closed peer, replay input,
                # or trust the new viewer's claim that old media was cleared.
                return await self._finish_close()
            self.closed = True
            if pause:
                try:
                    self.gateway.pause(*self.binding,preserve_return=True)
                except GatewayError:
                    pass
            self.input_gate.clear()
            while not self.inputs.empty():
                item = self.inputs.get_nowait()
                if item:
                    item[2].clear()
            self.inputs.put_nowait(None)
            # Await in-flight native calls instead of cancelling their threads.
            if self.pending_native:
                await asyncio.gather(*list(self.pending_native),return_exceptions=True)
            if self.input_task and self.input_task is not asyncio.current_task():
                await self.input_task
            return await self._finish_close()

    async def _finish_close(self):
        # Caller holds close_lock and has fenced the session and drained input.
        self.cleanup_attempts += 1
        self.cleanup_code = None
        released = False
        try:
            def release():
                with self.gateway.native_lock(self.scope.resource_id):
                    self.source.release_all()
            await asyncio.to_thread(release)
            released = True
        except Exception:
            self.cleanup_code = 'native_cleanup_failed'
        try:
            if self.track:
                self.track.stop()
            if self.channel:
                self.channel.close()
            await self.pc.close()
            self.cleared = released
        except Exception:
            self.cleanup_code = 'transport_close_failed'
            self.cleared = False
        if not self.cleared:
            try:
                self.gateway.pause(*self.binding)
            except GatewayError:
                pass
        if self.watchdog_task and self.watchdog_task is not asyncio.current_task():
            self.watchdog_task.cancel()
        return self.cleared


def video_track(session):
    from aiortc import VideoStreamTrack
    from aiortc.mediastreams import MediaStreamError
    from av import VideoFrame

    class PrivateVideoTrack(VideoStreamTrack):
        def __init__(self):
            super().__init__()
            self.next_capture = time.monotonic()

        async def recv(self):
            await asyncio.sleep(max(0,self.next_capture-time.monotonic()))
            self.next_capture = time.monotonic()+1/session.source.max_fps
            if session.closed:
                raise MediaStreamError
            try:
                frame = await session.capture()
                video = VideoFrame.from_image(frame.image)
                video.pts = int((time.monotonic()-session.started)*90000)
                video.time_base = Fraction(1,90000)
                session.gateway.validate_human(*session.binding)
                return video
            except asyncio.CancelledError:
                raise
            except Exception:
                session.schedule_close()
                raise MediaStreamError from None
    return PrivateVideoTrack()


class PrivateMediaHost:
    def __init__(self, config, *, gateway=None, source_factory=configured_source):
        self.config = config
        self.gateway = gateway or DeviceGateway(config.get('gateway_root'),private_access_ready=True)
        self.source_factory = source_factory
        self.bindings = {}
        for value in config.get('resources',[]):
            rid = identifier(value['resource_id'])
            for field in ('tenant_id','identity_id','connector_id'):
                identifier(value[field])
            if rid in self.bindings or value.get('kind') not in ('computer','android'):
                raise MediaError('invalid_media_binding')
            self.bindings[rid] = value
        if not self.bindings:
            raise MediaError('missing_media_bindings')
        self.sessions = {}
        self.lock = asyncio.Lock()

    def check_scope(self, body):
        try:
            scope = GatewayScope(**body['scope'])
            binding = self.bindings[scope.resource_id]
            if any(getattr(scope,key)!=binding[key] for key in ('tenant_id','identity_id','connector_id')):
                raise MediaError('private_resource_not_bound')
            session_id = identifier(body['session_id'])
            gateway_epoch = _integer(body['gateway_epoch'],1)
            return scope,session_id,gateway_epoch,binding
        except (KeyError,TypeError,GatewayError):
            raise MediaError('invalid_private_scope') from None

    async def offer(self, body):
        from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription
        scope,session_id,gateway_epoch,binding = self.check_scope(body)
        epoch = _integer(body.get('epoch'),1)
        sdp = body.get('sdp')
        if body.get('type')!='offer' or not isinstance(sdp,str) or not 1<=len(sdp)<=200_000:
            raise MediaError('invalid_offer')
        ice = validated_ice(body.get('ice_servers',[]))
        async with self.lock:
            self.gateway.validate_human(scope,session_id,gateway_epoch)
            previous = self.sessions.get(scope.resource_id)
            if previous:
                # Renegotiation cannot replace an active viewer. A new explicit
                # takeover has a new gateway epoch, fenced by the database.
                if not previous.closed and previous.binding==(scope,session_id,gateway_epoch):
                    raise MediaError('private_viewer_already_connected')
                if not await previous.close():
                    raise MediaError('private_media_not_cleared')
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(**item) for item in ice]))
            source = self.source_factory(binding)
            session = PrivateSession(self.gateway,scope,session_id,epoch,gateway_epoch,source,pc)
            self.sessions[scope.resource_id] = session
            session.track = video_track(session)
            pc.addTrack(session.track)

            @pc.on('datachannel')
            def datachannel(channel):
                session.bind_channel(channel)

            @pc.on('connectionstatechange')
            async def connectionstatechange():
                if pc.connectionState in ('closed','failed','disconnected') and not session.closed:
                    await session.close()

            @pc.on('iceconnectionstatechange')
            async def iceconnectionstatechange():
                if pc.iceConnectionState in ('failed','closed','disconnected') and not session.closed:
                    await session.close()

            session.input_task = asyncio.create_task(session.process_inputs())
            session.watchdog_task = asyncio.create_task(session.watch())
            try:
                await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp,type='offer'))
                await asyncio.wait_for(pc.setLocalDescription(await pc.createAnswer()),timeout=12)
                self.gateway.validate_human(scope,session_id,gateway_epoch)
                return {'type':'answer','sdp':pc.localDescription.sdp,'gateway_epoch':gateway_epoch,
                        'transport':'webrtc-dtls-srtp'}
            except Exception:
                await session.close()
                raise MediaError('private_negotiation_failed') from None

    async def clear(self, body):
        scope,session_id,gateway_epoch,_ = self.check_scope(body)
        async with self.lock:
            # Only the connector's prepared return can request a clean shutdown
            # without pausing. The DB fence prevents a racing second offer.
            with self.gateway.tx() as db:
                row = self.gateway._session(db,scope,session_id,gateway_epoch)
                if row['state']!='awaiting_scope':
                    raise MediaError('private_return_not_prepared')
            session = self.sessions.get(scope.resource_id)
            if session:
                if session.binding!=(scope,session_id,gateway_epoch):
                    raise MediaError('private_session_mismatch')
                if not await session.close(pause=False):
                    raise MediaError('private_media_not_cleared')
                del self.sessions[scope.resource_id]
            return {'cleared':True,'session_id':session_id,'gateway_epoch':gateway_epoch}

    async def shutdown(self):
        await asyncio.gather(*(session.close() for session in list(self.sessions.values())),return_exceptions=True)

    async def status(self):
        def available(binding):
            try:
                source = self.source_factory(binding)
                probe = getattr(source,'available',None)
                return probe() is True if callable(probe) else True
            except Exception:
                return False
        results = await asyncio.gather(*(asyncio.to_thread(available,binding) for binding in self.bindings.values()))
        return {'ready':any(results),'resources':[rid for rid,ok in zip(self.bindings,results) if ok],
                'sessions':{rid:{'closed':s.closed,'cleared':s.cleared,'cleanup_attempts':s.cleanup_attempts,
                                 'cleanup_code':s.cleanup_code}
                            for rid,s in self.sessions.items()}}


def create_app(config, *, host=None):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    token = config.get('token')
    if not isinstance(token,str) or len(token)<32:
        raise MediaError('private_host_token_required')
    host = host or PrivateMediaHost(config)

    @asynccontextmanager
    async def lifespan(app):
        host.gateway.recover(list(host.bindings))
        yield
        await host.shutdown()

    app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.private_media = host

    async def body(request):
        authorization = request.headers.get('authorization','')
        if not hmac.compare_digest(authorization,'Bearer '+token):
            raise MediaError('private_host_unauthorized')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>256*1024:
                raise MediaError('private_request_too_large')
        try:
            value = json.loads(raw)
        except (ValueError,UnicodeError):
            raise MediaError('invalid_private_request') from None
        if not isinstance(value,dict):
            raise MediaError('invalid_private_request')
        return value

    @app.exception_handler(MediaError)
    async def media_error(request, error):
        return JSONResponse({'error':error.code},status_code=401 if error.code=='private_host_unauthorized' else 409,
                            headers={'Cache-Control':'no-store'})

    @app.exception_handler(GatewayError)
    async def gateway_error(request, error):
        return JSONResponse({'error':error.code},status_code=409,headers={'Cache-Control':'no-store'})

    @app.post('/v1/offer')
    async def offer(request: Request):
        return JSONResponse(await host.offer(await body(request)),headers={'Cache-Control':'no-store'})

    @app.get('/v1/status')
    async def status(request: Request):
        if not hmac.compare_digest(request.headers.get('authorization',''),'Bearer '+token):
            raise MediaError('private_host_unauthorized')
        return JSONResponse(await host.status(),headers={'Cache-Control':'no-store'})

    @app.post('/v1/clear')
    async def clear(request: Request):
        return JSONResponse(await host.clear(await body(request)),headers={'Cache-Control':'no-store'})

    return app


def main():
    parser = argparse.ArgumentParser(description='Private device-terminated Pajio WebRTC host')
    parser.add_argument('--config',required=True)
    parser.add_argument('--port',type=int,default=8792)
    args = parser.parse_args()
    config = json.loads(read_private(Path(args.config)))
    import uvicorn
    # External access is exclusively through the operator's mTLS proxy. Do not
    # bind this bearer-authenticated internal service on all interfaces.
    uvicorn.run(create_app(config),host='127.0.0.1',port=args.port,access_log=False,log_level='warning')


if __name__ == '__main__':
    main()
