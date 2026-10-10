"""Invitation activation UI. Secrets never enter URLs or the signed cookie."""
from html import escape
import json
from pathlib import Path
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse

from sqlalchemy import delete, insert, select
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from .control import digest, states
from .invitations import InvitationStore, InvitationError
from .registration import RegistrationError, credentials
from .mobile_auth import CALLBACK


WORDMARK = (Path(__file__).parent.parent / 'web/pajio-wordmark.svg').read_text(encoding='utf-8').replace('fill="#202228"', 'fill="currentColor"').replace('<svg ', '<svg class="wordmark" role="img" aria-label="Pajio" ', 1)


ERRORS = {
    'invitation_unavailable': '这个邀请码暂时无法使用，请检查是否填写完整，或联系邀请你的人。',
    'username_invalid': '账号需为 4–32 位小写字母、数字、点、下划线或短横线，并以字母开头。',
    'username_unavailable': '这个账号名已被使用，请换一个。已有账号可以直接登录。',
    'password_invalid': '请设置 12–128 位密码，可以使用一句容易记住的话。',
    'registration_pending': '正在确认上次创建的结果，请稍后用相同账号和密码重试。',
    'registration_unavailable': '账号服务暂时未就绪，你的邀请码不会因此被消耗。请稍后再试。',
}

STYLE = '''
:root{color-scheme:light dark;--bg:#f6f5f2;--card:#fff;--ink:#292b32;--muted:#737781;--line:#dce0e6;--focus:#4c5fb0;--button:#303848}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100svh;display:grid;place-items:center;padding:28px 20px}main{width:min(100%,440px)}header{display:flex;align-items:center;gap:10px;margin:0 0 42px;font-size:27px;font-weight:700;letter-spacing:-1px}.wordmark{width:104px;height:46px}section{padding:32px;background:var(--card);border:1px solid var(--line);border-radius:24px}small{display:block;color:var(--muted);font-size:12px;letter-spacing:1px}h1{font-size:29px;letter-spacing:-.6px;line-height:1.3;margin:12px 0}p{color:var(--muted);margin:0 0 28px}label{display:block;font-size:14px;margin:18px 0 8px;font-weight:550}input{width:100%;min-height:50px;padding:12px 14px;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:12px}input:focus-visible,button:focus-visible,a:focus-visible{outline:3px solid var(--focus);outline-offset:3px}button{width:100%;min-height:50px;border:0;border-radius:12px;background:var(--button);color:#fff;font-family:inherit;font-size:16px;font-weight:600;line-height:1.4;cursor:pointer;margin-top:24px;padding:12px}button.secondary{background:transparent;color:var(--muted);font-size:14px;margin-top:10px;font-weight:400}button:active{transform:scale(.99)}.note{font-size:12px;color:var(--muted);margin-top:10px}.error{padding:12px;border-radius:10px;background:var(--bg);color:var(--ink);font-size:14px;margin:18px 0}.foot{text-align:center;color:var(--muted);font-size:13px;margin:24px 0}a{color:inherit;text-underline-offset:3px}.legal{font-size:12px;color:var(--muted);line-height:1.8;margin:20px 0 0}@media(prefers-color-scheme:dark){:root{--bg:#191c23;--card:#222630;--ink:#ececf0;--muted:#afb3bf;--line:#3b4150;--focus:#b3bfff;--button:#485773}}@media(max-width:380px){section{padding:24px}h1{font-size:26px}}@media(prefers-reduced-motion:reduce){button:active{transform:none}}
'''


def page(ticket, *, stage='invite', error=None, status=200, username='', issuer_origin=''):
    hidden = '<input type="hidden" name="ticket" value="' + escape(ticket, quote=True) + '">'
    alert = '<div class="error" role="alert">' + escape(error) + '</div>' if error else ''
    if stage == 'account':
        title, intro, step = '认识一下吧', '创建你的账号，以后在任何设备上都能找到 Pajio。', '02 / 创建账号'
        form = f'''<form method="post" action="/join/create">{hidden}
<label for="username">账号名</label><input id="username" name="username" value="{escape(username, quote=True)}" required minlength="4" maxlength="32" autocomplete="username" autocapitalize="none" spellcheck="false" pattern="[a-z][a-z0-9_.\\-]{{3,31}}" placeholder="例如 linlin2026">
<div class="note">4–32 位小写字母和数字，可加点、下划线、短横线。</div>
<label for="password">密码</label><input id="password" name="password" type="password" required autocomplete="new-password" placeholder="至少 12 位，推荐使用密码管理器">
<button type="submit">创建账号，进入 Pajio</button></form>
<form method="post" action="/join/login">{hidden}<button class="secondary" type="submit">已有账号？登录并激活</button></form>'''
    else:
        title, intro, step = '你好，我是 Pajio', '把事情交给我，给自己留点时间。', '01 / 邀请码激活'
        form = f'''<form method="post" action="/join/check">{hidden}
<label for="code">邀请码</label><input id="code" name="code" required maxlength="80" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="粘贴收到的邀请码">
<button type="submit">继续</button></form>
<form method="post" action="/join/existing">{hidden}<button class="secondary" type="submit">已加入 Pajio？直接登录</button></form>'''
    nonce = secrets.token_urlsafe(24)
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>加入 Pajio</title><style nonce="{nonce}">{STYLE}</style></head><body><main><header>{WORDMARK}</header><section><small>{step}</small><h1>{title}</h1><p>{intro}</p>{alert}{form}</section><div class="foot">你休息，我来。</div></main></body></html>'''
    return HTMLResponse(document, status_code=status, headers={
        # no-referrer also turns a native HTML form POST's Origin into "null".
        # Keep same-origin forms verifiable without disclosing cross-origin URLs.
        'Cache-Control': 'no-store', 'Referrer-Policy': 'same-origin',
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': f"default-src 'none'; style-src 'nonce-{nonce}'; form-action 'self' {issuer_origin}; frame-ancestors 'none'; base-uri 'none'"})


def native_ready(callback):
    """Finish the same-origin POST before an explicit native navigation.

    A form redirect to a custom scheme can be blocked by form-action even with
    a fixed host-source. An ordinary link preserves CSP and needs no script.
    """
    if not isinstance(callback, str) or len(callback) > 512:
        raise ValueError('Invalid native completion')
    target = urlparse(callback)
    pairs = parse_qs(target.query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
    if (target.scheme + '://' + target.netloc != CALLBACK or target.path or target.fragment
            or set(pairs) != {'code', 'state'} or any(len(values) != 1 for values in pairs.values())
            or not re.fullmatch(r'[A-Za-z0-9_-]{43}', pairs['code'][0])
            or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', pairs['state'][0])):
        raise ValueError('Invalid native completion')
    # Reconstruct the href from the fixed destination and validated proof only.
    href = escape(CALLBACK + '?' + urlencode({key: pairs[key][0] for key in ('code', 'state')}), quote=True)
    nonce = secrets.token_urlsafe(24)
    link_style = '.return-link{display:block;text-align:center;background:var(--button);color:#fff;border-radius:12px;padding:12px;margin-top:24px;text-decoration:none;font-weight:600}'
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>账号已准备好 · Pajio</title><style nonce="{nonce}">{STYLE}{link_style}</style></head><body><main><header>{WORDMARK}</header><section><h1>账号已准备好</h1><p>回到 App，就可以开始了。</p><a class="return-link" href="{href}">返回 Pajio</a><div class="note">若返回后提示登录过期，请在 App 中选择已有账号登录。</div></section></main></body></html>'''
    return HTMLResponse(document, headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': f"default-src 'none'; style-src 'nonce-{nonce}'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"})


def callback_error(request, detail, *, status):
    """Render callback failures for browsers without changing the JSON contract."""
    html = False
    for accept in request.headers.getlist('accept'):
        for item in accept.split(','):
            media, *parameters = item.split(';')
            if media.strip().lower() != 'text/html':
                continue
            quality = [value.strip() for parameter in parameters
                       for key, separator, value in [parameter.strip().partition('=')]
                       if key.lower() == 'q' and separator]
            if not quality or (len(quality) == 1 and re.fullmatch(r'(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)', quality[0])
                               and float(quality[0]) > 0):
                html = True
    if not html:
        return JSONResponse({'detail': detail}, status_code=status)
    nonce = secrets.token_urlsafe(24)
    # No callback query, provider error, state or proof belongs in this page.
    # A new native PKCE flow must start from the App, not from this browser.
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>登录未完成 · Pajio</title><style nonce="{nonce}">{STYLE}</style></head><body><main><header>{WORDMARK}</header><section><h1>这次登录没有完成</h1><p>登录信息可能已过期，或尚未通过验证。</p><p>如果你从 App 打开了此窗口，请关闭窗口，回到 Pajio 后重新点「已有账号登录」。</p><a href="/join">返回网页登录入口</a></section></main></body></html>'''
    return HTMLResponse(document, status_code=status, headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': f"default-src 'none'; style-src 'nonce-{nonce}'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"})


class JoinFlow:
    def __init__(self, config, store, cache, login, finish, registration, session):
        self.config, self.store, self.cache = config, store, cache
        self.invites = InvitationStore(store)
        self.login, self.finish, self.registration, self.session = login, finish, registration, session
        issuer = urlparse(config.issuer)
        self.issuer_origin = issuer.scheme + "://" + issuer.netloc

    def _limit(self, binding):
        now = int(time.time())
        # Shared DB limits survive gateway restarts. No raw IP or fingerprint is
        # retained; the global bucket also bounds deliberate cookie rotation.
        for key, seconds, maximum in [('global', 60, 240), (binding, 600, 24)]:
            hashed = digest('join-rate:' + key)
            with self.store.transaction(mutating=True, state_hash=hashed) as db:
                row = db.execute(select(states).where(states.c.id_hash == hashed)).mappings().first()
                count = int(row['value']) if row and row['expires'] > now else 0
                if count >= maximum:
                    return False
                if row:
                    db.execute(delete(states).where(states.c.id_hash == hashed))
                db.execute(insert(states).values(id_hash=hashed, value=str(count+1),
                           expires=row['expires'] if row and row['expires'] > now else now+seconds))
        return True

    async def render(self, request, context=None, *, error=None, status=200, username=''):
        context = context or {}
        binding = request.session.get('join_binding')
        if not isinstance(binding, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', binding):
            binding = secrets.token_urlsafe(32)
            request.session['join_binding'] = binding
        ticket = secrets.token_urlsafe(32)
        await self.cache.set('join-form:' + ticket, json.dumps({**context, 'binding': digest(binding)}), 600)
        return page(ticket, stage='account' if context.get('code_hash') else 'invite', error=error, status=status, username=username, issuer_origin=self.issuer_origin)

    async def start(self, request, mobile=None):
        if mobile is None and self.session(request) is not None:
            return RedirectResponse('/', status_code=303)
        binding = request.session.get('join_binding') or secrets.token_urlsafe(32)
        if not self._limit(binding):
            return page('', error='访问较为频繁，请稍后重新打开此页面。', status=429, issuer_origin=self.issuer_origin)
        request.session['join_binding'] = binding
        return await self.render(request, {'mobile': mobile} if mobile else {})

    async def _take(self, request):
        if request.headers.getlist('origin') != [self.config.public_origin]:
            return None, None
        binding = request.session.get('join_binding', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', binding) or not self._limit(binding):
            return None, None
        if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            return None, None
        try:
            body = (await request.body()).decode('utf-8')
            pairs = parse_qs(body, keep_blank_values=True, strict_parsing=True, max_num_fields=5)
            if any(len(v) != 1 for v in pairs.values()):
                return None, None
            data = {k: v[0] for k, v in pairs.items()}
        except (ValueError, UnicodeError):
            return None, None
        ticket = data.get('ticket', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', ticket):
            return None, None
        raw = await self.cache.get('join-form:' + ticket)
        context = json.loads(raw) if raw else None
        if not context or not secrets.compare_digest(context.pop('binding', ''), digest(binding)):
            return None, None
        return data, context

    async def post(self, request):
        data, context = await self._take(request)
        if context is None:
            return page('', error='页面已过期或请求过于频繁，请返回登录入口重新开始。', status=400, issuer_origin=self.issuer_origin)
        action = request.url.path.rsplit('/', 1)[-1]
        try:
            if action == 'check' and set(data) == {'ticket', 'code'}:
                context['code_hash'] = self.invites.check_code(data['code'].strip(), issuer=self.config.issuer)
                return await self.render(request, context)
            if action in {'existing', 'login'} and set(data) == {'ticket'}:
                if action == 'login' and not context.get('code_hash'):
                    raise InvitationError()
                if action == 'existing':
                    context.pop('code_hash', None)
                response = await self.login(request)
                state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
                await self.cache.set('join-auth:' + state, json.dumps(context), 600)
                return response
            if action == 'create' and set(data) == {'ticket', 'username', 'password'} and context.get('code_hash'):
                username, password = credentials(data['username'].strip().lower(), data['password'])
                subject = await self.registration.register(context['code_hash'], username, password)
                self.invites.redeem_hash(context['code_hash'], issuer=self.config.issuer, subject=subject)
                return await self.finish(request, subject, context.get('mobile'))
            raise InvitationError()
        except (InvitationError, RegistrationError) as error:
            code = error.code
            if code == 'invitation_unavailable':
                context.pop('code_hash', None)
            return await self.render(request, context, error=ERRORS.get(code, ERRORS['registration_unavailable']),
                                     status=422 if code in {'invitation_unavailable', 'username_invalid', 'username_unavailable', 'password_invalid'} else 503,
                                     username=data.get('username', '')[:32])

    def routes(self):
        return [Route('/join', self.start), *[Route('/join/' + name, self.post, methods=['POST'])
                for name in ('check', 'create', 'login', 'existing')]]
