# 每日自动简报与简报账户归属（2026-10-08）

## 用户流程

在既有简报偏好中展开“每天自动准备简报”，选择每天的时间、补做窗口，显式保存后生效。默认 08:00、两小时补做窗口；App 新设置默认本机 IANA 时区，已保存设置固定使用所选时区，旅行时不自行改变。时间使用项目已有 SDK 57 / DateTimePicker 9.1 的原生滚轮；时区在高级设置中更改。

自动安排保存一份已确认的简报兴趣、重点和来源快照。之后在上方修改普通简报偏好，不会悄悄扩大已委托的自动来源；页面显示“自动安排使用偏好版本 X”，新偏好保存后用户再保存自动安排即可更新。关闭安排不要求偏好版本仍相同。保存修改并未立即生成简报。

设置、时间规则和绑定 schedule 在同一个事务内更新，使用 revision CAS 与 request key/hash 回执。App 先持久化精确请求，结果未知沿用原编号；冲突保留输入，由用户读取最新设置后再核对。面板按完整 scope/credential 重挂，并检查父组件 isCurrent、账号删除围栏、AbortSignal，拒绝迟到响应。

## 执行与准确状态

复用 `ScheduleBook / ScheduleCoordinator` 和现有服务 tick，没有另起调度循环。`ScheduleBook.claim` 的 managed hook 只识别登记过的自动简报 schedule；其余普通安排原路径不变。到期领取事务同时建立当天回执、briefing 请求、唯一 schedule occurrence 任务与 immutable task owner，再由原 TaskService 启动模型。

- 手机或网页关闭不影响常驻服务；后台服务、执行引擎仍须在线。服务休眠期间不运行。
- 每个 owner + identity + 本地日期至多建立一次自动请求。设置变化、重启、并发领取或时区变化不会重复当天的自动生成。不同 owner 不共用当天状态。
- 同一 owner 当天已有手动简报时沿用其真实回执，即使它尚未开始或失败也不另开一份。“沿用”不等于生成完成；原请求若停在 reservation、尚未创建 task，应回原简报页面核对/重试原请求。
- 长时间离线后只考虑当天最近的到期时间，补做窗口内可补当天；已跨天或超过窗口记录 skipped。不会为积压的历史日期逐份生成。
- 夏令时不存在的钟点跳过；回拨重复钟点只触发第一次。沿用 existing `next_time` 的当地钟点计算。
- 关闭或改时间立即停止尚未派发的 draft 本轮。已经开始的本轮保留真实回执，可去任务页停止。生成失败/停止仍沿用普通 schedule reconcile 的暂停语义；设置页显示暂停，可核对后重新保存。
- 从普通定时管理更改其规则时，专用设置的 schedule revision 不再匹配，managed hook 暂停而不误用旧的自动授权。页面提示重新保存。
- 安静时段由已有通知发送管线处理，只延后通知；不会延后简报生成。此模块不新增推送、不索取通知权限。通知被关闭或不可用时仍可在简报页面查看。

最近回执最多返回七条，含本地日期、计划时区、设置版本、状态与真实 briefing 的 ID/日期/时区/版本/状态/task ID 摘要。没有把完整历史输出、来源内容或内部 owner 返回到设置页。图文 ready 仍要求原 BriefingBook 读到实际 artifact；仅模型文字完成为 text_only。

## Owner 与旧数据

`daily_briefings` 新增 nullable `owner_scope` 和 `direct_task_id`。新请求在任务创建之前就持久化可信 owner，避免预留阶段另一账户看到或接管请求。HTTP 从 trusted `pajio.storage_scope` 取 owner；云模式缺 scope 返回 401，显式 local_devices 参数防止漏边界时回退 local。

get/list 同时验证 briefing owner 和 task principal，task 可见性在列表 LIMIT 前过滤。request key 重放必须保持原 owner。submit_message 使用预留 owner；自动 schedule 的任务从 background principal 继承同一 owner。旧未绑定简报保留 legacy 可见语义，但重试不会借用现在打开的用户获得新授权；若旧记录实际关联有 owner 的 task，仍按该 task 隔离读取。

同一日期的版本号保持原表唯一约束，按身份内现有最大版本递增；不同 owner 可能看到不连续的版本号，但不能看到对方的内容、任务或来源。来源仍是当前身份的已保存 life/files 与显式选定连接，普通共享身份数据语义不变；元数据和备注不是新增执行指令。

## 模块、接线和生命周期

```python
briefings = install_briefing_routes(app, store, service, artifacts,
    cloud_apps=cloud_apps, local_devices=local_devices)
install_briefing_automation_routes(app, store, briefings, schedules,
    local_devices=local_devices)
```

`GET /api/briefing-automation` 只读当前账户配置/回执；`POST` 严格接收 enabled、local_time、timezone、grace_minutes、preferences_revision、revision、request_key，不接受 owner 或任意指令。grace 服务端允许 1–360 分钟，App 提供 30/60/120 分钟。

`BriefAutomationPanel` 已嵌入既有 `BriefPreferencesPanel`，`BriefPanel.isCurrent` 透传当前连接判定，无新 Mobile 路由。App 待确认请求键为 `briefing-automation-request:${scope}`，受现有精确账户缓存清理与围栏约束。

新增三表：产品设置 `briefing_automations`、日回执 `briefing_automation_days`、内部幂等表 `briefing_automation_requests`。产品字段导出已按可信 owner 精确过滤，并校验关联 schedule/task 可见性；请求 ledger 与 owner_scope 本身不导出。全专属 tenant 的实例/卷清理覆盖新表，共享 tenant 不以 identity 误删他人内容。

## 验证

本地合成：新增 13 个后端测试，连同手动简报、偏好和定时安排共 78 项；独立 DST 与导出审查追加 5 项，合跑 83 项通过。App 新增 9 项，与原简报/偏好共 23 项。覆盖 owner 预留、陌生账户请求和列表、legacy 不继承、原 scheduler 启动、并发领取、重启、跨日服务离线、grace、DST、偏好快照、关闭未派发轮次、修改后防重、storage 失败、旧请求恢复和账号切换/删除围栏。全 App TypeScript 与本次文件 ESLint 检查通过。

全部使用临时 SQLite、ASGI、合成 clock 和 NoNetworkHermes；没有调用真实模型、生成真实用户简报或发送真实通知。原生页面的候选包验收由 root 进行。本次未宣称实体手机弱网/通知到达验证。

原生选择器依据：[Expo SDK 57 DateTimePicker](https://docs.expo.dev/versions/v57.0.0/sdk/date-time-picker/) 与项目现有 wallClock / wallTimeToInstant 工具；未新增原生依赖。
