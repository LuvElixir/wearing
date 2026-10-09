# 定时意图与主动性：本轮验证

日期：2026-10-05。验证在本机进行，没有恢复云 VM；生活业务场景没有真实下单或付款。

## 当前结果

- 本地 `8765` 已运行新代码；Hermes Wearing profile v10 已加载，能力探测为 reachable，三项 schedule 工具实际注册成功。
- 真实用户安排列表仍为空。本轮自动测试和界面样例只写入隔离数据目录 `.wearing/qa/proactive-20261005/data`。
- UI 入口为“一起记着的 → 到时我来”。保留用户选定的折带 W 和既有 3D 角色资产。

## 验证证据

1. 首轮定时、目标、反馈、生活记录、profile 测试：78 passed。
2. 实际安装的 Hermes adapter、任务生命周期、租户 worker、远程 MCP 回归：37 passed。包含实际解释器启动与 life/schedule 工具发现，没有模拟该注册过程。
3. 增加定时任务不可自建子安排的测试后，定时与 profile 相关复验：22 passed。上述合计覆盖 116 个不同 Python 测试；不是 137 个不同测试。
4. 既有角色动效回归：1 个 Node 测试文件通过，涵盖切换、降级、无播放控件、连续循环等。
5. JS syntax check、`git diff --check` 通过。
6. 真实模型闭环：独立 Hermes home，仅共享已配置的模型凭据，启用隔离 life/schedule 连接器，不连接真实设备、文件或账户，也不复制聊天和记忆。通过自然语言创建单次安排；到真实约定时间由服务唤醒一次，最终“定时回来验收成功”写回隔离身份对话。结果：schedule finished、occurrence_count=1、conversation_delivery=1。回执在私有 QA 目录 `live-check.json`。
7. 浏览器真实操作：创建每周样例 → 打开详情 → 暂停后续 → 修改为周五 → 保存仍保持暂停。样例标题明确标为“验收样例”。桌面 1440×1000、手机 390×844 检查；临时 viewport 已恢复。
8. 当前正式页面刷新后可见新入口，真实数据没有测试安排。运行探测回执 `local-acceptance.json` 留在私有 QA 目录。

## 场景语义

- 时区、夏令时跳跃与回拨、无效日期；同请求并发创建、版本冲突、跨身份读写限制。
- 同一时间 occurrence 并发抢占只保留一个 task；重启只查询原运行，不重复提交。
- 电脑长期离线后跳过失效时机；离线前尚未提交的 draft 重试同一记录，到期失效。
- POST 结果不明保持 ambiguous；不会为下一周期复制未知副作用。
- 暂停/修改不冒充已终止在途操作；旧回执保持旧意图快照。
- 用户消息优先；单次安排完成后结束；严格 `[SILENT]` 不进入对话，但历史仍保留。

## 设计复核

Impeccable fresh-context reviewer：`disposition: ship`。四张桌面/手机表单及列表截图已检视；详情展开与错误视觉状态仅审阅源码，未声称全部视觉状态均已验收。无 material fixes。

设计 hook 的四个偏离均已修复：标题采用既有 17/20px 层级、字段 14px 圆角、边框使用现有 `--line`。

截图：`images/proactive-20261005/schedule-form-desktop.png`、`schedule-form-mobile.png`、`schedules-desktop.png`、`schedules-mobile.png`。正式空安排入口：`live-panel.png`，仅截面板，未包含用户历史对话。

## 未完成边界

本轮是时间唤醒通用层，不是完整自主生活管家。事件唤醒、按事项费用硬上限、可追溯且有时效的上下文、系统推送、完整网页/skills 能力供给、账单导入与真实支付交接仍在后续规划。它没有启用 Hermes 原生 Gateway cron，也没有添加固定生活业务 workflow。详见 `docs/personal-proactivity.md`。

日常身份隔离不等于独立租户 VM 隔离。当前单实例调度不会自动解决跨设备重放、外部业务 exactly-once 或多 worker 并发。
