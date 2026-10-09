# 恢复请求的用户展示与未开始请求撤回 · 2026-10-08

## 用户流程

点击确认卡的“重新核对并继续”后，对话和任务详情显示 `重新核对：{提案标题}`。引擎收到的只读核对约束、旧提案内容和再次批准要求完整保留在 `tasks.prompt`，不作为用户聊天正文展示。

若执行端尚未支持安全恢复，任务仍为 `draft`，显示具体未开始原因。App 详情提供“重新核对”和“撤回这次请求”，两者均需明确确认；重新核对使用原任务，不创建第二个恢复任务。排队、未提交、运行状态不明分别保留原语义，刷新不触发开始。

## 公共读取契约

- `GET /api/tasks`、单项详情、任务操作回执和 confirmation resume 回执统一经过带 Store 的任务展示层。恢复任务的 `title/prompt` 为用户语义，新增 `message_kind: confirmation_recovery`。普通任务和普通聊天不按关键词过滤，正文原样保留。
- `GET /api/conversation` 的对应消息 `content` 同样投影，并带 `kind: confirmation_recovery`。通过 `confirmation_recovery_tasks → durable_confirmations` 的真实账本识别，不用 prompt 前缀猜测。已有内部正文的恢复记录不改写原件，仍获得相同展示。
- 进展摘要、搜索结果、单条对话搜索读取、对话引用范围标题和身份导出也使用相同恢复标签。搜索在匹配前替换内部文本，因此输入内部工具名不会搜到恢复提示。来源卡损坏、缺失或身份不匹配时仅用通用“重新核对之前暂停的事情”。
- 任务公开回执新增 `can_cancel:boolean`、`can_retry:boolean`、`blocked_reason:string|null`。App 必须使用回执，不能把任意 draft 当作可撤回/可开始。旧服务仅有 `queued=true` 的排队撤回保持兼容；旧服务缺少 saved 能力字段不开放新操作。
- 启动拒绝原因写入该消息的 `message_handoffs.blocked_reason`，只影响仍未入场的 saved 任务；不把离线草稿转成自动队列。成功入场清除此原因。老记录没有保留过原因时不编造历史失败原因。

公开任务不再透传 `error`。已知执行上限由服务端受控 `failure_code: execution_limit` 表示，App 映射固定说明，保留已返回结果并说明任务尚未完成；未知类型仍显示通用失败说明。该代码仅来自服务端既有受控执行上限判定，不从模型任意文字推断。

## 撤回和重试边界

- `POST /api/tasks/{id}/cancel-message` 沿用接口。服务在锁与同一 SQLite 写事务内再次检查可信账户、身份、消息回执与 task；只允许 saved / queued / blocked 未入场消息，要求 `status=draft` 且 `run_id/payload/idempotency_key` 均为 SQL NULL。云端不认领缺 principal 的旧 saved 消息；明确本机模式保留旧本机数据兼容。
- 撤回把任务和消息回执一起改为 stopped/cancelled，并在同事务观察恢复确认卡。任何一步失败整体回滚。已撤回任务重复请求只回原任务，不重复追加事件或后继确认卡。其他终态、已入场或状态不明均不可按草稿撤回。
- `POST /api/tasks/{id}/start` 为显式重试。App 提交前重新读取同一 task 的 run_id 与 `can_retry`，提交后再读；响应丢失仅提示重读，不自动重试。服务仍经过现有安全恢复能力、来源代数和原子入场检查。另一进程先撤回，则后续入场失败，不向执行端发送。
- 旧恢复 request_key 永远返回原 task；撤回后旧 key 不能复活它。原恢复没有提案/permit/消费记录时产生新的待核对子卡，只有再次明确选择该子卡才能开始下一次核对。没有自动批准、操作重放或清除原话。

## 文件与接入

新增 `src/wearing/task_presentation.py`；窄改 `durable_confirmations.py`、`store.py`、`service.py`、`app.py`、`activity.py`、`search.py`、`identity_export.py`、`conversation_sources.py`。App 仅改 `TaskDetailPanel.tsx`、`task-detail.ts` 与其测试，无依赖、原生配置或 Mobile 根路由变化。

Web/Desktop 由 ZCode 接续：读取 `kind/message_kind` 与上述能力字段，恢复请求用“重新核对”代替通用“继续这句话”；展示 blocked_reason，saved 的撤回走同一端点。不得显示内部执行 prompt，也不得将恢复点击解释为批准旧提案。现有 API 投影已先修复聊天正文与任务标题。

QA `FixtureBriefClient.probe` 显式声明合成 `durable-v1 / sources-v1`，`start` 仅返回本地合成运行编号，未调用模型或外部工具；QA 任务路由支持显式重试。该声明不是实际 Hermes 引擎能力验收。本次未操作现有 QA 数据，须由根任务重启 QA 服务、同步 App 源码并重新构建后验收。

## 验证

- `tests/test_recovery_presentation.py` 13 项：新旧恢复文本、普通历史不变、双 owner、HTTP/进展/搜索/导出投影、缺能力原因持久、显式重试原内部 prompt、saved 撤回与旧 key、旧无归属云端拒绝、跨 worker 撤回/入场竞态、已入场和异常 draft 拒绝、损坏/跨身份来源通用展示、固定失败枚举不透传原错误。
- 连同 durable、撤回评审、消息队列、activity、search、owner 可见性、身份导出、来源控制/独立评审及 lifecycle / 合成 QA 共 **228 项 Python 测试通过**。
- `task-detail.test.ts` **15 项通过**，新增 saved 能力真值、原任务重试、入场后拒绝控制、撤回丢回执只读恢复、已知执行上限说明。全 App `tsc --noEmit` 与上述三文件 ESLint 通过。
- Python 编译与 `git diff --check` 通过。以上仅合成数据库和 MockTransport/ASGI 证据，未调用真实模型或更改真实用户内容；原生新流程验收单列。

独立只读复核（安全失败枚举追加前）覆盖 160 项 Python 和当时 14 项 App 测试：未发现普通聊天误替换、owner 越界、撤回复活、已入场撤回或恢复授权绕过。复核提出的执行上限说明缺口已按上述安全枚举补入，本包最终测试数见上。
