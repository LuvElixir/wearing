"""First-party sign-in presentation. Authentication stays in JoinFlow/OIDC."""
from html import escape
from pathlib import Path
import secrets
from starlette.responses import FileResponse, HTMLResponse, Response

ASSETS = Path(__file__).parent.parent / 'web' / 'auth'
STYLE = (ASSETS / 'auth.css').read_text(encoding='utf-8')
WORDMARK = (ASSETS.parent / 'pajio-wordmark.svg').read_text(encoding='utf-8').replace('fill="#202228"', 'fill="currentColor"').replace('<svg ', '<svg class="wordmark" role="img" aria-label="Pajio" ', 1)
CONTRACT = '''<!-- Pajio auth: selected Product Design direction 2, 2026-10-10. Flat page, left-aligned wordmark and form, persistent entry indicator separated from focus and pressed states. Authentication remains in JoinFlow and standard OIDC. -->'''


async def auth_asset(request):
    name = request.path_params['name']
    if name != 'auth.js':
        return Response(status_code=404)
    return FileResponse(ASSETS / name, headers={'Cache-Control':'public, max-age=3600',
                                               'X-Content-Type-Options':'nosniff'})


def page(ticket, *, stage='invite', error=None, status=200, username='', issuer_origin=''):
    hidden = '<input type="hidden" name="ticket" value="' + escape(ticket, quote=True) + '">'
    alert = '<div class="error" role="alert" id="form-error">' + escape(error) + '</div>' if error else ''
    existing_action = '/join/login' if stage == 'account' else '/join/existing'
    navigation = f'''<nav class="entry-nav" aria-label="账号入口"><span class="entry-item" aria-current="page">邀请码加入</span><form method="post" action="{existing_action}">{hidden}<button class="entry-item" type="submit">已有账号</button></form></nav>'''
    if stage == 'account':
        title, intro = '创建你的账号', '邀请已确认。设置账号，就可以开始了。'
        form = f'''<form method="post" action="/join/create">{hidden}
<label for="username">账号名</label><input id="username" name="username" value="{escape(username, quote=True)}" required minlength="4" maxlength="32" autocomplete="username" autocapitalize="none" spellcheck="false" pattern="[a-z][a-z0-9_.\\-]{{3,31}}" placeholder="给自己起个账号名" aria-describedby="username-note">
<div class="note" id="username-note">4–32 位，以小写字母开头，可用数字、点、下划线和短横线。</div>
<label for="password">设置密码</label><div class="password-field"><input id="password" name="password" type="password" required autocomplete="new-password" placeholder="至少 12 位" aria-describedby="password-note"><button class="password-toggle" type="button" data-password-toggle aria-controls="password" aria-pressed="false">显示</button></div>
<div class="note" id="password-note">可以用一句好记的话。也支持密码管理器自动填充。</div>
<button class="primary" type="submit">创建账号，进入 Pajio</button></form>'''
    else:
        title, intro = '欢迎来到 Pajio', '日常交给我，时间留给你。'
        form = f'''<form method="post" action="/join/check">{hidden}
<label for="code">邀请码</label><input id="code" name="code" required maxlength="80" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="粘贴邀请码" enterkeyhint="go" aria-describedby="code-note">
<div class="note" id="code-note">验证后，创建你的 Pajio 账号。</div>
<button class="primary" type="submit">继续</button></form>'''
    nonce = secrets.token_urlsafe(24)
    body_class = 'account-stage' if stage == 'account' else 'invite-stage'
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><title>加入 Pajio</title><style nonce="{nonce}">{STYLE}</style><script nonce="{nonce}" src="/auth/art/auth.js" defer></script></head><body class="{body_class}">{CONTRACT}<header class="brand">{WORDMARK}</header><main class="auth-stack"><section class="auth-card"><h1>{title}</h1><p class="intro">{intro}</p>{navigation}{alert}{form}</section></main><footer class="foot"><a href="/privacy">隐私说明</a> · <a href="/support">测试支持</a></footer></body></html>'''
    return HTMLResponse(document, status_code=status, headers={
        'Cache-Control':'no-store', 'Referrer-Policy':'same-origin',
        'X-Content-Type-Options':'nosniff', 'X-Frame-Options':'DENY',
        'Content-Security-Policy': f"default-src 'none'; img-src 'self'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; form-action 'self' {issuer_origin}; frame-ancestors 'none'; base-uri 'none'"})
