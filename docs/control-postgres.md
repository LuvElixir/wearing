# 平台 PostgreSQL

2026-10-03。平台会员、实例路由、会话和短期 OIDC 状态已接 PostgreSQL，并在本机真实 PostgreSQL 18.6 上验收。迁移复用 Alembic，访问复用 SQLAlchemy/Psycopg。平台库不保存用户对话、记忆、业务文件、截图、Hermes Home 或模型密钥；这些继续属于每租户的私有实例。

## 数据与权限

私有 schema 为 `wearing_control`。六张表是 users、tenants、memberships、routes、sessions、oidc_states；`alembic_version` 只记录迁移版本。首次迁移拒绝接管已有的未版本化 Wearing 表；迁移在事务与数据库 advisory lock 内执行，可重复升级。当前不提供破坏性的 downgrade，也不搬迁现有 `.wearing/wearing.sqlite3`。

| 凭据 | 权限与使用位置 |
| --- | --- |
| 网页登录角色，属于 NOLOGIN 组 `wearing_web` | 读取受作用域限制的元数据；插入/删除自己的会话及一次性登录状态；只允许更新会话的 `tenant_id` |
| 操作者登录角色，属于 NOLOGIN 组 `wearing_operator` | 登记/撤销会员、固定实例路由；可以查看所需平台元数据，不是网页进程使用的凭据 |
| 迁移对象所有者 | 创建/迁移 schema 和表；与前两种角色分开，不属于其权限组；不使用 superuser、BYPASSRLS、CREATEROLE 或 CREATEDB |
| 数据库管理员 | 在部署阶段创建数据库、权限组和登录角色；不会作为 Wearing 运行或迁移角色 |

网页进程只读取 `gateway.json` 中的网页数据库连接。操作者与迁移凭据仅由各自 CLI 环境提供，不写入入口配置。启动会检查迁移版本、角色、对象所有权、schema 创建权限、表/列权限、RLS/FORCE RLS 和策略名单；配置不符则拒绝启动。

## RLS 如何工作

六张表都开启 `ENABLE` 和 `FORCE ROW LEVEL SECURITY`。网页读取用户/会员/路由需要事务内的用户、租户作用域；会话先按不透明 SID 的散列读取，再从记录取得用户身份并复查会员。OIDC 状态仅按散列作用域读取和原子消费。每个事务都会重置全部作用域键，通过 `set_config(..., true)` 限定于本事务，防止连接池残留上一个用户。

会话写入同时受到 RLS 的 `WITH CHECK` 和 `(user_id, tenant_id)` 会员外键约束。网页角色无法更新会话所有者、CSRF 或期限，不能修改会员、路由或 schema，也不能 TRUNCATE。会话和 OIDC 状态过期后不可使用；PostgreSQL 运行角色不做跨用户过期记录清理，定期维护任务和硬限流仍待实现。

RLS 能保护应用遗漏筛选、错误作用域和连接复用；**可信入口程序有权设置这些作用域，因此它不防御被完全攻破的入口或特权数据库管理员。**平台元数据隔离也不替代每租户的独立 VM、私有卷与网络边界。[PostgreSQL RLS 规则](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)、[策略 USING/WITH CHECK](https://www.postgresql.org/docs/18/sql-createpolicy.html)、[事务内设置](https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-ADMIN-SET)。

## 配置顺序

先安装云端依赖：`uv sync --extra cloud`。在专用平台数据库中，由管理员执行 [权限组 SQL](../deploy/control/postgres-roles.sql)，然后通过实际数据库服务的安全配置创建三个独立 LOGIN 角色，给网页角色授予 `wearing_web`，给操作者角色授予 `wearing_operator`，让迁移角色拥有专用数据库。登录角色均不授予管理标志；迁移所有者不授予网页或操作者角色。网络鉴权使用实际服务的密码/证书及 Secret Manager，不把密码写在脚本和命令参数中。

安装 wheel 时，权限组 SQL 也位于 `wearing/cloud/postgres-roles.sql` 包资源中。PostgreSQL 本身不随 Wearing 包分发。

用 Secret Manager/受管环境分别注入以下环境变量：

- `WEARING_CONTROL_DATABASE_URL`：网页角色连接，仅在 `gateway init` 读取并私有保存。
- `WEARING_CONTROL_ADMIN_DATABASE_URL`：独立迁移所有者连接，仅在 `gateway database upgrade` 使用。
- `WEARING_CONTROL_OPERATOR_DATABASE_URL`：独立操作者连接，仅在 `gateway member/route` 使用。
- `WEARING_OIDC_CLIENT_SECRET`：如提供商需要，仅在初始化时私有保存。

连接使用 `postgresql+psycopg://`，必须指定数据库与登录角色。非开发的网络连接要求 `sslmode=verify-full`，并配置实际 CA/主机名；本机 Unix socket 可采用其本地鉴权。`--development` 的 PostgreSQL 仅允许回环地址或本机 socket，SQLite 仍限于该开发入口自己的私有目录。

```sh
uv run --extra cloud wearing gateway init --root ./entry --origin https://wearing.example --issuer https://identity.example --client-id actual-client
uv run --extra cloud wearing gateway database upgrade --root ./entry
uv run --extra cloud wearing gateway database check --root ./entry
uv run --extra cloud wearing gateway member --root ./entry --subject actual-verified-sub --tenant-id tenant_A
uv run --extra cloud wearing gateway route --root ./entry --tenant-root ./tenant-A --url https://private-worker.example
uv run --extra cloud wearing gateway serve --root ./entry --port 8780
```

地址均为部署占位。`tenant-A` 需先按[租户运行说明](tenant-runtime.md)初始化，固定相同公开来源。`serve` 继续只监听本机，由后续 TLS 入口代理对外提供 HTTPS；配置通过不表示代理、CA、真实 IdP、mTLS 或 VM 已部署。升级成功也不代替网页角色的 `database check`。

## 验收与剩余工作

真实 PostgreSQL 测试需明确提供一次性 QA 集群配置，测试配置必须标记 `qa_only: true`，含 app/operator/migration/admin 四个连接；禁止使用业务数据库。执行 `WEARING_POSTGRES_TEST_CONFIG=/private/qa-config.json uv run --extra dev --extra cloud pytest tests/test_control_postgres.py`。未提供时依赖真实集群的测试会明确跳过，不将跳过视为验收。

本次数据库测试及双用户实际 HTTP 登录/重启/撤销已通过，见[验收记录](evidence/control-postgres-2026-10-03.md)。本机测试使用私有 Unix socket 和测试用本地鉴权，不测试生产 TLS、备份/PITR、HA、线上压测、真实 OIDC 账户或硬件隔离。下一步是可替换 VM 的生命周期、两套真实实例验收，再接出站设备连接器；限流、过期记录维护、Secret Manager/轮换和生产运维继续逐项完成。
