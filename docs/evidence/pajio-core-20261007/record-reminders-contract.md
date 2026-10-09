# 日程 / 待办到期提醒：App、服务端与 ZCode 只读合同

日期：2026-10-08。对应原 life 设计中的自有提醒、改期后同步调整、完成或删除后停止提醒。不执行模型，不另起云服务。

## 用户可用流程

- 具体日程开始时间或待办截止时间可以开启提醒，提前量为准时、5 / 15 / 30 / 60 分钟、1 天。开关和提前量需点击保存。
- App 待办详情新增截止时间的原生日期/时间选择，明确保存后生效；取消截止时间用 due_at=null。记录编辑仍走原离线修改队列，不因设置时间自动打开提醒。
- 全天日程、无截止时间待办、已删除或已完成记录不可新开提醒，不猜测用户的日期或某个默认全天提醒时刻。日程改为具体时段，或待办保存截止时间后可启用。
- 重复日程打开具体实例后显示「这一次的提醒」，只绑定这次 occurrence。整个系列自动重复提醒不是本版范围；选定实例始终由服务端真实系列规则和例外投影读取。
- 设置保存在当前账户和身份。设置成功与手机系统通知可用是两件事；面板有实际的手机通知设置，可开启/停止系统推送登记、查看推送配置与安静时段。
- 这条记录有未保存输入、离线修改或冲突时，先处理记录版本再设置提醒。

## 接口与状态

沿用现有 identity/auth/CSRF 中间件；owner 只取可信 ASGI `pajio.storage_scope`，不是请求 body / header 或推送里的字段。本地明确使用 local scope。

```python
from .record_reminders_api import install_record_reminder_routes
install_record_reminder_routes(app, notifications.reminders, local_devices=local_devices)
```

`NotificationService` 已创建 `reminders`，并在原有 5 秒 tick 内收集到期提醒，无新后台进程。QA 本地安装可省略 local_devices 参数。

- `GET /api/record-reminders/{target}` 读取当前 source 和设置。
- `POST /api/record-reminders/{target}` 保存 / 精确重放同一设置操作。
- target 为 `life_<32hex>`，或 `recurrence_<32hex>_<YYYYMMDD>`；不接受任意路径、URL 或新纪录正文。

```json
{"revision":0,"record_revision":1,"enabled":true,"advance_minutes":15,"request_key":"a-persisted-uuid-request"}
```

revision 是提醒设置版本，record_revision 是当前具体 life 版本 / 系列 revision。参数闭集，两者都 CAS；key 匹配 `[A-Za-z0-9_-]{16,120}`。开启时提醒触发时刻必须在未来。关闭也使用版本核对，不能替另一账户停提醒。

回执字段：identity_id、target_id、revision、record_revision、enabled、advance_minutes、anchor_at、fire_at、status、reason、provider_status，写入另带 request_key。时刻是 UTC ISO8601，按源记录绝对时刻计算，不依赖服务端机器时区。

status 为 unavailable / disabled / scheduled / due / expired。reason 为 missing / removed / completed / all_day / no_time 或 null。provider_status 沿用原通知队列状态；ticket / provider_accepted 只证明服务商阶段，不代表手机已展示。

每账户每身份最多 500 份提醒设置、20,000 份设置请求回执。上限返回明确错误，不清旧回执冒险重放。

## 更新、失效和投递

- `record_reminders` 一份设置绑定 owner + identity + target。独立的 record_reminder_events 是投递去重索引，record_reminder_requests 是设置幂等账本；没有第二份 life 记录或周期实例副本。
- 时间改变会在 life/series 原事务内调整锚点、增加 activation 并取消旧 pending / awaiting_registration / sending。完成、删除、取消系列实例或移除系列在原事务内停用已配置提醒；随后立即恢复、取消完成或恢复例外，也不会重新打开旧提醒。
- 该失效逻辑在 `LifeBook.receipt` 与 `CalendarSeriesBook.mutate` 窄挂钩，原生同步也经 LifeBook.receipt。没有提醒表的独立 life/series 环境为安全 no-op。记录与提醒失效一起回滚。
- 仅修改标题/正文、或修改别的系列实例而不影响当前实例的时间，不重复提醒。改期先离开再改回，也不能使先前 claim 重新有效。
- key = reminder ID + activation + anchor + fire 的摘要。worker 重启 / 并发 tick 均只插一次事件；由原 notification outbox 按严格相同 owner 分发给已登记设备。
- 发送 claim 和最终 provider handoff 前再次检查真实 source、owner、activation、时间与当前设备登记。切换 owner、禁用通知、账户撤销沿用原 generation fence。已经交给提供方的通知无法撤回，不能声称修改能撤销手机已收到的消息。
- 安静时段与过期登记继续沿用现有等待语义；到期提醒超过原定时间 1 小时不再补发。provider TTL 也限制为剩余有效期，最长 1 小时。网络结果不明确不盲目重发；明确未连接 / 限流依原队列策略重试。
- 关闭通知期间触发的提醒不在重新开启后回放；提醒设置本身保留，以便未来改期后仍按明确设置执行。

## App 持久操作与通知打开

`record-reminder-request:<scope>:<target>` 保存冻结 body/phase；未知结果只能取回原回执，GET 不能证明上次写入是否成功。`record-reminder-last:<scope>:<target>` 保存上次读取/写入；离线缓存明确标注，不能据此冒充当前在线状态。

服务端同 owner+identity+key 同 body 返回原回执，改变 body 复用 key 409。App 收到无效成功回执、本机 batch 失败或网络错误保留原请求；真实 400/404/409/413/422 后允许显式读取最新设置并保留选择，再次保存会使用新 key。成功回执与本机 pending 清理原子提交，之后 GET 核实当前设置，防止把历史重放回执误当最新开关。

scope / credential 切换重挂载，注册 accountWork abort，通用账户存储清理与 fence 覆盖上述两个键。所有 HTTP 凭据在构造器冻结；不从推送取 URL 或秘密文本。

推送只带以下元数据：

```json
{"v":1,"type":"pajio.record","server_id":"32hex","event_key":"64hex","record_id":"life_or_recurrence_id","identity_id":"daily"}
```

沿用 `/api/notifications/resolve?event_key=...`，再次严格核对 owner+identity+实际 outbox归属。返回 kind=record_reminder、record_id、series_id/occurrence_key（普通 life 为 null）。旧 task 通知保持原协议。

NotificationClient.resolve 返回带 type 的联合类型：task 含 taskId；record 含 recordId、seriesId、occurrenceKey。根导航须先读取真实 life record 或 CalendarSeriesClient.get(seriesId, occurrenceKey).selected，验证准确 ID 与身份且仍有效，再切身份/open；不能直接信推送路由。root 已挂此分支及 routes，App 面板已挂 RecordDetail/CalendarSeriesPanel。

## 数据与验证

身份导出包含 reminder 设置的 target_id/revision/enabled/advance_minutes/anchor_at/reason/updated_at，按确切可信 owner + identity 闭集查询；不导出投递索引、幂等内部账本或 owner 值。专属 tenant 删除随 SQLite/数据卷清理，共享租户仍遵守原 leave_shared 边界。

本轮验证全为新临时 SQLite、Memory store 与 MockTransport，不触发真实推送或真实账号读写：

```sh
.venv/bin/python -m pytest -q tests/test_record_reminders.py tests/test_record_reminder_review.py tests/test_notifications.py tests/test_notification_quiet_hours.py tests/test_notification_owner_review.py tests/test_life.py tests/test_life_mutation_receipts.py tests/test_calendar_series.py tests/test_native_sync.py
# 143 passed in 3.37s
```

App 新 reminder 模型 / 通知路由 / 截止时间与原离线记录合跑 60 项通过；全 App tsc 与相关 App 文件 ESLint 通过。独立复核另外覆盖生命周期快速反转与 native_sync 路径；后续根完整测试为最终构建依据。

外测仍须配置真实 EAS/APNs/FCM 推送能力并在签名真机验证权限、锁屏、安静时段、点击路由。模拟器里保存设置和合成 provider 回执都不等于真机送达。ZCode 只读本合同及 App/backend 代码实现 Web/Desktop，不改 App 文件，不新建浏览器专属提醒副本。
