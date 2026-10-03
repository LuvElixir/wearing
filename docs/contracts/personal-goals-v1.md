# 持续目标契约 v1

当前作用域：单用户本地 Wearing 服务、现有身份分区。所有写接口沿用 CSRF token / Origin 检查，所有读写绑定 `X-Wearing-Identity`，不能跨身份访问目标。

| 接口 | 行为 |
| --- | --- |
| `GET /api/goals` | 当前身份的目标 |
| `POST /api/goals` | 创建暂停目标；objective、boundaries、success_criteria、max_steps（1–10）；可选同身份 source_task_id |
| `GET /api/goals/{id}` | 目标、用户补充、每轮任务、模型报告、人工核对记录 |
| `POST /api/goals/{id}/control` | 带 revision 执行 resume / pause / cancel / note / complete；revision 不符返回 409 |
| `POST /api/conversation` | content；可选 goal_id、goal_mode（discuss / note，默认 discuss）；note 需 goal_revision 和 3–2000 字补充 |
| `POST /api/tasks/{id}/cancel-message` | 仅取消尚为 draft 的已排队目标消息；原话和已保存的补充保留，重复或已送出返回 409 |

`note` 和 `complete` 需要至少 3 个非首尾空白字符；`add_steps` 仅可用于 resume，每次不超过 10，累计不超过 100。API 不允许模型报告改变目标范围、轮次或完成状态。创建接口始终暂停，启动必须独立调用 resume。

状态：paused、active、waiting、needs_user、needs_review、limited、completed、cancelled。用户修订导致 revision 增加、旧建议与唤醒清空。旧轮次回执可以保存，但不能覆盖新修订的方向或复活暂停/结束的目标。已结束目标不再修改，需要另记新目标。

报告结构：summary；evidence（observation + source）；unknowns；next_step；decision（continue / wait / needs_user / review）；wait_seconds（0–604800）。额外字段、超长字段与不支持的决策被拒绝，不从自由文本猜完成状态。

continue / wait 自动推进必须同时有下一步和至少一项报告依据，且有剩余轮次。wait=0 视为未知外部条件，交回用户。review 只转 needs_review。报告字段长度、格式检查不证明报告内容属实。

派发沿用 tasks / events 表；新增 personal_goals / goal_steps / goal_notes / goal_messages 表。每轮任务与额度在同一 SQLite 事务中预占。TaskService 通过数据库原子占用从 draft 转为 starting，同时检查已有 ACTIVE 任务；记录 idempotency key 后才发起 POST。连接异常不重发。恢复逻辑继续查询原 run_id；有不明运行时阻止新派发。

后台进展合并进 `/api/conversation`，kind 为 goal_step，不写成用户消息。目标详情保留模型原报告；主对话展示摘要、未知和下一步，不展示中间 JSON。

目标对话保留实际用户消息；GET 返回 goal_id / goal_title / goal_mode / queued。discuss 不改变目标和修订；note 的补充、修订、实际消息及目标关联在同一个事务提交，修订冲突整笔不写入。已结束目标可以讨论，不能通过 note 重新激活。来源 source_task_id 必须属于同一身份，执行时带入最多各 4000 字的原话及回应，回应仍保留原核验状态。

仅在提交时已有 ACTIVE 运行的关联消息明确排队；服务恢复后可继续。普通离线草稿不会自动送出，也会阻挡较后的同身份对话。排队草稿按原消息顺序发送，前置失败退避 60 秒，提交不明确后只核对原运行。修订发生在提交途中时，拿到旧 run_id 后也请求停止，等待原运行确认后才回复新消息。当前为单服务协调，尚无跨实例 exactly-once 保证。
