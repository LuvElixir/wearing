# 记录变化主动唤醒：验收记录

日期：2026-10-05。本机开发与隔离样例验收；本轮未启动云 VM，未访问外部账户、下单或付款。

## 已接通

- `ScheduleDraft.kind=life_change`，复用 ScheduleBook / TaskService / Hermes 与原有 schedule MCP 工具。
- `schedule_events.py` 从同身份 life_changes 读取变化，保存游标、待处理批次、冻结回执。用户手动保存和真实对话代记可触发；后台结果不触发自己。来源由任务日志确定，不能由模型参数改写。
- 创建/编辑/恢复从当前日志位置开始；连续修改合并、等待媒体整理、单轮 50 条不同记录、剩余记录留后续批次；行动间隔与滚动 24 小时轮次限制。限制按预留轮次计数，不等于模型金额或 token 硬预算。
- 网页“一起记着的 → 到时我来 → 什么时候 → 记录有变化时”；来源范围与回应节奏可编辑，后台结果仍回原身份对话。

## 验证

1. **154 个不同 Python 测试通过**：schedule_events、schedules、life、capture、profile、goals、goal_updates、engine_integration、lifecycle、tenant_worker、remote_mcp。包含真实安装的引擎启动与工具发现测试。
2. 批量处理改为游标保留后，schedule_events + schedules **35 项复验通过**，是上述集合的复验，不额外计数。
3. 覆盖事件新旧边界、跨身份隔离、来源过滤、合并和最大等待窗口、并发 claim、服务重启、运行中收到新变化、批次冻结、暂停恢复、修改不重置计数、无内容变化保存、归档记录、50 条批量边界、媒体整理等待、结果不明不重发，以及旧时间安排格式兼容。
4. 真实模型第一次发现 MCP JSON Schema 嵌套 `$defs` 引用不可解析；将定义提升到整个工具 schema 根层后重跑成功，并增加 create/change 两个 schema 解析回归。
5. **真实模型闭环**：隔离 Hermes home，仅使用现有模型配置与 life/schedule 工具；不复制用户聊天、记忆或设备能力。模型在对话中建立“验收 · 灵感有新变化”；随后 API 新增测试笔记“想去泉州，待三天，慢慢走走”；服务自动唤醒，返回“地点是泉州，天数是三天”。回执为 `profile_version=11`、`occurrence_count=1`、`conversation_delivery=1`、`completed_unverified`。这个状态表示模型已回复，不代表外部业务经过核对。验收后暂停该样例。
6. 浏览器桌面 1440×1000 与窄屏 390×844：建立待办变化安排 → 暂停 → 修改为 60 分钟间隔 → 保存仍保持暂停。范围选择、节奏展开、详情与一次真实模型运行历史可见。窄屏文档宽度、面板宽度均为 390，无水平溢出。临时 viewport 已恢复，浏览器 error 日志为空。
7. Node 角色动效回归、JS syntax 与 `git diff --check` 通过。保持折带 W 与 3D 角色资产不变。
8. 当前 `8765` 已重新启动最终代码；runtime running、Hermes reachable、profile v11，六项 life/schedule 工具实际注册。真实用户安排数量仍为 0，测试数据全在隔离目录。正式页面已刷新并实际打开新表单，但未提交测试安排。

私有回执：`.wearing/qa/event-intentions-20261005/live-check.json`、`local-acceptance.json`；修改前 SQLite 备份 `before-event-intentions.sqlite3` 权限 0600。截图：`images/event-intentions-20261005/event-form-desktop.png`、`event-form-mobile.png`、`event-receipt.png`，均为隔离验收数据。正式页仅做 DOM/可见画面核对，没有保留用户历史对话截图。

## 设计与边界

沿用既有 Impeccable 设计语言，在原表单中按触发方式显示相关字段，主动作仍为“交给 Wearing”。高级响应节奏折叠；切换详情清除上一次保存提示。Hook 的既有 20px 详情标题提示按已记录的局部层级判为误报，不改变字体或加忽略配置。详见 `docs/design-schedules.md`。

本轮没有外部微信/支付宝/邮箱事件、系统推送、费用硬上限、GoalBook 事件关联或通用事件 Webhook。当前为单实例 SQLite，独立租户 VM 边界不变；事件去重不等于外部订单 exactly-once。服务需运行；超时批次会跳过，暂停期间的变化不会恢复补做。媒体整理完成后的自动写回不会单独唤醒第二轮。
