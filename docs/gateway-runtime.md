# OIDC 登录与实例路由

2026-10-03。S1 新增入口服务：用 Authlib 的授权码流程、S256 PKCE、Discovery/JWKS 与 ID Token 验证接成熟 OIDC；用 SQLAlchemy 保存平台会员、实例路由和登录会话。平台不存 Wearing 对话、记忆、业务文件、截图或模型密钥，也不运行共享 Agent Gateway。

**当前部署仍是本地验收。**双用户实际 HTTP 链路及真实 PostgreSQL/RLS 已通过；配置支持 HTTPS + PostgreSQL 的非开发模式，并在启动时检查数据库版本与权限。真实 OIDC 账号、生产 TLS/mTLS 和独立 VM 尚未部署。当前 8765 本地入口保持独立。

## 配置与命令

以下地址和主体仅为示例，需由实际 OIDC 服务提供。注册授权码客户端，允许 S256 PKCE，把固定 `origin/auth/callback` 登记为回调地址；本入口只申请 `openid`。客户端密钥如有需要，通过 `WEARING_OIDC_CLIENT_SECRET` 环境变量提供，不放在命令参数或 URL 中。

```sh
uv run wearing gateway init --root ./entry-lab --origin http://127.0.0.1:8780 --issuer https://identity.example --client-id wearing-client --development
uv run wearing tenant init --root ./tenant-A --tenant-id tenant_A --origin http://127.0.0.1:8780
uv run wearing gateway member --root ./entry-lab --subject subject-from-provider --tenant-id tenant_A
uv run wearing gateway route --root ./entry-lab --tenant-root ./tenant-A --url http://127.0.0.1:8781
uv run wearing tenant serve --root ./tenant-A --port 8781
uv run wearing gateway serve --root ./entry-lab --port 8780
```

两个 `serve` 命令在独立终端或受管服务中运行。浏览器访问入口根地址会进入 OIDC 登录，成功后路由到用户自己的原 Wearing 页面。普通 API 和资源下载通过同一登录会话进入。示例 IdP 并不存在；没有配置真实提供商时不能完成真实账号登录。

`member` 是操作者命令，不是公共注册接口。会员按已验证的 **issuer + sub** 绑定，不能用邮箱同名自动加入或合并用户。撤销方式是同一命令增加 `--revoke`；当前会话的下一次请求会重新查授权。每次代理派发也重新检查会员关系，正在执行的动作仍需后续资源租约和取消链路处理。

以上示例未设置数据库环境变量时使用该开发入口的独立 SQLite。PostgreSQL 模式中，网页登录角色只读会员/路由；`member/route` 需要独立的 `WEARING_CONTROL_OPERATOR_DATABASE_URL`。版本迁移用 `gateway database upgrade` 和单独迁移凭据，运行角色验收用 `gateway database check`，见[数据库配置](control-postgres.md)。

`route` 是操作者登记实例的命令。先核对实例 tenant_id / instance_id / public_origin，再保存最少的内部凭据到入口私有 `credentials/`；元数据库只保留凭据引用。已有路由不能被该命令改绑到另一个实例或地址，迁移另行实施。它不复制 Hermes Home、用户数据库或模型配置。

## 登录与凭据边界

- 验证固定 issuer、签名、audience、期限、nonce；仅接受 RS256/ES256。Authlib 处理 PKCE 交换和 ID Token 解析，产品不自行实现密码或 JWT 签名验证。
- 登录 state 需要发起浏览器的签名会话标记；PKCE verifier 与 nonce 保留在服务端的短期状态中。状态最多十分钟，数据库原子消费后不能重放，可跨入口重启完成。
- 登录成功后，Cookie 只保存随机不透明会话 ID，数据库保存它的 SHA-256、用户/租户关联、期限和 CSRF token；不保存提供商 access/refresh/ID token。
- HTTPS 来源使用 host-only `__Host-wearing-session`、Secure、HttpOnly、SameSite=Lax、固定 `/` 路径。开发用回环 HTTP 时使用单独的 `wearing-session-dev`；服务端会话期限八小时，刷新 Cookie 不延长数据库期限。
- 入口从当前服务端会员关系决定实例和内部密钥，丢弃浏览器提交的 Authorization / X-Wearing-Tenant / Cookie。HTTPX 自带的上游 Cookie 也不转发到其他实例。
- 修改产品内容要求相同 Origin，Worker 继续检查原页面 CSRF token。门户的租户选择与退出额外要求 `/auth/session` 提供的 `X-Wearing-CSRF`。
- 不开放 Worker 的 `/internal/*`、任意 URL 代理或任意提供商地址选择。请求正文最多 1 MiB；文件与动画返回流式传输，保留 Range 相关头，不把完整视频积压在内存中。
- 所有入口响应禁止共享缓存，设置 `Referrer-Policy: no-referrer`；入口 CLI 关闭访问日志，不输出登录回调参数、内部密钥或提供商错误详情。生产 TLS 代理同样要关闭回调查询串及敏感正文日志。

登录步骤复用 [Authlib 官方 Starlette 集成](https://docs.authlib.org/en/v1.6.5/client/starlette.html)；固定 issuer 与 nonce 的处理根据实际安装版本源码核对。数据库约束复用 [SQLAlchemy 官方约束支持](https://docs.sqlalchemy.org/en/20/core/constraints.html)。依赖版本与散列见 `uv.lock`，本次实测 Authlib 1.8.0、SQLAlchemy 2.0.54、itsdangerous 2.2.0。

## 门户接口与剩余工作

| 接口 | 用途 |
| --- | --- |
| `GET /auth/login` | 发起固定提供商的登录；不接收自选回调地址 |
| `GET /auth/callback` | 验证一次性关联与提供商凭据，然后创建新会话 |
| `GET /auth/session` | 返回当前用户的不透明编号、所选租户、可进入的租户与门户 CSRF |
| `POST /auth/tenant` | 请求进入当前账号获准的另一租户，不改变同租户内的日常/出海身份 |
| `POST /auth/logout` | 删除服务端会话；旧 Cookie 即使重放也失效 |

原 Wearing 页面继续复用，账户选择/退出按钮、登录失败和会员邀请的完整界面仍待接入；当前门户接口用于工程验收。退出仅结束 Wearing 会话，不声称注销整个 OIDC 提供商的登录。

PostgreSQL 的版本迁移、独立运行/操作者/迁移角色、FORCE RLS 和事务作用域已在真实本机数据库验收；生产网络 TLS、Secret Manager/轮换、真实 IdP 客户端、TLS/mTLS 入口、限流、过期记录维护、独立 VM 入口与部署/观测仍需完成。设备配对、出站转发、动作账本、VM 提供商和持久调度继续是独立工作。

实际验收见 [OIDC 入口与双实例](evidence/gateway-2026-10-03.md)及[真实 PostgreSQL](evidence/control-postgres-2026-10-03.md)，全项目进度见 [进度表](progress.md)。
