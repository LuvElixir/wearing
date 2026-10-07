import base64
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlparse

import httpx
from joserfc import jwt
from joserfc.jwk import RSAKey
import pytest
from sqlalchemy import select, update

from wearing.cloud.control import ControlStore, routes, sessions, states
from wearing.cloud.gateway import (GatewayError, create_gateway_app, initialize_gateway,
                                   load_gateway, register_route)
from wearing.cloud.instance import initialize_instance
from wearing.cloud.worker import create_tenant_app
from wearing.config import write_private_json


ORIGIN = "https://wearing.example"
ISSUER = "https://identity.example"
KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})


class Provider:
    """Test identity provider; real RSA signature and S256 exchange, no accounts."""
    def __init__(self):
        self.codes = {}
        self.token_calls = 0

    def authorize(self, url, subject="alice", overrides=None, key=KEY):
        params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        assert params["response_type"] == "code" and params["scope"] == "openid"
        assert params["code_challenge_method"] == "S256"
        assert params["redirect_uri"] == ORIGIN + "/auth/callback"
        code = "code_" + params["state"]
        self.codes[code] = (params, subject, overrides or {}, key)
        return {"code": code, "state": params["state"]}

    def handle(self, request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
                                           "token_endpoint": ISSUER + "/token", "jwks_uri": ISSUER + "/jwks",
                                           "id_token_signing_alg_values_supported": ["RS256"]})
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [KEY.as_dict(private=False)]})
        assert request.url.path == "/token" and request.method == "POST"
        self.token_calls += 1
        values = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        params, subject, overrides, key = self.codes.pop(values["code"])
        challenge = base64.urlsafe_b64encode(hashlib.sha256(values["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        assert challenge == params["code_challenge"]
        assert values["redirect_uri"] == ORIGIN + "/auth/callback"
        claims = {"iss": ISSUER, "sub": subject, "aud": "wearing-test", "iat": int(time.time()),
                  "exp": int(time.time()) + 300, "nonce": params["nonce"], **overrides}
        if claims.get("nonce") is None:
            claims.pop("nonce", None)
        token = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)
        return httpx.Response(200, json={"access_token": "private-access-token", "refresh_token": "private-refresh-token",
                                       "id_token": token, "token_type": "Bearer", "expires_in": 300})


class Workers(httpx.AsyncBaseTransport):
    def __init__(self, apps):
        self.apps = {port: httpx.ASGITransport(app=app) for port, app in apps.items()}
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return await self.apps[request.url.port].handle_async_request(request)


@asynccontextmanager
async def lab(tmp_path):
    gateway_root, a, b = tmp_path / "entry", tmp_path / "A", tmp_path / "B"
    initialize_gateway(gateway_root, ORIGIN, ISSUER, "wearing-test", development=True)
    initialize_instance(a, "tenant_A", ORIGIN)
    initialize_instance(b, "tenant_B", ORIGIN)
    control = ControlStore(load_gateway(gateway_root).database_url.get_secret_value())
    control.grant(ISSUER, "alice", "tenant_A")
    control.grant(ISSUER, "bob", "tenant_B")
    register_route(gateway_root, a, "http://127.0.0.1:39001")
    register_route(gateway_root, b, "http://127.0.0.1:39002")
    wa, wb = create_tenant_app(a, engine_autostart=False), create_tenant_app(b, engine_autostart=False)
    workers, provider = Workers({39001: wa, 39002: wb}), Provider()
    app = create_gateway_app(gateway_root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=workers)
    async with wa.router.lifespan_context(wa), wb.router.lifespan_context(wb), app.router.lifespan_context(app):
        try:
            yield gateway_root, a, b, control, workers, provider, app
        finally:
            control.close()


async def login(client, provider, subject="alice", **kwargs):
    redirect = await client.get("/auth/login")
    assert redirect.status_code == 302
    callback = provider.authorize(redirect.headers["location"], subject, **kwargs)
    return await client.get("/auth/callback", params=callback)


async def test_oidc_login_routes_only_own_worker_and_drops_untrusted_credentials(tmp_path):
    async with lab(tmp_path) as (_, a, b, control, workers, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as alice, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as bob:
            assert (await alice.get("/")).status_code == 303
            assert (await alice.get("/api/bootstrap")).status_code == 401
            assert (await alice.get("/assets/app.js")).status_code == 401
            result = await login(alice, provider)
            assert result.status_code == 303
            cookie = result.headers["set-cookie"]
            assert "__Host-wearing-session=" in cookie and "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
            decoded = json.loads(base64.b64decode(alice.cookies.get("__Host-wearing-session").split(".")[0]))
            assert set(decoded) == {"sid"}
            assert (await login(bob, provider, "bob")).status_code == 303
            assert (await alice.get("/auth/session")).json()["tenant_id"] == "tenant_A"
            assert (await bob.get("/auth/session")).json()["tenant_id"] == "tenant_B"
            bootstrap = (await alice.get("/api/bootstrap")).json()
            for path in ("/", "/assets/chat-portrait.png", "/api/bootstrap", "/api/memory"):
                response = await alice.get(path)
                assert response.status_code == 200
                assert response.headers["cache-control"] == "private, no-store"
                assert (a / "gateway.key").read_text().strip() not in response.text
            posted = await alice.post("/api/conversation", headers={"Origin": ORIGIN, "X-Wearing-Token": bootstrap["token"],
                                                                    "X-Wearing-Tenant": "tenant_B", "Authorization": "Bearer attacker"},
                                      json={"content": "Alice-only idea"})
            assert posted.status_code == 201
            assert "Alice-only idea" in (await alice.get("/api/conversation")).text
            assert (await bob.get("/api/conversation")).json() == []
            assert (await bob.get("/api/tasks/" + posted.json()["task"]["id"])).status_code == 404
            sent = next(r for r in workers.requests if r.method == "POST")
            assert sent.headers["x-wearing-tenant"] == "tenant_A"
            assert sent.headers["authorization"] == "Bearer " + (a / "gateway.key").read_text().strip()
            assert "cookie" not in sent.headers
            assert (await alice.get("/internal/runtime")).status_code == 404
            assert (await alice.post("/api/conversation", json={"content": "missing origin"})).status_code == 403
            assert (await alice.post("/api/conversation", headers={"Origin": "https://foreign.example"}, json={"content": "foreign"})).status_code == 403
            assert (await alice.get("/auth/session", headers={"Host": "wearing.example:444"})).status_code == 400
            control.grant(ISSUER, "alice", "tenant_A", active=False)
            assert (await alice.get("/api/conversation")).status_code == 401
            assert (await bob.get("/api/bootstrap")).status_code == 200


@pytest.mark.parametrize("claims", [{"iss": "https://wrong.example"}, {"aud": "wrong-app"}, {"exp": int(time.time()) - 3600},
                                   {"nonce": "wrong"}, {"nonce": None}, {"nonce_supported": False, "nonce": "wrong"}])
async def test_real_signature_claim_validation_rejects_wrong_identity(tmp_path, claims):
    async with lab(tmp_path) as (*_, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            result = await login(client, provider, overrides=claims)
            assert result.status_code == 400
            assert "private-" not in result.text
            assert (await client.get("/auth/session")).status_code == 401


async def test_wrong_signature_uninvited_user_and_state_from_another_browser(tmp_path):
    async with lab(tmp_path) as (*_, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as first, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as stranger:
            wrong_key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
            assert (await login(first, provider, key=wrong_key)).status_code == 400
            assert (await login(first, provider, "uninvited")).status_code == 403
            redirect = await first.get("/auth/login")
            params = provider.authorize(redirect.headers["location"])
            previous_calls = provider.token_calls
            assert (await stranger.get("/auth/callback", params=params)).status_code == 400
            assert provider.token_calls == previous_calls
            old_cookie = first.cookies.get("__Host-wearing-session")
            assert (await first.get("/auth/callback", params=params)).status_code == 303
            stranger.cookies.set("__Host-wearing-session", old_cookie)
            assert (await stranger.get("/auth/callback", params=params)).status_code == 400
            assert provider.token_calls == previous_calls + 1


async def test_logout_switch_expiry_and_server_session_restart(tmp_path):
    async with lab(tmp_path) as (root, a, b, control, workers, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            assert (await login(client, provider)).status_code == 303
            account = (await client.get("/auth/session")).json()
            mutation = {"Origin": ORIGIN, "X-Wearing-CSRF": account["csrf"]}
            assert (await client.post("/auth/tenant", headers=mutation, json={"tenant_id": "tenant_B"})).status_code == 403
            assert (await client.post("/auth/logout", headers={"Origin": ORIGIN})).status_code == 403
            saved_cookie = client.cookies.get("__Host-wearing-session")
            second = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=workers)
            async with second.router.lifespan_context(second), httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url=ORIGIN, cookies={"__Host-wearing-session": saved_cookie}) as restarted:
                assert (await restarted.get("/api/bootstrap")).status_code == 200
                control.grant(ISSUER, "alice", "tenant_B")
                assert (await restarted.post("/auth/tenant", headers=mutation, json={"tenant_id": "tenant_B"})).status_code == 200
                assert (await restarted.get("/auth/session")).json()["tenant_id"] == "tenant_B"
                assert (await restarted.post("/auth/logout", headers=mutation)).status_code == 200
                restarted.cookies.set("__Host-wearing-session", saved_cookie)
                assert (await restarted.get("/api/bootstrap")).status_code == 401
            assert (await login(client, provider)).status_code == 303
            with control.engine.begin() as db:
                db.execute(update(sessions).values(expires=0))
            assert (await client.get("/auth/session")).status_code == 401


async def test_pending_oidc_flow_survives_restart_and_expires(tmp_path):
    async with lab(tmp_path) as (root, a, b, control, workers, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as first:
            redirect = await first.get("/auth/login")
            params = provider.authorize(redirect.headers["location"])
            cookie = first.cookies.get("__Host-wearing-session")
            payload = json.loads(base64.b64decode(cookie.split(".")[0]))
            assert len(payload) == 1 and set(next(iter(payload.values()))) == {"exp"}
            second = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=workers)
            async with second.router.lifespan_context(second), httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url=ORIGIN, cookies={"__Host-wearing-session": cookie}) as restarted:
                assert (await restarted.get("/auth/callback", params=params)).status_code == 303
                redirect = await restarted.get("/auth/login")
                params = provider.authorize(redirect.headers["location"])
                with control.engine.begin() as db:
                    db.execute(update(states).values(expires=0))
                calls = provider.token_calls
                assert (await restarted.get("/auth/callback", params=params)).status_code == 400
                assert provider.token_calls == calls


async def test_wrong_route_credential_unavailable_worker_and_bounded_body(tmp_path):
    async with lab(tmp_path) as (root, a, b, control, workers, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            assert (await login(client, provider)).status_code == 303
            assert (await client.post("/api/conversation", headers={"Origin": ORIGIN}, content=b"x" * 1048577)).status_code == 413
            account = (await client.get("/auth/session")).json()
            route = control.route(control.session(json.loads(base64.b64decode(client.cookies.get("__Host-wearing-session").split(".")[0]))["sid"]))
            path = root / "credentials" / route["credential_ref"]
            write_private_json(path, {"tenant_id": "tenant_B", "instance_id": route["instance_id"], "key": (b / "gateway.key").read_text().strip()})
            count = len(workers.requests)
            result = await client.get("/api/bootstrap")
            assert result.status_code == 503 and len(workers.requests) == count
            assert "private" not in result.text
            for path in ("/api/%2e%2e/internal/runtime", "/assets/%252e%252e/internal/runtime", "/internal/runtime"):
                assert (await client.get(path)).status_code == 404


async def test_wrong_upstream_is_rejected_by_worker_and_cookie_jar_never_crosses(tmp_path):
    async with lab(tmp_path) as (root, a, b, control, workers, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            assert (await login(client, provider)).status_code == 303
            with control.engine.begin() as db:
                db.execute(update(routes).where(routes.c.tenant_id == "tenant_A").values(upstream="http://127.0.0.1:39002"))
            assert (await client.get("/api/bootstrap")).status_code == 401
            assert (await client.get("/api/conversation")).status_code == 401
            with control.engine.begin() as db:
                db.execute(update(routes).where(routes.c.tenant_id == "tenant_A").values(upstream="http://127.0.0.1:39001"))
            assert (await client.get("/api/bootstrap")).status_code == 200
        class ResponseStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"ok":true}'
        captured = []
        def worker(request):
            captured.append(request)
            return httpx.Response(200, stream=ResponseStream(), headers={"Set-Cookie": "private-worker-cookie=secret; Path=/", "Content-Type": "application/json"})
        another = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=httpx.MockTransport(worker))
        async with another.router.lifespan_context(another), httpx.AsyncClient(transport=httpx.ASGITransport(app=another), base_url=ORIGIN) as client:
            assert (await login(client, provider)).status_code == 303
            for _ in range(2):
                response = await client.get("/api/bootstrap")
                assert response.status_code == 200
                assert "private-worker-cookie" not in response.headers.get("set-cookie", "")
            assert all("cookie" not in request.headers for request in captured)


async def test_unavailable_worker_and_wrong_discovery_do_not_expose_private_errors(tmp_path):
    async with lab(tmp_path) as (root, a, b, control, workers, provider, app):
        def offline(request):
            raise httpx.ConnectError("private-worker-address", request=request)
        another = create_gateway_app(root, oidc_transport=httpx.MockTransport(provider.handle), worker_transport=httpx.MockTransport(offline))
        async with another.router.lifespan_context(another), httpx.AsyncClient(transport=httpx.ASGITransport(app=another), base_url=ORIGIN) as client:
            assert (await login(client, provider)).status_code == 303
            response = await client.get("/api/bootstrap")
            assert response.status_code == 503 and "private-worker" not in response.text
        def bad_discovery(request):
            response = provider.handle(request)
            value = response.json()
            value["issuer"] = "https://untrusted.example"
            return httpx.Response(200, json=value)
        another = create_gateway_app(root, oidc_transport=httpx.MockTransport(bad_discovery), worker_transport=workers)
        async with another.router.lifespan_context(another), httpx.AsyncClient(transport=httpx.ASGITransport(app=another), base_url=ORIGIN) as client:
            response = await client.get("/auth/login")
            assert response.status_code == 503
            assert "untrusted.example" not in response.text


def test_configuration_enrollment_and_route_rebind_are_bounded(tmp_path):
    root = tmp_path / "entry"
    with pytest.raises(GatewayError):
        initialize_gateway(root, "http://wearing.public", ISSUER, "app", development=True)
    assert not root.exists()
    initialize_gateway(root, ORIGIN, ISSUER, "app", development=True)
    with pytest.raises(GatewayError):
        initialize_gateway(root, ORIGIN, ISSUER, "app", development=True)
    a = tmp_path / "A"
    initialize_instance(a, "tenant_A", ORIGIN)
    control = ControlStore(load_gateway(root).database_url.get_secret_value())
    try:
        control.grant(ISSUER, "alice", "tenant_A")
        register_route(root, a, "http://127.0.0.1:39001")
        register_route(root, a, "http://127.0.0.1:39001")
        with pytest.raises(ValueError):
            register_route(root, a, "http://127.0.0.1:39002")
        with pytest.raises(ValueError):
            register_route(root, a, "http://169.254.169.254")
    finally:
        control.close()


def test_development_metadata_cannot_adopt_or_symlink_another_user_database(tmp_path):
    original = tmp_path / "original.sqlite3"
    original.write_bytes(b"original-user-database")
    root = tmp_path / "entry"
    with pytest.raises(GatewayError):
        initialize_gateway(root, ORIGIN, ISSUER, "app", development=True, database_url="sqlite:///" + str(original))
    assert not root.exists()
    initialize_gateway(root, ORIGIN, ISSUER, "app", development=True)
    database = root / "control.sqlite3"
    database.unlink()
    database.symlink_to(original)
    with pytest.raises(GatewayError):
        create_gateway_app(root)
    assert original.read_bytes() == b"original-user-database"
