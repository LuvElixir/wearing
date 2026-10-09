# 账户注销入口、重新验证与受限查询凭证

2026-10-08。本轮实现 gateway 与控制面接口连接、App 注销页面和本机恢复/清理。没有调用真实身份供应商或删除云资源，没有更改 Web、Desktop 页面。

## App 调用顺序

1. 用当前业务 bearer `GET /auth/account-deletion/plan`。服务端只从真实 session 得到 user；计划资源来自操作者登记，不接受客户端提交归属或资源路径。返回控制面计划及 `request_key`、`receipt_token`、`receipt_expires_in`（90 天）、`reauth_required`。
2. **提交前**把 `receipt_token`、request_key、plan revision 与 gateway origin 保存在设备安全存储。查询凭证需要在清理业务会话时保留，避免请求成功但响应丢失后无法得知结果。
3. 新建 PKCE verifier/challenge/state，以当前业务 bearer `POST /auth/account-deletion/reauth`，body 只能是 `{challenge,state}`。返回 `authorize_url`；用系统认证浏览器打开。回调仍为 `pajio://auth?code=…&state=…`，按既有 `/auth/mobile/exchange` 完成一次性交换。保存新 access token，并保持相同 user / tenant；旧 scope 的草稿不可迁移到别人的账号。Web 使用受 CSRF 保护的空 body，回调更新浏览器 session。
4. 用户确认当前计划后，以新业务 bearer `POST /auth/account-deletion/request`，body 必须恰好是 `{request_key,plan_revision,receipt_token,confirm:"DELETE"}`。无刷新身份、篡改计划、未明确归属、归属改变均拒绝。计划变更后重新查看并保存新凭证。
5. 接受时返回 202 与持久请求回执。此时业务会话立即失效，App 应进入注销状态页。接受不代表已清除数据。`awaiting_operator / adapter_unconfigured / data_erased:false` 必须如实显示为等待执行。
6. 无论提交响应是否收到，都可用 **独立凭证** `Authorization: Bearer <receipt_token>` 查询 `GET /auth/account-deletion/status`。此接口不接受 query、user_id 或 job_id；只查询凭证绑定的 user + request_key。尚未入库返回 `{state:"not_submitted",code:"not_submitted"}`。状态凭证不能提交注销、刷新业务登录、进入租户、读取业务数据或打开语音。

接口统一在 `/auth/account-deletion`，因此走公共 OIDC gateway，而非 tenant worker。当前私有 SSH 预览不是已接入此账户生命周期的云入口。

## 新近身份验证

依据 [OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html#AuthRequest) 使用 `max_age=0`、`prompt=login`，并请求 ID token 的 `auth_time`。除既有 issuer/audience/signature/nonce 校验，服务端还检查：

- 原业务会话仍有效，user 与 tenant 没变；重新登录后的 subject 必须映射到原 user。
- `auth_time` 必须是整数，不接受 bool、字符串、浮点数或缺失。
- 验证时间在最近 300 秒内，不早于专用流程开始前 30 秒，也不能超前服务器 30 秒以上。
- 仅专用 reauth 流程会赋予新业务 session 的 auth_time。普通网页登录、普通 mobile handoff、token 交换发生得很近，都不等价于新近身份验证。
- 重新认证 ticket 一次性、120 秒有效；OIDC 关联仍由持久的一次性 state/nonce 保存。Mobile handoff 一次性、120 秒、PKCE 与 state 绑定，错误 verifier 不会消费合法 handoff。

供应商不给合格 auth_time 时明确拒绝；不从普通 token 的 iat 或本地交换时间猜测。

## 冻结与在途数据

控制面的请求入库就是业务权限围栏：旧 session、重新登录、待交换的旧 mobile handoff、切换 tenant、新的 HTTP 和 WSS 都不能恢复业务访问。无需等操作者物理冻结才停止业务授权。

HTTP 代理在读取请求体、等待上游响应和转发每段响应时重新查询服务端 session；等待期间每 250 ms 检查一次。撤权则取消等待或停止流，并关闭上游响应。WSS 在连接完成后的首帧、上行、下行及空闲时复查；在途连接建立期间发生冻结也不能发送首帧。

这保证 gateway 不继续使用撤销后的旧权限转发；**它不证明已被 worker 接受的持久任务或远端设备动作已经终止**。操作者仍必须完成 drain_actions、停止实例与撤销外部凭据，并拿到相应回执。网络撤销也不能收回撤销前已经发出的字节或已完成的系统副作用。未配置实际 adapter 时没有 `completed` 或 `data_erased:true`。

## 回执凭证

`pdr1.` 前缀，独立签名用途与 90 天有效期；绑定服务端产生的 user、request_key、计划 revision。保存在设备安全存储，只放 Authorization header，不放 URL、日志或普通页面脚本。签名不是加密，不承载敏感业务内容。gateway 重启保留相同 session signing key 时仍可查询；密钥轮换或凭证到期后的长期人工恢复流程尚未实现。

业务 bearer 固定 64 字符，回执格式不会被业务 session/parser 接受。状态接口也不会退回浏览器 cookie。回执持有者可读取该请求状态，因此应当作受限凭据保护。

## 验证

`tests/test_deletion_gateway.py` 17 项，连同 `test_gateway.py`、`test_mobile_gateway.py`、`test_gateway_voice.py`：**43 passed**（2 项依赖弃用警告）。日志 `/tmp/pajio-deletion-gateway-all.log`。

覆盖真实 RSA 签名的模拟 OIDC、auth_time 类型/时间/换账户拒绝、普通登录不得充当 reauth、PKCE 重放与租户保持、提交前回执恢复与 gateway 重启、cookie/bearer/receipt 分权、未知/变化归属阻止提交、重登/旧 handoff/切 tenant 冻结、HTTP 上传前/在途/流式回执截断，以及 WSS 首帧前/流中冻结。仅使用临时数据库、模拟供应商和模拟系统模块，没有真实注销、日历/提醒/位置、外部身份或云 API 操作。

## App integration and local recovery (2026-10-08)

`AccountDeletionPanel` is a native App view with `connection`, `onReauthenticated(next)`,
`onFrozen(target)`, and optional `isCurrent()` callbacks. The host keys the view by account,
not by bearer or credential rotation. It displays every registered tenant and the exact
private-space deletion / shared-space membership-exit scope. It requires dedicated OIDC
reauthentication and literal `DELETE` confirmation. The limited receipt is saved to
`WHEN_UNLOCKED_THIS_DEVICE_ONLY` SecureStore before the request is sent. SQLite never
receives this receipt or the business bearer.

`startupDeletionDisposition(connection)` returns `clear` or `review`. A durable local fence
or submitted receipt always selects review. A prepared or uncertain receipt is checked
through the receipt-only status endpoint, bounded to 15 seconds. `not_submitted` is the only
response allowing ordinary restoration; transport or storage uncertainty selects review.
No recovery receipt is discarded. A review screen may open account connection settings for
a fresh login after `not_submitted`; it must not silently re-enable the old business session.

The host invalidates its current business reference and unmounts business sessions/WebView
before awaiting `clearDeletedAccountLocalData(target)`. A late response for account A may
clean A, but never replaces account B's current UI or saved connection. The helper first
stops registered A voice sessions, then serializes against the existing SQLite save queue.
It commits an origin+user write fence, a restart-safe file/credential inventory, scoped row
removal, and matching saved-connection token removal in one transaction before deleting
files. The fence also rejects stale whole-share-index writes that would restore A's bound
intake. Scoped asynchronous saves cannot repopulate a deleted account; other accounts and
unbound App Group intake remain intact.

Precise local scope includes drafts, outbox, snapshots, record edits/mutations, voice recovery,
wardrobe, native intents/journals, result-choice intents, ongoing-task requests, workspace
imports, share delivery and conversation drafts, and cloud memory edit v2. The matcher uses
the exact canonical origin/user/tenant/identity scope and includes all identities and tenants
belonging to the account. Old memory-edit v1 lacks user ownership and is retained/reported.

Original media and share folders are deleted only from confirmed scoped references and only
when remaining account/unbound records do not reference their UUID or exact URI. Copying a
new original records an account inventory before copying and runs inside the same save queue.
Recorder source paths are limited to the Expo SDK 57 `ExpoAudio/recording-UUID` (iOS),
`Audio/recording-UUID` (Android), and Pajio `voice-takes/voice-UUID.wav` paths in the app's
Documents/Cache roots. No photo-library, user-picked external original, arbitrary document,
or whole originals directory is deleted. The host can provide owned, just-stopped recorder
URIs through `{recordingUris}` so they are journaled before losing the in-memory pointer.

`clearDeletedAccountLocalData` reports `rowsRemoved`, `filesRemoved`, `pendingFiles`,
`unownedLegacy`, and `legacyCredentialInventoryIncomplete: true`. Failed/unsupported cleanup
entries remain journaled for retry. Keychain session/native credentials created by this
version are indexed before use. Older unindexed credentials and orphaned files cannot be
attributed safely and are not bulk-erased. Thus the UI must say it cleaned **confirmed owned
copies**, not all historic app data. Shared device appearance/installation data and restricted
deletion receipts remain. Existing OS calendar/reminder records are not deleted.

C operator receipts extend states with `waiting` (known finite reason codes) and `completed`.
The App accepts completion only with the matching user/request/revision, `code=verified`,
and `data_erased=true`, and validates all returned tenant actions. Completion means the
registered private contents/indexes/backups were verified deleted. A minimal identity
tombstone remains and shared-member content is not represented as globally erased. Missing
production adapters remain waiting; no actual provider, identity or cloud deletion was
performed during implementation.

Validation uses fake gateway/OIDC/provider responses, pure client protocol tests, and actual
isolated temporary SQLite databases. There is no real-device SecureStore, native recording,
account deletion or production-provider acceptance claim. Full App validation is recorded by
the parent build handoff separately.

App 定向回归：73 passed，包含注销协议、启动恢复、临时 SQLite 清理、session/语音/SDK57真实数据形状回归；日志 `/tmp/pajio-account-targeted-final.log`。Gateway 最后复跑 43 passed，日志 `/tmp/pajio-deletion-gateway-final.log`。

Final App regression at source freeze: **485/485 passed**, `/tmp/pajio-account-mobile-all-final.log`;
`tsc --noEmit` and `eslint src` passed. This is code/protocol/storage validation, not physical
phone or production account-deletion acceptance.
