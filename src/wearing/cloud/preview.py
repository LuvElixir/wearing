"""Single-user, loopback-only browser entry over an operator-established SSH tunnel.

Not an IdP or a SaaS account. A private one-use handoff establishes an expiring
browser session; the VM service key is kept exclusively in this local process.
"""
from contextlib import asynccontextmanager
import hashlib
import secrets
import time
from urllib.parse import urlparse

import httpx
from filelock import FileLock
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from .gateway import EntryHeaders, forward_worker, proxy_path
from .instance import load_instance, read_private
from ..config import write_private_json

COOKIE = 'wearing-private-cloud'
ENTRY_JS = """const access = new URLSearchParams(location.hash.slice(1)).get('access');
history.replaceState(null, '', '/');
if (access) {
  fetch('/auth/local', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({access})})
    .then(r => { if (!r.ok) throw Error(); location.replace('/'); })
    .catch(() => { document.getElementById('entry-status').textContent='入口已过期，请重新打开私人入口。'; });
}
"""
ENTRY_CSS = """body{margin:0;background:#fafafa;color:#343846;font-family:system-ui,sans-serif;min-height:100vh;display:grid;align-content:center;justify-content:center;padding:0 24px;box-sizing:border-box}h1{font-size:30px;letter-spacing:-.02em}p{max-width:480px;line-height:1.9;font-size:15px}p:last-of-type{color:#586172;font-size:13px}"""
ENTRY_HTML = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wearing · 私人云端入口</title><link rel="stylesheet" href="/auth/entry.css"><body><h1>你的 Wearing</h1><p id="entry-status">请从这台电脑生成的私人入口进入。</p>
<p>云端实例持续运行，对话和记忆留在你的独立实例中。</p><script type="module" src="/auth/entry.js"></script></body></html>"""


def create_preview_app(root, upstream, *, worker_transport=None):
    instance = load_instance(root)
    origin = instance.public_origin
    parsed, remote = urlparse(origin), urlparse(upstream)
    # No arbitrary external proxy, privileged worker or public HTTP listener.
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
            or remote.scheme != 'http' or remote.hostname != '127.0.0.1'
            or not remote.port or remote.path or remote.query or remote.fragment
            or remote.username or remote.password or remote.netloc == parsed.netloc):
        raise ValueError('私人入口仅支持独立端口的本机 SSH 隧道。')
    key = read_private(root / 'gateway.key').strip()
    # Cookies do not separate localhost ports. Bind each private entry to its
    # instance/origin so a QA or second VM login cannot replace another session.
    cookie_name = COOKIE + '-' + hashlib.sha256((instance.instance_id + origin).encode()).hexdigest()[:16]
    lock = FileLock(root / 'preview.lock', timeout=0)
    lock.acquire()
    access = secrets.token_urlsafe(48)
    access_hash, access_expires = hashlib.sha256(access.encode()).digest(), time.monotonic() + 600
    consumed = False
    sessions = {}
    wire = httpx.AsyncClient(transport=worker_transport, trust_env=False, follow_redirects=False,
                            timeout=httpx.Timeout(30), limits=httpx.Limits(max_connections=40))
    write_private_json(root / 'preview-access.json', {'url': origin + '/#access=' + access})

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            sessions.clear()
            await wire.aclose()
            lock.release()

    def logged_in(request):
        cookie = request.cookies.get(cookie_name, '')
        expires = sessions.get(hashlib.sha256(cookie.encode()).digest(), 0)
        return expires > time.monotonic()

    async def enter(request):
        nonlocal consumed
        if request.headers.get('origin') != origin:
            return JSONResponse({'detail': '请求来源未通过验证。'}, status_code=403)
        # Handoff is short-lived, never in a query string or access log.
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 256:
                return JSONResponse({'detail': '入口已失效。'}, status_code=400)
            body.extend(chunk)
        try:
            import json
            candidate = json.loads(body)['access']
            valid = isinstance(candidate, str) and secrets.compare_digest(hashlib.sha256(candidate.encode()).digest(), access_hash)
        except (ValueError, KeyError, TypeError):
            valid = False
        if consumed or time.monotonic() > access_expires or not valid:
            return JSONResponse({'detail': '入口已失效，请重新生成。'}, status_code=401)
        consumed = True
        session = secrets.token_urlsafe(48)
        sessions[hashlib.sha256(session.encode()).digest()] = time.monotonic() + 28800
        response = JSONResponse({'entered': True})
        response.set_cookie(cookie_name, session, max_age=28800, httponly=True, samesite='strict', path='/')
        return response

    async def account(request):
        if not logged_in(request):
            return JSONResponse({'detail': '私人入口已失效，请重新打开。'}, status_code=401)
        return JSONResponse({'mode': 'private_ssh_preview', 'tenant_id': instance.tenant_id})

    async def proxy(request):
        if not proxy_path(request.url.path):
            return JSONResponse({'detail': '此入口不存在。'}, status_code=404)
        if not logged_in(request):
            if request.url.path == '/':
                return HTMLResponse(ENTRY_HTML, headers={'Content-Security-Policy': "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
            return JSONResponse({'detail': '请从私人入口进入 Wearing。'}, status_code=401)
        if request.method not in {'GET', 'HEAD'} and request.headers.get('origin') != origin:
            return JSONResponse({'detail': '请求来源未通过验证。'}, status_code=403)
        return await forward_worker(wire, request, upstream, origin, instance.tenant_id, key)

    async def unavailable(request, error):
        return JSONResponse({'detail': '云端暂未连接，请检查私人隧道后重新查看。'}, status_code=503)

    app = Starlette(routes=[Route('/auth/local', enter, methods=['POST']),
        Route('/auth/session', account), Route('/auth/entry.js', lambda request: Response(ENTRY_JS, media_type='text/javascript')),
        Route('/auth/entry.css', lambda request: Response(ENTRY_CSS, media_type='text/css')),
        Route('/{path:path}', proxy, methods=['GET', 'HEAD', 'POST', 'PATCH', 'PUT', 'DELETE'])],
        lifespan=lifespan, exception_handlers={httpx.HTTPError: unavailable})
    app.add_middleware(EntryHeaders, host=parsed.netloc)
    app.state.cookie_name = cookie_name
    return app
