import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI, Request

from wearing.cloud_apps import CloudApps, CloudAppError, FeishuCloudNetwork, FEATURES
from wearing.cloud_apps_api import install_cloud_app_routes
from wearing.cloud_apps_tools import read_resource, TOOLS
from wearing.store import Store


SECRET = "private-app-secret-canary"
SCOPES = "offline_access " + " ".join(scope for feature in FEATURES.values() for scope in feature["scopes"])


class Network:
    def __init__(self):
        self.calls, self.exchanges, self.revocations = [], [], []
        self.poll_result = None
        self.revoke_fails = False
        self.read_error = None
        self.verify_fails = False
        self.start_url = "https://accounts.feishu.cn/authorize?user_code=TEST"
        self.scope = SCOPES

    async def start(self, app_id, secret, scopes):
        self.calls.append(("start", app_id, scopes))
        return {"device_code": "private-device-code", "user_code": "TEST-CODE", "verification_uri_complete": self.start_url, "expires_in": 600, "interval": 5}

    async def exchange(self, app_id, secret, **grant):
        self.exchanges.append(grant)
        await asyncio.sleep(.01)
        if self.poll_result:
            return self.poll_result
        return {"access_token": "private-user-token-" + str(len(self.exchanges)), "refresh_token": "private-refresh-token-" + str(len(self.exchanges)), "expires_in": 7200, "refresh_token_expires_in": 86400, "scope": self.scope}

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if self.read_error:
            raise self.read_error
        if path.endswith("/user_info"):
            if self.verify_fails:
                raise CloudAppError("temporary", 503, "network")
            return {"data": {"open_id": "ou_user_test", "name": "测试用户", "email": "not-exported@example.com"}}
        if path.endswith("/get_node"):
            return {"data": {"node": {"obj_type": "docx", "obj_token": "docxResolved", "title": "知识库内容"}}}
        if path.endswith("/raw_content"):
            return {"data": {"content": "文" * 42000}}
        if path.endswith("/files"):
            return {"data": {"files": [{"token": "folderOne", "name": "文件夹", "type": "folder", "owner_id": "not-exported"}], "has_more": True, "next_page_token": "page-two"}}
        if path.endswith("/calendars"):
            return {"data": {"calendar_list": [{"calendar_id": "feishu.cn_a@group.calendar.feishu.cn", "summary": "主日历", "role": "owner"}], "has_more": False}}
        if path.endswith("/events"):
            return {"data": {"items": [{"event_id": "event-one", "summary": "测试会议", "start_time": {"timestamp": "1800000000"}}], "has_more": False}}
        raise AssertionError(path)

    async def revoke(self, app_id, secret, token, hint):
        self.revocations.append((token, hint))
        if self.revoke_fails:
            raise CloudAppError("network", 503)

    async def close(self):
        pass


@pytest.fixture
def cloud(tmp_path):
    return CloudApps(Store(tmp_path / "wearing.sqlite3"), Network())


def due(cloud):
    row = cloud._read("daily")
    row["pending"]["next_poll"] = 0
    cloud._write("daily", row)


async def start(cloud):
    config = await cloud.configure("daily", "cli_testapp", SECRET, ["documents", "calendar"])
    return await cloud.authorize("daily", config["revision"])


async def connect(cloud):
    pending = await start(cloud)
    due(cloud)
    return await cloud.poll("daily", pending["authorization"]["id"])


async def test_actual_user_grant_not_configuration_is_connected_and_no_secrets_return(cloud):
    configuration = await cloud.configure("daily", "cli_testapp", SECRET, ["documents", "calendar"])
    assert configuration["state"] == "configured"
    assert not any(item["authorized"] for item in configuration["capabilities"])
    assert cloud.network.calls == []
    pending = await cloud.authorize("daily", configuration["revision"])
    assert pending["state"] == "authorizing"
    assert pending["authorization"]["user_code"] == "TEST-CODE"
    assert "private-device-code" not in json.dumps(pending)
    # Native repeated taps don't mint several grants or bypass provider rate limits.
    assert (await cloud.authorize("daily", configuration["revision"]))["authorization"]["id"] == pending["authorization"]["id"]
    await cloud.poll("daily", pending["authorization"]["id"])
    assert not cloud.network.exchanges
    due(cloud)
    connected = await cloud.poll("daily", pending["authorization"]["id"])
    assert connected["state"] == "connected"
    assert all(item["authorized"] for item in connected["capabilities"])
    assert connected["account_name"] == "测试用户"
    assert connected["authorization"] is None
    serialized = json.dumps(connected)
    assert "private-" not in serialized and "email" not in serialized


async def test_pending_slowdown_denial_and_invalid_url_are_truthful(cloud):
    pending = await start(cloud)
    cloud.network.poll_result = {"error": "slow_down"}
    due(cloud)
    slowed = await cloud.poll("daily", pending["authorization"]["id"])
    assert slowed["authorization"]["interval"] == 10
    cloud.network.poll_result = {"error": "access_denied"}
    due(cloud)
    denied = await cloud.poll("daily", pending["authorization"]["id"])
    assert denied["state"] == "configured"
    assert denied["error"] and denied["authorization"] is None
    cloud.network.start_url = "https://feishu.cn.attacker.example/authorize"
    with pytest.raises(CloudAppError):
        await cloud.authorize("daily", denied["revision"])


async def test_issued_single_use_grant_survives_userinfo_network_failure(cloud):
    pending = await start(cloud)
    cloud.network.verify_fails = True
    due(cloud)
    with pytest.raises(CloudAppError):
        await cloud.poll("daily", pending["authorization"]["id"])
    assert cloud.snapshot("daily")["state"] == "authorizing"
    assert len(cloud.network.exchanges) == 1
    cloud.network.verify_fails = False
    due(cloud)
    assert (await cloud.poll("daily", pending["authorization"]["id"]))["state"] == "connected"
    assert len(cloud.network.exchanges) == 1


async def test_identity_scope_and_grant_ids_never_cross_connections(cloud):
    pending = await start(cloud)
    other = cloud.store.save_identity("另一个身份")["id"]
    assert cloud.snapshot(other)["state"] == "not_configured"
    with pytest.raises(CloudAppError):
        await cloud.poll(other, pending["authorization"]["id"])
    with pytest.raises(CloudAppError):
        await cloud.read(other, "/open-apis/authen/v1/user_info")
    with pytest.raises(CloudAppError):
        await cloud.poll("daily", "0" * 32)
    result = await read_resource(cloud, "daily", "cloud_connections", {})
    assert "authorization" not in result["items"][0]


async def test_refresh_rotates_once_across_two_service_instances_and_keeps_identity(cloud):
    await connect(cloud)
    row = cloud._read("daily")
    row["oauth"]["expires_at"] = time.time() - 1
    cloud._write("daily", row)
    second = CloudApps(cloud.store, cloud.network)
    await asyncio.gather(cloud.check("daily"), second.check("daily"))
    assert len(cloud.network.exchanges) == 2
    assert cloud.network.exchanges[-1]["refresh_token"] == "private-refresh-token-1"
    assert cloud._read("daily")["oauth"]["refresh_token"] == "private-refresh-token-2"
    assert cloud.snapshot("daily")["account_id"] == "ou_user_test"


async def test_expired_refresh_cannot_pretend_connected_or_read(cloud):
    await connect(cloud)
    row = cloud._read("daily")
    row["oauth"].update(expires_at=0, refresh_expires_at=0)
    cloud._write("daily", row)
    assert cloud.snapshot("daily")["state"] == "expired"
    with pytest.raises(CloudAppError) as error:
        await cloud.check("daily")
    assert error.value.status_code == 401
    assert cloud._read("daily")["needs_authorization"]


async def test_missing_scope_and_remote_permission_errors_do_not_become_empty_success(cloud):
    cloud.network.scope = "offline_access calendar:calendar:read"
    await connect(cloud)
    assert not any(item["authorized"] for item in cloud.snapshot("daily")["capabilities"])
    with pytest.raises(CloudAppError) as denied:
        await read_resource(cloud, "daily", "cloud_feishu_files", {})
    assert denied.value.status_code == 403
    cloud.network.read_error = CloudAppError("权限不足", 403, "permission")
    with pytest.raises(CloudAppError):
        await cloud.check("daily")
    assert cloud.snapshot("daily")["error"] == "权限不足"


async def test_disconnect_blocks_access_even_when_provider_revoke_fails_then_retries(cloud):
    result = await connect(cloud)
    cloud.network.revoke_fails = True
    stopped = await cloud.disconnect("daily", result["revision"])
    assert stopped["revocation_pending"] and stopped["state"] == "expired"
    with pytest.raises(CloudAppError):
        await cloud.check("daily")
    assert len(cloud.network.calls) == 2  # OAuth start + verified user-info only.
    cloud.network.revoke_fails = False
    disconnected = await cloud.disconnect("daily", result["revision"])
    assert disconnected["state"] == "not_configured"
    assert cloud._read("daily") is None
    assert cloud.network.revocations[-2:] == [("private-refresh-token-1", "refresh_token"), ("private-user-token-1", "access_token")]


async def test_documents_wiki_pagination_calendar_use_only_user_bearer(cloud):
    await connect(cloud)
    files = await read_resource(cloud, "daily", "cloud_feishu_files", {"folder_token": "folderOne", "page_token": "next"})
    assert files["next_page_token"] == "page-two"
    assert "owner_id" not in files["items"][0]
    doc = await read_resource(cloud, "daily", "cloud_feishu_document", {"document": "https://example.feishu.cn/wiki/wikiToken"})
    assert doc["document_id"] == "docxResolved" and doc["next_offset"] == 40000
    tail = await read_resource(cloud, "daily", "cloud_feishu_document", {"document": "docxResolved", "offset": 40000})
    assert len(tail["content"]) == 2000 and tail["next_offset"] is None
    calendars = await read_resource(cloud, "daily", "cloud_feishu_calendars", {})
    calendar = calendars["items"][0]["calendar_id"]
    events = await read_resource(cloud, "daily", "cloud_feishu_events", {"calendar_id": calendar, "start_time": 1800000000, "end_time": 1800003600})
    assert events["items"][0]["event_id"] == "event-one"
    call = cloud.network.calls[-1]
    assert "%40" in call[1]
    assert call[2]["token"] == "private-user-token-1"
    assert events["content_is_untrusted"] and doc["content_is_untrusted"]


async def test_tool_rejects_ssrf_path_escape_and_unbounded_time_before_request(cloud):
    await connect(cloud)
    count = len(cloud.network.calls)
    for name, args in [
        ("cloud_feishu_document", {"document": "https://attacker.example/docx/doc"}),
        ("cloud_feishu_document", {"document": "../../secret"}),
        ("cloud_feishu_events", {"calendar_id": "ok", "start_time": 0, "end_time": 94 * 86400}),
        ("cloud_feishu_files", {"folder_token": "folder/../../file"}),
    ]:
        with pytest.raises(CloudAppError):
            await read_resource(cloud, "daily", name, args)
    assert len(cloud.network.calls) == count
    assert all("identity" not in tool.inputSchema["properties"] for tool in TOOLS)


async def test_network_matches_official_device_flow_and_revocation_contracts():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("device_authorization"):
            return httpx.Response(200, json={"verification_uri": "https://accounts.feishu.cn/device", "device_code": "device", "user_code": "code", "expires_in": 600})
        if request.url.path.endswith("oauth/token"):
            return httpx.Response(400, json={"error": "authorization_pending"})
        if request.url.path.endswith("/revoke"):
            return httpx.Response(200, content=b"")
        return httpx.Response(200, json={"code": 0, "tenant_access_token": "verify-only"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        network = FeishuCloudNetwork(client)
        await network.start("cli_testapp", SECRET, ["offline_access"])
        pending = await network.exchange("cli_testapp", SECRET, grant_type="urn:ietf:params:oauth:grant-type:device_code", device_code="device")
        await network.revoke("cli_testapp", SECRET, "revoke-token", "refresh_token")
    assert pending == {"error": "authorization_pending"}
    assert requests[1].url == "https://open.feishu.cn/open-apis/authen/v2/oauth/device_authorization"
    assert json.loads(requests[1].content) == {"client_id": "cli_testapp", "scope": "offline_access"}
    assert requests[-1].url == "https://accounts.feishu.cn/oauth/v1/revoke"
    assert requests[-1].headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert b"token_type_hint=refresh_token" in requests[-1].content
    assert all(SECRET not in str(request.url) for request in requests)


async def test_network_bounds_bodies_and_never_echoes_provider_secrets():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"code": 7, "msg": SECRET}))) as client:
        with pytest.raises(CloudAppError) as error:
            await FeishuCloudNetwork(client).request("GET", "/open-apis/drive/v1/files", token="hidden")
        assert SECRET not in error.value.detail
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b" " * (2 * 1024 * 1024 + 1)))) as client:
        with pytest.raises(CloudAppError) as error:
            await FeishuCloudNetwork(client).request("GET", "/open-apis/drive/v1/files", token="hidden")
        assert error.value.status_code == 413


async def test_native_routes_use_request_identity_and_return_actual_resource_data(cloud):
    await connect(cloud)
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.identity_id = request.headers.get("X-Wearing-Identity", "daily")
        return await call_next(request)

    install_cloud_app_routes(app, cloud)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        files = await client.get("/api/cloud-apps/feishu/files")
        assert files.status_code == 200 and files.json()["items"][0]["token"] == "folderOne"
        assert (await client.get("/api/cloud-apps/feishu/document", params={"document": "../../bad"})).status_code == 422
        snapshot = (await client.get("/api/cloud-apps/feishu")).json()
        assert "private-" not in json.dumps(snapshot)
        conflict = await client.request("DELETE", "/api/cloud-apps/feishu", json={"revision": "f" * 32})
        assert conflict.status_code == 409
