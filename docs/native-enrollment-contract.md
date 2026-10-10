# Pajio App 原生邀请注册合同 v1

固定入口 `https://pajio.luckyloading.com`。首次邀请验证和创建账号使用 App 原生界面；已有账号继续 `/auth/mobile/start` 的标准 OIDC 系统认证会话。没有密码登录 API、ROPC、IdP 页面抓取或可填写服务器地址。

## 操作凭据

App 在发送第一条请求之前，生成并在当前正式 origin 的 SecureStore 中保存：

- `operation_id`：16 个安全随机字节的小写十六进制（32 字符）。
- `receipt`：32 个安全随机字节的 base64url，无 padding（43 字符）。
- `verifier`：现有 PKCE S256 verifier，43–128 个 RFC7636 字符。
- `state`：32–128 个 base64url 字符；`challenge = base64url(SHA256(verifier))`。
- `expires_at`：首发前暂用本机当前时间 +900秒；首次成功后以服务器固定到期时间为准，绝不因重试延长。

密码和原始邀请码只存在于当前输入内存，不能写 SecureStore、日志、分析事件、URL 或错误报告。恢复凭据不是已登录 session；只有原有 `sessionReceipt` 验证过 `/auth/mobile/exchange` 成功响应后，才进入产品的新手引导。

## 路由与请求

以下均为 `POST`，`Content-Type: application/json`，最多4096字节，无 URL query；禁止重复/额外字段。Native 请求无 Origin，或只有严格等于固定正式 origin 的一个 Origin；跨域和 `Origin: null` 拒绝。不依赖浏览器 cookie。

| 路由 | JSON 字段 |
| --- | --- |
| `/auth/mobile/enrollment/verify` | `operation_id, receipt, code, challenge, state` |
| `/auth/mobile/enrollment/register` | `operation_id, receipt, verifier, state, username, password` |
| `/auth/mobile/enrollment/status` | `operation_id, receipt, verifier, state` |
| `/auth/mobile/enrollment/cancel` | `operation_id, receipt, verifier, state` |

用户名使用4–32个小写字母、数字、点、下划线或短横线，首字符为字母。密码12–128个Unicode code points，禁止控制字符和孤立 surrogate；不擅自 trim 密码。

## 成功响应

识别原操作后，HTTP200（pending为202）包含：

```json
{
  "operation_id": "<original 32 hex>",
  "state": "<original PKCE state>",
  "status": "verified",
  "expires_at": "2026-10-10T12:00:00+00:00",
  "attempts_remaining": 5,
  "cancel_requested": false,
  "next_action": "register"
}
```

`status` 与 PKCE 的 `state` 是不同字段。客户端应严格验证 operation_id/state/expiry，拒绝跨 origin、跨操作或无预期字段的响应。

| status | 行为 |
| --- | --- |
| `verified` | 邀请码有效，可提交账号密码。相同 verify 重试不延长到期时间。 |
| `rejected` | `code` 仅 username_invalid / username_unavailable / password_invalid 时允许用户更正后重试；最多5次实际创建尝试。 |
| `pending` | `next_action: check_status`、`retry_after: 2`。只查询原操作；不能重复提交密码或创建新操作来重放创建。 |
| `completed` | 账号及专属空间准入已完成，不等于 App 已登录。 |
| `cancelled` | 创建前已取消，不能再 register；可明确重新开始。 |

`completed` 若含 `handoff: {code, state}`，则 `next_action: exchange`；App 调原 `/auth/mobile/exchange`，JSON仍为 `{code, verifier, state}`。handoff最长120秒、只能用一次，错误verifier/state不消耗正确proof。原生恢复凭据不能直接访问个人空间。

handoff已消费、过期或被取消时，响应无handoff且 `next_action: existing_login`。如果 exchange 响应丢失，不重复 exchange、不宣称登录成功；显示“账号已创建，请选择已有账号登录”，进入标准 OIDC。服务端不为丢失响应无限签发 session 或重新创建账号。

## 取消与失败

- verified/rejected 取消后为 cancelled，未发出创建请求。
- pending 取消仍返回 pending，并设 `cancel_requested: true`。这表示停止本次 App 登录交付；不能承诺撤销已经发送的账号创建。原操作可继续 status 确认结果，完成后仅 existing_login，不发handoff。
- completed 取消使未消费handoff失效；不会删除账号、会员或空间。
- 网络错误/503 保留原 SecureStore receipt，先查 status。网关/broker 重启后凭据仍绑定同一操作，broker只能查原 creation receipt，不重新创建。
- 仅服务端私有 socket 在建立连接时的本地 ConnectError/ConnectTimeout 能证明尚未发送HTTP，返回 verified、code registration_unavailable，不消耗创建次数；用户可以主动重试。不能从 HTTP503、读写错误或缺少收据推断“没创建”。broker回包无法声明这一特权状态。
- verify 明确HTTP422 `invitation_unavailable` 时不创建操作，也未调用注册。可安全让用户改邀请码，使用同operation重新 verify；响应未知时先 status，不据404重放 register。
- register 的 username_invalid/password_invalid 本地格式校验为 code-only422，操作仍 verified；没有向 IdP 发送创建。用户可更正账号或密码。
- 没有可识别操作的错误仅返回 `{code}`：`invalid_request`422/400、`invitation_unavailable`422、`operation_unavailable`404、`operation_expired`410、`rate_limited`429、`attempts_exhausted`429。错误不回显提交字段。operation_unavailable不能被解释为“此前注册一定没发生”。

## 服务端边界

固定15分钟到期；每分钟全局600、来源摘要90、操作60次，实际注册尝试最多5次。来源摘要使用服务端密钥HMAC，不保留明文IP；网关未信任任意客户端传入的转发IP。

首次 IdP create 前持久记录 pending。网关存邀请码/receipt摘要、PKCE challenge、账号名、受控结果及最长120秒的PKCE绑定handoff；不存密码、verifier或最终bearer session。broker仅保留服务端HMAC请求指纹、原操作绑定和结果，不存密码。确认失败才允许释放该次注册预留。未知结果走私有 inspect-only，不能改用户名/密码、挪用另一个操作或重发 create。

同一邀请竞争仍由原邀请预留/会员事务和固定 IdP subject 保证单归属。tenant_id/subject/上游由服务端决定。数据库复用现有 states 的 scoped SELECT/DELETE/INSERT，没有扩展公开网关的会员、注册角色或账号管理权限。

本合同描述代码与测试约束；线上部署、真实 IdP/App 链路验收单独记录。
