"""Private transport acceptance: real local WebRTC and synthetic native devices."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import time
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from wearing.device_gateway import DeviceGateway, GatewayScope, GatewayError
from wearing.private_media import InputGate, MediaError, PrivateMediaHost, PrivateSession, create_app, parse_input
from wearing.private_media_sources import AndroidScreencapSource, CapturedFrame, SourceError, X11Source
from wearing.connectors.remote.adapter import NativeAdapter


SCOPE = GatewayScope('tenant_test','daily','actor_test','connector_test','computer_test')


@pytest.fixture(autouse=True)
def isolated_home(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',lambda:tmp_path/'home')


@pytest.fixture
def gate(tmp_path):
    gateway = DeviceGateway(tmp_path/'gateway',private_access_ready=True)
    claim = gateway.begin_human(SCOPE,'session_test',expected_epoch=0)
    gateway.activate_human(SCOPE,'session_test',claim['epoch'])
    return gateway


class FakeSource:
    name = 'synthetic'
    max_fps = 8
    capabilities = {'pointer':True,'text':'unicode','keyboard':True,'touch':True,'scroll':True}
    def __init__(self):
        self.applied = []
        self.released = False
    def capture(self):
        return CapturedFrame(Image.new('RGB',(160,120),(100,140,200)),time.monotonic())
    def apply(self,event):
        self.applied.append(dict(event))
    def release_all(self):
        self.released = True


def config():
    return {'token':'x'*48,'resources':[{**vars(SCOPE),'kind':'computer'}]}


def message(frame,**kw):
    return json.dumps({'type':'input','session_id':'session_test','epoch':3,'gateway_epoch':1,
                       'seq':1,'frame_id':frame['frame_id'],'action':'tap','x':10,'y':20,**kw})


def test_input_scope_replay_and_geometry_are_independent_checks():
    clock = [10.]
    guard = InputGate(SCOPE,'session_test',3,1,clock=lambda:clock[0])
    frame = guard.frame(160,120)
    assert guard.decode(message(frame))[2]=={'action':'tap','x':10,'y':20}
    with pytest.raises(MediaError,match='replayed'):
        guard.decode(message(frame))
    for field,value in [('session_id','other'),('epoch',4),('gateway_epoch',2),('epoch',True)]:
        with pytest.raises(MediaError,match='mismatch'):
            guard.decode(message(frame,seq=2,**{field:value}))
    clock[0] += 2.1
    with pytest.raises(MediaError,match='stale_frame'):
        guard.decode(message(frame,seq=2))
    fresh = guard.frame(160,120)
    guard.frame(120,160)
    with pytest.raises(MediaError,match='stale_frame'):
        guard.decode(message(fresh,seq=3))
    fresh = guard.frame(120,160,1)
    guard.frame(120,160,2)
    with pytest.raises(MediaError,match='stale_frame'):
        guard.decode(message(fresh,seq=4))


@pytest.mark.parametrize('event',[
    {'action':'tap','x':-1,'y':0}, {'action':'tap','x':160,'y':0},
    {'action':'pointer','x':1,'y':2,'phase':'shell'}, {'action':'tap','x':True,'y':0},
    {'action':'scroll','delta_y':float('nan')}, {'action':'text','text':'x'*4097},
    {'action':'text','text':'a\0b'}, {'action':'shell','command':'anything'},
    {'action':'key','phase':'down','key':[]},
])
def test_native_event_allowlist_rejects_untrusted_arguments(event):
    with pytest.raises(MediaError):
        parse_input(event,160,120)


def test_text_is_not_placed_in_subprocess_argv_or_error(monkeypatch):
    calls = []
    def run(args,**kw):
        calls.append((args,kw))
        return b''
    monkeypatch.setattr('wearing.private_media_sources._run',run)
    secret = "p' $dollar `tick` 中文"
    X11Source().apply({'action':'text','text':secret})
    with pytest.raises(SourceError, match='android_private_input_unavailable'):
        AndroidScreencapSource(serial='synthetic').apply({'action':'text','text':secret})
    for args,kw in calls:
        assert all(secret not in str(arg) for arg in args)
        assert isinstance(kw['stdin'],bytes)
    with pytest.raises(SourceError,match='android_private_input_unavailable') as error:
        AndroidScreencapSource(serial='synthetic').apply({'action':'text','text':'private%中文'})
    assert 'private%' not in str(error.value)


def test_x11_text_uses_shared_unicode_cadence_and_codepoint_limit(monkeypatch):
    from wearing.linux_computer_helper import text_input_command
    calls = []
    monkeypatch.setattr('wearing.private_media_sources._run',
                        lambda args, **kwargs: calls.append((args, kwargs)))
    # Astral characters count once, matching Array.from in the native viewer.
    text = '😊' * 32
    source = X11Source(xdotool='/reviewed/xdotool')
    source.apply({'action':'text', 'text':text})
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv == text_input_command(text, maximum=32, xdotool='/reviewed/xdotool')
    assert argv[argv.index('--delay') + 1] == '30'
    assert options['stdin'] == text.encode('utf-8')
    assert all(text not in part for part in argv)


@pytest.mark.parametrize(('text', 'code'), [
    ('中' * 33, 'text_too_long'), ('😊' * 33, 'text_too_long'),
    ('', 'text_invalid'), ('private\nmarker', 'text_invalid'),
    ('private\x00marker', 'text_invalid'), ('private\ud800marker', 'text_invalid'),
])
def test_x11_text_rejects_entire_request_before_any_native_input(monkeypatch, text, code):
    calls = []
    monkeypatch.setattr('wearing.private_media_sources._run',
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    with pytest.raises(SourceError, match='^' + code + '$'):
        X11Source().apply({'action':'text', 'text':text})
    assert calls == []


def test_ready_advertises_limits_and_android_keeps_original_byte_budget(gate, tmp_path):
    from wearing.private_media_android import AndroidScrcpySource
    source = X11Source()
    sent = []
    session = PrivateSession(gate, SCOPE, 'session_test', 3, 1, source, None)
    session.channel = SimpleNamespace(readyState='open', bufferedAmount=0,
                                      send=lambda raw: sent.append(json.loads(raw)))
    session.ready()
    assert sent[0]['capabilities']['text'] == 'unicode'
    assert sent[0]['capabilities']['text_max_chars'] == 32
    assert sent[0]['capabilities']['text_max_bytes'] == 4096
    assert sent[0]['capabilities']['text_disallow_controls'] is True
    android = AndroidScrcpySource(serial='synthetic', server=tmp_path/'unused', unicode_ime=True)
    assert android.capabilities['text'] == 'unicode'
    assert android.capabilities['text_max_chars'] == 4096
    assert android.capabilities['text_max_bytes'] == 4096
    assert 'text_disallow_controls' not in android.capabilities


@pytest.mark.asyncio
async def test_host_auth_and_resource_scope(gate):
    host = PrivateMediaHost(config(),gateway=gate,source_factory=lambda _:FakeSource())
    app = create_app(config(),host=host)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://host') as client:
        assert (await client.get('/v1/status')).status_code==401
        headers = {'Authorization':'Bearer '+'x'*48}
        assert (await client.get('/v1/status',headers=headers)).json()['resources']==['computer_test']
        body = {'scope':vars(replace(SCOPE,identity_id='other')),'session_id':'session_test','gateway_epoch':1}
        reply = await client.post('/v1/clear',headers=headers,json=body)
        assert reply.status_code==409
        assert 'scope' not in reply.json()
        huge = await client.post('/v1/clear',headers=headers,content=b'x'*(256*1024+1))
        assert huge.status_code==409


@pytest.mark.asyncio
async def test_prepare_return_blocks_racing_media_until_awaited_clear(gate,tmp_path):
    async def clear(scope,session):
        assert gate.snapshot(scope.resource_id)['state']=='awaiting_scope'
        with pytest.raises(GatewayError):
            gate.validate_human(scope,session,1)
        with pytest.raises(GatewayError):
            gate.permit_agent(scope.resource_id)
        await asyncio.sleep(0)
        return True
    adapter = NativeAdapter(tmp_path/'data',private_gateway=gate,private_media=SimpleNamespace(clear=clear))
    result = await adapter.apply_human_control({'session_id':'session_test','epoch':3,'revision':2,
        'action':'return','safe_screen_confirmed':True,'scope_confirmed':True},SCOPE)
    assert result['state']=='agent_ready'
    assert result['gateway_epoch']==2


@pytest.mark.asyncio
@pytest.mark.parametrize('release_fails',[False,True])
async def test_media_worker_close_racing_explicit_return_preserves_fence(gate,tmp_path,release_fails):
    source=FakeSource()
    if release_fails:
        def fail():raise SourceError('synthetic_release_failed')
        source.release_all=fail
    class Peer:
        async def close(self):pass
    session=PrivateSession(gate,SCOPE,'session_test',3,1,source,Peer())
    async def clear(scope,session_id):
        assert gate.snapshot(scope.resource_id)['state']=='awaiting_scope'
        # Simulates the capture worker seeing validate_human fail at the return
        # fence before the authenticated clear request reaches the media host.
        await session.close()
        assert gate.snapshot(scope.resource_id)['state']==('paused' if release_fails else 'awaiting_scope')
        with pytest.raises(GatewayError):gate.permit_agent(scope.resource_id)
        return await session.close(pause=False)
    adapter=NativeAdapter(tmp_path/'data',private_gateway=gate,private_media=SimpleNamespace(clear=clear))
    control={'session_id':'session_test','epoch':3,'revision':2,'action':'return',
             'safe_screen_confirmed':True,'scope_confirmed':True}
    if release_fails:
        with pytest.raises(GatewayError):await adapter.apply_human_control(control,SCOPE)
        assert gate.snapshot(SCOPE.resource_id)['state']=='paused'
    else:
        result=await adapter.apply_human_control(control,SCOPE)
        assert result['state']=='agent_ready' and result['gateway_epoch']==2


@pytest.mark.asyncio
async def test_uncertain_flush_never_returns_agent_control(gate,tmp_path):
    async def clear(scope,session):
        raise TimeoutError('synthetic flush timeout')
    adapter = NativeAdapter(tmp_path/'data',private_gateway=gate,private_media=SimpleNamespace(clear=clear))
    with pytest.raises(GatewayError,match='not_cleared'):
        await adapter.apply_human_control({'session_id':'session_test','epoch':3,'revision':2,
            'action':'return','safe_screen_confirmed':True,'scope_confirmed':True},SCOPE)
    assert gate.snapshot(SCOPE.resource_id)['state']=='paused'
    with pytest.raises(GatewayError):
        gate.permit_agent(SCOPE.resource_id)


@pytest.mark.asyncio
async def test_heartbeat_timeout_releases_input_and_stays_paused(gate):
    source = FakeSource()
    class Peer:
        async def close(self):
            pass
    session = PrivateSession(gate,SCOPE,'session_test',3,1,source,Peer())
    session.last_heartbeat = time.monotonic()-16
    session.watchdog_task = asyncio.create_task(session.watch())
    await asyncio.wait_for(session.watchdog_task,3)
    assert session.closed and session.cleared and source.released
    assert gate.snapshot(SCOPE.resource_id)['state']=='paused'


@pytest.mark.asyncio
async def test_real_webrtc_video_input_fencing_and_explicit_clear(gate):
    aiortc = pytest.importorskip('aiortc')
    source = FakeSource()
    host = PrivateMediaHost(config(),gateway=gate,source_factory=lambda _:source)
    viewer = aiortc.RTCPeerConnection(aiortc.RTCConfiguration(iceServers=[]))
    viewer.addTransceiver('video',direction='recvonly')
    channel = viewer.createDataChannel('pajio-control',ordered=True)
    frames,acks,tracks = asyncio.Queue(),asyncio.Queue(),asyncio.Queue()
    @viewer.on('track')
    def track(value):
        tracks.put_nowait(value)
    @channel.on('message')
    def receive(raw):
        value = json.loads(raw)
        if value['type']=='frame':
            frames.put_nowait(value)
        if value['type'] in ('input_ack','error'):
            acks.put_nowait(value)
    try:
        await viewer.setLocalDescription(await viewer.createOffer())
        answer = await host.offer({'scope':vars(SCOPE),'session_id':'session_test','epoch':3,
            'gateway_epoch':1,'type':'offer','sdp':viewer.localDescription.sdp,'ice_servers':[]})
        assert answer['transport']=='webrtc-dtls-srtp'
        assert 'a=fingerprint:sha-256' in answer['sdp']
        await viewer.setRemoteDescription(aiortc.RTCSessionDescription(sdp=answer['sdp'],type='answer'))
        video = await asyncio.wait_for(tracks.get(),5)
        decoded = await asyncio.wait_for(video.recv(),8)
        assert (decoded.width,decoded.height)==(160,120)
        frame = await asyncio.wait_for(frames.get(),5)
        channel.send(message(frame))
        assert (await asyncio.wait_for(acks.get(),3))=={'type':'input_ack','seq':1}
        assert source.applied==[{'action':'tap','x':10,'y':20}]
        # Mutation on the real device gate prevents another command or frame.
        gate.prepare_return(SCOPE,'session_test',1)
        result = await host.clear({'scope':vars(SCOPE),'session_id':'session_test','gateway_epoch':1})
        assert result['cleared'] is True
        assert source.released
        assert gate.snapshot(SCOPE.resource_id)['state']=='awaiting_scope'
        gate.finish_human(SCOPE,'session_test',1,safe_screen_confirmed=True,scope_confirmed=True,
                          clear_media=lambda:result['cleared'])
        assert gate.permit_agent(SCOPE.resource_id).epoch==2
    finally:
        await viewer.close()
        await host.shutdown()


@pytest.mark.asyncio
async def test_live_peer_close_pauses_without_return(gate):
    aiortc = pytest.importorskip('aiortc')
    source = FakeSource()
    host = PrivateMediaHost(config(),gateway=gate,source_factory=lambda _:source)
    viewer = aiortc.RTCPeerConnection(aiortc.RTCConfiguration(iceServers=[]))
    viewer.addTransceiver('video',direction='recvonly')
    channel = viewer.createDataChannel('pajio-control',ordered=True)
    opened = asyncio.Event()
    @channel.on('open')
    def connected():
        opened.set()
    try:
        await viewer.setLocalDescription(await viewer.createOffer())
        answer = await host.offer({'scope':vars(SCOPE),'session_id':'session_test','epoch':3,
            'gateway_epoch':1,'type':'offer','sdp':viewer.localDescription.sdp,'ice_servers':[]})
        await viewer.setRemoteDescription(aiortc.RTCSessionDescription(sdp=answer['sdp'],type='answer'))
        await asyncio.wait_for(opened.wait(),8)
        await viewer.close()
        for _ in range(40):
            if host.sessions[SCOPE.resource_id].closed:
                break
            await asyncio.sleep(.05)
        assert host.sessions[SCOPE.resource_id].closed
        assert gate.snapshot(SCOPE.resource_id)['state']=='paused'
        with pytest.raises(GatewayError):
            gate.permit_agent(SCOPE.resource_id)
    finally:
        await viewer.close()
        await host.shutdown()


@pytest.mark.asyncio
async def test_public_api_offer_routes_only_authenticated_scope(monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from wearing.device_access_api import install_device_access_routes
    import wearing.private_media_access as signaling
    actor = 'b'*64
    calls = []
    async def offer(store,identity,owner,resource,**values):
        calls.append((identity,owner,resource,values))
        return {'type':'answer','sdp':'v=0\r\nsynthetic','gateway_epoch':1}
    monkeypatch.setattr(signaling,'offer',offer)
    monkeypatch.setattr(signaling,'transport',lambda *args:{'kind':'webrtc','ice_servers':[]})
    app = FastAPI()
    @app.middleware('http')
    async def scope(request:Request,call_next):
        request.state.identity_id='daily'
        if request.headers.get('test-auth')=='yes':
            request.scope['pajio.storage_scope']=actor
        return await call_next(request)
    @app.exception_handler(RequestValidationError)
    async def validation(request,error):
        return JSONResponse({'error':'invalid_fields'},status_code=422)
    install_device_access_routes(app,lambda:object(),local_devices=False)
    body = {'session_id':'session_test','epoch':3,'type':'offer','sdp':'v=0\r\nsynthetic'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://worker') as client:
        assert (await client.post('/api/devices/access/computer_test/offer',json=body)).status_code==401
        for extra in ({'scope':vars(SCOPE)},{'ice_servers':[]},{'url':'http://untrusted'}, {'text':'secret-sentinel'}):
            response=await client.post('/api/devices/access/computer_test/offer',json={**body,**extra},headers={'test-auth':'yes'})
            assert response.status_code==422 and 'secret-sentinel' not in response.text
        assert calls==[]
        response=await client.post('/api/devices/access/computer_test/offer',json=body,headers={'test-auth':'yes','x-owner':'forged'})
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        assert calls==[('daily',actor,'computer_test',body)]
        response=await client.get('/api/devices/access/computer_test/transport',headers={'test-auth':'yes'})
        assert response.status_code==200 and response.headers['cache-control']=='no-store'


def test_scrcpy_requires_guard_and_official_server_digest(tmp_path):
    from wearing.private_media_android import AndroidScrcpySource
    path=tmp_path/'server'
    path.write_bytes(b'wrong binary')
    source=AndroidScrcpySource(serial='synthetic',server=path)
    with pytest.raises(SourceError,match='not_authorized'):
        source.capture()
    source.set_guard(lambda:None)
    with pytest.raises(SourceError,match='digest_mismatch'):
        source.capture()


def test_unicode_delivery_uses_private_nonce_socket_not_argv_broadcast_or_clipboard(monkeypatch,tmp_path):
    from wearing.private_media_android import AndroidScrcpySource,IME,PRIVATE_IME_SHA256
    source=AndroidScrcpySource(serial='synthetic',server=tmp_path/'unused',unicode_ime=True)
    source.set_guard(lambda:None)
    calls=[]; packets=[]
    def adb(*args,**kwargs):
        calls.append((args,kwargs))
        if args==('shell','settings','get','secure','default_input_method'):
            return b'org.keyboard/.IME\n'
        if args==('shell','ime','list','-a','-s'):
            return IME.encode()+b'\n'
        if args==('shell','pm','path','io.pajio.privateinput'):
            return b'package:/data/app/test/base.apk\n'
        if args==('shell','cmd','package','list','packages','-U','io.pajio.privateinput'):
            return b'package:io.pajio.privateinput uid:10001\n'
        if args==('shell','sha256sum','/data/app/test/base.apk'):
            return (PRIVATE_IME_SHA256+'  /data/app/test/base.apk\n').encode()
        if args==('shell','ps','-A','-o','NAME'):
            return b'NAME\ninit\n'
        if args[:2]==('shell','-T'):
            packet=bytes(kwargs['stdin']);packets.append(packet)
            return b'\x03' if packet[36]==1 and len(packet)==41 else b'\x00'
        return b''
    monkeypatch.setattr(source,'_adb',adb)
    secret='中文口令✨with%symbol'
    source.apply({'action':'text','text':secret})
    assert source.capabilities['text']=='unicode'
    assert all(secret not in str(args) for args,kw in calls)
    assert all(args[:2]==('shell','-T') for args,kw in calls if kw.get('stdin'))
    assert all('broadcast' not in str(args) and 'CLIPBOARD' not in str(args) for args,_ in calls)
    assert packets[0].startswith(b'PIM1') and packets[1][41:]==secret.encode()
    assert source.previous_ime=='org.keyboard/.IME'
    source.release_all()
    assert len({packet[4:36] for packet in packets})==1
    assert packets[-1][36]==2 and len(packets[-1])==41
    assert ('shell','ime','set','org.keyboard/.IME') in [args for args,_ in calls]
    assert ('shell','am','force-stop','io.pajio.privateinput') in [args for args,_ in calls]
    assert source.ime_nonce==bytearray(32) and source.ime_apk is None and source.ime_uid is None


@pytest.mark.parametrize('obstacle',[None,'ime_mismatch','process_present','unverified_process_list'])
def test_ime_lost_release_ack_requires_verified_cleanup_and_can_retry(monkeypatch,tmp_path,obstacle):
    from wearing.private_media_android import AndroidScrcpySource,PRIVATE_IME_SHA256
    source=AndroidScrcpySource(serial='synthetic',server=tmp_path/'unused',unicode_ime=True)
    source.previous_ime='org.keyboard/.IME';source.ime_apk='/data/app/test/base.apk';source.ime_uid=10001
    state={'obstacle':obstacle};calls=[]
    def request(*args):raise SourceError('android_text_delivery_uncertain')
    def adb(*args,**kw):
        calls.append(args)
        if args==('shell','sha256sum','/data/app/test/base.apk'):
            return (PRIVATE_IME_SHA256+'  /data/app/test/base.apk\n').encode()
        if args==('shell','settings','get','secure','default_input_method'):
            return b'wrong/.IME\n' if state['obstacle']=='ime_mismatch' else b'org.keyboard/.IME\n'
        if args==('shell','ps','-A','-o','NAME'):
            if state['obstacle']=='process_present':return b'NAME\nio.pajio.privateinput\n'
            if state['obstacle']=='unverified_process_list':return b''
            return b'NAME\ninit\n'
        return b''
    monkeypatch.setattr(source,'_ime_request',request);monkeypatch.setattr(source,'_adb',adb)
    if obstacle:
        with pytest.raises(SourceError,match='private_android_cleanup_failed'):source.release_all()
        assert source.previous_ime=='org.keyboard/.IME' and source.ime_apk
        assert source.cleanup_errors==['ime_cleanup_unconfirmed']
        state['obstacle']=None
    source.release_all()
    assert source.ime_release_ack is False and not source.cleanup_errors
    assert source.previous_ime is None and source.ime_apk is None and source.ime_uid is None
    assert ('shell','am','force-stop','io.pajio.privateinput') in calls


@pytest.mark.asyncio
async def test_closed_session_retries_only_cleanup_and_retains_pause_until_proven(gate):
    source=FakeSource();attempts=[]
    def release():
        attempts.append(True)
        if len(attempts)==1:raise SourceError('synthetic transient cleanup failure')
        source.released=True
    source.release_all=release
    class Peer:
        async def close(self):pass
    session=PrivateSession(gate,SCOPE,'session_test',3,1,source,Peer())
    assert not await session.close()
    assert session.closed and not session.cleared and session.cleanup_code=='native_cleanup_failed'
    assert gate.snapshot(SCOPE.resource_id)['state']=='paused'
    assert await session.close()
    assert session.cleared and session.cleanup_attempts==2 and session.cleanup_code is None
    assert gate.snapshot(SCOPE.resource_id)['state']=='paused'
    assert not source.applied


def test_unicode_uncertain_ack_has_no_automatic_retry(monkeypatch,tmp_path):
    from wearing.private_media_android import AndroidScrcpySource,PRIVATE_IME_SHA256
    source=AndroidScrcpySource(serial='synthetic',server=tmp_path/'unused',unicode_ime=True)
    source.set_guard(lambda:None);source.previous_ime='org.keyboard/.IME';source.ime_apk='/data/app/test/base.apk';source.ime_uid=10001
    sends=[]
    def adb(*args,**kw):
        if args==('shell','sha256sum','/data/app/test/base.apk'):
            return (PRIVATE_IME_SHA256+'  /data/app/test/base.apk\n').encode()
        sends.append(bytes(kw['stdin']))
        return b'\x04'
    monkeypatch.setattr(source,'_adb',adb)
    with pytest.raises(SourceError,match='delivery_uncertain'):
        source.apply({'action':'text','text':'synthetic marker'})
    assert len(sends)==1


@pytest.mark.parametrize('initialized',[False,True])
def test_private_input_rejects_replaced_installed_apk_before_transmitting(monkeypatch,tmp_path,initialized):
    from wearing.private_media_android import AndroidScrcpySource,IME
    source=AndroidScrcpySource(serial='synthetic',server=tmp_path/'unused',unicode_ime=True)
    source.set_guard(lambda:None)
    if initialized:
        source.previous_ime='org.keyboard/.IME';source.ime_apk='/data/app/test/base.apk';source.ime_uid=10001
    calls=[]
    replies={
        ('shell','settings','get','secure','default_input_method'): b'org.keyboard/.IME\n',
        ('shell','ime','list','-a','-s'): IME.encode()+b'\n',
        ('shell','pm','path','io.pajio.privateinput'): b'package:/data/app/test/base.apk\n',
        ('shell','cmd','package','list','packages','-U','io.pajio.privateinput'): b'package:io.pajio.privateinput uid:10001\n',
        ('shell','sha256sum','/data/app/test/base.apk'): b'0'*64+b'  /data/app/test/base.apk\n',
    }
    def adb(*args,**kw):
        calls.append((args,kw))
        return replies.get(args,b'')
    monkeypatch.setattr(source,'_adb',adb)
    with pytest.raises(SourceError,match='^android_private_input_digest_mismatch$'):
        source.apply({'action':'text','text':'synthetic-private-marker'})
    assert all('app_process' not in args and not kw.get('stdin') for args,kw in calls)
    assert not any(args[:3]==('shell','ime','set') for args,kw in calls)
    assert all('synthetic-private-marker' not in str(args) for args,kw in calls)


def test_scrcpy_framed_h264_rotation_and_decoder_cleanup(tmp_path):
    av=pytest.importorskip('av')
    import socket
    import struct
    import threading
    from fractions import Fraction
    from wearing.private_media_android import AndroidScrcpySource
    encoder=av.CodecContext.create('libx264','w')
    encoder.width,encoder.height,encoder.pix_fmt=160,120,'yuv420p'
    encoder.time_base=Fraction(1,24)
    encoder.options={'preset':'ultrafast','tune':'zerolatency'}
    picture=av.VideoFrame.from_image(Image.new('RGB',(160,120),(30,140,220)))
    picture.pts=0
    packets=encoder.encode(picture)
    assert packets
    payload=bytes(packets[0])
    first=b'h264'+struct.pack('>III',1<<31,160,120)+struct.pack('>QI',1<<61,len(payload))+payload
    left,right=socket.socketpair()
    left.settimeout(.1)
    source=AndroidScrcpySource(serial='synthetic',server=tmp_path/'unused')
    source.set_guard(lambda:None)
    source.sock=left
    thread=threading.Thread(target=source._decode,args=(first,))
    source.thread=thread
    thread.start()
    try:
        deadline=time.monotonic()+2
        while source.latest is None and time.monotonic()<deadline:
            time.sleep(.01)
        assert source.latest and source.latest.image.size==(160,120)
        assert source.latest.geometry_token==1
        # An equal-sized second capture session still invalidates prior input.
        right.sendall(struct.pack('>III',1<<31,160,120)+struct.pack('>QI',1<<61,len(payload))+payload)
        deadline=time.monotonic()+2
        while (source.latest is None or source.latest.geometry_token!=2) and time.monotonic()<deadline:
            time.sleep(.01)
        assert source.latest and source.latest.geometry_token==2
    finally:
        source.release_all()
        right.close()
    assert source.latest is None and not thread.is_alive()


@pytest.mark.asyncio
async def test_capture_fps_does_not_count_repeated_cached_android_frame(gate):
    source=FakeSource()
    cached=source.capture()
    source.capture=lambda:cached
    session=PrivateSession(gate,SCOPE,'session_test',3,1,source,SimpleNamespace())
    packets=[];session.send=packets.append
    await session.capture();await session.capture()
    assert len(session.capture_times)==1 and packets[-1]['capture_fps']==0
    cached=replace(cached,captured_at=cached.captured_at+.1)
    await session.capture()
    assert packets[-1]['capture_fps']==10


def test_static_scrcpy_refresh_reads_new_pixels_and_preserves_timestamp(monkeypatch,tmp_path):
    from wearing.private_media_android import AndroidScrcpySource
    from wearing.private_media_sources import AndroidScreencapSource
    source=AndroidScrcpySource(serial='synthetic',server=tmp_path/'unused')
    source.set_guard(lambda:None)
    monkeypatch.setattr(source,'_start',lambda:None)
    old=CapturedFrame(Image.new('RGB',(160,120),'red'),time.monotonic()-3,1)
    fresh=CapturedFrame(Image.new('RGB',(160,120),'blue'),time.monotonic())
    source.latest=old
    calls=[]
    def capture(_):
        calls.append(True)
        return fresh
    monkeypatch.setattr(AndroidScreencapSource,'capture',capture)
    result=source.capture()
    assert result.image.getpixel((0,0))==(0,0,255)
    assert result.captured_at==fresh.captured_at and result.geometry_token==1
    assert source.latest is old and old.captured_at<fresh.captured_at
    assert source.last_capture_mode=='adb-static-refresh'
    assert source.capture() is result and calls==[True]
    source.release_all()
    assert source.static_refresh is None


@pytest.mark.parametrize('failure',['capture','rotation'])
def test_static_refresh_never_returns_expired_pixels_on_failure(monkeypatch,tmp_path,failure):
    from wearing.private_media_android import AndroidScrcpySource
    from wearing.private_media_sources import AndroidScreencapSource
    source=AndroidScrcpySource(serial='synthetic',server=tmp_path/'unused')
    source.set_guard(lambda:None)
    monkeypatch.setattr(source,'_start',lambda:None)
    source.latest=CapturedFrame(Image.new('RGB',(160,120),'red'),time.monotonic()-3,1)
    def capture(_):
        if failure=='capture':raise SourceError('screen_capture_unavailable')
        return CapturedFrame(Image.new('RGB',(120,160),'blue'),time.monotonic())
    monkeypatch.setattr(AndroidScreencapSource,'capture',capture)
    with pytest.raises(SourceError):source.capture()
    assert source.static_refresh is None
