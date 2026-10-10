"""One private Wearing app per instance. Service authentication is not user OIDC."""

from contextlib import asynccontextmanager
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlparse

from filelock import FileLock, Timeout
from starlette.responses import JSONResponse

from .instance import InstanceError, checked_root, instance_status, load_instance, read_private
from ..app import create_app
from ..config import Settings


class TenantBoundary:
    def __init__(self, app, tenant_id, gateway_key, public_host=None):
        self.app = app
        self.tenant = tenant_id.encode("ascii")
        self.credential = ("Bearer " + gateway_key).encode("ascii")
        self.public_host = public_host.encode("ascii") if public_host else None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        is_voice = scope["type"] == "websocket" and scope.get("path") == "/api/voice/stream"
        if scope["type"] != "http" and not is_voice:
            await send({"type": "websocket.close", "code": 1008})
            return
        headers = scope.get("headers", [])
        auth = [v for k, v in headers if k.lower() == b"authorization"]
        tenants = [v for k, v in headers if k.lower() == b"x-wearing-tenant"]
        if len(auth) != 1 or not secrets.compare_digest(auth[0], self.credential):
            if is_voice:
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse({"detail": "实例入口未通过验证。"}, status_code=401,
                                      headers={"Cache-Control": "no-store"})(scope, receive, send)
        if len(tenants) != 1 or not secrets.compare_digest(tenants[0], self.tenant):
            if is_voice:
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse({"detail": "请求不属于此实例。"}, status_code=403,
                                      headers={"Cache-Control": "no-store"})(scope, receive, send)
        path = scope["path"]
        if path.startswith(("/api/phone", "/api/computer", "/api/doctor", "/api/device-report", "/api/device-doctor", "/api/connection")):
            return await JSONResponse({"detail": "云端实例的设备转发尚未接通，请通过设备连接器接入。"}, status_code=501)(scope, receive, send)
        # Internal credentials must never become ordinary application headers.
        scoped = dict(scope, headers=[(k, v) for k, v in headers if k.lower() not in {b"authorization", b"x-wearing-tenant", b"x-pajio-session-expires", b"x-pajio-storage-scope", b"x-pajio-private-owner-scope"}])
        scoped['pajio.cloud_worker'] = True
        storage_scopes = [v for k, v in headers if k.lower() == b'x-pajio-storage-scope']
        if storage_scopes:
            if len(storage_scopes) != 1 or not re.fullmatch(rb'[a-f0-9]{64}', storage_scopes[0]):
                if is_voice:
                    return await send({'type': 'websocket.close', 'code': 1008})
                return await JSONResponse({'detail': '账户存储关联无效，请重新登录。'}, status_code=401)(scope, receive, send)
            scoped['pajio.storage_scope'] = storage_scopes[0].decode('ascii')
        owner_scopes = [v for k, v in headers if k.lower() == b'x-pajio-private-owner-scope']
        if owner_scopes:
            if (len(owner_scopes) != 1 or not re.fullmatch(rb'[a-f0-9]{64}', owner_scopes[0])
                    or scoped.get('pajio.storage_scope') != owner_scopes[0].decode('ascii')):
                if is_voice:
                    return await send({'type': 'websocket.close', 'code': 1008})
                return await JSONResponse({'detail': '个人空间归属未通过验证。'}, status_code=403)(scope, receive, send)
            scoped['pajio.private_owner_scope'] = owner_scopes[0].decode('ascii')
        expiries = [v for k, v in headers if k.lower() == b'x-pajio-session-expires']
        if expiries:
            try:
                expiry = float(expiries[0])
                if len(expiries) != 1 or not math.isfinite(expiry) or not time.time() < expiry <= time.time() + 28860:
                    raise ValueError('Invalid session expiry')
            except (ValueError, TypeError):
                if is_voice:
                    return await send({'type': 'websocket.close', 'code': 1008})
                return await JSONResponse({'detail': '账户会话已过期，请重新登录。'}, status_code=401)(scope, receive, send)
            scoped['pajio.session_expires'] = expiry
        # websocket-client supplies the fixed private upstream's Host. Normalize
        # only after both internal credentials pass, before TrustedHost checks.
        if is_voice and self.public_host:
            scoped["headers"] = [(k, v) for k, v in scoped["headers"] if k.lower() != b"host"] + [(b"host", self.public_host)]
        return await self.app(scoped, receive, send)


def create_tenant_app(root: Path, *, hermes=None, engine_autostart=True):
    root = checked_root(root)
    instance = load_instance(root, allow_deleting=True)
    origin = urlparse(instance.public_origin)
    try:
        loopback = ipaddress.ip_address(origin.hostname).is_loopback
    except ValueError:
        loopback = origin.hostname == "localhost"
    if origin.scheme == "https" and not loopback and os.environ.get("PAJIO_TRIAL_LIMITS") != "1":
        raise InstanceError("公开租户必须启用调用限额：请在服务环境设置 PAJIO_TRIAL_LIMITS=1 后再启动。")
    from .account_deletion_tenant import DeletionBoundary, TenantDeletionControl, tombstoned
    key = read_private(root / "gateway.key").strip()
    data = root / "data"
    lock = FileLock(data / "tenant-worker.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout as error:
        raise InstanceError("这份私有卷已有运行实例；没有启动第二个写入者。") from error
    try:
        settings = Settings(data)
        connection = data / "connection.json"
        if connection.exists() or connection.is_symlink():
            try:
                saved = json.loads(read_private(connection))
                if (not isinstance(saved, dict)
                        or not isinstance(saved.get("url"), str) or not saved["url"]
                        or not isinstance(saved.get("key"), str) or not saved["key"]):
                    raise ValueError("Invalid private engine connection")
                settings = Settings(data, saved["url"], saved["key"])
            except (OSError, ValueError, TypeError) as error:
                raise InstanceError("实例引擎配置无法读取；请修复本实例的 connection.json，原数据仍保留。") from error
        # No inherited WEARING_DATA_DIR / WEARING_HERMES_* or platform tenant ID.
        app = create_app(settings, hermes=hermes,
                         allowed_hosts=["localhost", "127.0.0.1", "[::1]", urlparse(instance.public_origin).hostname],
                         browser_origin=instance.public_origin, engine_autostart=engine_autostart and not tombstoned(root), local_devices=False)
    except Exception:
        lock.release()
        raise
    original = app.router.lifespan_context

    @asynccontextmanager
    async def tenant_lifespan(app):
        try:
            if tombstoned(root):
                # Restart exposes only the fixed operator controller; no recovery,
                # engines, scheduled work, capture or channel receiver starts.
                yield
            else:
                async with original(app):
                    yield
        finally:
            lock.release()

    app.router.lifespan_context = tenant_lifespan
    app.state.tenant_instance = instance
    app.add_middleware(TenantBoundary, tenant_id=instance.tenant_id, gateway_key=key, public_host=urlparse(instance.public_origin).netloc)

    app.add_middleware(DeletionBoundary, controller=TenantDeletionControl(root, instance, app))

    @app.get("/internal/runtime")
    async def runtime_status():
        probe = await app.state.service.hermes.probe()
        return {**instance_status(root), "engine_state": probe["state"],
                "engine_owned": app.state.runtime.status()["running"], "data_owner_checked": True}

    @app.get("/internal/devices")
    async def device_status():
        from .relay import instance_relay
        return {"devices": instance_relay(root).inventory("daily"), "identity_id": "daily"}

    return app
