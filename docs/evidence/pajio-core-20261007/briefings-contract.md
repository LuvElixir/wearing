# 持久每日简报契约

2026-10-07。本文件描述已实现的 App / 服务接口。QA 合成回执只验证链路，不是模型能力或美术验收。

## 服务

入口：`install_briefing_routes(app, store, service, artifacts)`。注册在现有身份、认证与 CSRF 边界内；复用 `TaskService`、`message_handoffs` 和 `ArtifactBook`。

- `GET /api/briefings?date=2026-10-07&timezone=Asia%2FShanghai`：只读，返回身份、日期、时区、按版本倒序排列的 `items`（最多 30 版）。不会启动任务。
- `GET /api/briefings/{id}`：只读，返回某一版实时保存状态。仅当前身份可读。
- `POST /api/briefings`：`{date, timezone, request_key, base_version}`。首次 `base_version=0`；明确重新整理时传已看到的最新版本。

`request_key` 为 16–120 位英文、数字、下划线或连字符。必须在发出请求前持久化；未知结果重试使用原 key 和原 body。

相同 key 取回原版；同一天/同一时区尚未结束的多个点击合并到原版，各 key 都持久化为原版的回执。新版本使用乐观版本检查。每一版有唯一持久化的消息 request_id；重启、丢回复、重复点击均从 `message_handoffs` 找回同一个 task。未开始且未排队的旧 task 可显式继续；不会创建第二条消息。

状态：

| state | 原生文案 | 证据 |
| --- | --- | --- |
| not_started | 尚未开始 | 版本已保存；没有 task 或 task 仍为未排队 draft |
| queued | 已排队 | 真实 message handoff queued |
| running | 正在整理 | 真实 task starting/running |
| needs_attention | 需要查看进展 | 审批等待、停止中、连接丢失或不确定状态 |
| ready | 图文已生成 | task 已返回，且有该 task 实际发布的 artifact |
| text_only | 文字已返回，图文未交付 | task 已返回但没有 artifact |
| failed | 这次没有完成 | 真实 task failed，可能仍有部分输出 |
| stopped | 已停止 | 真实 task stopped/closed_by_user |

回执含 `id, identity_id, date, timezone, version, created_at, updated_at, state, task_id, task_status, output, error, delivery, sources, artifacts`。不暴露模型 payload、服务 request_id 或凭据。

`sources` 是提交时实际读取到的**可用性快照**，包括日程、待办、笔记、文件空间的计数、索引、观察时间和 available/empty/failed 状态。不是模型已阅读的证明。实际使用来源展示 artifact 的 `sources`；缺口展示 `limitations`，文件保存不等于内容/视觉核对通过。

## App

- `BriefPanel({connection,onTask,onArtifact,onBack?})`；TodayPanel 用 `onBriefing()` 打开，不再写聊天草稿。
- 日期用系统控件；已有版本直接读取；版本、真实任务、图文成果均可打开。
- 请求按 endpoint+identity 保存在原有 SQLite Store，收到严格核对的当前身份回执才清除。未知回执可跨页面/重启恢复。
- 前台有运行时每 5 秒读状态，失败 15 秒重试；后台停止轮询。
- 生成回执不确定时按钮取回同一次请求；revision 冲突不自动换版本再生成。

## 原生目标 / 定时

`OngoingPanel` 支持 `createRequest={id,title?,instruction?,repeat?,timezone?,time?,weekday?}`，仅预填；用户保存前不写入。`id` 每次推荐点击换新值。

- 目标：明确名称、要求、边界、完成标准、1–1000 整数轮次；保存后进入真实详情，再由“开始推进”启动。POST `/api/goals` 使用 `request_key`。
- 定时：一次/每天/每周、系统日期时间、明确 IANA 时区；POST `/api/schedules` 使用原有 `request_key`。修改 PATCH 使用完整 schedule 与当前 revision。
- 高级 cron / 记录变化规则默认保留，不悄悄改成每天；隐藏的宽限时间、debounce、cooldown、关联 goal 原样保留。
- 夏令时不存在/重复的单次时间拒绝提交；周期按当地钟点执行。
- 单次未知回执持久化原 body/key；编辑冲突先读最新状态保留草稿，由用户再次保存。

## QA

隔离 `127.0.0.1:8891` / identity `qa`。生产数据库与运行服务未改动。

`qa-server.py` 支持只恢复自身 `/tmp/pajio-core-qa-*` 合成目录的 `--resume-root`，不重新播种。文件导入、records、goals、schedules、briefings、artifacts 使用真实存储契约；briefing task client 无网络能力，生成的 HTML 和输出显著标注 QA。已有 QA task 占用时真实排队，用户在测试界面停止它后继续 QA brief。审计 `requests.jsonl` 只保存接口、方法、状态、动作/版本与字段名。

验证：11 个独立 backend briefing tests；6 个 App briefing 协议测试；23 个目标/定时协议测试；2 个既有面板 API 测试。额外隔离临时目录通过创建→排队→结束前项→合成 artifact→重开→幂等回执。真实模型生成、真机视觉仍需另行验收。
