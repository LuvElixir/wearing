# Pajio 云端对外就绪审计

审计日期：2026-10-09。范围：`deploy/`、`src/wearing/cloud/`、用量与任务恢复相关源码，以及仓库云端验收记录。本审计不读取私有凭据、不 SSH、不修改云资源。当前实例状态引用主会话本轮腾讯云官方 CLI 的脱敏只读结果；历史运行测试没有在本轮重做。下面的源码判断以本报告写入时为准，后续修复应另附测试证据。

## 结论：核心曾上云，目前没有在线的外测服务

- **曾经真实上云。**10 月 3 日，一个租户、一台腾讯香港 CVM、独立数据盘实际运行 Wearing/Hermes；真模型、工具、记忆、有限轮次目标、整 VM 重启与数据保留均有记录。本机既有个人对话与数据没有迁移。见 [首台 VM 验收](../tencent-vm-2026-10-03.md:5)；后续 [私人入口验收](../private-cloud-entry-2026-10-03.md)补充云模型通过 HTTPS 出站连接器访问真实 Mac/Android 的证据。
- **现在仍停机。**2026-10-09 15:03:14（Asia/Shanghai）的 [cloud-current.json](cloud-current.json:2) 记录 `STOPPED / STOP_CHARGING`，没有公网地址；2 vCPU、4 GiB，系统盘和数据盘各 40 GiB。`LatestOperation=RenewInstances / SUCCESS` 不是启动成功，判断运行状态仍应看 `instance_state`。10 月 4 日停机时保留了磁盘、配对资料和本机开发服务，见 [暂停记录](../cloud-pause-2026-10-04.md:14)。
- **最近 App/核心新增能力没有云发布证据。**10 月 3 日的真实执行只能证明当时版本；不能据此声称 10 月 7—9 日新增的账户注销、来源控制、原生能力、通知与用量限制已在服务器上线。
- **不满足外部用户独立使用。**生产 OIDC、公共 HTTPS 账户入口、生产控制库、真实签名推送与最新核心的云验收没有形成闭环。开发机二维码、SSH 私人入口和模拟器通过均不能替代外测入口。

## 已有边界与缺口

| 领域 | 已有实现或证据 | 对外仍缺什么 | 优先级 |
| --- | --- | --- | --- |
| 租户归属 | 固定 tenant/instance，数据卷 owner 标记，私有目录校验，FileLock 单写者；Worker 不根据请求切换目录。每个请求校验唯一内部 Bearer 与 tenant。见 `cloud/instance.py`、[worker.py](../../../src/wearing/cloud/worker.py:20)。 | 本机两个 Worker 只证明进程/数据边界；云上仍只验过一台 VM。需要第二独立 VM 的越权验收、卷误挂拒绝、VPC/出站策略实证。`hardware_isolation_verified=false` 不应仅因启动配置而改真。 | P0 |
| 公网暴露 | Worker CLI 固定回环；`/internal/*` 不通过公共代理。设备 relay 单独 TLS 443，拒绝浏览器 Origin，配对与连接凭据分离。旧试验曾限定 SSH 来源。见 [cli.py](../../../src/wearing/cli.py:302)、[gateway.py](../../../src/wearing/cloud/gateway.py:153)。 | `deploy/` 没有完整生产 gateway/HTTPS 反向代理与证书续期交付；停机释放 IP 后需重新核对地址/证书。恢复旧 relay 不等于上线用户门户。 | P0 |
| 用户登录与会话 | 固定 issuer，Authlib 授权码 + S256 PKCE，服务端一次性 state、随机会话散列、会员路由；原生交接单次使用，当前空间绑定；HTTP/WS 长连接重查撤权。 | 真实 IdP 客户端、正式回调域名、账号邀请/登记与独立外部用户首登仍需部署验收；当前 membership/route 是操作者入口。不得将内部 Worker 服务密钥当用户登录。 | P0 |
| 内部服务信任 | 入口从可信路由加载实例凭据，丢弃调用者 Cookie/内部头，Worker 再核对租户；不提供任意 URL 代理。 | 生产私网/TLS 或 mTLS 路径、内部凭据轮换/失效方案、Secret Manager 尚无完成证据。现有私有配置文件权限不等于托管密钥与轮换已接入。 | P0/P1 |
| 请求资源保护 | Worker 代理普通 body 1 MiB、文件导入 20 MiB、素材 15 MiB；relay 8 MiB；上游 HTTPX 40 个连接、30 秒超时；语音帧大小、总时长有界。 | **HTTPX 超时不覆盖客户端上传。**relay 在校验 Bearer 前读取完整 body；proxy/mobile exchange 没有上传期限；`/auth/tenant` 直接 `request.json()`。也无已验证的边缘/跨进程限流与按租户请求接纳。见 [relay.py](../../../src/wearing/cloud/relay.py:604)、[gateway.py](../../../src/wearing/cloud/gateway.py:159)。 | P0 |
| 模型与语音预算 | [UsageBook](../../../src/wearing/usage.py:31) 已持久记录模型/语音调用、音频时长、并发预占；SDK transport guard 计实际尝试，未知结果保留已占额度。默认 200 模型次、100 语音次、1 小时语音、各 2 并发。 | **只有 `PAJIO_TRIAL_LIMITS=1` 才执行限制；当前 service 模板未配置且云 Worker 未强制。**现有金额为 unknown，并非金额预算；输入 token、工具/网络/云资源开销不受该计数器完整约束。应复用已有 guard，不能另造表面额度 UI。 | P0 |
| VM/进程配额 | 独立 VM、私有卷、非 root 租户用户；systemd 只读代码、私有临时目录、服务失败重启、挂载依赖。 | [service 模板](../../../deploy/tenant/wearing-tenant.service:7) 没有 MemoryMax/CPUQuota/TasksMax 等边界；磁盘空间、产物/日志保留和服务级配额需明确。2C4G 单人试验不构成多用户容量证据。 | P0/P1 |
| 平台数据库 | PostgreSQL 生产模式与 `verify-full` 校验、独立 web/operator/migration 角色、8 表 FORCE RLS、每事务作用域重置、启动权限审查。见 [postgres.py](../../../src/wearing/cloud/postgres.py:23)。10 月 3 日本机真实 PG 验收通过。 | 无生产数据库/TLS/HA/PITR 证据。控制层同步 DB 查询与全局变更锁需并发测试；暂无明确 statement/lock timeout 配置。生产 PG 过期 session/state 不清理（仅 SQLite 登录时清理），需要独立操作者维护，不能放宽网页 RLS。 | P0/P1 |
| 备份与恢复 | 旧云实验做过排空停止后的加密冷备份、37 文件恢复到独立目录、散列和 SQLite integrity_check；未覆盖原实例。 | 不是全新 VM 容灾。无自动备份策略、异地/独立故障域副本、保留周期、失败告警、平台 PG 备份/PITR 和恢复演练闭环。快照存在与磁盘保留都不是可恢复性结论。 | P0 |
| 任务持久与恢复 | SQLite 保存任务、目标、schedule occurrence；revision/唯一键防重复；启动把原活跃任务标 `connection_lost/ambiguous`，核对原 run，避免自动重发。逾期定时任务按 grace window 跳过；device relay 有持久动作账本。 | 调度仍由 Worker lifespan 中的循环驱动；VM 停机时不会推进。需要最新版本跨日、进程崩溃、网断、关 App、旧确认不重放的云实证；不能宣称任意有副作用动作具有自动恢复/恰好一次执行。 | P0/P1 |
| 可观测与支持 | 已有 health monitor、脱敏诊断、持久通知 outbox 与回执逻辑；systemd 可重启服务。 | 公网健康、后台调度落后、额度阻止、备份失败、磁盘水位、租户启动失败的操作者告警未形成生产闭环。手机实际通知可达、APNs/FCM、签名外测包仍独立待验收。 | P0 |
| 注销和数据清除 | 已有 ownership plan、冻结、0002 迁移、tenant tombstone、撤权/排空及受限 Tencent 删除适配；额外存储或未知动作会阻止误报完成。 | 真实云资产完整登记、专用操作者权限、保留策略、真实清除读回与手机本机清理尚未完整验收；冻结/受理不代表删除完成。 | P0 |

## 持久任务的精确边界

`TaskService.recover_startup()` 在重启后保留原 task/run，标记核对状态；[service.py:383](../../../src/wearing/service.py:383) 没有自动重发原指令。`ScheduleBook.claim()` 用事务、schedule revision 和唯一 occurrence 管理触发，过期超过允许窗口写 skipped，见 [schedules.py:270](../../../src/wearing/schedules.py:270)。目标受轮次数与 revision 约束，已接受用户消息与目标轮次交替，见 [goals.py:618](../../../src/wearing/goals.py:618)。

这些是有价值的现有实现，但 [app.py:214](../../../src/wearing/app.py:214) 的 sweep 依赖在线进程。需要实际确认“App 和开发 Mac 关闭后，云 Worker 仍执行并保存结果”“服务重启只核对原运行”“恢复不会补发过期设备操作”。旧 VM 整机重启证据只覆盖当时版本和一轮试验，不覆盖新调度和所有外部副作用。

## 立即可编码的三项

1. **云启动必须启用既有试用限制。**在云 Worker 启动和部署模板处建立显式检查，复用 UsageBook / usage_guard；无法装入 guard、预算读取失败、配置不支持时拒绝开始模型/ASR 调用。测试禁用配置、并发额度、重启未知尝试仍计费、跨身份共用 runtime 额度。运行层资源限额也需明确，但实际阈值要按整套受管子进程压测确定。
2. **公共 HTTP 请求的有界读取与期限。**统一 proxy、移动登录交接、门户小 JSON 和 relay 的 body 读取；保留现有上传上限、OIDC form 回调、流式返回和 WebSocket。relay 对非配对接口尽早验证连接凭据；慢请求超时、超限与损坏输入返回确定错误，日志不含正文/密钥。有限进程内并发保护只能描述为本进程保护，不能冒充集群限流。主会话已指派本项随后实施，测试证据另记。
3. **生产元数据过期维护。**增独立 operator-only、每批有上限的 session/state 过期清理命令与定时模板。默认只预览计数、显式执行；不输出 token/state 内容，不删除有效会话，不扩大 web 角色权限。清理失败只告警，不中断正常会话。边缘限流和生产数据库资源上限仍须在正式部署时配置。

## 外测上线必须补齐的实证

1. 部署最新可追溯 release；记录源版本、服务版本、固定租户/卷归属、运行状态，禁止用 HTTP 200 代替引擎可执行。
2. 正式 HTTPS / OIDC / 控制数据库：两名真实测试用户各自进入独立租户；错误租户、伪造内部头、撤销中下载/语音、注销冻结均拒绝；正常租户不受影响。
3. 至少两份独立云实例完成磁盘误挂、连接器误配和文件/记忆/任务隔离验收；内部网络口、SSH、数据库只对必要来源开放。
4. 在真实模型与语音服务上耗尽小额测试配额，证明新调用被挡住，旧记录可读、用户能理解并重试；核对供应商账单与未知回执，不把调用数当金额。
5. 关 App、断开发 Mac、重启云进程后保留原任务/结果；跑一次真实定时与跨日简报；手机收到真正推送并准确进入对应结果。
6. 从一致性备份在全新隔离 VM 恢复，验证平台成员/路由和租户数据，并确认旧设备动作/通知没有被重新执行；确定 RPO/RTO 与保留策略后才能承诺恢复能力。

本次未启动付费实例、未更改安全组/数据库/服务、未读取或输出凭据。历史证据中的旧价格、旧“当前运行”段落以及当时的测试数量均不作为今天的运行、费用或最新版本结论。

## 审计后的代码修复

第二项请求读取保护已完成并通过 128 项关联回归，见 [HTTP 请求保护实施证据](public-request-body-hardening.md)。云启动限额由并行任务接入，关联网关测试已显式满足新启动约束。上表保留审计时的缺口，以便区分发现、源码修复和真实部署；公网环境与云恢复没有因测试通过而自动变成完成。
