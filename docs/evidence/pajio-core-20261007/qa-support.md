# 隔离 QA 服务扩展 / 2026-10-08

当前地址 `http://127.0.0.1:8891/`，最新进程 6448；保留目录 `/private/tmp/pajio-core-qa-jf1qwuko`。8765 运行实例未动（核验 PID 79991）。重启后须重新读取 `/api/bootstrap` 获取 CSRF。分页、导出与用量扩展见 `workspace-pages.md`。

最新诊断/搜索扩展：45 张既有表全部旧行保留，integrity_check=ok；备份 `before-diagnostics-search-1791428057.sqlite3`，证据 `diagnostics-search-restart.json`、`diagnostics-search-acceptance.json` 均在同一临时目录。

## 可验收接口

- `/api/diagnostics`：真实白名单诊断投影，`deployment=synthetic`、引擎`not_configured`，不调用实际引擎。
- `/api/search` 与 `/api/search/messages/{message_id}`：真实 SearchBook；关键词“搜索验收”返回问答和笔记，task过滤返回原任务，另一身份数据不混入。QA guard拒绝切到另一身份；业务级隔离另由行为测试覆盖。
- `/api/skills`、detail、install、enabled：真实 SkillLibrary，只有临时目录中的两个合成 SKILL.md；没有脚本或模型执行。
- `/api/memory` GET/PATCH：真实 memory_controls 校验 target/action/revision/index/capacity，文件锁和原子持久化的合成 storage adapter；支持添加、修改、删除、冲突与重启恢复。没有读取真实 Hermes 记忆，未宣称 fixture scanner 等同生产完整扫描器。
- `/api/cloud-apps/feishu` 配置/授权/查询/文档/日历/断开：真实业务路由、令牌交换与账本，HTTP 显式 MockTransport。模拟授权在返回前完成，不向 UI 返回可打开的外部 OAuth 地址。
- `/api/messaging` Telegram/飞书：真实验证/启用/停用/断开/版本冲突；合成网络及空接收器，不创建消息接收子进程。状态 listening 仅指模拟状态。
- `/api/notifications`：真实持久事件/outbox/登记/停用/resolve，模拟 Expo tickets/receipts。`POST /_qa/notifications/receipts`（须 CSRF）推进模拟 receipt，返回 `actual_device_delivery=false`。
- `/api/confirmations` 与 `/api/confirmations/{id}/resume`：同一 TaskService 和 DurableConfirmations，真实过期迁移/身份/版本/幂等/恢复队列。只 seed 一条独立过期合成卡，不改已有活跃任务。恢复始终 `authorized=false`，没有批准、重放或执行原操作。
- 当前合成恢复卡 ID：`decision_b93644991d435fe6ba53e790d24639f2`，符合真实 decision + 32 hex 契约；旧 fixture ID 已仅针对该合成卡迁移并保留引用。

合成凭据与项目 ID 在 `/_qa/manifest.synthetic_credentials`。只接受这些固定值，其余凭据被 422 拒绝；不要输入真实账号或密钥。模拟传输仅允许列出的路径，未知路径直接失败；没有读取凭据环境变量。请求审计不记录内容和密钥。

## 验证证据

- `tests/test_qa_support.py` 当前 13 项行为测试（此前支持扩展、分页/导出/用量、诊断/搜索）：技能复制与版本冲突、记忆 CRUD/重启、飞书模拟授权与只读资料、拒绝外部凭据、Telegram/飞书启停、推送 ticket/receipt/停用、identity/CSRF、确认恢复幂等、保留断开状态。测试封锁 socket.connect 和创建子进程。
- 本轮 QA13＋诊断8＋搜索8 共29项Python通过；诊断TS9项、相关lint、全App tsc通过。此前通知后端22与通知TS13项通过，分轮证据不冒充同一次全量执行。
- live GET bootstrap、skills、memory、cloud-apps/feishu、messaging、notifications/status、confirmations 均 200，并带 `X-Pajio-QA: synthetic-no-model`。
- 旧库 33 张已有表的全部原有行逐一比较仍在，SQLite integrity_check=ok。备份：`/private/tmp/pajio-core-qa-jf1qwuko/before-support-1791391452.sqlite3`。
- 重启与核对证据在临时目录 `support-restart.json`、`support-acceptance.json`；日志 `support-server.log`。

这只证明 UI/API 和合成传输闭环；不证明真实模型、ASR、外部授权、飞书长连接、消息投递、APNs/FCM 设备到达。
