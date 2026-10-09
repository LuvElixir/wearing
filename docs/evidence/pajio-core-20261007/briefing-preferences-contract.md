# 今天简报偏好与来源契约

2026-10-08。补充 [每日简报](briefings-contract.md)，供 ZCode 只读对齐 Web / Desktop。实现位于 `src/wearing/briefing_preferences.py`、`briefing_api.py` 和 `clients/mobile/src/BriefPreferencesPanel.tsx`、`briefing-preferences.ts`、`BriefPanel.tsx`。本轮只使用临时数据与合成回执，不代表真实模型生成、原生界面或供应商读取验收。

## 已实现的设置

设置按现有服务认证得到的当前身份保存，不接受请求体中的 identity / owner。偏好保存不创建任务，不连接云端应用，不申请手机权限。

| 字段 | 约束 / 默认 |
| --- | --- |
| `interests` | 0–8 个兴趣，每项去首尾空白后 1–60 字，不重复；默认空数组 |
| `priorities` | 关注重点，最多 1000 字；默认空串 |
| `sources` | 从 `event, task, note, files, feishu` 中选择 1–5 项，不重复；默认前四项，延续旧简报范围 |
| `max_items` | 首屏重点数量，整数 1–3；默认 3 |

`event` 指 Pajio 已保存日程，不表示手机系统日历已授权或已同步。飞书只有明确勾选才进入新简报的来源范围。

## HTTP 与版本

- `GET /api/briefings/preferences` 返回 `{preferences, available_sources}`。`preferences` 含上表字段以及 `schema:1, identity_id, revision, updated_at`；无历史设置时 revision 为 0、updated_at 为 null。
- `POST /api/briefings/preferences` 接收上表完整四字段，加 `revision`（读取到的非负整数）和 `request_key`（16–120 位英文、数字、连字符、下划线）。沿用现有身份认证、CSRF 和 Origin 边界。
- 保存使用同一事务中的 revision 比较与更新。新保存成功返回完整偏好、revision + 1 和原 `request_key`。同身份、同 key、相同规范化请求返回原回执，即使偏好之后又改过；同 key 不同内容或旧 revision 新 key 返回 409。
- SQLite 表为 `briefing_preferences` 和 `briefing_preference_requests`；旧简报表仅追加 `preferences` 快照列。旧行返回 `preferences:null`，旧生成请求省略新字段仍可重放。

挂载仍调用 `install_briefing_routes(app, store, service, artifacts, cloud_apps=cloud_apps)`，位于 `CloudApps` 实例创建之后。父任务已完成 `app.py` 接线。本轮未增加原生依赖或修改原生工程。

## 来源状态不等于读取成功

设置 GET 只检查当前身份的本地记录/文件可用性以及本地飞书授权账本，不向供应商发请求，不启动模型。设置响应不包含记录标题、文件路径、token 或账号字段；每项包含 `id,label,state,count,observed_at,truncated,selected`，飞书可额外返回已申请且授权的 `features`。

| 状态 | 含义 |
| --- | --- |
| `available` / `empty` | 本地保存资料当前有 / 无可用条目，计数可能是有上限的索引 |
| `failed` | 该项状态读取失败；其他来源可继续，服务异常路径不返回给用户 |
| `authorized` | 飞书账本显示 connected、未撤销、且 documents 或 calendar 功能既 requested 又 authorized；尚未证明读到了任何内容 |
| `not_connected` | 未满足上述授权条件，包括撤销中或已失效 |
| `unavailable` | 当前安装未传入连接账本读取器 |

新简报保存请求时仅收集所选来源索引，并将偏好和来源可用性固定为本版快照。生成提示要求模型实际只读已选来源、列出真正读取的来源/时间、分列失败或缺失部分、保留其他已读成果，不编造数据。模型调用仍由现有 `TaskService` 发起；真实读取和输出证据沿用 artifact 的 `sources` / `limitations`。

来源选择是本次整理请求的资料范围与提示约束，不是新增的工具权限沙箱。既有工具身份授权仍有效；本轮没有声称已经验证模型在真实供应商上的来源遵从性，也没有接入未实现的云端来源。

## 生成与刷新

`POST /api/briefings` 新增可选 `preferences_revision`。新 App 必须传当前读到的值。服务在预留简报版本的同一写事务中读取偏好并比较 revision；不一致返回 409，不悄悄改用另一版设置。

- 同一生成 key 优先返回原简报，偏好改变也不会重写原版。
- 同天还有未结束的版本时，偏好相同的点击仍合并；偏好不同返回 409，提示完成后按新偏好重新整理。
- 明确重新整理时继续传最新 `base_version`，完成旧版后新建的版本使用当前偏好。
- 设置“刷新偏好与来源”只读状态；简报“刷新”只读已有版本。只有用户点生成 / 重新整理才进入任务服务。

首屏最多 1–3 项，其余折叠，排序依据为截止时间、变化、用户关注重点及待决定事项。这是生成要求，真实 HTML 视觉与模型遵从仍须单独验收。

## App 与 ZCode 对齐

“今天 → 图文简报”内含原生偏好设置，可输入兴趣/关注重点、勾选来源、选择重点数量、保存、刷新。旧版简报显示自己的偏好版本；设置变化提示仅对下次生成生效。

App 在 SQLite `briefing-preference-request:${scopeOf(connection)}` 保存完整待提交请求，然后才发 HTTP。未知回执、重启、离开页面均保留同 body/key；严格核对身份、key、revision 和返回值后才清除。409 后提供“读取最新版本，保留我的输入”，明确读取最新状态后重新核对保存，禁止自动覆盖另一设备的设置。账户本地清理应包含这个 key 前缀；已向父任务提示。

页面按 endpoint / identity / credential 切换生命周期，忽略旧身份晚到的 UI 结果。对未确认的保存先提供取回原回执，不能直接改输入覆盖请求。来源失败和未连接保持可见，没有把状态改成成功来解锁按钮。

ZCode 只读上述协议与原生代码实现同样的字段、来源状态、未知回执和冲突恢复。不要把 GET 变为生成，不要把 `authorized` 写成“已读取”，不要新增假来源或自动连接。

## 验证

- `tests/test_briefings.py` + `tests/test_briefing_preferences.py`：30 passed，覆盖旧迁移/重放、并发 CAS、身份、CSRF、同 key 内容冲突、选择范围、部分失败、授权账本、生成快照以及完成后按新偏好重新生成。
- App `briefing.test.ts` + `briefing-preferences.test.ts`：14 passed，覆盖严格回执、持久化先于网络、写盘失败、不确定结果、重启重放、409 恢复、身份隔离、单次提交与旧字段兼容。
- App 全量 TypeScript 检查及本轮六个文件 ESLint 通过；无新原生库。UI 使用现有 React Native 控件与主题；SDK 基线为 [Expo SDK 57](https://docs.expo.dev/versions/v57.0.0/)。

上述验证未运行真实模型、未读取用户云端服务、未操作真实用户记录。真实源数据、部分供应商失败时的生成行为和手机设置页仍由主任务统一验收。
