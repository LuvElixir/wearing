"""Expiring, single-identity LAN bridge for a trusted-Wi-Fi development session.

The normal Wearing service remains on loopback. This is deliberately separate
from production HTTPS/OIDC and is never started by the ordinary service CLI.
The random capability prevents anonymous access; HTTP is NOT link encryption.
"""

import argparse
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlparse

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from .cloud.gateway import EntryHeaders, proxy_path
from .speech_api import PATH as VOICE_PATH, first_message, MAX_FRAME

TTL_SECONDS = 4 * 60 * 60
MAX_BODY = 15 * 1024 * 1024
LAN_NETWORKS = tuple(ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
FORWARD_HEADERS = ("content-type", "accept", "range", "if-none-match", "if-modified-since", "x-wearing-token")
RESPONSE_HEADERS = ("content-type", "content-length", "content-disposition", "etag", "last-modified",
                    "accept-ranges", "content-range", "content-encoding", "content-security-policy", "x-content-type-options")


def addresses(listen: str, port: int, upstream: str):
    try:
        ip = ipaddress.IPv4Address(listen)
        remote = urlparse(upstream)
        if (not any(ip in network for network in LAN_NETWORKS) or not 1 <= port <= 65535
                or any(ord(char) < 33 or ord(char) > 126 for char in upstream)
                or remote.scheme != "http" or remote.hostname != "127.0.0.1"
                or remote.netloc != f"127.0.0.1:{remote.port}" or not remote.port
                or not 1 <= remote.port <= 65535 or remote.path not in {"", "/"}
                or remote.query or remote.fragment or remote.username or remote.password):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("开发桥需要指定局域网 IPv4 地址、有效端口和固定的 127.0.0.1 HTTP 上游根地址。") from None
    return f"http://{ip}:{port}", f"http://127.0.0.1:{remote.port}"


def _write_pairing(path: Path, pairing: dict):
    """Never overwrite a previous session or follow a credential-file symlink."""
    path = path.expanduser().absolute()
    if path.parent.is_symlink():
        raise ValueError("配对文件不能保存在符号链接目录中。")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(pairing, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return path


def create_dev_mobile_app(listen: str, port: int, upstream: str, identity: str, pairing_file: Path,
                          *, transport=None, clock=time.monotonic):
    origin, upstream = addresses(listen, port, upstream)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity):
        raise ValueError("身份编号格式不正确。")
    access = secrets.token_urlsafe(48)
    access_hash = hashlib.sha256(access.encode()).digest()
    session = secrets.token_urlsafe(48)
    session_hash = hashlib.sha256(session.encode()).digest()
    cookie_name = "wearing-dev-mobile-" + secrets.token_hex(8)
    deadline = clock() + TTL_SECONDS
    # Expo Go decodes query params before parsing them again. A literal +00:00
    # becomes a space; UTC milliseconds are portable across native JS engines.
    expires_at = datetime.fromtimestamp(time.time() + TTL_SECONDS, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    pairing_path = _write_pairing(Path(pairing_file), {
        "endpoint": origin + "/", "identity": identity, "accessToken": access, "expiresAt": expires_at,
    })
    # Retain only the bearer digest; the private file is the handoff to the operator.
    del access
    alive = True
    wire = httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                            timeout=httpx.Timeout(150, connect=5, pool=5),
                            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4))

    @asynccontextmanager
    async def lifespan(app):
        nonlocal alive
        try:
            yield
        finally:
            alive = False
            await wire.aclose()

    def matches(candidate, digest):
        return secrets.compare_digest(hashlib.sha256(candidate.encode()).digest(), digest)

    async def proxy(request):
        authorization = request.headers.getlist("authorization")
        bearer = (len(authorization) == 1 and authorization[0].startswith("Bearer ")
                  and matches(authorization[0][7:], access_hash))
        cookie = matches(request.cookies.get(cookie_name, ""), session_hash)
        if not alive or clock() >= deadline or (not bearer and (authorization or not cookie)):
            return JSONResponse({"detail": "手机开发连接已失效，请重新配对。"}, status_code=401)
        origins = request.headers.getlist("origin")
        if ((origins and origins != [origin])
                or (not bearer and request.method not in {"GET", "HEAD"} and origins != [origin])):
            return JSONResponse({"detail": "请求来源未通过验证。"}, status_code=403)
        if not proxy_path(request.url.path):
            return JSONResponse({"detail": "此入口不存在。"}, status_code=404)
        identity_headers = request.headers.getlist("x-wearing-identity")
        identity_query = request.query_params.getlist("identity")
        if ((identity_headers and identity_headers != [identity])
                or (identity_query and identity_query != [identity])):
            return JSONResponse({"detail": "这份手机连接属于另一个身份，请重新配对。"}, status_code=403)
        if request.url.path.startswith("/api/identities") and request.method not in {"GET", "HEAD"}:
            return JSONResponse({"detail": "开发连接不能修改身份，请在电脑上处理。"}, status_code=403)
        try:
            length = request.headers.get("content-length")
            if length is not None and (int(length) < 0 or int(length) > MAX_BODY):
                return JSONResponse({"detail": "请求内容超过 15 MB。"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "请求长度不正确。"}, status_code=400)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY:
                return JSONResponse({"detail": "请求内容超过 15 MB。"}, status_code=413)
            body.extend(chunk)
        headers = {name: request.headers[name] for name in FORWARD_HEADERS if name in request.headers}
        headers.update({"Host": urlparse(upstream).netloc, "X-Wearing-Identity": identity})
        # The authenticated bridge is the browser-origin boundary. The ordinary
        # loopback app keeps its own CSRF token check and sees its own exact origin.
        if origins:
            headers["Origin"] = upstream
        outgoing_url = httpx.URL(upstream).copy_with(path=request.url.path, query=request.scope.get("query_string", b""))
        outgoing = wire.build_request(request.method, outgoing_url, headers=headers, content=bytes(body))
        # A worker Set-Cookie must never become an HTTPX cookie on a later request.
        outgoing.headers.pop("cookie", None)
        try:
            response = await wire.send(outgoing, stream=True)
        except httpx.TimeoutException:
            return JSONResponse({"detail": "Wearing 响应超时，请稍后重试。"}, status_code=504)
        except httpx.HTTPError:
            return JSONResponse({"detail": "电脑上的 Wearing 暂时未连接。"}, status_code=503)
        if 300 <= response.status_code < 400 and response.status_code != 304:
            await response.aclose()
            return JSONResponse({"detail": "开发连接不接受跳转地址。"}, status_code=502)
        forwarded = {name: response.headers[name] for name in RESPONSE_HEADERS if name in response.headers}
        if request.url.path == "/api/bootstrap" and request.method == "GET" and response.status_code == 200:
            try:
                data = json.loads(await response.aread())
                available = [item for item in data["identities"] if item.get("id") == identity]
                if not available:
                    return JSONResponse({"detail": "电脑上没有这份连接对应的身份。"}, status_code=404)
                data.update(identities=available, default_identity_id=identity)
                result = JSONResponse(data)
            except (ValueError, KeyError, TypeError, AttributeError):
                return JSONResponse({"detail": "电脑没有返回兼容的 Wearing 数据。"}, status_code=502)
            finally:
                await response.aclose()
        else:
            result = StreamingResponse(response.aiter_raw(), status_code=response.status_code, headers=forwarded,
                                       background=BackgroundTask(response.aclose))
        if bearer and request.url.path == "/" and request.method == "GET" and response.status_code == 200:
            result.set_cookie(cookie_name, session, max_age=max(1, int(deadline - clock())),
                              httponly=True, samesite="strict", path="/")
        result.headers["X-Content-Type-Options"] = "nosniff"
        return result

    async def voice_proxy(socket):
        # An explicit first packet carries the expiring capability; no token in
        # a URL, browser cookie fallback, or access log. Cloud entry stays closed.
        if not alive or clock() >= deadline or socket.url.query or socket.headers.getlist("origin") not in ([], [origin]):
            await socket.close(code=1008)
            return
        await socket.accept()
        pumps = []
        try:
            start = await first_message(socket)
            access = start.pop("access", None)
            if (not isinstance(access, str) or not matches(access, access_hash)
                    or start.get("identity") != identity or clock() >= deadline):
                await socket.close(code=1008)
                return
            from websockets.asyncio.client import connect
            async with asyncio.timeout(min(210, max(0, deadline - clock()))):
                async with connect(upstream.replace("http://", "ws://", 1) + VOICE_PATH,
                                   origin=upstream, proxy=None, open_timeout=5, close_timeout=1,
                                   max_size=65536, max_queue=8,
                                   logger=logging.Logger("wearing.voice.relay", logging.WARNING)) as remote:
                    await remote.send(json.dumps(start))
                    async def upload_audio():
                        while True:
                            message = await socket.receive()
                            if message["type"] == "websocket.disconnect":
                                return
                            data = message.get("bytes") if message.get("bytes") is not None else message.get("text", "")
                            if not data or len(data) > (MAX_FRAME if isinstance(data, bytes) else 2048):
                                raise ValueError()
                            await remote.send(data)
                    async def download_text():
                        async for message in remote:
                            if not isinstance(message, str) or len(message) > 65536:
                                raise ValueError()
                            await socket.send_text(message)
                    pumps = [asyncio.create_task(upload_audio()), asyncio.create_task(download_text())]
                    done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        await task
        except (Exception, WebSocketDisconnect):
            # No provider headers, audio, transcript or credentials in logs.
            pass
        finally:
            for task in pumps:
                task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            try:
                await socket.close()
            except (RuntimeError, WebSocketDisconnect):
                pass

    app = Starlette(routes=[WebSocketRoute(VOICE_PATH, voice_proxy), Route("/{path:path}", proxy, methods=["GET", "HEAD", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"])],
                    lifespan=lifespan)
    app.add_middleware(EntryHeaders, host=urlparse(origin).netloc, websocket_paths=(VOICE_PATH,))
    app.state.cookie_name = cookie_name
    app.state.pairing_file = pairing_path
    app.state.expires_at = expires_at
    return app


def main():
    parser = argparse.ArgumentParser(description="Start a four-hour Wearing bridge for trusted-Wi-Fi mobile development only.")
    parser.add_argument("--listen", required=True, help="A specific RFC1918 LAN IPv4 address on this Mac")
    parser.add_argument("--port", type=int, default=8795)
    parser.add_argument("--upstream", required=True, help="Fixed http://127.0.0.1:port root address")
    parser.add_argument("--identity", default="daily")
    parser.add_argument("--pairing-file", type=Path, required=True, help="A new private file; existing files are never replaced")
    args = parser.parse_args()
    app = create_dev_mobile_app(args.listen, args.port, args.upstream, args.identity, args.pairing_file)
    print(json.dumps({"endpoint": f"http://{args.listen}:{args.port}/", "pairing_file": str(app.state.pairing_file),
                      "expires_at": app.state.expires_at, "mode": "trusted_wifi_development"}), flush=True)
    import uvicorn
    uvicorn.run(app, host=args.listen, port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
