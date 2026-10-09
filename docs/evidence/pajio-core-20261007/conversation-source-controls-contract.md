# 对话引用范围 — App / API / 引擎合同（2026-10-08）

## 用户动作与真实范围

在记忆页进入「对话引用范围」，选择一整段连续会话 → 查看范围说明 → 点击「确认停止引用」。页面显示标题、开始时间、入场消息数、当前是否排除；分页每页 20 条，可继续加载。未获准归属的旧共享会话不显示为个人可操作来源。

确认后的效果：

- 当前 owner + identity 的所选会话根和所有压缩后继，不再进入 Agent 的关键词搜索、直接读取、邻近翻阅、最近会话列表。
- 这个人的后续聊天从全新会话上下文开始。已排队但未入场的消息在真正开始时重新绑定。
- 目标执行以前会直接注入原对话 prompt/output；现在同样核对来源设置，排除时不再注入这一 raw `source_conversation`。
- 用户仍能查看自己的历史；对话原文、FTS、备份、已经保存的记忆、文件、目标和报告不删除。其他对话中已有的转述/副本不做语义擦除，不声称彻底遗忘。
- 首版不提供恢复引用，避免一次误触重新纳入全部旧内容。确认前可取消；取消不发请求。

共享 identity 的 memory/workspace 语义保留。此功能不是终端/文件工具的逐 owner OS 沙箱，不能声称任意文件访问已被隔离。

## 挂载

```python
from wearing.conversation_sources import ConversationSources
from wearing.conversation_sources_api import install_conversation_source_routes
sources = ConversationSources(store)
install_conversation_source_routes(app, sources, local_devices=settings.local_devices)
```

`clients/mobile/src/ConversationSourcesPanel.tsx` default export，仅 prop `{connection: Connection}`，由根 Mobile 放入带返回按钮的滚动页面。入口由根 PersonalHub 接。无新增 native 依赖，无需另一个付费服务。

Web/Desktop 由 ZCode 只读此合同与 App 模型实现；不要改 App。

## API

身份由既有身份中间件决定；云端 owner 只读可信 ASGI `pajio.storage_scope`，不接收 JSON/header 中声明的 owner。本机明确使用 `local`。

`GET /api/conversation-sources?offset=0&limit=20`

返回 `identity_id, revision, snapshot, items, next_offset`。每项：

- `source_id`：`source_` + SHA-256 的不透明来源 ID。
- `source_revision`：本次已入场任务及 session 凭证成员的指纹。
- `source_task_id`：这一段中最早的可核对任务，可关联用户历史。
- `title, started_at, updated_at, message_count, excluded, excluded_at`。

后续页附同一 `snapshot`；列表成员、凭证或设置变更返回 409，需从第一页重新加载，不拼接不同快照。

`POST /api/conversation-sources/exclude` 闭集 body：

```json
{"source_id":"source_<64 hex>","source_revision":"<64 hex>","revision":0,"request_key":"<stable UUID>"}
```

成功回执：`identity_id, source_id, source_revision, revision=old+1, request_key, excluded=true, excluded_at, continuation_reset=true, history_retained=true`。同 owner/identity/key + 相同请求返回原始回执，即使后来已有新消息；同 key 改参数 409。旧设置 revision、来源成员发生变化或重复排除均 409；其他 owner/identity 来源 404。请求参数额外字段 422。

## 并发与运行事实

单个 `BEGIN IMMEDIATE` 内核对归属、两级 CAS、同 owner+identity 的 `starting/running/waiting_for_approval/stopping/connection_lost/ambiguous`。本机 local 还保守包含无 principal 的旧任务。存在这些状态时拒绝提交，用户先结束或核对原任务；不会自动终止任务，也不透露另一 owner 的运行内容。

同事务写入排除根、递增 policy generation、替换本人 canonical session、重绑本人排队 draft、持久完成回执。新入场在 `conversation_source_tasks` 记录 generation 与不可变 initial_session_id。存在来源 policy 时，每个目标/安排/独立任务也获得新的 engine session，防止复用旧目标的隐含 history；已保存目标报告仍保留。无 principal 的旧任务在 policy 后不能默认升级为 local，入场明确拒绝并保留草稿。晚到的旧 `sync_conversation_session` 无法改回 canonical。

`Service._start` 在构建 context 前读取 generation；`Store.reserve_start(..., source_generation=...)` 在最终入场事务再次比较。排除发生于 context 构建与入场之间时，旧 payload 不 dispatch，draft 留存，下一次需重建 context。

引擎 capability 升为 `wearing.session_recall_guard="sources-v1"`。存在来源设置时，旧引擎不允许开始新运行；不会因源代码存在就信任旧进程。四种模式共用同一允许集合，在返回前再次核对运行状态、generation 和范围。host 只信真实 `approval_context._approval_session_key` contextvar，不采用同名环境变量 fallback。未自动重启真实引擎。

## 持久与有界规则

新增 `conversation_source_state`、`conversation_source_exclusions`、`conversation_source_requests`、`conversation_source_tasks`。来源只保存 ID 和元数据，不复制对话正文。范围最大 10,000 条入场/展开会话，查询 2 秒预算；每 owner+identity 请求回执最大 10,000 项，超过后拒绝新操作，旧回执仍可取回。不会清除幂等日志再重用 key。

App 先把完整请求写入当前账户+身份 SQLite scope，再发送。网络未知/无法核对回执/本机回执事务失败保持同 key 待核对；按钮「取回原操作回执」重试原请求。已证明的 4xx 冲突保留为 rejected，必须重新读取、重新选定确认，不能静默变更 revision。切换账户取消请求；注销通用 key scope fence 拦截晚写。

身份导出仅包含本人 `conversation_source_exclusions` 的 `source_id, source_task_id, revision, created_at`；manifest 说明历史保留与此设置含义。不导出内部 session 根、generation、请求 hash/回执 journal。沿用导出的每表行数与包大小上限。专属 tenant 整体清除会覆盖 SQLite；不据此扩大共享 tenant 的清除权。

## 合成 QA 与验证

`tests/source_controls_qa_seed.py:seed(store)` 只接受 `/private/tmp/pajio-core-qa-jf1qwuko`，只在 `qa` 身份和 `identities/qa/hermes/state.db` 创建两个明确标注的合成已入场会话及 history 元数据；不写 daily 历史。历史路径经安全单段身份格式与 symlink 检查。不调用模型。root 可在其隔离 QA 启动脚本中调用。它不是实际 Hermes 运行或 native 成功证据，也不会改变真实 profile。

已执行：

- 来源专属 `tests/test_conversation_sources.py`：24 项通过，包含重启、相同 key 并发、双 owner/identity、所有活跃状态、压缩子链、未来压缩后继、四种 recall 模式、symlink、CAS、分页、排队/晚到回执、真正 Service context→reserve 竞态、旧引擎拒绝、新引擎允许、目标 raw source 和导出。
- 来源+来源独立 review+guard+独立 owner review+owner conversations+实际临时 engine integration+export+lifecycle+goals+schedules：142 项通过（10.22 秒）。独立来源 review 10 项证明目标新旧排队轮次不复用旧 engine history、新目标仍能读未排除来源、本机六类无归属活跃任务阻挡及旧无归属草稿不复活。
- message handoff/task visibility/export documents/reminder review/durable confirmations/cancel owner：89 项通过。
- App 来源 7 项 + 独立 body-arrival 身份切换/abort 2 项，共 9 项通过；提醒 8 项也通过。初始 effect 使用本次 abort fence 防 StrictMode 旧请求复活。整 App `tsc --noEmit` 通过；本包三个 owned TS/TSX 文件 ESLint 通过。
- Python compile、`git diff --check` 通过。全为临时/合成数据，没有真实模型调用、真实用户历史更改或通知投递。

App 原生入口挂线、独立复核和候选设备验收由 root 继续完成，不能把上述单元测试当作设备成功。
