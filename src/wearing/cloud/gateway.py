"""OIDC entry and membership router. Internal worker credentials stay server-side."""

from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import re
import secrets
from urllib.parse import unquote, urlparse

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
import httpx
from pydantic import Field, SecretStr, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.routing import Route

from .commands import Identifier, Record
from .control import ControlError, ControlStore, OIDCStateCache
from .instance import TenantInstance, checked_root, load_instance, read_private
from .postgres import same_database, validate_database_url
from ..config import private_directory, write_private_json


class GatewayError(ValueError):
    pass


def endpoint(value, development=False):
    url = urlparse(value)
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise GatewayError("服务地址格式不正确。")
    if url.scheme != "https" and not (development and url.hostname in {"127.0.0.1", "localhost", "::1"}):
        raise GatewayError("服务地址需要 HTTPS；只有本地开发允许回环 HTTP。")
    if url.port is not None and not 1 <= url.port <= 65535:
        raise GatewayError("服务端口不正确。")
    return value.rstrip("/")


class GatewayConfig(Record):
    schema_version: int = Field(default=1, ge=1, le=1, strict=True)
    public_origin: str
    issuer: str
    client_id: str = Field(min_length=1, max_length=256)
    client_secret: SecretStr = Field(default=SecretStr(""), max_length=4096)
    session_key: SecretStr = Field(min_length=32, max_length=256)
    database_url: SecretStr
    development: bool = False

    @field_validator("public_origin")
    @classmethod
    def origin(cls, value):
        return TenantInstance.origin(value)

    @model_validator(mode="after")
    def addresses(self):
        endpoint(self.issuer, self.development)
        if self.issuer.endswith("/"):
            raise GatewayError("Issuer 应使用提供商声明的固定地址，不带结尾斜线。")
        if not self.development and (urlparse(self.public_origin).scheme != "https" or not self.database_url.get_secret_value().startswith("postgresql+psycopg://")):
            raise GatewayError("生产入口需要 HTTPS 与 PostgreSQL。")
        if not self.database_url.get_secret_value().startswith("sqlite:///"):
            validate_database_url(self.database_url.get_secret_value(), development=self.development)
        return self


def load_gateway(root):
    root = checked_root(root)
    try:
        config = GatewayConfig.model_validate_json(read_private(root / "gateway.json"))
        if config.database_url.get_secret_value().startswith("sqlite:///"):
            database = root / "control.sqlite3"
            if (config.database_url.get_secret_value() != "sqlite:///" + str(database)
                    or database.is_symlink() or not database.is_file()):
                raise GatewayError("开发元数据库必须属于本入口的私有目录。")
        return config
    except (ValueError, OSError) as error:
        raise GatewayError("入口配置无法读取；请检查私有目录与配置。") from error


def initialize_gateway(root, public_origin, issuer, client_id, *, client_secret="", database_url="", development=False):
    root = checked_root(root)
    local_database = "sqlite:///" + str(root / "control.sqlite3")
    if development and database_url.startswith("sqlite:///") and database_url != local_database:
        raise GatewayError("开发元数据库必须使用本入口独立的新目录。")
    try:
        config = GatewayConfig(public_origin=public_origin, issuer=issuer, client_id=client_id,
                               client_secret=client_secret, session_key=secrets.token_urlsafe(48),
                               database_url=database_url or local_database, development=development)
    except ValueError as error:
        raise GatewayError("入口地址、登录服务或数据库配置不正确。") from error
    if root.exists() and any(root.iterdir()):
        raise GatewayError("入口目录已有内容，不能覆盖配置。")
    private_directory(root)
    private_directory(root / "credentials")
    data = config.model_dump(mode="json")
    for name in ("client_secret", "session_key", "database_url"):
        data[name] = getattr(config, name).get_secret_value()
    write_private_json(root / "gateway.json", data)
    if config.database_url.get_secret_value().startswith("sqlite:///"):
        store = ControlStore(config.database_url.get_secret_value(), initialize=True)
        store.close()
        (root / "control.sqlite3").chmod(0o600)
    return config


def operator_store(config, *, database_url=None):
    runtime = config.database_url.get_secret_value()
    if runtime.startswith("sqlite:///"):
        return ControlStore(runtime)
    operator_url = database_url or os.environ.get("WEARING_CONTROL_OPERATOR_DATABASE_URL", "")
    if not operator_url or not same_database(runtime, operator_url):
        raise GatewayError("会员与路由登记需要同一数据库的独立操作者凭据。")
    validate_database_url(operator_url, development=config.development)
    return ControlStore(operator_url, operator=True)


def register_route(root, tenant_root, upstream):
    root = checked_root(root)
    config, instance = load_gateway(root), load_instance(tenant_root)
    upstream = endpoint(upstream, config.development)
    if urlparse(upstream).path:
        raise GatewayError("实例地址需要服务根地址。")
    if instance.public_origin != config.public_origin:
        raise GatewayError("实例与入口的网页来源不一致。")
    credential_ref = instance.instance_id + ".json"
    store = operator_store(config)
    try:
        # Bind before writing a credential, so invalid rebinds do not replace secrets.
        store.bind(instance.tenant_id, instance.instance_id, upstream, credential_ref)
        write_private_json(root / "credentials" / credential_ref,
                           {"tenant_id": instance.tenant_id, "instance_id": instance.instance_id,
                            "key": read_private(checked_root(tenant_root) / "gateway.key").strip()})
    finally:
        store.close()


def proxy_path(path):
    decoded = unquote(path)
    return ("%" not in decoded and not any(p in {".", ".."} for p in decoded.split("/"))
            and (decoded == "/" or decoded.startswith(("/api/", "/assets/"))))


async def forward_worker(wire, request, upstream, public_origin, tenant_id, key):
    """Same fixed-origin, bounded, cookie-free forwarding for OIDC and private SSH entry."""
    headers = {"Authorization": "Bearer " + key, "X-Wearing-Tenant": tenant_id,
               "Host": urlparse(public_origin).netloc}
    for name in ("content-type", "accept", "range", "if-none-match", "if-modified-since", "x-wearing-token", "x-wearing-identity", "origin"):
        if name in request.headers:
            headers[name] = request.headers[name]
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 1048576:
            return JSONResponse({"detail": "请求内容过大。"}, status_code=413)
        body.extend(chunk)
    upstream_url = httpx.URL(upstream).copy_with(path=request.url.path, query=request.scope.get("query_string", b""))
    if not proxy_path(upstream_url.path):
        return JSONResponse({"detail": "此入口不存在。"}, status_code=404)
    outgoing = wire.build_request(request.method, upstream_url, headers=headers, content=bytes(body))
    # HTTPX has a client cookie jar, including cookies set by prior workers.
    # None of those, or the browser session cookie, may cross this boundary.
    outgoing.headers.pop("cookie", None)
    response = await wire.send(outgoing, stream=True)
    response_headers = {name: response.headers[name] for name in ("content-type", "content-length", "content-disposition", "etag", "last-modified", "accept-ranges", "content-range", "content-encoding", "content-security-policy", "x-content-type-options") if name in response.headers}
    response_headers["Cache-Control"] = "private, no-store"
    return StreamingResponse(response.aiter_raw(), status_code=response.status_code, headers=response_headers,
                             background=BackgroundTask(response.aclose))



class EntryHeaders:
    def __init__(self, app, host, websocket_paths=()):
        self.app, self.host = app, host.encode("ascii")
        self.websocket_paths = frozenset(websocket_paths)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket" and scope.get("path") in self.websocket_paths:
            hosts = [v for k, v in scope.get("headers", []) if k.lower() == b"host"]
            if hosts == [self.host]:
                return await self.app(scope, receive, send)
        if scope["type"] != "http":
            return await send({"type": "websocket.close", "code": 1008})
        hosts = [v for k, v in scope.get("headers", []) if k.lower() == b"host"]
        if hosts != [self.host]:
            return await JSONResponse({"detail": "入口地址不正确。"}, status_code=400)(scope, receive, send)
        async def private_response(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "private, no-store"
                headers["Referrer-Policy"] = "no-referrer"
            await send(message)
        return await self.app(scope, receive, private_response)


def create_gateway_app(root: Path, *, oidc_transport=None, worker_transport=None):
    root = checked_root(root)
    config = load_gateway(root)
    # Upstream debug logging includes fetched token values. Never enable it here.
    logging.getLogger("authlib").setLevel(logging.WARNING)
    store = ControlStore(config.database_url.get_secret_value())
    cache = OIDCStateCache(store)
    oauth = OAuth(cache=cache)
    oauth.register("wearing", client_id=config.client_id, client_secret=config.client_secret.get_secret_value() or None,
                   server_metadata_url=config.issuer + "/.well-known/openid-configuration",
                   client_kwargs={"scope": "openid", "code_challenge_method": "S256", "trust_env": False,
                                  "timeout": 10, "follow_redirects": False,
                                  "token_endpoint_auth_method": "client_secret_basic" if config.client_secret.get_secret_value() else "none",
                                  **({"transport": oidc_transport} if oidc_transport else {})})
    oidc = oauth.create_client("wearing")
    oidc.framework.expires_in = 600
    wire = httpx.AsyncClient(transport=worker_transport, trust_env=False, follow_redirects=False,
                            timeout=httpx.Timeout(30), limits=httpx.Limits(max_connections=40))

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await wire.aclose()
            store.close()

    def session(request):
        return store.session(request.session.get("sid"))

    def unsafe_allowed(request, current, *, portal=False):
        if request.headers.get("origin") != config.public_origin:
            return False
        return not portal or secrets.compare_digest(request.headers.get("x-wearing-csrf", "").encode("utf-8"), current.csrf.encode("ascii"))

    async def verified_metadata():
        metadata = await oidc.load_server_metadata()
        if metadata.get("issuer") != config.issuer:
            raise GatewayError("登录服务声明与配置不一致。")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            endpoint(metadata.get(name, ""), config.development)
        # Use asymmetric signatures only, independently of metadata suggestions.
        oidc.server_metadata["id_token_signing_alg_values_supported"] = ["RS256", "ES256"]

    async def login(request):
        await verified_metadata()
        return await oidc.authorize_redirect(request, config.public_origin + "/auth/callback")

    async def callback(request):
        state = request.query_params.get("state", "")
        if len(state) > 256 or not request.session.get("_state_wearing_" + state):
            return JSONResponse({"detail": "登录关联已失效，请重新登录。"}, status_code=400)
        nonce = cache.nonce("_state_wearing_" + state)
        if not nonce:
            return JSONResponse({"detail": "登录关联已失效，请重新登录。"}, status_code=400)
        # A callback can land on a restarted gateway: reapply the algorithm limit.
        await verified_metadata()
        try:
            token = await oidc.authorize_access_token(request, claims_options={"iss": {"essential": True, "value": config.issuer}}, leeway=30)
            user = token.get("userinfo", {})
            if not isinstance(user.get("sub"), str) or not user["sub"] or user.get("nonce") != nonce:
                raise GatewayError("登录凭据无效。")
            sid = store.login(config.issuer, user["sub"])
        except ControlError:
            return JSONResponse({"detail": "此账号尚未加入 Wearing 试用。"}, status_code=403)
        except Exception:
            # Authlib/JOSE errors can contain provider tokens or callback values.
            return JSONResponse({"detail": "登录验证未完成，请重新登录。"}, status_code=400)
        store.logout(request.session.get("sid"))
        request.session.clear()
        request.session["sid"] = sid
        return RedirectResponse("/", status_code=303)

    async def account(request):
        current = session(request)
        if current is None:
            return JSONResponse({"detail": "请先登录 Wearing。"}, status_code=401)
        return JSONResponse({"user_id": current.user_id, "tenant_id": current.tenant_id,
                             "tenants": store.memberships(current), "csrf": current.csrf})

    async def logout(request):
        current = session(request)
        if current is None or not unsafe_allowed(request, current, portal=True):
            return JSONResponse({"detail": "登录或页面验证已失效。"}, status_code=403)
        store.logout(request.session.get("sid"))
        request.session.clear()
        return JSONResponse({"logged_out": True})

    async def switch(request):
        current = session(request)
        if current is None or not unsafe_allowed(request, current, portal=True):
            return JSONResponse({"detail": "登录或页面验证已失效。"}, status_code=403)
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("tenant_id"), str):
            return JSONResponse({"detail": "请选择自己的 Wearing。"}, status_code=422)
        store.switch(request.session["sid"], body["tenant_id"])
        return JSONResponse({"switched": True})

    async def proxy(request):
        if not proxy_path(request.url.path):
            return JSONResponse({"detail": "此入口不存在。"}, status_code=404)
        current = session(request)
        if current is None:
            if request.url.path == "/":
                return RedirectResponse("/auth/login", status_code=303)
            return JSONResponse({"detail": "请先登录 Wearing。"}, status_code=401)
        if request.method not in {"GET", "HEAD"} and not unsafe_allowed(request, current):
            return JSONResponse({"detail": "请求来源未通过验证。"}, status_code=403)
        route = store.route(current)
        if route is None:
            return JSONResponse({"detail": "你的 Wearing 正在准备，请稍后再试。"}, status_code=503)
        if not re.fullmatch(r"instance_[a-f0-9]{32}\.json", route["credential_ref"]):
            raise GatewayError("实例凭据引用无效。")
        credential = json.loads(read_private(root / "credentials" / route["credential_ref"]))
        if (not isinstance(credential, dict) or credential.get("tenant_id") != current.tenant_id
                or credential.get("instance_id") != route["instance_id"]
                or not isinstance(credential.get("key"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{64}", credential["key"])):
            raise GatewayError("实例凭据与路由不一致。")
        return await forward_worker(wire, request, route["upstream"], config.public_origin, current.tenant_id, credential["key"])

    async def safe_failure(request, error):
        return JSONResponse({"detail": "入口暂时未就绪，请稍后再试。"}, status_code=503)

    async def denied(request, error):
        return JSONResponse({"detail": "此账号不能进入该 Wearing。"}, status_code=403)

    app = Starlette(routes=[Route("/auth/login", login), Route("/auth/callback", callback),
                           Route("/auth/session", account), Route("/auth/logout", logout, methods=["POST"]),
                           Route("/auth/tenant", switch, methods=["POST"]),
                           Route("/{path:path}", proxy, methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])],
                    lifespan=lifespan,
                    exception_handlers={ControlError: denied, GatewayError: safe_failure, SQLAlchemyError: safe_failure,
                                        httpx.HTTPError: safe_failure, OAuthError: safe_failure, ValueError: safe_failure})
    app.state.control = store
    app.state.oidc = oidc
    app.add_middleware(SessionMiddleware, secret_key=config.session_key.get_secret_value(),
                       session_cookie="__Host-wearing-session" if config.public_origin.startswith("https:") else "wearing-session-dev",
                       max_age=28800, same_site="lax", https_only=config.public_origin.startswith("https:"))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(config.public_origin).hostname])
    app.add_middleware(EntryHeaders, host=urlparse(config.public_origin).netloc)
    return app
