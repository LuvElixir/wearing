import httpx
import json
import pytest

from wearing.app import create_app
from wearing.config import Settings
from wearing.hermes import HermesClient, HermesError


def snapshot():
    return {"available": True, "targets": {
        "user": {"enabled": True, "entries": ["本身份的偏好"], "used_chars": 6, "limit_chars": 1375},
        "memory": {"enabled": True, "entries": [], "used_chars": 0, "limit_chars": 2200}}}


async def test_memory_read_stays_in_requested_identity_and_does_not_start_engine(tmp_path):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=snapshot())
    hermes = HermesClient(Settings(tmp_path, hermes_key="test-secret"), httpx.MockTransport(handler))
    app = create_app(Settings(tmp_path), hermes)
    other = app.state.store.save_identity("另外的身份")["id"]
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            daily = (await client.get("/api/memory")).json()
            assert daily["identity_id"] == "daily" and daily["targets"]["user"]["entries"] == ["本身份的偏好"]
            hidden = (await client.get("/api/memory", headers={"X-Wearing-Identity": other})).json()
            assert hidden["available"] is False and "targets" not in hidden
            assert calls == ["/v1/wearing/memory"]
            assert (await client.get("/api/memory", headers={"X-Wearing-Identity": "unknown"})).status_code == 404
            assert (await client.get("/api/memory", headers={"Origin": "https://foreign.example"})).status_code == 403
    finally:
        await hermes.close()


@pytest.mark.parametrize("body", [{}, {"available": True, "targets": {}}, {"available": True, "targets": {"user": {"entries": [42], "enabled": True}}}])
async def test_unrecognized_memory_response_is_not_shown_as_empty_or_saved(tmp_path, body):
    hermes = HermesClient(Settings(tmp_path, hermes_key="test"), httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    try:
        with pytest.raises(HermesError):
            await hermes.memories()
    finally:
        await hermes.close()


async def test_unavailable_engine_keeps_memory_unavailable(tmp_path):
    hermes = HermesClient(Settings(tmp_path, hermes_key="test"), httpx.MockTransport(lambda r: httpx.Response(503, text="private-error")))
    app = create_app(Settings(tmp_path), hermes)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/memory")
            assert response.status_code == 200
            assert response.json()["available"] is False
            assert "targets" not in response.json() and "private-error" not in response.text
    finally:
        await hermes.close()


async def test_memory_patch_routes_valid_write_and_rejects_invalid_json(tmp_path):
    calls = []
    def handler(request):
        assert request.method == 'PATCH' and request.url.path == '/v1/wearing/memory'
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=snapshot())
    hermes = HermesClient(Settings(tmp_path, hermes_key='test'), httpx.MockTransport(handler))
    app = create_app(Settings(tmp_path), hermes)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            token = (await client.get('/api/bootstrap')).json()['token']
            client.headers['X-Wearing-Token'] = token
            change = {'target': 'user', 'action': 'add', 'revision': '0' * 64, 'content': '合成偏好'}
            saved = await client.patch('/api/memory', json=change)
            assert saved.status_code == 200 and saved.json()['identity_id'] == 'daily'
            assert calls == [change]
            for raw in (b'{', b'[]', b'null', b'\xff', json.dumps({'content': 'x' * 100001}).encode()):
                invalid = await client.patch('/api/memory', content=raw, headers={'Content-Type': 'application/json'})
                assert invalid.status_code == 422
            assert calls == [change]
    finally:
        await hermes.close()
