# 公开租户调用限额启动保护

2026-10-09，本轮仅修改源码和部署模板；未启动/重启生产服务、未改变云资源计费、未调用付费模型或语音接口。

## 变更

- `cloud/worker.py`：非 loopback 的 HTTPS 租户入口必须由启动环境显式提供 `PAJIO_TRIAL_LIMITS=1`。否则在创建应用、数据库和引擎前抛出明确的 `InstanceError`；不因注入测试客户端或关闭自动启动而绕过。localhost、回环 IP 本地开发保持原行为；私网 IP 和伪 localhost 域名不豁免。
- `runtime.py`：构造时固定 enabled、租户账本根目录和身份。生成子进程环境时以该配置覆盖环境变量；环境后续变动不能切换这三个值。
- `usage_guard.py`：新增不可变 `UsageGuardConfig`，两条模型桥接入口在 provider dotenv 加载前捕获；实际安装、SDK 账本和 Agent fallback 检查都使用快照。不同配置不能覆盖已安装的守卫。账本路径和身份缺失/不合法时拒绝。
- `engine_runner.py` 和 `capture_bridge.py`：执行引擎与记录整理均在 dotenv 前捕获同类配置，dotenv 不能关闭限额或把调用记到另一租户。
- `deploy/tenant/wearing-tenant.service`：显式启用限额；整棵服务 cgroup 配置 `CPUQuota=150%`、`MemoryHigh=2G`、`MemoryMax=3G`、`TasksMax=256`。这些是当前 2C4G 模板的保守进程资源护栏；不等于 VM/microVM 内核隔离，也不是自有 PC 的已验证容量。未在目标 Linux 宿主应用或实测这些限制。
- 公开租户相关测试显式开启环境开关，没有产品中的测试 bypass；网关测试文件由另一开发任务负责。

## 验证

`pytest -q tests/test_usage.py tests/test_usage_guard_boot.py tests/test_usage_sdk.py tests/test_runtime.py tests/test_tenant_worker.py tests/test_account_deletion_tenant.py tests/test_context_routes_integration.py tests/test_desktop_input.py tests/test_device_permissions.py tests/test_device_setup.py tests/test_chat_imports.py`：**145 passed**。

覆盖缺失/错误开关早于引擎构建失败、loopback 不受影响、Runtime 配置固定、两条桥接入口的恶意 dotenv 覆盖、无效身份/目录拒绝。SDK 回归使用本机已安装的 Hermes Python、真实 OpenAI SDK / dotenv / SQLite 与 HTTP MockTransport；只有上游 Agent 构造被合成替身替代。校验 503 不被 SDK 自动重复发送、并发/耗尽在网络前拒绝、stream 槽位释放、未知结果保持占用次数、输出上限、重复安装不能换账本、dotenv 不能关闭 provider/fallback 检查。

`pytest -q tests/test_control_postgres.py`：**9 passed，18 skipped**；跳过的是缺少专用 PostgreSQL 测试配置的数据库集成场景，未连接生产数据库。`git diff --check` 和目标 Python 文件 `compileall` 通过。

## 边界

限额沿用现有试用调用次数、语音时长和并发策略；没有实现人民币支出硬封顶。模型输入规模、供应商价格、工具费用和未知 token 回执仍可能影响实际支出。目标宿主资源限额生效、完整上游模型调用及公开用户容量仍需部署后的专门验收。
