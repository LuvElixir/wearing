# 当前身份数据导出

`IdentityExports` 把当前身份在服务端保存的数据打包为 ZIP；不会删除、修改原记录，也不会创建模型调用、付款或向外发送消息。App 的“带走我的数据”由用户点击生成，再使用 iOS/Android 原生分享面板选择保存位置。

## 内容与边界

- `records.json`：身份基本资料、对话、任务及事件、目标/步骤/备注/更新、安排及执行记录、生活记录、采集结果、原件元数据、录音转写、已发布结果元数据、用户确认卡。采用显式列白名单，不导出 task payload、会话凭据、settings、OAuth token、设备密钥或提供商配置。
- `records.json.task_lists` 与 `task_list_members`：清单名称、归档状态、revision/时间，以及同身份清单和原生活记录双向可证实的 record_id/list_id/position；不导出内部 board/request 表。
- `records.json.calendar_series` 与 `calendar_exceptions`：当前身份重复日程的 template/rule、revision/删除时间，以及单次例外正文、取消状态和 revision；不展开成伪造的已保存事件，不导出 calendar_series_requests。
- `records.json.briefing_preferences`：当前身份实际保存的一份简报偏好（revision、interests、priorities、sources、max_items、updated_at）。没有保存时是空数组，不伪造一份已持久化的默认偏好；字段遵循现有闭集 schema 校验，不包含偏好保存请求日志。
- `records.json.briefing_automations` 与 `briefing_automation_days`：当前账户在该身份内保存的每日简报时间、时区、补做窗口、偏好快照和逐日执行回执；同时核对关联安排/任务可见性，不导出其他账户的配置、owner_scope 或内部请求 ledger。
- `records.json.record_reminders`：当前账户在该身份内为记录保存的提醒设置，仅包含 target_id、revision、enabled、advance_minutes、anchor_at、reason、updated_at。投递事件、请求 ledger、activation 和轮询时间等内部状态不包含。
- `records.json.workspace_text_versions`：最近已完成保存的文本文档恢复版本。包含 source_path、path、created_at、saved_at、save_mode、原正文的 size/SHA256、text_included 与 text。id 是身份与内部版本键的 SHA256，只用于识别导出版本，不是可直接调用恢复 API 的凭据。严格核对数据库身份、普通文档路径、完整保存回执和新字节摘要；恢复原文来自同一数据库快照，不依赖当前文件仍存在。未完成的保存意图、spec、请求键、完整 receipt、待写入 new_bytes 不导出。
- `memory/USER.md`、`memory/MEMORY.md`：该身份实际 Hermes home 中的两个记忆文件，不启动引擎。读取单份最多 64 KiB，停用记忆仍可带走原文。不存在的文件会列入说明。
- `media/`：在当前身份 `life_assets` 有归属证据的图片/音频，文件大小及 SHA256 必须与数据库一致。ZIP 使用服务器生成的 asset ID 文件名，显示名称保留在 JSON。
- `results/`：当前身份且关联该身份任务的已发布 HTML 原件，SHA256 校验后包含。HTML 属于用户内容，不被服务或 App 执行。
- `manifest.json`：各部分取样时间、文件 SHA256、工作区文件清单和明确遗漏原因。
- 工作区当前文件仅提供清单，不递归打包当前原件。已完成编辑的恢复原文属于用户数据，按上述规则另存于 records.json。隐藏项、配置/密钥文件名、证书、私钥和数据库文件不列入；符号链接、硬链接和非常规文件不读取。工作区当前文件可从原有文件页逐份导出。
- 手机尚未同步的数据不包含。App 显示待同步数量和同步记录入口。

这里是用户自己的内容副本；若用户曾在对话或文档中写入敏感信息，这些内容仍属于导出数据。凭据排除指服务保存的连接与运行凭据，不宣称对任意自由文本完成敏感信息识别。

## 一致性、限制与临时保留

所有关系记录和 HTML 原件来自同一个 SQLite 只读事务快照。记忆在之后逐文件打开，通过 descriptor/no-follow 路径约束、文件类型/链接数检查、读取前后 inode/size/mtime/ctime 比较保证该份文件稳定；媒体另有持久摘要证据。工作区清单是之后的有界观察。manifest 明示这三个时点，不声称全系统同时快照。

记录上限 8 MiB / 50,000 行，超过即返回 413，不悄悄截断记录。原件读取/打包最多 500 项；工作区清单最多 500 文件、2,000 次遍历、12 层。整个 ZIP 上限 15 MiB，原件占用预算达到上限后明确列出遗漏，完整原件元数据仍保留在 JSON。包内附 README。

新增两表各自有界：偏好最多 1 行 / 8 KiB；恢复版本最多最近 200 行，每份原/新文本最多 64 KiB，恢复原文合计最多 2 MiB。超过正文合计预算时保留该版本的路径、时间、大小和摘要，并置 `text_included=false,text=null`；不输出截断正文。更早版本、非法/超长记录与正文预算遗漏均明确写入 manifest.omitted；具体上限同时写入 manifest.limits。所有新增记录还必须服从整包 JSON 的 8 MiB / 50,000 行上限。

单 owner + 身份最多 3 份有效包，同运行服务最多 12 份。生成用进程锁串行，owner + 身份 + request_key 使网络重试幂等；份额达到上限时仍能取回已有包。同一份副本可重新打开分享面板。GET 清单允许离页/重进后找回未过期副本，不必再生成。

云端 owner 只取 gateway 验证后写入的可信 ASGI `pajio.storage_scope`，要求 64 位小写十六进制；云 worker 缺失或错误时所有导出 API 返回 401。公开请求头/body 不能指定 owner。临时导出包的列出、重试、详情与下载都同时匹配 owner 和身份；其他 owner 返回 404。owner/request_hash 不进入公开回执或 ZIP。有主任务及其对话、目标、安排、报告和发布结果按同一任务可见性规则投影；明确无主的旧任务仍沿用身份共享定义。生活记录、清单、重复日程、记忆和工作区仍是身份共享内容，不宣称整个身份的数据均按账户私有。旧包缺少任务可见性版本标记时不再提供读取/重试，等待原 TTL 清理；用户可重新生成经过过滤的副本。

服务保存到专属 `exports/`，目录 0700、文件 0600；下载有效期 30 分钟。过期下载返回 410。启动、生成/列清单及 `purge_expired()` 清理过期包；主应用轮询应定期调用清理。清理只操作匹配导出 ID 的文件，不操作业务数据。包和元数据保持同一 UUID，未完成写入在到期后清理。

App 下载需要当前连接凭据和身份头，拒绝重定向。核对 Content-Length、15 MiB 上限和 ZIP MIME 后计算 SHA256，与收据一致才把本地临时文件传给原生分享。临时文件在分享完成/取消/失败后清理。离页或切换身份会阻止后续分享；关闭分享面板不被报告为“已保存”。

## API 与挂载

必须安装在主应用现有 auth / identity / CSRF 中间件之后，不能独立公开运行。

```python
from wearing.identity_export import IdentityExports
from wearing.identity_export_api import install_identity_export_routes
exports = IdentityExports(store)
install_identity_export_routes(app, exports)
# Existing lifecycle poll, outside any business transaction:
await asyncio.to_thread(exports.purge_expired)
```

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | `/api/data-exports` | 当前身份有效副本收据列表 |
| POST | `/api/data-exports` | `{request_key}` 生成或取回同一请求副本，201 |
| GET | `/api/data-exports/{id}` | 当前身份收据；过期 410、其他身份 404 |
| GET | `/api/data-exports/{id}/file` | 校验后 ZIP bytes；no-store/nosniff |

Native `NativeDataPanel` props：`connection`、可选 `fetcher`（主应用传 `serviceFetch`）、`pendingCount`、`onSync`、`onFiles`。父容器负责标题/返回和导航。该页不承担注销、取消第三方授权、账户删除或所有设备数据清除，现有登录/连接入口继续处理退出。

## 验证证据

`tests/test_identity_export.py` 覆盖当前/非默认身份隔离、凭据列排除、真实 ZIP/摘要、链接与变更文件拒绝、同事务并发写一致性、过期清理、包大小上限、请求重试、容量上限、HTTP headers 和身份下载拒绝。`data-export.test.ts` 覆盖输入校验、身份/CSRF、下载约束、摘要失败阻止分享、分享失败重试、切换身份撤销分享、重新打开取回已有副本。`workspace-export.test.ts` 验证原生临时文件清理。

2026-10-08：`tests/test_identity_export_documents.py` 使用临时双身份、双 tenant Store、双 owner 验证简报偏好/真实编辑恢复数据，另测闭集列排除、未完成意图排除、路径和回执归属、无效/超大正文、历史与正文总量限制、整包行数限制、并发写期间恢复正文与回执同快照、local 旧包兼容、云可信 scope 与公开头/body 伪造拒绝。本轮这两份导出测试共 36 项通过；没有读取真实用户文档，没有真实云导出或原生保存验收。

以上使用临时目录与模拟分享，没有读取/导出真实用户内容，也没有向第三方发送文件。原生分享 API 对照 [Expo SDK 57 Sharing](https://docs.expo.dev/versions/v57.0.0/sdk/sharing/)；摘要 API 对照 [Expo SDK 57 Crypto](https://docs.expo.dev/versions/v57.0.0/sdk/crypto/)。需要候选二进制真机检验分享目标实际保存行为。

2026-10-08 清单/重复日程补充：`tests/test_task_list_data_lifecycle.py` 覆盖有界导出、身份双向关联、内部请求字段排除，以及临时专属账户的整 SQLite/索引/备份清除。后端账户清除沿用整体 tenant 资源证明，没有新增按猜测 owner 删业务行的机制。

2026-10-08 自动简报/提醒补充：`tests/test_briefing_automation_export_review.py` 与 `tests/test_record_reminder_review.py` 覆盖同身份不同 owner 的设置和日回执隔离、派生安排/任务归属、列白名单、内部投递/请求日志排除，以及隐藏记录不占导出预算。与现有提醒、通知、原生同步、生活记录、重复日程和导出测试合跑 186 项通过；全部使用临时合成数据。
