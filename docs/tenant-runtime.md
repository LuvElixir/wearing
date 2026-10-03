# 独立租户运行入口

2026-10-03。本次是 S1 的租户 Worker 基础：把现有 Wearing 与 Hermes 的状态和生命周期封装进一份独立实例，复用原会话、目标、文件和记忆实现。没有引入第二个 Agent 循环。

## 初始化与启动

以下为开发示例。生产应在每租户独立 VM/microVM 内执行，不能在共享服务器上建立两个目录就宣称完成 VM 隔离。

```sh
wearing tenant init --root ./tenant-A --tenant-id tenant_A --origin https://wearing.example
wearing tenant status --root ./tenant-A
wearing tenant serve --root ./tenant-A --port 8781
```

初始化生成私有 `instance.json`、内部服务凭据 `gateway.key`、`data/instance-owner.json`。重复初始化相同租户与网页来源不会换密钥；尝试改租户或采用已有本地用户目录会拒绝。云厂商可替换，实例配置不写入提供商管理凭据。

实例固定一个 tenant_id。数据卷也保存 instance_id/tenant_id，启动前核对归属，发现错误卷时不打开用户数据库。实例私有状态位于 `data/`：Wearing SQLite、Hermes Home/SessionDB/记忆、身份和文件都在里面；启动参数与请求不能切换这份目录。

每份数据卷使用现有 FileLock 防止同时启动两个本服务写入者。锁不能阻止拥有文件系统权限的其他程序或管理员。Windows 需当前用户私有 ACL，不能仅依赖 POSIX chmod。

## 私有入口与公共登录

本入口只监听回环地址，不是可直接开放公网的 SaaS 登录服务。所有页面、文件、记忆和 API 都要求：

- 每实例独立的 `Authorization: Bearer ...` 内部服务凭据。
- 与启动配置相同的 `X-Wearing-Tenant`，重复字段或误路由拒绝。
- 网页 Origin 必须与初始化记录完全匹配，Host 仍由 TrustedHostMiddleware 检查；产品修改操作继续要求页面 CSRF token。

内部凭据由受信任入口代理添加，不能发送到浏览器、放进 URL 或访问日志。代理必须先用成熟 OIDC 验证用户及 membership，再从可信平台记录决定实例和凭据；不能依据用户提交的 tenant_id 直接转发。当前已新增 [OIDC 入口](gateway-runtime.md)、会员查询、入口路由与会话撤销，平台 PostgreSQL 权限/RLS 已在本机真实数据库及合成 IdP 双用户 HTTP 链路验收；真实 IdP、生产入口、独立 VM 和内部凭据轮换仍待接通。私有 Worker 的服务凭据校验自身不能冒充用户登录。

`GET /internal/runtime` 同样鉴权，报告固定归属、引擎状态及 `hardware_isolation_verified: false`。这个值不会因配置写了“VM”或本机启动两个进程而变为已验证。真实提供商实例、guest kernel、磁盘与网络证据需要后续验收。

中间件复用 FastAPI/Starlette 的 ASGI 与 TrustedHost 能力，见 [FastAPI 官方说明](https://fastapi.tiangolo.com/advanced/middleware/)。

## 引擎、设备与恢复

使用同一固定版本 Hermes。每实例自行安装和配置，模型凭据由本人或明确的租户配置流程接入；本工具不会复制开发机 `.env`、会话、记忆或设备配置。可以在实例内用已有命令准备引擎：

```sh
wearing engine install --data-dir ./tenant-A/data
wearing engine model --data-dir ./tenant-A/data
```

启动 Worker 时，已安装的受管引擎会自动尝试启动，并保存本实例的连接。未安装或模型未配置时保留产品记录，允许继续配置，不伪造执行成功。停止 Worker 沿用现有生命周期清理自己启动的引擎。未发送草稿不会因重启就自动成为授权任务；原运行恢复沿用 TaskService 的核对规则。

云端运行时关闭本机 computer_use / 手机 MCP 的自动装配，相关设备管理及外部引擎换绑 API 返回未接通。VM 宿主不是用户的电脑；远程设备要走后续连接器。文件工具使用实例私有工作目录。原生记忆和旧会话检索沿用 v6 配置。

`--no-engine-autostart` 仅供独立测试或离线开发。双实例验收用两份原生 Hermes Home 和单独测试引擎，不调用模型或操作设备；这不是生产管理方式。

## VM 内服务模板

[wearing-tenant.service](../deploy/tenant/wearing-tenant.service) 供 Linux VM 内使用：一个 `wearing` 用户、一份私有 StateDirectory、失败重启与受管进程关闭。Linux 承载云端 Agent 核心，不替代用户用于 App/账号的 Mac、Windows 或手机。

部署者需先准备独立 VM、具有 `/var/lib/wearing` home 的服务用户、`/opt/wearing/venv` 安装环境和对应实例。模板不下载未知脚本、不携带密钥、不创建付费实例，也不自动安装到本机。systemd 语义以 [官方服务说明](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.service.xml) 为依据；本机是 macOS，模板尚未经过 Linux VM 的启动与恢复验收。

私有状态需要一致性备份与恢复，不能只把运行中的 SQLite 文件复制走。生产 OIDC、TLS/mTLS 入口、平台 Secret Manager、持久唤醒、VM 网络限制、自动备份和远程设备转发仍是后续工作。本次实际证据见 [租户 Worker 验收](evidence/tenant-worker-2026-10-03.md)。
