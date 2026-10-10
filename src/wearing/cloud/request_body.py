"""Bound HTTP body consumption without buffering or touching WS/response streams.

The limit applies when an endpoint first reads, so authentication may reject a
request without consuming an attacker-controlled upload. These deadlines protect
one process; they are not an edge rate limit or a cross-worker admission quota.
"""
import asyncio
import re
import time

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


BODY_IDLE_SECONDS = 15.0
BODY_TOTAL_SECONDS = 120.0


class RequestBodyError(HTTPException):
    def __init__(self, status, code, detail):
        super().__init__(status, detail, headers={"Cache-Control": "no-store"})
        self.code = code


async def rejected_body(request, error):
    return JSONResponse({"detail": error.detail, "code": error.code},
                        status_code=error.status_code, headers=error.headers)


class RequestBodyBoundary:
    """Pure ASGI receive guard; request-local state cannot leak between callers."""

    def __init__(self, app, *, limit, idle_seconds=None, total_seconds=None):
        self.app = app
        self.limit = limit
        self.idle_seconds = BODY_IDLE_SECONDS if idle_seconds is None else idle_seconds
        self.total_seconds = BODY_TOTAL_SECONDS if total_seconds is None else total_seconds
        if self.idle_seconds <= 0 or self.total_seconds <= 0:
            raise ValueError("Body deadlines must be positive")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        maximum = self.limit(scope) if callable(self.limit) else self.limit
        started, received, complete = None, 0, False

        async def bounded_receive():
            nonlocal started, received, complete
            # StreamingResponse may keep listening for a disconnect after the
            # request is complete. Never apply an upload deadline to that wait.
            if complete:
                return await receive()
            if started is None:
                lengths = [value for name, value in scope.get("headers", []) if name.lower() == b"content-length"]
                if lengths:
                    if len(lengths) != 1 or not re.fullmatch(rb"[0-9]{1,20}", lengths[0]):
                        raise RequestBodyError(400, "invalid_content_length", "请求长度格式不正确。")
                    if int(lengths[0]) > maximum:
                        raise RequestBodyError(413, "request_too_large", "请求内容过大。")
                started = time.monotonic()
            remaining = self.total_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise RequestBodyError(408, "request_body_timeout", "上传时间过长，请检查网络后重试。")
            try:
                async with asyncio.timeout(min(self.idle_seconds, remaining)):
                    message = await receive()
            except TimeoutError:
                raise RequestBodyError(408, "request_body_timeout", "上传时间过长，请检查网络后重试。") from None
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    raise RequestBodyError(413, "request_too_large", "请求内容过大。")
                complete = not message.get("more_body", False)
            elif message["type"] == "http.disconnect":
                complete = True
            return message

        await self.app(scope, bounded_receive, send)


def gateway_body_limit(scope):
    path = scope["path"]
    if path == "/api/workspace/import":
        return 20 * 1024 * 1024
    if path == "/api/life/assets":
        return 15 * 1024 * 1024
    if path.startswith("/join/"):
        return 8192
    if path == "/auth/mobile/exchange":
        return 2048
    if path == "/auth/tenant" or path.startswith("/auth/account-deletion/"):
        return 4096
    # Authlib may parse an OIDC callback as a form. Keep that encoding intact;
    # this guard only counts bytes and never parses or logs provider material.
    if path.startswith("/auth/"):
        return 64 * 1024
    return 1024 * 1024
