import json
import os
import re
from datetime import datetime, timezone

import httpx
import pytest

from wearing.dev_mobile import MAX_BODY, TTL_SECONDS, addresses, create_dev_mobile_app

ORIGIN = "http://192.168.1.42:8795"
UPSTREAM = "http://127.0.0.1:8794"


class Payload(httpx.AsyncByteStream):
    def __init__(self, content=b'{"ok":true}'):
        self.content = content

    async def __aiter__(self):
        yield self.content


def reply(body=b'{"ok":true}', **kwargs):
    return httpx.Response(200, stream=Payload(body), **kwargs)


def setup(tmp_path, worker=None, **kwargs):
    path = tmp_path / "pairing.json"
    app = create_dev_mobile_app("192.168.1.42", 8795, UPSTREAM, "daily", path,
                                transport=httpx.MockTransport(worker or (lambda _: reply())), **kwargs)
    pairing = json.loads(path.read_text())
    headers = {"Authorization": "Bearer " + pairing["accessToken"]}
    return app, pairing, headers


@pytest.mark.parametrize("listen", ["0.0.0.0", "127.0.0.1", "8.8.8.8", "169.254.1.1", "::1", "localhost", "192.0.2.1", "100.64.0.1"])
def test_bridge_rejects_unspecified_public_loopback_and_non_lan_listeners(listen):
    with pytest.raises(ValueError):
        addresses(listen, 8795, UPSTREAM)


@pytest.mark.parametrize("upstream", ["http://localhost:8794", "http://192.168.1.2:8794", "https://127.0.0.1:8794",
                                      "http://127.0.0.1:8794/api", "http://127.0.0.1:8794/?secret=1",
                                      "http://127.0.0.1:8794/#fragment", "http://user:password@127.0.0.1:8794",
                                      "http://127.0.0.1", "http://127.0.0.1:65536"])
def test_bridge_accepts_only_a_fixed_loopback_http_upstream(upstream):
    with pytest.raises(ValueError):
        addresses("192.168.1.42", 8795, upstream)


async def test_private_pairing_shape_randomness_and_every_resource_requires_authentication(tmp_path):
    seen = []
    app, pairing, auth = setup(tmp_path, lambda request: (seen.append(request), reply())[1])
    assert set(pairing) == {"endpoint", "identity", "accessToken", "expiresAt"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", pairing["expiresAt"])
    assert pairing["endpoint"] == ORIGIN + "/" and pairing["identity"] == "daily"
    assert len(pairing["accessToken"]) == 64
    assert 14390 < (datetime.fromisoformat(pairing["expiresAt"]) - datetime.now(timezone.utc)).total_seconds() <= TTL_SECONDS
    if os.name != "nt":
        assert (tmp_path / "pairing.json").stat().st_mode & 0o777 == 0o600
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        for path in ["/", "/api/bootstrap", "/assets/app.js", "/api/life/assets/anything", "/internal/runtime", "/favicon.ico"]:
            response = await client.get(path)
            assert response.status_code == 401
            assert "token" not in response.text
            assert response.headers["cache-control"] == "private, no-store"
        assert not seen
        assert (await client.get("/internal/runtime", headers=auth)).status_code == 404
        assert not seen


async def test_native_bearer_webview_cookie_and_credential_header_boundary(tmp_path):
    seen = []

    def worker(request):
        seen.append(request)
        assert request.headers["Host"] == "127.0.0.1:8794"
        assert request.headers["X-Wearing-Identity"] == "daily"
        for name in ["authorization", "cookie", "x-forwarded-host", "x-forwarded-for", "x-wearing-tenant", "x-arbitrary"]:
            assert name not in request.headers
        return reply(headers={"Content-Type": "application/json", "Set-Cookie": "upstream-secret=bad", "Content-Security-Policy": "default-src 'self'"})

    app, _, auth = setup(tmp_path, worker)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        response = await client.get("/", headers={**auth, "X-Forwarded-Host": "bad.example", "Cookie": "browser=bad", "X-Wearing-Tenant": "bad", "X-Arbitrary": "bad"})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=" in cookie
        assert "upstream-secret" not in cookie and app.state.cookie_name in client.cookies
        response = await client.get("/assets/app.js")
        assert response.status_code == 200 and "set-cookie" not in response.headers
        assert response.headers["content-security-policy"] == "default-src 'self'"
        assert (await client.post("/api/conversation", json={}, headers={"Origin": ORIGIN, "X-Wearing-Token": "csrf-token"})).status_code == 200
        assert seen[-1].headers["origin"] == UPSTREAM
        assert seen[-1].headers["x-wearing-token"] == "csrf-token"
        assert (await client.post("/api/conversation", json={}, headers=auth)).status_code == 200
        assert "origin" not in seen[-1].headers
        assert (await client.get("/assets/app.js", headers={"Authorization": "Bearer invalid"})).status_code == 401


async def test_csrf_exact_host_identity_scope_and_no_bearer_forwarding(tmp_path):
    seen = []
    app, _, auth = setup(tmp_path, lambda request: (seen.append(request), reply())[1])
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        await client.get("/", headers=auth)
        seen.clear()
        assert (await client.get("/api/life", headers={**auth, "Host": "evil.example"})).status_code == 400
        assert (await client.get("/api/life", headers=[*auth.items(), ("Host", "192.168.1.42:8795"), ("Host", "evil.example")])).status_code == 400
        assert (await client.get("/api/life", headers={**auth, "Origin": "http://192.168.1.42:1111"})).status_code == 403
        assert (await client.post("/api/conversation", json={})).status_code == 403
        assert (await client.post("/api/conversation", headers={"Origin": "null"}, json={})).status_code == 403
        assert (await client.get("/api/life", headers={**auth, "X-Wearing-Identity": "other"})).status_code == 403
        assert (await client.get("/api/life?identity=other", headers=auth)).status_code == 403
        assert (await client.get("/api/life?identity=daily&identity=other", headers=auth)).status_code == 403
        assert (await client.post("/api/identities", json={}, headers=auth)).status_code == 403
        assert not seen
        assert (await client.get("/api/life?identity=daily", headers=auth)).status_code == 200


async def test_bootstrap_only_authenticated_and_filtered_to_paired_identity(tmp_path):
    data = {"token": "upstream-csrf", "version": "0.2.0", "deployment": "local", "default_identity_id": "daily",
            "identities": [{"id": "daily", "name": "日常"}, {"id": "other", "name": "其他"}]}
    app, _, auth = setup(tmp_path, lambda _: reply(json.dumps(data).encode()))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (await client.get("/api/bootstrap")).status_code == 401
        response = await client.get("/api/bootstrap", headers=auth)
        assert response.status_code == 200
        assert response.json()["identities"] == [{"id": "daily", "name": "日常"}]
        assert response.json()["token"] == "upstream-csrf"
        assert "set-cookie" not in response.headers


async def test_token_and_cookie_expire_together_and_restart_revokes_both(tmp_path):
    ticks = [100.0]
    app, _, auth = setup(tmp_path / "first", clock=lambda: ticks[0])
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (await client.get("/", headers=auth)).status_code == 200
        cookies = dict(client.cookies)
        ticks[0] += TTL_SECONDS
        assert (await client.get("/assets/app.js")).status_code == 401
        assert (await client.get("/assets/app.js", headers=auth)).status_code == 401
    restarted, _, _ = setup(tmp_path / "second")
    async with restarted.router.lifespan_context(restarted), httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=ORIGIN, cookies=cookies) as client:
        assert (await client.get("/", headers=auth)).status_code == 401
        assert (await client.get("/assets/app.js")).status_code == 401


async def test_15mb_stream_limit_accepts_audio_size_and_blocks_both_declared_and_chunked_overflow(tmp_path):
    seen = []
    app, _, auth = setup(tmp_path, lambda request: (seen.append(request), reply())[1])

    async def overflow():
        yield b"x" * MAX_BODY
        yield b"x"

    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        response = await client.post("/api/life/assets?name=sample.m4a", content=b"x" * MAX_BODY,
                                     headers={**auth, "Content-Type": "audio/mp4", "X-Wearing-Token": "csrf"})
        assert response.status_code == 200 and len(seen[-1].content) == MAX_BODY
        assert seen[-1].headers["content-type"] == "audio/mp4"
        response = await client.post("/api/life/assets", content=b"", headers={**auth, "Content-Length": str(MAX_BODY + 1)})
        assert response.status_code == 413
        response = await client.post("/api/life/assets", content=overflow(), headers=auth)
        assert response.status_code == 413
        assert len(seen) == 1


@pytest.mark.parametrize("failure,expected", [(httpx.ConnectError("private detail"), 503), (httpx.ReadTimeout("private detail"), 504)])
async def test_upstream_failure_returns_safe_recoverable_error(tmp_path, failure, expected):
    def worker(request):
        assert request.extensions["timeout"]["read"] == 150
        raise failure
    app, _, auth = setup(tmp_path, worker)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        response = await client.post("/api/life/assets/asset_test/transcribe", json={}, headers=auth)
        assert response.status_code == expected and "private detail" not in response.text


async def test_upstream_redirect_not_followed_or_exposed_and_304_preserved(tmp_path):
    seen = []
    def worker(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://external.example/credential"}, stream=Payload(b""))
    app, _, auth = setup(tmp_path, worker)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        response = await client.get("/", headers=auth)
        assert response.status_code == 502 and "location" not in response.headers and len(seen) == 1
    app, _, auth = setup(tmp_path / "cache", lambda _: httpx.Response(304, stream=Payload(b"")))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (await client.get("/assets/app.js", headers=auth)).status_code == 304


def test_pairing_file_is_never_overwritten_or_written_through_symlink(tmp_path):
    file = tmp_path / "pairing.json"
    file.write_text("preserve")
    with pytest.raises(FileExistsError):
        create_dev_mobile_app("192.168.1.42", 8795, UPSTREAM, "daily", file)
    assert file.read_text() == "preserve"
    link = tmp_path / "link.json"
    link.symlink_to(file)
    with pytest.raises(FileExistsError):
        create_dev_mobile_app("192.168.1.42", 8795, UPSTREAM, "daily", link)
    assert file.read_text() == "preserve"


async def test_bridge_keeps_real_loopback_app_origin_and_csrf_guards(tmp_path):
    from wearing.app import create_app
    from wearing.config import Settings

    core = create_app(Settings(tmp_path / "isolated-core"), engine_autostart=False, local_devices=False)
    path = tmp_path / "pair.json"
    app = create_dev_mobile_app("192.168.1.42", 8795, UPSTREAM, "daily", path,
                                transport=httpx.ASGITransport(app=core))
    auth = {"Authorization": "Bearer " + json.loads(path.read_text())["accessToken"]}
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        bootstrap = (await client.get("/api/bootstrap", headers=auth)).json()
        token = bootstrap["token"]
        assert bootstrap["identities"][0]["id"] == "daily"
        assert (await client.post("/api/activity/seen", json={"items": []}, headers={**auth, "Origin": ORIGIN})).status_code == 403
        response = await client.post("/api/activity/seen", json={"items": []},
                                     headers={**auth, "Origin": ORIGIN, "X-Wearing-Token": token})
        assert response.status_code != 403
        assert (await client.get("/api/activity", headers=auth)).status_code == 200
    await core.state.service.hermes.close()
