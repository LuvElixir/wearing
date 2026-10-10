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


from .auth_pages import WORDMARK, STYLE, page, auth_asset


ERRORS = {
    'invitation_unavailable': '这个邀请码暂时无法使用，请检查是否填写完整，或联系邀请你的人。',
    'username_invalid': '账号需为 4–32 位小写字母、数字、点、下划线或短横线，并以字母开头。',
    'username_unavailable': '这个账号名已被使用，请换一个。已有账号可以直接登录。',
    'password_invalid': '请设置 12–128 位密码，可以使用一句容易记住的话。',
    'registration_pending': '正在确认上次创建的结果，请稍后用相同账号和密码重试。',
    'registration_unavailable': '账号服务暂时未就绪，你的邀请码不会因此被消耗。请稍后再试。',
}


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
    link_style = '.return-link{display:block;text-align:center;background:var(--button);color:var(--button-ink);border-radius:12px;padding:12px;margin-top:24px;text-decoration:none;font-weight:600}'
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>账号已准备好 · Pajio</title><style nonce="{nonce}">{STYLE}{link_style}</style></head><body><header class="brand">{WORDMARK}</header><main class="auth-stack"><section class="auth-card"><h1>账号已准备好</h1><p>回到 App，就可以开始了。</p><a class="return-link" href="{href}">返回 Pajio</a><div class="note">若返回后提示登录过期，请在 App 中选择已有账号登录。</div></section></main></body></html>'''
    return HTMLResponse(document, headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': f"default-src 'none'; img-src 'self'; style-src 'nonce-{nonce}'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"})


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
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>登录未完成 · Pajio</title><style nonce="{nonce}">{STYLE}</style></head><body><header class="brand">{WORDMARK}</header><main class="auth-stack"><section class="auth-card"><h1>这次登录没有完成</h1><p>登录信息可能已过期，或尚未通过验证。</p><p>如果你从 App 打开了此窗口，请关闭窗口，回到 Pajio 后重新点「已有账号登录」。</p><a href="/join">返回网页登录入口</a></section></main></body></html>'''
    return HTMLResponse(document, status_code=status, headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': f"default-src 'none'; img-src 'self'; style-src 'nonce-{nonce}'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"})


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
        return [Route('/auth/art/{name}', auth_asset, methods=['GET', 'HEAD']), Route('/join', self.start), *[Route('/join/' + name, self.post, methods=['POST'])
                for name in ('check', 'create', 'login', 'existing')]]
