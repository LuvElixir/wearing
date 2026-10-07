# 持续目标契约 v1

当前作用域：单实例 Wearing 服务（本地或每租户独立 VM）、现有身份分区。所有写接口沿用 CSRF token / Origin 检查，所有读写绑定 `X-Wearing-Identity`，不能跨身份访问目标。

| 接口 | 行为 |
| --- | --- |
| `GET /api/goals` | 当前身份的目标 |
| `GET /api/goal-updates` | 当前身份未读数量与最近 20 条反馈；读取不自动标记已读 |
| `POST /api/goal-updates/seen` | 明确的 1–100 个正整数 ID；只标记这些记录，跨身份或未知 ID 整笔拒绝，重复请求幂等 |
| `POST /api/goals` | 创建暂停目标；objective、boundaries、success_criteria、max_steps（默认 100，范围 1–1000）；可选同身份 source_task_id |
| `GET /api/goals/{id}` | 目标、用户补充、每轮任务、模型报告、人工核对记录 |
| `POST /api/goals/{id}/control` | 带 revision 执行 resume / pause / cancel / note / complete；revision 不符返回 409 |
| `POST /api/conversation` | content；可选 goal_id、goal_mode（discuss / note，默认 discuss）；note 需 goal_revision 和 3–2000 字补充 |
| `POST /api/tasks/{id}/cancel-message` | 仅取消尚为 draft 的已排队目标消息；原话和已保存的补充保留，重复或已送出返回 409 |

`note` 和 `complete` 需要至少 3 个非首尾空白字符；`add_steps` 仅可用于 resume，累计不超过 1000；网页每次补充最多 100 轮，到累计上限前补足剩余空间。API 不允许模型报告改变目标范围、轮次或完成状态。创建接口始终暂停，启动必须独立调用 resume。

`GET /api/bootstrap` 返回 `goal_policy`，统一告知默认 100、上限 1000、网页补充 100。既有目标保留原额度；不因升级自动启动或增加。轮次并非金额硬预算。

状态：paused、active、waiting、needs_user、needs_review、limited、completed、cancelled。用户修订导致 revision 增加、旧建议与唤醒清空。旧轮次回执可以保存，但不能覆盖新修订的方向或复活暂停/结束的目标。已结束目标不再修改，需要另记新目标。

报告结构：summary；evidence（observation + source）；unknowns；next_step；decision（continue / wait / needs_user / review）；wait_seconds（0–604800）。额外字段、超长字段与不支持的决策被拒绝，不从自由文本猜完成状态。

continue / wait 自动推进必须同时有下一步和至少一项报告依据，且有剩余轮次。wait=0 仅在已有有效记录变化安排时保持等待；无明确唤醒条件时交回用户。review 只转 needs_review。报告字段长度、格式检查不证明报告内容属实。

派发沿用 tasks / events 表；新增 personal_goals / goal_steps / goal_notes / goal_messages / goal_updates / goal_requests / goal_changes 表。每轮任务与额度在同一 SQLite 事务中预占。反馈以 task_id 唯一，与收取报告、processed 标记和目标状态同一事务保存；过时修订不会产生当前方向的提醒。已读只改变 seen_at，不修改目标或任务核验状态，不新增运行。TaskService 通过数据库原子占用从 draft 转为 starting，同时检查已有 ACTIVE 任务；记录 idempotency key 后才发起 POST。连接异常不重发。恢复逻辑继续查询原 run_id；有不明运行时阻止新派发。

后台进展合并进 `/api/conversation`，kind 为 goal_step，不写成用户消息。目标详情保留模型原报告；主对话展示摘要、未知和下一步，不展示中间 JSON。

目标对话保留实际用户消息；GET 返回 goal_id / goal_title / goal_mode / queued。discuss 不改变目标和修订；note 的补充、修订、实际消息及目标关联在同一个事务提交，修订冲突整笔不写入。已结束目标可以讨论，不能通过 note 重新激活。来源 source_task_id 必须属于同一身份，执行时带入最多各 4000 字的原话及回应，回应仍保留原核验状态。

仅在提交时已有 ACTIVE 运行的关联消息明确排队；服务恢复后可继续。普通离线草稿不会自动送出，也会阻挡较后的同身份对话。排队草稿按原消息顺序发送，前置失败退避 60 秒，提交不明确后只核对原运行。修订发生在提交途中时，拿到旧 run_id 后也请求停止，等待原运行确认后才回复新消息。当前为单服务协调，尚无跨实例 exactly-once 保证。

## 对话委托工具 · profile v21

MCP `goal_create` 接收 `goal`（objective、boundaries、success_criteria、max_steps，默认 100，上限 1000；start，默认 false）和 `request_key`。运行身份由连接器启动参数固定，来源从事务内唯一活动任务及真实 messages 记录取得；工具参数不能指定身份或来源。仅普通用户对话的 starting/running 可创建；无对话、停止中、来源含糊、多运行、跨身份、后台安排和已有目标讨论均拒绝。语义上的持续执行授权由 Agent 依据用户原话判断，工程检查不等于已形式化验证所有语义授权。

目标和 `goal_requests` 回执在同一事务提交；回执按身份和 request_key 唯一，原始规格不同则拒绝。同轮完全相同规格即使更换 key 也复用目标。重试只返回当前状态，不重新启动、加轮或覆盖。start=true 创建 active 目标，既有调度器等本轮对话终止后处理；start=false 保存 paused。不改变 HTTP 创建始终暂停的契约，也不改变暂停、完成、审批、额度和模型报告核验机制。

`goal_list` 可选 goal_id 读取本身份目标详情；普通列表保留原结构。`life_records/create/change` 的模型回执去掉与记录类型无关的默认字段（例如笔记上的 Todo 列表名），canonical 记录和客户端 API 保持兼容。

## 对话调整原目标 · profile v23

MCP `goal_change` 支持 pause / resume / cancel / revise / note。必须提供目标 ID、最新 revision 和稳定 request_key；revise 的 patch 仅允许 objective、boundaries、success_criteria，只修改传入字段。暂停目标修改后保持暂停；active 目标修改后按新修订继续；waiting / needs_user / needs_review / limited 的补充或修订先转暂停，明确继续再 resume。note 需具体内容。add_steps 仅在 resume 使用，累计仍不超过 1000；工具不支持 complete，阶段完成仍需用户核对。

仅事务内唯一、同身份 starting/running 的真实用户消息可调整目标。普通对话与当前目标关联讨论可用，关联讨论不能修改其他目标；goal_steps 与 schedule_occurrences 即使误关联 messages 也拒绝。来源从任务账本取得，不允许模型传身份或来源。用户语义授权仍由模型判断，这些检查不声称能替代语义权限判断。

调整、旧计划/事件失效、旧 draft 步骤停止及 goal_changes 回执原子提交。request_key 的重复返回目标当前状态，不重放操作；同轮相同规格换 key 也不会重复。目标已经由用户手动暂停时，重试 resume 不会复活或再次加轮次。旧 revision 的运行报告不能覆盖新的约定，已有报告与用户补充保留。

真实模型已验收：修改暂停目标 → 对话继续 → 既有执行器按新方向完成一轮 → 对话暂停且保留结果。服务仍使用单活动运行；这项能力在当前用户对话获得运行后生效，不能承诺聊天会即时打断正在执行的后台目标。需要立即停止时，现有停止/暂停入口继续可用。跨天决策恢复和独立的打断通道另行建设。
