import json

import httpx
import pytest

from wearing.app import create_app
from wearing.config import Settings
from wearing.doctor import inspect_host, parse_adb_devices


@pytest.fixture
async def client(tmp_path):
    app = create_app(Settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        token = (await client.get("/api/bootstrap")).json()["token"]
        client.headers["X-Wearing-Token"] = token
        yield client
    await app.state.service.hermes.close()


async def test_draft_persists_and_cannot_run_without_hermes(client):
    response = await client.post("/api/tasks", json={"prompt":"保留这个想法", "target":"computer"})
    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "draft"
    assert "payload" not in task
    failed = await client.post(f'/api/tasks/{task["id"]}/start')
    assert failed.status_code == 409
    assert (await client.get("/api/tasks")).json()[0]["status"] == "draft"


async def test_offline_conversation_preserves_words_without_fabricated_reply(client):
    response = await client.post("/api/conversation", json={"content": "  今天突然有个想法  "})
    assert response.status_code == 201
    assert response.json()["delivery"] == "saved"
    messages = (await client.get("/api/conversation")).json()
    assert len(messages) == 1
    assert messages[0]["content"] == "今天突然有个想法"
    assert messages[0]["turn"]["output"] == ""
    assert messages[0]["turn"]["status"] == "draft"
    assert "payload" not in messages[0]["turn"]
    assert (await client.post("/api/conversation", json={"content": " "})).status_code == 422


async def test_mutation_requires_local_token_and_origin(client):
    no_token = await client.post("/api/tasks", headers={"X-Wearing-Token":""}, json={"prompt":"x"})
    assert no_token.status_code == 403
    foreign = await client.post("/api/tasks", headers={"Origin":"https://elsewhere.example"}, json={"prompt":"x"})
    assert foreign.status_code == 403
    rebound = await client.get("/api/bootstrap", headers={"Host":"evil.example"})
    assert rebound.status_code == 400


async def test_input_validation_and_no_secret_echo(client):
    assert (await client.post("/api/tasks", json={"prompt":"   "})).status_code == 422
    assert (await client.post("/api/tasks", json={"prompt":"x", "target":"arbitrary-host"})).status_code == 422
    assert "hermes_key" not in (await client.get("/api/bootstrap")).json()
    secret = "secret-not-for-errors-" * 220
    invalid = await client.post("/api/connection", json={"url":"http://localhost:8642", "key":secret})
    assert invalid.status_code == 422
    assert "secret-not-for-errors" not in invalid.text
    assert (await client.post("/api/device-report", content="not-json")).status_code == 422
    assert (await client.post("/api/device-report", json={"schema_version":1, "system":"Windows", "phones":"bad"})).status_code == 422


async def test_static_ui_and_portable_doctor(client):
    page = await client.get("/")
    assert page.status_code == 200
    assert "Wearing" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert (await client.get("/assets/app.js")).status_code == 200
    report = inspect_host(False)
    assert (await client.post("/api/device-report", json=report)).status_code == 200
    status = (await client.get("/api/status")).json()
    assert status["hermes"]["state"] == "not_configured"
    assert status["limits"]["device_control_validated"] is False
    assert status["device_report"]["system"] == report["system"]


def test_adb_parser_keeps_offline_and_unauthorized_distinct():
    result = parse_adb_devices("""* daemon started successfully *
List of devices attached
abc device product:wayne model:MI_6X device:wayne transport_id:1
def unauthorized usb:1
ghi offline
""")
    assert [r["state"] for r in result] == ["device", "unauthorized", "offline"]
    assert result[0]["model"] == "MI_6X"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://host.example:8642", "http://user:pass@localhost:8642", "http://127.0.0.1:8642/v1", "http://localhost:not-a-port", "http://localhost:0"])
def test_connection_url_policy(tmp_path, url):
    with pytest.raises(ValueError):
        Settings(tmp_path, hermes_url=url)


@pytest.mark.parametrize("key", ["中文密钥", "has\na-newline", "has a space"])
def test_invalid_header_key_never_enters_http_client(tmp_path, key):
    with pytest.raises(ValueError):
        Settings(tmp_path, hermes_key=key)
