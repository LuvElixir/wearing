"""One private Wearing app per instance. Service authentication is not user OIDC."""

from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets
from urllib.parse import urlparse

from filelock import FileLock, Timeout
from starlette.responses import JSONResponse

from .instance import InstanceError, checked_root, instance_status, load_instance, read_private
from ..app import create_app
from ..config import Settings


class TenantBoundary:
    def __init__(self, app, tenant_id, gateway_key):
        self.app = app
        self.tenant = tenant_id.encode("ascii")
        self.credential = ("Bearer " + gateway_key).encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        headers = scope.get("headers", [])
        auth = [v for k, v in headers if k.lower() == b"authorization"]
        tenants = [v for k, v in headers if k.lower() == b"x-wearing-tenant"]
        if len(auth) != 1 or not secrets.compare_digest(auth[0], self.credential):
            return await JSONResponse({"detail": "实例入口未通过验证。"}, status_code=401,
                                      headers={"Cache-Control": "no-store"})(scope, receive, send)
        if len(tenants) != 1 or not secrets.compare_digest(tenants[0], self.tenant):
            return await JSONResponse({"detail": "请求不属于此实例。"}, status_code=403,
                                      headers={"Cache-Control": "no-store"})(scope, receive, send)
        path = scope["path"]
        if path.startswith(("/api/phone", "/api/computer", "/api/doctor", "/api/device-report", "/api/device-doctor", "/api/connection")):
            return await JSONResponse({"detail": "云端实例的设备转发尚未接通，请通过设备连接器接入。"}, status_code=501)(scope, receive, send)
        # Internal credentials must never become ordinary application headers.
        scoped = dict(scope, headers=[(k, v) for k, v in headers if k.lower() not in {b"authorization", b"x-wearing-tenant"}])
        return await self.app(scoped, receive, send)


def create_tenant_app(root: Path, *, hermes=None, engine_autostart=True):
    root = checked_root(root)
    instance = load_instance(root)
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
                         browser_origin=instance.public_origin, engine_autostart=engine_autostart, local_devices=False)
    except Exception:
        lock.release()
        raise
    original = app.router.lifespan_context

    @asynccontextmanager
    async def tenant_lifespan(app):
        try:
            async with original(app):
                yield
        finally:
            lock.release()

    app.router.lifespan_context = tenant_lifespan
    app.state.tenant_instance = instance
    app.add_middleware(TenantBoundary, tenant_id=instance.tenant_id, gateway_key=key)

    @app.get("/internal/runtime")
    async def runtime_status():
        probe = await app.state.service.hermes.probe()
        return {**instance_status(root), "engine_state": probe["state"],
                "engine_owned": app.state.runtime.status()["running"], "data_owner_checked": True}

    return app
