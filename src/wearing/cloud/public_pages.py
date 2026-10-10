"""Public information for the individual-developer invitation test.

These documents describe the reviewed deployment, not every optional feature in
the repository. Revisit the dated disclosure before enabling another supplier.
"""
import secrets

from starlette.responses import HTMLResponse
from starlette.routing import Route

from .auth_pages import WORDMARK


CONTACT = 'tiancaimiaosan233@gmail.com'
STYLE = '''
:root{color-scheme:light dark;--bg:#f7f8fa;--ink:#22252b;--muted:#656a75;--line:#dce0e7;--link:#36559b}
@media(prefers-color-scheme:dark){:root{--bg:#17191e;--ink:#eceef3;--muted:#a6adba;--line:#343842;--link:#b4c7f7}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.85 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header,main,footer{width:min(100% - 48px,720px);margin:auto}header{padding-top:36px}.wordmark{width:68px;height:auto}
nav{display:flex;gap:24px;flex-wrap:wrap;margin-top:22px}a{color:var(--link);text-underline-offset:4px}a:focus-visible{outline:2px solid var(--link);outline-offset:5px;border-radius:3px}
main{padding:38px 0 56px}h1{font-size:32px;line-height:1.3;letter-spacing:-.6px;margin:0 0 12px}h2{font-size:20px;line-height:1.5;margin:32px 0 10px}
p{margin:10px 0}.meta{color:var(--muted);font-size:14px}.intro{font-size:18px}.notice{border-left:3px solid var(--line);padding-left:18px;margin:26px 0}
ul{padding-left:23px}li{margin:8px 0}footer{padding:22px 0 36px;border-top:1px solid var(--line);font-size:14px;color:var(--muted)}
@media(max-width:480px){header,main,footer{width:calc(100% - 40px)}h1{font-size:28px}main{padding-top:30px}}
'''

PRIVACY = '''
<h1>隐私说明</h1><p class="meta">Pajio 个人邀请测试 · 更新于 2026 年 10 月 10 日</p>
<p class="intro">你选择交给 Pajio 的内容，用于完成你的请求和保留工作进度。这份说明介绍本轮测试实际使用的数据与服务。</p>
<p>Pajio 由个人开发者 ArchieLiew 提供，目前采用邀请码制。问题、查阅、更正、导出或删除请求可发送至 <a href="mailto:tiancaimiaosan233@gmail.com">tiancaimiaosan233@gmail.com</a>。</p>
<h2>账号与登录</h2>
<p>注册时处理你的邀请码、账号名和密码，并由身份服务验证登录。注册密码经过加密连接传给账号服务，不作为 Agent 的对话或任务输入。登录后的凭据用于识别账号和访问属于你的环境；iPhone 的登录凭据存放于系统钥匙串。</p>
<h2>你交给助手的内容</h2>
<p>对话、任务、记忆、你选择提交的文件和图片，以及任务所需的工具结果，可能传到你的服务端环境并保存。它们用于回答问题、执行任务、展示结果和延续上下文。部分记录也会保存在 App 本机；本产品不是仅在本机处理数据的工具。</p>
<p>当前 AI 模型服务由 DeepSeek 提供。完成请求时，相关对话、你允许使用的上下文和工具结果会发送给该服务。其数据处理规则请查阅 <a href="https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html">DeepSeek 隐私政策</a>。请只提交你有权使用的内容；不要把密码、验证码或不必要的敏感信息写进对话。</p>
<h2>权限与连接的应用</h2>
<p>相机、照片、麦克风、系统日历、提醒事项和位置等权限按具体操作申请，你可以拒绝或在系统设置中撤回。选择一个常用应用或兴趣，不代表已经授权读取该应用的数据。第三方账号仍需你自行登录，并按你给定的范围使用。</p>
<p>当前部署未启用云端语音转写和消息推送。后续如启用，会在对应功能处说明服务商、传输内容并请求所需授权；本说明也会随之更新。</p>
<h2>云电脑与云手机</h2>
<p>个人环境保存已安装应用、工作文件和你在其中建立的登录状态。Agent 执行任务和你远程接管时，服务会处理设备画面与操作指令。远程画面通过加密连接传输；这不等于所有数据都只在手机上处理，也不代表服务器无法接触任务内容。</p>
<p>当前个人环境和身份服务运行于中国大陆的自有设备，公网接入及远控中继使用腾讯云广州资源。AI 服务和你主动访问的第三方网站按各自的服务安排处理数据；不能据此承诺所有第三方处理都发生在同一地区。</p>
<h2>保留、更正与删除</h2>
<p>测试服务会保留账号、对话、任务、文件和使用记录，以支持持续使用、任务恢复和故障排查。不同记录的保存方式不同；本轮尚未实行统一的自动清除期限。</p>
<p>你可以在产品中编辑或删除支持操作的记录，或通过反馈邮箱提出查阅、更正、导出及删除请求。删除一条记忆不会自动删除曾包含该信息的历史对话、文件或备份。</p>
<p>App 内提供注销申请入口。提交后会限制该账号继续访问业务；当前测试阶段，云端环境、身份账号及备份的清除需要开发者核对处理。申请提交、访问冻结与数据清除完成是不同状态，以实际处理结果为准。注销 Pajio 不会删除你在其他平台的账号，第三方授权也需要在相应平台检查和撤回。</p>
<h2>测试反馈</h2>
<p>通过 TestFlight 发送的测试反馈由 Apple 按其测试服务规则处理；通过邮件发送的内容用于排查你报告的问题。请尽量只提供问题发生时间、App 版本、操作步骤和经过遮挡的截图，不必发送密码、验证码或完整私人资料。</p>
'''

SUPPORT = '''
<h1>测试支持</h1><p class="meta">Pajio · 个人开发者邀请测试</p>
<p class="intro">遇到问题，把卡住的那一步告诉我。</p>
<p>反馈邮箱：<a href="mailto:tiancaimiaosan233@gmail.com">tiancaimiaosan233@gmail.com</a><br>开发者：ArchieLiew</p>
<h2>加入测试</h2>
<p>本轮采用邀请码制。收到安装邀请后，在 iPhone 上安装 Pajio，选择「邀请码加入」，验证邀请码并创建账号。App 使用固定服务地址，无需填写服务器地址。已有账号可以直接选择登录。</p>
<h2>邀请码或开通进度有问题</h2>
<p>检查邀请码是否完整。若已提交注册后连接中断，请保留页面里的进度，使用「查询这次进度」核对；若账号已创建，可尝试已有账号登录。个人云环境需要完成开通后才能使用，页面上的准备状态不代表任务已经执行。</p>
<h2>怎样反馈更容易定位</h2>
<ul><li>问题发生的大致时间和 App 版本。</li><li>你点了什么，期望出现什么，实际发生了什么。</li><li>如有截图，请先遮挡私人内容。不要发送密码、验证码或第三方登录凭据。</li></ul>
<p>也可以通过 TestFlight 的反馈入口提交。测试版本仍在完善中，重要结果请自行核对。</p>
<h2>管理你的资料</h2>
<p>查阅、更正、导出或删除请求可联系上述邮箱。注销可从 App 内的账号注销入口发起；申请提交不代表云端数据已经清除。具体数据处理方式见 <a href="/privacy">隐私说明</a>。</p>
'''


async def public_page(request):
    privacy = request.url.path == '/privacy'
    title, body = ('隐私说明', PRIVACY) if privacy else ('测试支持', SUPPORT)
    nonce = secrets.token_urlsafe(24)
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>{title} · Pajio</title><meta name="robots" content="noindex,nofollow"><style nonce="{nonce}">{STYLE}</style></head><body><header>{WORDMARK}<nav aria-label="测试信息"><a href="/join">登录 Pajio</a><a href="/privacy">隐私说明</a><a href="/support">测试支持</a></nav></header><main>{body}</main><footer>Pajio · 邀请测试 · ArchieLiew</footer></body></html>'''
    return HTMLResponse(document, headers={
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'Content-Security-Policy': f"default-src 'none'; style-src 'nonce-{nonce}'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    })


def public_routes():
    # Exact, static GET/HEAD endpoints; never a file path or an auth bypass.
    return [Route('/privacy', public_page), Route('/support', public_page)]
