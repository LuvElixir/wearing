import asyncio
import json

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from wearing.app import create_app
from wearing.config import Settings
from wearing.dev_mobile import create_dev_mobile_app
from wearing import speech_api


@pytest.fixture
def live(tmp_path, monkeypatch):
    seen = []
    async def recognize(chunks, key):
        assert key == 'test-key'
        try:
            async for chunk in chunks:
                seen.append(chunk)
            return '明天3点拿快递。'
        finally:
            seen.append('closed')
    monkeypatch.setattr(speech_api, 'recognize_stream', recognize)
    monkeypatch.setattr(speech_api, 'speech_key', lambda _: 'test-key')
    app = create_app(Settings(tmp_path))
    client = TestClient(app)
    token = client.get('/api/bootstrap').json()['token']
    start = dict(type='start', identity='daily', take='test-take', token=token, format='pcm_s16le_16000_mono')
    return client, start, seen, app


def test_stream_preserves_order_waits_for_finish_and_does_not_create_agent_work(live):
    client, start, seen, app = live
    before = len(app.state.store.list())
    with client.websocket_connect(speech_api.PATH) as ws:
        ws.send_json(start)
        assert ws.receive_json() == {'type': 'ready', 'take': 'test-take'}
        ws.send_bytes(b'\x01\x00' * 100)
        ws.send_bytes(b'\x02\x00' * 20)
        ws.send_json({'type': 'finish', 'bytes': 240})
        assert ws.receive_json() == {'type': 'final', 'take': 'test-take', 'text': '明天3点拿快递。'}
    assert seen == [b'\x01\x00'*100, b'\x02\x00'*20, 'closed']
    assert len(app.state.store.list()) == before


@pytest.mark.parametrize('patch', [{'token': 'wrong'}, {'identity': 'missing'}, {'take': '../escape'}, {'format': 'arbitrary'}])
def test_auth_and_format_fail_before_provider(live, patch):
    client, start, seen, _ = live
    with client.websocket_connect(speech_api.PATH) as ws:
        ws.send_json({**start, **patch})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert seen == []


@pytest.mark.parametrize('path,headers', [(speech_api.PATH+'?token=secret', {}), (speech_api.PATH, {'Origin': 'https://foreign.example'})])
def test_foreign_origin_and_query_credentials_are_rejected(live, path, headers):
    with pytest.raises(WebSocketDisconnect):
        with live[0].websocket_connect(path, headers=headers):
            pass
    assert live[2] == []


@pytest.mark.parametrize('data,ending', [(b'0', 1), (b'0'*32002, 32002), (b'00', 4)])
def test_malformed_or_missing_audio_never_produces_final(live, data, ending):
    client, start, _, _ = live
    with client.websocket_connect(speech_api.PATH) as ws:
        ws.send_json(start); assert ws.receive_json()['type'] == 'ready'
        ws.send_bytes(data); ws.send_json({'type': 'finish', 'bytes': ending})
        assert ws.receive_json() == {'type': 'error', 'code': 'invalid_audio'}


def test_cancellation_closes_provider_without_any_final(live):
    client, start, seen, _ = live
    with client.websocket_connect(speech_api.PATH) as ws:
        ws.send_json(start); ws.receive_json(); ws.send_bytes(b'00')
        ws.close()
        # Wait for app cleanup before TestClient tears down its task scope.
        import time
        for _ in range(100):
            if seen and seen[-1] == 'closed':
                break
            time.sleep(.001)
    assert seen[-1] == 'closed'


@pytest.mark.parametrize('patch', [{'access': 'wrong'}, {'identity': 'other'}])
def test_dev_bridge_rejects_credentials_and_foreign_identity(tmp_path, patch):
    app = create_dev_mobile_app('192.168.1.42', 8795, 'http://127.0.0.1:1', 'daily', tmp_path/'pair.json')
    pair = json.loads((tmp_path/'pair.json').read_text())
    client = TestClient(app, base_url='http://192.168.1.42:8795')
    with client.websocket_connect('ws://192.168.1.42:8795' + speech_api.PATH) as ws:
        ws.send_json({'access': pair['accessToken'], 'identity': 'daily', **patch})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1008


def test_bridge_closes_unknown_websocket_routes_and_expired_sessions(tmp_path):
    now = [0]
    app = create_dev_mobile_app('192.168.1.42', 8795, 'http://127.0.0.1:1', 'daily', tmp_path/'pair.json', clock=lambda: now[0])
    client = TestClient(app, base_url='http://192.168.1.42:8795')
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('ws://192.168.1.42:8795/api/other'):
            pass
    now[0] = 15000
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('ws://192.168.1.42:8795' + speech_api.PATH):
            pass
