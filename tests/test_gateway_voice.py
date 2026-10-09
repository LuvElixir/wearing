import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from starlette.middleware.trustedhost import TrustedHostMiddleware
from wearing.cloud.gateway import create_gateway_app
from wearing.cloud.worker import TenantBoundary
from test_gateway import lab, ORIGIN, ISSUER

class Remote:
    def __init__(self): self.messages=[]; self.queue=asyncio.Queue()
    async def send(self, message):
        self.messages.append(message)
        if len(self.messages)==1:
            self.take=json.loads(message)['take']
            await self.queue.put(json.dumps({'type':'ready','take':self.take}))
        elif isinstance(message,str):
            await self.queue.put(json.dumps({'type':'final','take':self.take,'text':'合成测试'}))
            await self.queue.put(None)
    def __aiter__(self): return self
    async def __anext__(self):
        result=await self.queue.get()
        if result is None: raise StopAsyncIteration
        return result

class Connector:
    def __init__(self): self.calls=[]
    @asynccontextmanager
    async def __call__(self,url,**kwargs):
        remote=Remote();self.calls.append((url,kwargs,remote))
        yield remote

def start(token):
    return {'type':'start','take':'test_take','identity':'daily','token':'page-token','access':token,'format':'pcm_s16le_16000_mono'}

async def test_gateway_voice_routes_with_server_credential_and_streams_without_exposing_user_access(tmp_path):
    async with lab(tmp_path) as (root,a,_,control,_,_,_):
        connector=Connector();app=create_gateway_app(root,voice_connector=connector)
        try:
            access=control.login(ISSUER,'alice')
            client=TestClient(app,base_url=ORIGIN)
            with client.websocket_connect('wss://wearing.example/api/voice/stream') as ws:
                ws.send_json(start(access));assert ws.receive_json()['type']=='ready'
                ws.send_bytes(b'\0\0'*80);ws.send_json({'type':'finish','bytes':160})
                assert ws.receive_json()['text']=='合成测试'
            url,kwargs,remote=connector.calls[0]
            assert url=='ws://127.0.0.1:39001/api/voice/stream'
            assert kwargs['additional_headers']=={'Authorization':'Bearer '+(a/'gateway.key').read_text().strip(),'X-Wearing-Tenant':'tenant_A'}
            assert kwargs['origin']==ORIGIN and kwargs['proxy'] is None
            assert 'access' not in json.loads(remote.messages[0]) and access not in str(remote.messages)
            assert remote.messages[1]==b'\0\0'*80
        finally:
            async with app.router.lifespan_context(app): pass

async def test_gateway_voice_rejects_missing_foreign_oversize_and_revoked_access(tmp_path):
    async with lab(tmp_path) as (root,_,_,control,_,_,_):
        connector=Connector();app=create_gateway_app(root,voice_connector=connector)
        try:
            client=TestClient(app,base_url=ORIGIN)
            for path,headers in [('/api/voice/stream?token=leak',{}),('/api/voice/stream',{'Origin':'https://other.example'}),('/wrong',{})]:
                with pytest.raises(WebSocketDisconnect):
                    with client.websocket_connect('wss://wearing.example'+path,headers=headers): pass
            for payload in [start(None),start('bad'),start('x'*64)]:
                with client.websocket_connect('wss://wearing.example/api/voice/stream') as ws:
                    ws.send_json(payload)
                    with pytest.raises(WebSocketDisconnect):ws.receive_json()
            assert connector.calls==[]
            access=control.login(ISSUER,'alice')
            with client.websocket_connect('wss://wearing.example/api/voice/stream') as ws:
                ws.send_json({**start(access),'expected_tenant':'tenant_B'})
                with pytest.raises(WebSocketDisconnect):ws.receive_json()
            assert connector.calls==[]
            access=control.login(ISSUER,'alice')
            with client.websocket_connect('wss://wearing.example/api/voice/stream') as ws:
                ws.send_json(start(access));ws.receive_json();control.logout(access);ws.send_bytes(b'\0\0')
                with pytest.raises(WebSocketDisconnect):ws.receive_json()
            assert len(connector.calls)==1 and len(connector.calls[0][2].messages)==1
            access=control.login(ISSUER,'bob')
            with client.websocket_connect('wss://wearing.example/api/voice/stream') as ws:
                ws.send_json(start(access));ws.receive_json();ws.send_bytes(b'x'*32001)
                with pytest.raises(WebSocketDisconnect):ws.receive_json()
            assert connector.calls[-1][0].endswith(':39002/api/voice/stream')
            assert len(connector.calls[-1][2].messages)==1
        finally:
            async with app.router.lifespan_context(app):pass

async def test_tenant_boundary_accepts_only_authenticated_voice_path_and_strips_private_headers():
    seen=[]
    async def app(scope,receive,send):seen.append(scope)
    gate=TenantBoundary(app,'tenant_A','k'*64)
    for path,headers,allowed in [('/api/voice/stream',[],False),('/wrong',[(b'authorization',b'Bearer '+b'k'*64),(b'x-wearing-tenant',b'tenant_A')],False),('/api/voice/stream',[(b'authorization',b'Bearer '+b'k'*64),(b'x-wearing-tenant',b'tenant_B')],False),('/api/voice/stream',[(b'authorization',b'Bearer '+b'k'*64),(b'x-wearing-tenant',b'tenant_A')],True)]:
        sent=[]
        async def send(data):sent.append(data)
        await gate({'type':'websocket','path':path,'headers':headers},None,send)
        assert bool(seen)==allowed
        if allowed:assert seen[-1]['headers']==[]
        else:assert sent==[{'type':'websocket.close','code':1008}]

async def test_private_voice_upstream_host_is_normalized_only_after_service_authentication():
    seen = []
    async def inner(scope, receive, send):
        seen.append(scope)
    gate = TenantBoundary(TrustedHostMiddleware(inner, allowed_hosts=['wearing.example']),
                          'tenant_A', 'k' * 64, public_host='wearing.example')
    credentials = [(b'authorization', b'Bearer ' + b'k' * 64),
                   (b'x-wearing-tenant', b'tenant_A')]
    for private_host in (b'10.0.0.4:8000', b'tenant-a.internal:8000', b'127.0.0.1:39001'):
        sent = []
        async def send(value): sent.append(value)
        await gate({'type': 'websocket', 'path': '/api/voice/stream',
                    'headers': [(b'host', private_host), *credentials]}, None, send)
        assert dict(seen[-1]['headers']) == {b'host': b'wearing.example'}
        assert not sent
    count = len(seen)
    for auth in ([], credentials[:1], [(b'authorization', b'Bearer invalid'), credentials[1]],
                 [credentials[0], (b'x-wearing-tenant', b'tenant_B')]):
        sent = []
        async def send(value): sent.append(value)
        await gate({'type': 'websocket', 'path': '/api/voice/stream',
                    'headers': [(b'host', b'tenant-a.internal:8000'), *auth]}, None, send)
        assert sent == [{'type': 'websocket.close', 'code': 1008}]
        assert len(seen) == count
    # HTTP has its own gateway Host handling; this fix must not silently widen it.
    sent = []
    async def send(value): sent.append(value)
    await gate({'type': 'http', 'path': '/', 'method': 'GET',
                'headers': [(b'host', b'tenant-a.internal:8000'), *credentials]}, None, send)
    assert sent[0]['status'] == 400 and len(seen) == count

async def test_worker_session_lease_is_bounded_stripped_and_available_only_in_trusted_scope():
    import time
    seen=[]
    async def inner(scope,receive,send):seen.append(scope)
    gate=TenantBoundary(inner,'tenant_A','k'*64)
    credentials=[(b'authorization',b'Bearer '+b'k'*64),(b'x-wearing-tenant',b'tenant_A')]
    expiry=str(time.time()+3600).encode()
    for lease,allowed in [([expiry],True),([],True),([b'1'],False),([b'nan'],False),([b'inf'],False),([b'bad'],False),([str(time.time()+86400).encode()],False),([expiry,expiry],False)]:
        seen.clear();sent=[]
        async def send(value):sent.append(value)
        await gate({'type':'http','method':'GET','path':'/api/bootstrap','headers':credentials+[(b'x-pajio-session-expires',v) for v in lease]},None,send)
        assert bool(seen)==allowed
        if allowed:
            assert seen[0]['pajio.cloud_worker'] is True
            assert not seen[0]['headers']
            assert seen[0].get('pajio.session_expires')==(float(expiry) if lease else None)
        else:assert sent[0]['status']==401
