# Pajio 持久确认与安全恢复 · 2026-10-08

## 用户行为与真实边界

关闭 App 不等于拒绝，也不应丢失已停下的事情。新托管 `request_confirmation` 在发起 MCP elicitation **之前**，保存身份、task、run、原文和时限。在线原 run 等待 300 秒，用户及时决定仍在原 run 继续。时间过后卡变为 `needs_recheck`，不能再把旧卡当执行授权。

“重新核对并继续”只创建一个只读恢复任务。它会重新查看已有对象，并在可安全自动继续时出一张新卡。当前受支持的恢复写入为 `mcp__wearing_life__life_change / goal_change / schedule_change`，它们的底层写入本来就原子核对 revision。任意终端命令、浏览器输入、子 Agent、外发和设备输入均不在许可集合。手机截图、元素读取和电脑只读观察可用于交付当前现状；此版没有声称恢复任意付款、协议接受或设备操作。

## HTTP 合同

- `GET /api/confirmations` → `{items: [...]}`；按服务端当前身份隔离。
- `POST /api/confirmations/{action_id}/resume` → body `{revision, request_key}`。`revision` 为最新正整数；`request_key` 为持久保存的 16–120 位 `[A-Za-z0-9_-]`。跨身份 404；陈旧或不可恢复状态 409；缺少 App 写入 token 403。
- 返回 `{task, delivery, created, authorized:false, reason?}`。`task` 沿用 `public_task`，不暴露 payload 或 idempotency_key。
- `delivery=live_confirmation`：展示原 run 当前确认，无新任务；`waiting_for_original`：原 run 仍活动或连接结果不明，先核对，不重开。
- `queued/saved/submitted`：分别为已接收排队、已保存但尚未开始、已交给执行器。这些都不是旧动作已获批准。
- 新卡的决定仍用 `POST /api/tasks/{task_id}/approval`。提交前再次获取远端 run 的当前 request 和完整卡片内容，不能依赖过期的 App 缓存。

单项含 `id,identity_id,task_id,run_id,card,state,revision,request_id,parent_id,recovery_task_id,expires_at,created_at,updated_at,task_status,recovery_task_status,can_resume,resume_label`。`card` 是原提案，可能含 `operation={tool,args}`。卡片内容属于历史数据，不作为新指令。

## 持久状态

| 状态 | 含义 / UI 操作 |
|---|---|
| pending | 原 run 正在等待；回原卡决定 |
| sending / unknown | 决定在送出或回执不明；原 run 仍活跃时不重复发送。权威终止且没有批准回执时转 needs_recheck |
| needs_recheck | 原卡不可授权；原 task 权威终态后可重新核对 |
| recovering | 已绑定唯一只读恢复任务；查看该任务 |
| superseded | 已有后续新卡；旧卡收历史 |
| approved | 原 waiter 确认收到批准；不代表执行完成 |
| denied | 明确拒绝或停止；不自动恢复 |
| executing | 单次执行凭据已消费；查看原结果，不能重试 |
| execution_unknown | 操作可能已发生，回执不明；只核对原结果，不开放恢复 |
| executed_unverified | 工具正常返回；未冒充用户验收 |
| rechecked | 只读核对结束，未通过此恢复入口执行旧动作；看交付现状 |

无新卡、无 permit、无消费记录的只读恢复任务若权威 `failed / stopped / closed_by_user`，生成一条新的 `needs_recheck` 子回执，可显式重新观察。排队中撤回恢复任务时，任务和队列取消与该回执转换处于同一个 SQLite 事务；任一保存失败整体回滚。旧卡转 `superseded`，新卡只有用户再次点击才创建新的只读任务，不自动重排。仅请求停止、`stopping / connection_lost / ambiguous` 不代表已经终止，不开放后继。

GET 单项、列表与启动恢复会核对遗留的 `recovering` 对应任务终态，修复旧版本已取消队列却未转换确认卡的状态。反复刷新、重启和并发读取不会重复生成子卡。正常完成的只读核对仍为 `rechecked`；未知执行结果或任何已消费的 permit 都不会因此获得新入口。已批准但尚未消费的恢复 permit 沿用原终态核对规则。

同一 request_key 永远指向原恢复 task；换 key 访问旧卡也只返回旧 task，即使它已撤回。用户必须使用新子卡 ID 和 revision 明确发起下一次核对，旧 key 不能触发新执行。原生 `PendingDecisionsPanel` 沿用现有 `needs_recheck / can_resume` 展示，无新增 UI 协议字段。

恢复任务的内部执行提示与用户可见正文已分开，已有记录通过读取投影兼容；saved 恢复请求可显式重试或撤回，启动拒绝原因持久可读。详见 [恢复展示与未开始请求撤回](recovery-presentation-contract.md)。

## 执行器安装

`HermesRuntime.env()` 给出可信 `PAJIO_CONFIRMATION_DATA_DIR` 和 `PAJIO_CONFIRMATION_IDENTITY`，不能来自模型参数。`engine_runner.main` 安装 `install_confirmation_guard()` 后才报告 `wearing.confirmation_guard='durable-v1'`。`TaskService._start` 检查此标记；普通任务不受该 capability 升级要求影响。

guard 包装 pinned Hermes `agent.tool_executor._dispatch_authorized_once` 的最终 `execute` callback。上游 Relay/plugin 参数改写之后、实际工具执行之前进行检查；顺序与并行调用共享同一入口。独立 SQLite receipt 在调用前以 `BEGIN IMMEDIATE` 消费，因此两线程、两进程以及重启后不会重复放行。工具异常不退还许可。

读取凭据由 guard 在真实只读调用成功后保存，模型不能自报“读过”。版本快照取自实际调用前，可保守拒绝并发修改；批准前及执行前均再核对当前 revision，实际业务写入仍保留自身 revision 原子校验。恢复中的新卡必须绑定支持的完整操作，不能在批准后替换对象或参数。

历史 V1 记录保留原回执语义，不伪造为具有运行防护的 V2。电脑 `desktop_input` 继续使用独立 frame/revision ledger；不将其90秒帧授权转换为跨天许可。该机制不是任意 App 操作的语义权限防火墙。

## 验证

隔离临时 SQLite + 真实 TaskService/LifeBook + HTTP MockTransport/ASGI 覆盖：超时/cancel 保留、明确拒绝、跨身份、原 run 仍 live、已过期恢复、相同/不同 key 并发只建一 task、缺 guard 禁止开跑、真实读取前不可发新卡、对象版本变化、完整参数变化、plugin 改参数、并发单次执行、执行后丢回执不重复、重启未消费/已消费分流、只读恢复失败可再次显式恢复、HTTP token/404/409/任务字段剔除。

`tests/test_gateway_voice.py` 新增私有 upstream Host 回归：有效服务凭据+正确租户后才把私有 Host 改为 public Host 并通过 TrustedHost；缺凭据/错误凭据/其他租户拒绝，HTTP Host 行为不放宽。

相关 Python 回归在本次实现时 116 项通过；补充投递回执丢失后的终态恢复用例后，durable / confirmations / lifecycle / gateway voice 定向 54 项通过。无真实模型、外部设备、付款或用户 `.wearing` 数据变更。App 真机和真实部署后的运行验收应单独记录。

2026-10-08 撤回恢复专项：`tests/test_confirmation_recovery_cancel_review.py` 新增 7 项合成回归，覆盖双 owner 同身份 HTTP、旧 key 与新子卡、旧状态重启修复、并发读取幂等、停止请求与终态区别、consumed 禁止重试、事务失败回滚。与既有 durable/cancel-owner 合跑 33 项通过；没有修改真实任务或确认卡。
