# Pajio 持久健康历史与脱敏支持导出

2026-10-08。对应 `PRODUCT.md` 中持续运行、资源健康、失效恢复、结果可核对，以及 `external-test-gaps.md` 中 P0 运维闭环。此包是共享后端软件，App 由 root 接线，Web/Desktop 仍由 ZCode 按契约接入。

## 已实现范围

- 将现有 `Diagnostics.snapshot()` 的有限元数据保存到租户自己的 SQLite。默认每 300 秒读取一次；手动观测同一身份至少间隔 15 秒。仅读取运行环境状态、既有引擎 `GET /v1/capabilities`、已接 relay 的状态与当前身份最近 30 项任务状态。
- 记录故障首次出现、类别变化、条件消除及任务结束。相同故障连续观测不会重复制造故障事件；服务重启后沿用持久条件起点。
- 默认保留 7 天，每身份最多 2016 份观测、1000 条事件、1000 个条件记录。达到时间或数量上限均会淘汰旧行；失效导出在下一次采样/导出事务中清理。没有后台进程运行时不会宣称已经物理清理，但过期数据不会通过接口返回。
- 历史及事件可分别分页。读取历史不会发起探测。`read_at` 表示读取历史的时间；`observed_at` 表示该次采样完成并持久化的时刻，不是 OS/任务执行心跳。一次诊断中的任务、引擎、设备读取不构成外部原子快照。
- 用户显式创建支持包后，保存不可变 JSON，返回 SHA-256、字节数、文件名和有效期；同 request_key 重试拿到同一份内容，重启不改变回执。导出有效期 24 小时，每账户＋身份最多 5 份有效文件，单份最大 1 MiB。
- 没有支持服务、邮件、工单或告警连接；导出恒为 `transmission=not_sent`。下载不表示已分享、已接收或有人处理。包内没有自动发送端点。

文件：`src/wearing/health_history.py`、`health_history_api.py`、`tests/test_health_history.py`。另在注销 `_freeze()` 固定取消列表中加入 `health_task`，并用真实临时 tenant ASGI 测试证明已 await 采样取消，冻结后无迟到诊断写入、重启不启动采样。

## 证据含义与状态

所有数据经白名单重新构建，不保存 prompt、message、task title、error 正文、stack、文件内容/路径、URL、模型配置、设备名称/serial、凭据或账号名称。任意上游 run ID 仅保留固定哈希引用；生成的 UUID 保留便于查找。导出的账号 storage_scope 和原始 identity_id 均被去除。

`component`：`runtime | engine | devices | task | collector`。

`status`：

- `ok`：该项的本次证据支持其正常状态；引擎只证明 capabilities 响应，runtime 只证明进程状态，任务只证明当前排队/执行状态。均不证明业务结果已验收。
- `fault`：明确探测失败或任务错误类别。
- `review`：设备需核对、运行结果未知/停止未确认，或运行阶段 15 分钟无状态变化需要核对。最后一种不是卡死判断。
- `waiting`：等待用户决定，不记作故障。
- `inactive`：未运行或所有设备均暂停；不能拿来证明旧故障恢复。
- `ended`：任务进入停止/关闭/完成未验收/已核对终态；不把全部终态叫“执行成功”。
- `unknown`：未观察、证据不足或设备列表截断，不能宣称全体健康。
- `not_configured`：明确未配置、未安装或无已登记设备。

`code` 固定集合：`observed/runtime_unavailable/runtime_error/engine_unavailable/engine_timeout/device_source_unavailable/device_disconnected/device_review/run_failed/engine_connection_lost/run_state_unknown/stop_unconfirmed/progress_check/collection_failed`。

事件 `kind`：

- `condition_started`：第一次明确 fault/review，存条件起点。
- `condition_changed`：现存异常的类别发生变化。
- `condition_cleared`：后续同组件明确变为 ok；有 `condition_started_at`、观测时间与 `previous_code` 可核对。**只证明在两次观测之间发生恢复，不提供精确宕机时长。**
- `condition_ended`：该任务以某个终态结束了异常；不称为成功恢复。
- `state_changed`：其他已观测状态变化。unknown/inactive/not_configured 不关闭旧异常。

未采样期间不能补造历史；短于采样间隔的故障可能漏掉。最近 30 个任务以外不在本包覆盖范围。事件仍可能留存而其 sample 已被数量上限淘汰；不能保证每个旧 sample_id 都可检索。引擎因网络原因无法响应时，证据只叫引擎不可达，不能据此断言云服务器崩溃或用户手机断网。

## 账户、身份与持久化边界

云模式 `require_owner=True`：每个路由均要求 gateway 可信 `pajio.storage_scope`（64 位小写十六进制），不接受客户端 body/query 的 owner。无 scope 返回 401；不能回退到 local。

采样时从 `tasks JOIN task_principals` 获取真实任务归属；云端无可信 principal 的任务省略。task 样本/事件按当前 owner_scope 精确过滤；即使同租户、同 identity 的两个用户也不能读取对方 task 编号/状态或导出。runtime/engine/设备总体健康属于该 identity 的服务级状态，仍按身份共享，且不含任何具体设备标识。

导出按 identity＋owner＋request_key 幂等；按 identity＋owner＋export_id 下载。越界、缺失和过期均 404；query identity 与 header 不一致沿用现有 409。已有 TenantBoundary、登录有效性、identity middleware、CSRF/Origin 围栏继续生效。不得将 installer 挂到一个没有这些围栏的公开 app。

这套数据只存当前租户私有 SQLite；不会上传控制面或跨租户聚合。生产注销 adapter 擦除登记私有数据盘时包含此库。个人空间/账户删除或物理保留政策仍以注销契约及生产登记为准，不由健康模块自称执行完成。

## 路由

`GET /api/diagnostics/history`

- `sample_limit` 默认 48，范围 1–288；`event_limit` 默认 100，范围 1–500。
- `before_sample` / `before_event` 独立正整数游标，只向旧编号读取，不能改变身份或账户过滤。读取期间新样本不会造成后续页重复。
- 返回 `schema=1, scope=current_identity, read_at, sampler_running, coverage, samples, events`，各自 `*_truncated` 与 `next_before_*`。
- `sampler_running` 仅表示当前进程采样协程启动且尚未退出，不是服务健康证明。导出没有该瞬时字段。

响应缩略（完整 task observation 另有 `run_id, attempt, phase, last_state_event_at`，未提供时为 null）：

```json
{
  "schema": 1,
  "scope": "current_identity",
  "read_at": "2026-10-08T00:10:00+00:00",
  "sampler_running": true,
  "coverage": {
    "retention_seconds": 604800,
    "sample_interval_seconds": 300,
    "latest_observed_at": "2026-10-08T00:05:00+00:00",
    "earliest_retained_at": "2026-10-08T00:00:00+00:00",
    "seconds_since_observation": 300,
    "freshness": "recent",
    "continuous_uptime_proven": false,
    "mode": "point_in_time_samples"
  },
  "samples": [],
  "samples_truncated": false,
  "next_before_sample": null,
  "events": [],
  "events_truncated": false,
  "next_before_event": null
}
```

freshness 为 `never_observed | recent | stale`，最新保存观测超过两倍采样间隔为 stale。翻旧页不会把该页的时间误作最新观测。采样器自身失败可以形成最近 collector=fault 样本，不能据 freshness=recent 将引擎/设备改成正常。

`POST /api/diagnostics/sample`：无请求内容，现有 CSRF 必需。实际发起一次只读采样；返回 `{schema:1,sampled:true|false}`。false 代表触发了 15 秒去重，不能显示“重新探测完成”。组件失败仍会保存明确 fault；整个采集失败只保存 collector=fault，不沿用旧正常状态。整个采样失败且无法持久化返回 503 `observation_unavailable`。

`POST /api/diagnostics/exports`：strict body：

```json
{"request_key":"client-durable-request-01","category":"devices"}
```

category 为 `chat|voice|sync|files|notifications|devices|performance|other`。不允许附加自由文本或秘密数据。返回 201 `{schema,id,created_at,expires_at,category,sha256,bytes,filename,transmission:"not_sent"}`。创建过程读取一致的 SQLite 历史视图，不启动模型或采样；预览用户看到的 bytes 与下载相同。最多取最新 288 次样本和 500 事件，超过 1 MiB 继续裁掉较旧样本，明确标记 truncated。

`GET /api/diagnostics/exports/{id}/file`：`application/json` 附件下载，含 `X-Content-SHA256`。当前账户仍需有效登录/身份；这不是匿名文件链接。过期后旧 id 不再可取。同 request_key 在原文件过期后可生成新报告并返回新 id/摘要。

所有成功响应 `Cache-Control:no-store`、`Pragma:no-cache`、`X-Content-Type-Options:nosniff`。错误使用有限代码，无底层路径/异常信息。没有支持提交成功/送达状态。

## root 挂载说明

本包未改 App/Web/Desktop 或 `app.py`。root 在已有 `install_diagnostic_routes` 之后挂载：

```python
from .health_history import HealthHistory, HealthMonitor
from .health_history_api import install_health_history_routes
health_history = HealthHistory(store, require_owner=not local_devices)
health_monitor = HealthMonitor(
    health_history, app.state.diagnostics,
    deployment='local' if local_devices else 'cloud',
)
install_health_history_routes(app, health_history, health_monitor)
app.state.health_history = health_history
app.state.health_monitor = health_monitor
```

`Diagnostics` 的 runtime/probe/devices adapter 必须保持既有只读语义。当前 `diagnostic_probe` 使用已有 `service.hermes` 或 `identity_clients.get(identity)`，不会经 `identity_client` 自动拉起引擎；runtime_for 可能构造状态读取对象但不启动进程。禁止在探针中调用 `service.refresh/start/stop` 或自动修复。QA 必须注入 synthetic 假适配器。

在现有 lifespan 初始化已完成后、yield 之前：

```python
health_stop = asyncio.Event()
health_task = asyncio.create_task(health_monitor.run(health_stop))
app.state.health_task = health_task
```

在关闭客户端/运行环境之前：

```python
health_stop.set()
health_task.cancel()
with suppress(asyncio.CancelledError):
    await health_task
```

取消向上传播，不生成“正常结束”样本。当前 `TenantDeletionControl._freeze()` 已加 health_task 取消并 await；tenant tombstone 重启路径不进入普通 lifespan，因而不会重新创建 sampler。不得把采样循环放到该围栏外。单个 worker 一个 sampler；后台采样不需要 App 常开，但实例自身必须持续运行。

## 验证与真实运营门槛

测试仅使用临时 SQLite、真实 FastAPI/TenantBoundary ASGI、`httpx.MockTransport`、假 runtime/probe/relay；没有访问真实云账号、用户目录、外部模型或支持收件箱。用 MockTransport 驱动实际 HermesClient 验证仅请求 `GET /v1/capabilities`，tasks/events 原行不变。

涵盖故障去重与重启起点、未知不恢复、独立 engine/device/collector 错误、等待用户不报故障、任务归属/身份隔离、历史分页、保留/数量/大小上限、脱敏 canary、导出丢回执幂等/过期/跨账户拒绝、采样超时/取消、暂时 DB 清单失败后恢复、实际 HTTP 401/403/404/409/422、CSRF、稳定下载摘要以及注销停机。

保留的生产门槛：公网常驻 worker、独立外部可用性监控（进程停止时它无法自报）、告警收件人/频率/静默规则、实际支持工单服务与明确的数据授权/保留规则、真实 kill engine/断 relay/断网恢复演练。这些没有配置或真实验收时不会声明“24 小时监控”“已发告警”“客服已收到”或外测完成。

本包最终回归：

```text
uv run pytest -q tests/test_health_history.py tests/test_diagnostics.py tests/test_account_deletion_tenant.py tests/test_account_deletion_operator.py tests/test_qa_support.py
76 passed in 9.16s
```

其中健康历史 17 项、原诊断 8 项、tenant 注销 10 项（新增 health sampler 冻结项）、operator 28 项、QA 13 项。`compileall` 与限定文件 `git diff --check` 通过。没有以这些合成测试代替 App 原生点击、云端持续运行、真实故障演练或支持工单送达。
