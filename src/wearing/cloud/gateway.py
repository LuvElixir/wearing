"""OIDC entry and membership router. Internal worker credentials stay server-side."""

from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import unquote, urlparse, parse_qs
from datetime import datetime, timezone

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
import httpx
from pydantic import Field, SecretStr, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from .voice import voice_endpoint, PATH as VOICE_PATH

from .commands import Identifier, Record
from .control import ControlError, ControlStore, OIDCStateCache, users
from .deletion_gateway import ReceiptCodec, deletion_routes, fresh_auth, small_json, PREFIX
from .session_guard import SessionRevoked, checked_wait
from .request_body import RequestBodyBoundary, RequestBodyError, gateway_body_limit, rejected_body
from .mobile_auth import mobile_request, issue_handoff, exchange_handoff, session_storage_scope
from .upstream_tls import upstream_tls_context
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


async def forward_worker(wire, request, upstream, public_origin, tenant_id, key, session_expires=None, storage_scope=None, access_check=None, private_owner_scope=None):
    """Same fixed-origin, bounded, cookie-free forwarding for OIDC and private SSH entry."""
    headers = {"Authorization": "Bearer " + key, "X-Wearing-Tenant": tenant_id,
               "Host": urlparse(public_origin).netloc}
    if session_expires is not None:
        headers['X-Pajio-Session-Expires'] = str(session_expires)
    if storage_scope is not None:
        # Never copy this value from caller-controlled headers/query parameters.
        headers['X-Pajio-Storage-Scope'] = storage_scope
    if private_owner_scope is not None:
        headers['X-Pajio-Private-Owner-Scope'] = private_owner_scope
    for name in ("content-type", "accept", "range", "if-none-match", "if-modified-since", "x-wearing-token", "x-wearing-identity", "origin"):
        if name in request.headers:
            headers[name] = request.headers[name]
    limit = gateway_body_limit({"path": request.url.path})
    body = bytearray()
    chunks = request.stream().__aiter__()
    while True:
        try:
            chunk = await checked_wait(anext(chunks), access_check)
        except StopAsyncIteration:
            break
        if len(body) + len(chunk) > limit:
            return JSONResponse({"detail": "请求内容过大。"}, status_code=413)
        body.extend(chunk)
    upstream_url = httpx.URL(upstream).copy_with(path=request.url.path, query=request.scope.get("query_string", b""))
    if not proxy_path(upstream_url.path):
        return JSONResponse({"detail": "此入口不存在。"}, status_code=404)
    outgoing = wire.build_request(request.method, upstream_url, headers=headers, content=bytes(body))
    # HTTPX has a client cookie jar, including cookies set by prior workers.
    # None of those, or the browser session cookie, may cross this boundary.
    outgoing.headers.pop("cookie", None)
    response = await checked_wait(wire.send(outgoing, stream=True), access_check, cleanup=lambda value: value.aclose())
    response_headers = {name: response.headers[name] for name in ("content-type", "content-length", "content-disposition", "etag", "last-modified", "accept-ranges", "content-range", "content-encoding", "content-security-policy", "x-content-type-options") if name in response.headers}
    response_headers["Cache-Control"] = "private, no-store"
    async def stream():
        chunks = response.aiter_raw().__aiter__()
        try:
            while True:
                try:
                    yield await checked_wait(anext(chunks), access_check)
                except (StopAsyncIteration, SessionRevoked):
                    return
        finally:
            await response.aclose()
    return StreamingResponse(stream(), status_code=response.status_code, headers=response_headers,
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


def create_gateway_app(root: Path, *, oidc_transport=None, worker_transport=None, voice_connector=None):
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
    upstream_tls = upstream_tls_context()
    wire = httpx.AsyncClient(transport=worker_transport, trust_env=False, follow_redirects=False,
                            verify=upstream_tls if upstream_tls is not None else True,
                            timeout=httpx.Timeout(30), limits=httpx.Limits(max_connections=40))

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await wire.aclose()
            store.close()

    def session_id(request):
        headers = request.headers.getlist("authorization")
        if headers:
            if len(headers) != 1 or not re.fullmatch(r"Bearer [A-Za-z0-9_-]{64}", headers[0]):
                return None
            return headers[0][7:]
        return request.session.get("sid")

    def session(request):
        current = store.session(session_id(request))
        expected = request.headers.getlist('x-pajio-expected-tenant')
        if expected and (len(expected) != 1 or current is None or expected[0] != current.tenant_id):
            return None
        pinned = request.session.get('native_tenant')
        if not request.headers.get('authorization') and pinned and (current is None or pinned != current.tenant_id):
            return None
        return current

    def unsafe_allowed(request, current, *, portal=False):
        origin = request.headers.getlist("origin")
        if request.headers.get("authorization"):
            # Explicit native bearer proof cannot be attached by cross-site forms.
            return origin in ([], [config.public_origin])
        if origin != [config.public_origin]:
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

    async def login(request, **options):
        await verified_metadata()
        return await oidc.authorize_redirect(request, config.public_origin + "/auth/callback", **options)

    async def deletion_reauth(request):
        current = session(request)
        if current is None:
            return JSONResponse({'detail': '请先登录 Pajio。'}, status_code=401)
        if not unsafe_allowed(request, current, portal=True):
            return JSONResponse({'detail': '请求来源未通过验证。'}, status_code=403)
        try:
            body = await small_json(request)
            mobile = mobile_request(body) if body else None
            if body and set(body) != {'challenge', 'state'}:
                raise ValueError('登录关联不完整。')
        except ValueError:
            return JSONResponse({'detail': '登录关联不完整。'}, status_code=422)
        latest = session(request)
        if latest is None or latest.user_id != current.user_id or latest.tenant_id != current.tenant_id:
            return JSONResponse({'detail': '身份验证已失效。'}, status_code=401)
        ticket = secrets.token_urlsafe(32)
        await cache.set('deletion-start:' + ticket, json.dumps({'sid': session_id(request), 'mobile': mobile}), 120)
        return JSONResponse({'authorize_url': config.public_origin + PREFIX + '/reauth/start?ticket=' + ticket})

    async def deletion_reauth_start(request):
        ticket = request.query_params.get('ticket', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', ticket):
            return JSONResponse({'detail': '身份验证关联已失效。'}, status_code=400)
        saved = await cache.get('deletion-start:' + ticket)
        context = json.loads(saved) if saved else None
        current = store.session(context['sid']) if context else None
        if current is None:
            return JSONResponse({'detail': '身份验证关联已失效。'}, status_code=401)
        response = await login(request, max_age=0, prompt='login',
                               claims=json.dumps({'id_token': {'auth_time': {'essential': True}}}))
        state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
        await cache.set('deletion-reauth:' + state, json.dumps({**context, 'user_id': current.user_id,
                        'tenant_id': current.tenant_id, 'started': int(time.time())}), 600)
        return response

    async def mobile_start(request):
        try:
            handoff = mobile_request(request.query_params)
        except ValueError as error:
            return JSONResponse({"detail": str(error)}, status_code=422)
        response = await login(request)
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        request.session["_mobile_" + state] = handoff
        return response

    async def mobile_exchange(request):
        if request.headers.getlist("origin") not in ([], [config.public_origin]):
            return JSONResponse({"detail": "请求来源未通过验证。"}, status_code=403)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 2048:
                return JSONResponse({"detail": "登录请求过大。"}, status_code=413)
        try:
            proof = await exchange_handoff(cache, json.loads(raw))
        except (ValueError, TypeError):
            proof = None
        if not proof:
            return JSONResponse({"detail": "登录关联已失效，请重新登录。"}, status_code=400)
        sid = store.login(config.issuer, proof['subject'], auth_time=proof.get('auth_time'))
        if proof.get('tenant_id'):
            store.switch(sid, proof['tenant_id'])
        current = store.session(sid)
        return JSONResponse({"access_token": sid, "token_type": "Bearer", "user_id": current.user_id,
                             "tenant_id": current.tenant_id,
                             "expires_at": datetime.fromtimestamp(current.expires, timezone.utc).isoformat()})

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
            saved = await cache.get('deletion-reauth:' + state)
            reauth = json.loads(saved) if saved else None
            auth_time = None
            if reauth is not None:
                prior = store.session(reauth['sid'])
                if (prior is None or prior.user_id != reauth['user_id'] or prior.tenant_id != reauth['tenant_id']
                        or not fresh_auth(user.get('auth_time'), started=reauth['started'])):
                    raise GatewayError('需要重新验证本人身份。')
                with store.transaction(issuer=config.issuer, subject=user['sub']) as db:
                    verified_user = db.scalar(select(users.c.id).where(users.c.issuer == config.issuer, users.c.subject == user['sub']))
                if verified_user != prior.user_id:
                    raise GatewayError('重新验证的账户不一致。')
                auth_time = user['auth_time']
            handoff = reauth.get('mobile') if reauth is not None else request.session.pop("_mobile_" + state, None)
            if handoff is not None:
                return RedirectResponse(await issue_handoff(cache, mobile_request(handoff), user["sub"],
                    auth_time=auth_time, tenant_id=reauth['tenant_id'] if reauth else None), status_code=303)
            sid = store.login(config.issuer, user["sub"], auth_time=auth_time)
            if reauth is not None:
                store.switch(sid, reauth['tenant_id'])
                store.logout(reauth['sid'])
        except ControlError:
            return JSONResponse({"detail": "此账号尚未加入 Pajio 试用。"}, status_code=403)
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
            return JSONResponse({"detail": "请先登录 Pajio。"}, status_code=401)
        return JSONResponse({"user_id": current.user_id, "tenant_id": current.tenant_id,
                             "tenants": store.memberships(current), "csrf": current.csrf, "expires_at": datetime.fromtimestamp(current.expires, timezone.utc).isoformat()})

    async def logout(request):
        current = session(request)
        if current is None or not unsafe_allowed(request, current, portal=True):
            return JSONResponse({"detail": "登录或页面验证已失效。"}, status_code=403)
        store.logout(session_id(request))
        request.session.clear()
        return JSONResponse({"logged_out": True})

    async def switch(request):
        current = session(request)
        if current is None or not unsafe_allowed(request, current, portal=True):
            return JSONResponse({"detail": "登录或页面验证已失效。"}, status_code=403)
        if request.headers.get('authorization') or request.session.get('native_tenant'):
            return JSONResponse({'detail': 'App 会话已绑定当前空间。请从 App 重新登录后切换空间。'}, status_code=403)
        try:
            body = await request.json()
        except (ValueError, UnicodeError):
            return JSONResponse({"detail": "请选择自己的 Pajio。"}, status_code=422)
        if not isinstance(body, dict) or not isinstance(body.get("tenant_id"), str):
            return JSONResponse({"detail": "请选择自己的 Pajio。"}, status_code=422)
        store.switch(session_id(request), body["tenant_id"])
        return JSONResponse({"switched": True})

    def credentials(current):
        route = store.route(current)
        if route is None:
            return None, None
        store.private_owner_scope(current, route)
        if not re.fullmatch(r"instance_[a-f0-9]{32}\.json", route["credential_ref"]):
            raise GatewayError("实例凭据引用无效。")
        credential = json.loads(read_private(root / "credentials" / route["credential_ref"]))
        if (not isinstance(credential, dict) or credential.get("tenant_id") != current.tenant_id
                or credential.get("instance_id") != route["instance_id"]
                or not isinstance(credential.get("key"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{64}", credential["key"])):
            raise GatewayError("实例凭据与路由不一致。")
        return route, credential["key"]

    async def proxy(request):
        if not proxy_path(request.url.path):
            return JSONResponse({"detail": "此入口不存在。"}, status_code=404)
        current = session(request)
        if current is None:
            if request.url.path == "/":
                return RedirectResponse("/auth/login", status_code=303)
            return JSONResponse({"detail": "请先登录 Pajio。"}, status_code=401)
        if request.method not in {"GET", "HEAD"} and not unsafe_allowed(request, current):
            return JSONResponse({"detail": "请求来源未通过验证。"}, status_code=403)
        if request.url.path == "/" and request.headers.get("authorization"):
            # WKWebView's initial authenticated document establishes its own
            # HttpOnly session; no token is injected into page JavaScript.
            request.session["sid"] = session_id(request)
            request.session['native_tenant'] = current.tenant_id
        route, key = credentials(current)
        if route is None:
            return JSONResponse({"detail": "你的 Pajio 正在准备，请稍后再试。"}, status_code=503)
        owner_scope = store.private_owner_scope(current, route)
        def still_allowed():
            latest = session(request)
            if latest is None or latest.user_id != current.user_id or latest.tenant_id != current.tenant_id:
                return False
            try:
                return store.private_owner_scope(latest, route) == owner_scope
            except ControlError:
                return False
        return await forward_worker(wire, request, route["upstream"], config.public_origin, current.tenant_id, key,
                                    current.expires, session_storage_scope(current.user_id, current.tenant_id), still_allowed, owner_scope)

    async def session_revoked(request, error):
        return JSONResponse({'detail': '登录权限已失效。'}, status_code=401)

    async def safe_failure(request, error):
        return JSONResponse({"detail": "入口暂时未就绪，请稍后再试。"}, status_code=503)

    async def denied(request, error):
        return JSONResponse({"detail": "此账号不能进入该 Pajio。"}, status_code=403)

    from .account_deletion_control import AccountDeletionControl
    deletion = AccountDeletionControl(store)
    receipt_codec = ReceiptCodec(config.session_key.get_secret_value())
    voice = voice_endpoint(config.public_origin, store, credentials, ssl_context=upstream_tls,
                           **({"connector": voice_connector} if voice_connector else {}))
    app = Starlette(routes=[*deletion_routes(deletion, receipt_codec, session, unsafe_allowed, reauth=deletion_reauth),
                           Route(PREFIX + '/reauth/start', deletion_reauth_start), WebSocketRoute(VOICE_PATH, voice), Route("/auth/login", login), Route("/auth/callback", callback),
                           Route("/auth/mobile/start", mobile_start), Route("/auth/mobile/exchange", mobile_exchange, methods=["POST"]),
                           Route("/auth/session", account), Route("/auth/logout", logout, methods=["POST"]),
                           Route("/auth/tenant", switch, methods=["POST"]),
                           Route("/{path:path}", proxy, methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])],
                    lifespan=lifespan,
                    exception_handlers={RequestBodyError: rejected_body, SessionRevoked: session_revoked, ControlError: denied, GatewayError: safe_failure, SQLAlchemyError: safe_failure,
                                        httpx.HTTPError: safe_failure, OAuthError: safe_failure, ValueError: safe_failure})
    app.state.control = store
    app.state.deletion = deletion
    app.state.oidc = oidc
    app.add_middleware(RequestBodyBoundary, limit=gateway_body_limit)
    app.add_middleware(SessionMiddleware, secret_key=config.session_key.get_secret_value(),
                       session_cookie="__Host-wearing-session" if config.public_origin.startswith("https:") else "wearing-session-dev",
                       max_age=28800, same_site="lax", https_only=config.public_origin.startswith("https:"))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(config.public_origin).hostname])
    app.add_middleware(EntryHeaders, host=urlparse(config.public_origin).netloc, websocket_paths=(VOICE_PATH,))
    return app
