import json
import time

from fastapi import HTTPException
import httpx
import pytest

from wearing.messaging import ChannelError, ChannelNetwork, MessagingBridge
from wearing.service import TaskService
from wearing.store import Store


TOKEN = "123456789:" + "fake-secret-" * 3


class Engine:
    def __init__(self):
        self.starts = []

    async def probe(self):
        return {"state": "reachable", "wearing": {}}

    async def start(self, payload, key):
        self.starts.append((payload, key))
        return {"run_id": "run-test"}


class Network:
    def __init__(self):
        self.updates, self.sent = [], []
        self.fail_send = False

    async def verify_telegram(self, secret):
        return "123456789", "pajio_test_bot"

    async def verify_feishu(self, app_id, secret):
        return app_id, "Test Feishu"

    async def send_feishu(self, app_id, secret, user, text, request_id):
        self.sent.append({"user": user, "text": text, "request_id": request_id})

    async def telegram(self, secret, method, body=None):
        if method == "getUpdates":
            return self.updates
        if method == "sendMessage":
            self.sent.append(body)
            if self.fail_send:
                raise ChannelError("uncertain")
            return {"message_id": len(self.sent)}

    async def close(self):
        pass


def update(event=1, user=42, kind="private", text="Prepare a summary", stamp=None):
    return {"update_id": event, "message": {"text": text, "date": int(time.time()) if stamp is None else stamp,
            "from": {"id": user, "is_bot": False}, "chat": {"id": user, "type": kind}}}


@pytest.fixture
def bridge(tmp_path):
    store = Store(tmp_path / "pajio.sqlite3")
    network = Network()
    service = TaskService(store, Engine())
    return MessagingBridge(store, service, network)


async def connect(bridge):
    configured = await bridge.configure("daily", "telegram", TOKEN, ["42"])
    await bridge.enabled("daily", "telegram", True, configured["channels"][0]["revision"])


async def test_configure_verifies_without_enabling_or_sending_and_never_returns_secret(bridge):
    result = await bridge.configure("daily", "telegram", TOKEN, ["42"])
    assert result["channels"][0]["state"] == "configured"
    assert not result["channels"][0]["enabled"]
    assert TOKEN not in json.dumps(result)
    await bridge.tick()
    assert not bridge.network.sent
    assert not bridge.store.conversation("daily")


async def test_private_allowlist_and_post_enable_messages_only(bridge):
    await connect(bridge)
    bridge.network.updates = [update(1, user=99), update(2, kind="group"), update(3, stamp=1), update(4)]
    await bridge.tick()
    messages = bridge.store.conversation("daily")
    assert len(messages) == 1
    assert messages[0]["content"] == "Prepare a summary"
    assert len(bridge.service.hermes.starts) == 1
    assert not bridge.network.sent
    await bridge.tick()
    assert len(bridge.store.conversation("daily")) == 1
    assert len(bridge.service.hermes.starts) == 1


async def test_result_and_approval_use_same_task_without_channel_approval_bypass(bridge):
    await connect(bridge)
    bridge.network.updates = [update()]
    await bridge.tick()
    task_id = bridge.store.conversation("daily")[0]["task_id"]
    bridge.store.update(task_id, status="waiting_for_approval", approval={"id": "approve-test", "command": "private-command"})
    await bridge.tick()
    assert len(bridge.network.sent) == 1
    assert "Pajio" in bridge.network.sent[0]["text"]
    assert "private-command" not in bridge.network.sent[0]["text"]
    assert bridge.store.get(task_id)["status"] == "waiting_for_approval"
    bridge.store.update(task_id, status="completed_unverified", output="Here is your summary.")
    await bridge.tick()
    await bridge.tick()
    assert [item["text"] for item in bridge.network.sent][-1] == "Here is your summary."
    assert len(bridge.network.sent) == 2


async def test_failed_reply_is_not_blindly_repeated_and_disable_stops_delivery(bridge):
    await connect(bridge)
    bridge.network.updates = [update()]
    await bridge.tick()
    task_id = bridge.store.conversation("daily")[0]["task_id"]
    bridge.store.update(task_id, status="completed_unverified", output="Done")
    bridge.network.fail_send = True
    await bridge.tick()
    await bridge.tick()
    assert len(bridge.network.sent) == 1
    state = bridge.list("daily")["channels"][0]
    assert state["uncertain_replies"] == 1
    await bridge.enabled("daily", "telegram", False, state["revision"])
    bridge.network.updates = [update(2)]
    await bridge.tick()
    assert len(bridge.store.conversation("daily")) == 1
    assert len(bridge.network.sent) == 1


async def test_one_bot_cannot_cross_identities_and_disconnect_removes_credentials(bridge):
    configured = await bridge.configure("daily", "telegram", TOKEN, ["42"])
    other = bridge.store.save_identity("工作", "", "CN")
    with pytest.raises(HTTPException) as error:
        await bridge.configure(other["id"], "telegram", TOKEN, ["42"])
    assert error.value.status_code == 409
    assert not bridge.list(other["id"])["channels"][0]["configured"]
    await bridge.disconnect("daily", "telegram", configured["channels"][0]["revision"])
    assert not bridge.list("daily")["channels"][0]["configured"]
    with bridge.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM messaging_connections").fetchone()[0] == 0


async def test_official_api_failure_cannot_echo_token_and_existing_webhook_is_preserved():
    requests = []
    async def handler(request):
        requests.append(request.url.path.rsplit("/", 1)[-1])
        if requests[-1] == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 123456789, "is_bot": True}})
        return httpx.Response(200, json={"ok": True, "result": {"url": "https://existing.example/hook"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ChannelError) as error:
            await ChannelNetwork(http).verify_telegram(TOKEN)
        assert TOKEN not in str(error.value)
        assert requests == ["getMe", "getWebhookInfo"]


async def test_feishu_credentials_are_verified_and_state_does_not_pretend_listener(bridge):
    result = await bridge.configure("daily", "feishu", "feishu-test-secret", ["ou_testuser"], "cli_testapp")
    item = result["channels"][1]
    assert item["configured"] and not item["enabled"]
    assert "feishu-test-secret" not in str(result)


async def test_feishu_uses_bound_app_personal_open_id_and_same_canonical_conversation(bridge):
    class Receiver:
        async def synchronize(self, rows):
            pass
        async def stop(self, identity):
            pass
    bridge.feishu = Receiver()  # No network or child process in unit tests.
    result = await bridge.configure("daily", "feishu", "feishu-test-secret", ["ou_testuser"], "cli_testapp")
    result = await bridge.enabled("daily", "feishu", True, result["channels"][1]["revision"])
    assert result["channels"][1]["state"] == "connecting"
    row = bridge._connection("daily", "feishu")
    event = {"header": {"event_id": "event-one", "app_id": "cli_testapp"}, "event": {
        "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_testuser"}},
        "message": {"chat_type": "p2p", "message_type": "text", "content": '{"text":"Prepare my day"}', "create_time": str(int(time.time() * 1000) + 1000)}}}
    await bridge.receive_feishu(row, {**event, "header": {"event_id": "bad-app", "app_id": "cli_otherapp"}})
    group = json.loads(json.dumps(event))
    group["event"]["message"]["chat_type"] = "group"
    await bridge.receive_feishu(row, group)
    assert not bridge.store.conversation("daily")
    await bridge.receive_feishu(row, event)
    await bridge.receive_feishu(row, event)
    assert len(bridge.store.conversation("daily")) == 1
    task_id = bridge.store.conversation("daily")[0]["task_id"]
    bridge.store.update(task_id, status="completed_unverified", output="Your plan")
    await bridge.tick()
    await bridge.tick()
    assert bridge.network.sent == [{"user": "ou_testuser", "text": "Your plan", "request_id": bridge.network.sent[0]["request_id"]}]
    await bridge.feishu_status(row, "connected")
    assert bridge.list("daily")["channels"][1]["state"] == "listening"
    await bridge.enabled("daily", "feishu", False, row["revision"])
    await bridge.receive_feishu(row, {**event, "header": {"event_id": "event-after-disabled", "app_id": "cli_testapp"}})
    assert len(bridge.store.conversation("daily")) == 1


async def test_feishu_verification_and_send_use_official_hosts_and_header_auth():
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path.endswith("tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tenant-secret", "expire": 7200})
        if request.url.path.endswith("bot/v3/info"):
            return httpx.Response(200, json={"code": 0, "bot": {"app_name": "Private Bot"}})
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_test"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        network = ChannelNetwork(http)
        assert await network.verify_feishu("cli_testapp", "secret-fixture") == ("cli_testapp", "Private Bot")
        await network.send_feishu("cli_testapp", "secret-fixture", "ou_testuser", "hello", "idempotent-uuid")
    assert len(calls) == 3
    assert all(request.url.host == "open.feishu.cn" for request in calls)
    assert calls[-1].headers["Authorization"] == "Bearer tenant-secret"
    assert json.loads(calls[-1].content)["uuid"] == "idempotent-uuid"


async def test_httpx_logging_never_records_telegram_bot_credential(caplog):
    async def handler(request):
        return httpx.Response(200, json={"ok": True, "result": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with caplog.at_level("INFO", logger="httpx"):
            await ChannelNetwork(http).telegram(TOKEN, "getUpdates")
    assert TOKEN not in caplog.text
    assert "redacted" in caplog.text


async def test_channel_routes_inherit_product_csrf_identity_and_secret_safe_validation(tmp_path):
    from wearing.app import create_app
    from wearing.config import Settings
    from wearing.messaging_api import install_messaging_routes
    app = create_app(Settings(tmp_path))
    bridge = getattr(app.state, "messaging", None)
    if bridge is None:
        bridge = MessagingBridge(app.state.store, app.state.service, Network())
        install_messaging_routes(app, bridge)
    else:
        await bridge.network.close()
        bridge.network = Network()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        body = {"secret": TOKEN, "allowed_users": ["42"]}
        assert (await client.put("/api/messaging/telegram", json=body)).status_code == 403
        token = (await client.get("/api/bootstrap")).json()["token"]
        client.headers["X-Wearing-Token"] = token
        result = await client.put("/api/messaging/telegram", json=body)
        assert result.status_code == 200
        assert TOKEN not in result.text
        assert not result.json()["channels"][0]["enabled"]
        assert (await client.put("/api/messaging/telegram", headers={"Origin": "https://attacker.invalid"}, json=body)).status_code == 403
        invalid = await client.put("/api/messaging/telegram", json={"secret": "secret-canary" * 100, "allowed_users": []})
        assert invalid.status_code == 422
        assert "secret-canary" not in invalid.text
    await bridge.close()
    await app.state.service.hermes.close()
