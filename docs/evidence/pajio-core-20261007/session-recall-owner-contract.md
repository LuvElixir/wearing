# Agent 历史检索账户边界（2026-10-08）

## 实际修复

此前 App 的 task/message/search 已按账户限制，Hermes 当前聊天也有 `owner_conversations`；但原生 `session_search` 仍检索一个身份 Home 的整个 `state.db`。已用两个合成账户会话证明：关键词、直接读取、scroll、browse 均可能返回另一账户会话。

`src/wearing/session_recall_guard.py` 现在由 `engine_runner.main` 在服务开放前安装。替换的是 `tools.session_search_tool.session_search` 的进程内 callable，没有修改 pinned Hermes 文件。Hermes 的 inline executor 动态调用该 callable；注册工具的 handler 同样经它。只替换 registry 不足以覆盖 inline 路径，本包两者都测试。

## 可信输入与范围

- 配置：`HermesRuntime.env` 固定 `PAJIO_RECALL_DATA_DIR/IDENTITY/LOCAL`。host 在载入 provider dotenv 前捕获配置；缺少或格式不符会阻止引擎启动。安装还要求真实 task principal/会话入场表存在。
- 运行：读取 Hermes `approval_context._approval_session_key` contextvar 的真实 run ID，不采用环境变量 fallback；模型不能从工具参数指定 owner、run ID、数据目录或当前 Agent session。查询数据库路径只由 host 配置推导，不采用工具 kw `db` 的路径。
- 已知 run 必须属于当前 identity 且为 starting/running/waiting_for_approval。已停止、连接不确定等状态拒绝读取；不会借新 starting task 恢复旧 run 权限。
- `/runs` 回执写回前，仅允许唯一 starting/无 run ID 的 task，且当前 Agent session 必须匹配该 task 入场 session 或其获准的压缩后继。
- cloud 必须有真实 `task_principals` owner。会话白名单来自一致的 `task_conversation_sessions` 凭证与该 task 的入场 payload session；独立任务优先使用新的不可变 `conversation_source_tasks.initial_session_id` 入场证明，必须与 task 的冻结 payload、identity、owner 一致；没有新证明时只认可服务端生成的 `wearing-<task id>`，其余已观察 session 作为负面归属阻止误收。旧共享会话没有新凭证，不推定归属。冲突/其他身份/其他 owner 的证明阻断该 session 和分支。
- 允许原生压缩后继，但只从已确认归属的根向下展开；不向上采用旧共享父会话。已知外部账户或缺失证明的 task session 会阻断分支。
- local 模式必须由 host 明确启用，允许当前 identity Home 中既有本机会话；已有 cloud/其他 identity 归属证明仍排除。
- 所有模式都拒绝 `profile` 与嵌入 profile 的 session 路径。不把工具参数当授权。
- 返回前再次读取 task 权限和允许范围；停止/变更期间读出的内容不返回旧调用。

## 检索与读回

源数据库用 `mode=ro`、`query_only` 打开，不增加索引、不修改历史。查询先在 SQL 中联结会话白名单再做搜索/排序/limit。

支持原有四种调用形状：关键词搜索、session ID 读取、session ID + message ID 附近翻阅、无关键词的最近会话列表。scroll 锚点必须实际属于所选且获准的 session，不能传另一账户的 message ID。

搜索优先现有 FTS5；不可用、语法不兼容或无命中时使用同样白名单约束的字面包含匹配，并返回 `query_semantics`。不是语义搜索。当前会话从 browse/discover 排除，明确读取当前 session 仍需同样授权。

有界：10,000 条入场任务/会话上限，2 秒 SQLite 查询预算，关键词最多 600 字，结果最多 10 个 session；直接读取最多前 20 + 后 10 条（每条 2,000 字），scroll 最多前后各 20 条（每条 4,000 字）。超范围/错误返回通用失败，不回退未过滤的原工具。没有完整召回率保证。

capabilities 增加 `wearing.session_recall_guard = "sources-v1"`。来源排除的新增行为见 `conversation-source-controls-contract.md`。旧进程必须重启加载新 host；源代码存在不能证明旧进程已受保护。

## 验证与限制

`tests/test_session_recall_guard.py` 使用临时 wearing.sqlite3 与合成 Hermes 会话。覆盖两 owner 同 identity、直接/关键词/scroll/browse、伪造 profile/session/owner/run、无归属/缺入场凭证、旧共享会话、stopped run 对新 pending task、读中停止、压缩后继、跨身份证明、外部 db 参数、本机旧会话、字面中文及长度边界。独立 subprocess 使用已安装 pinned Hermes 的真实 inline 与 registry 入口，不发模型请求。

`tests/test_engine_integration.py` 实际启动临时 host，核对 guard capability、既有 memory 路由与工具发现。初始账户隔离包的专属 24 项通过；连同 engine integration、runtime、memory、memory controls、owner conversations、task visibility、cancel owner、durable confirmations、profile 共 91 项通过（9.72 秒）。仅合成数据，无真实模型请求。

此包只修复 Agent 历史检索工具隔离。既有 `USER.md/MEMORY.md` 与 workspace 仍是 identity 共享内容；文件、终端、设备工具没有因此获得逐 owner OS 沙箱。原始聊天、备份和已导出内容没有删除；不承诺完整遗忘。
