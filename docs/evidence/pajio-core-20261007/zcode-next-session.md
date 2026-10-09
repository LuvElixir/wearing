# ZCode Web/Desktop 下一会话交接 · 2026-10-09（第二十二轮后更新）

作者：ZCode（Web/Desktop 负责人）。App/backend 只读不变；QA 8891（合成数据）是唯一验收环境；8765 不动；不真实注销/推送/模型/部署。

## 第二十轮状态（2026-10-08，已完成）

- **链接收藏**（bookmarks-contract）Web 已 QA 实证（2026-10-08，PID81367）：列表/搜索/伪协议拒绝/新建默认标题=主机名/409 读最新保留输入/归档→恢复 rev3→4/url=null 移除收藏属性仍保留 note/「打开网页」noopener 实开。修复成功提示被 refresh 清空的顺序 bug（bookmarks.js v3）。
- **对话引用范围** Web 已完成列表、预览、取消零 POST；随后经 root 指定对合成「来源范围2」完成两击确认排除，revision 1→2，历史经 API 与 UI 核验仍保留。合成「来源范围1」由 App 验收。详见下方第二十一轮补验。
- 系列 request_key 已从单槽改为**多槽账本**（slot=action:series|new:occurrence；同意图沿用原 key 重放；管理/编辑器/实例三入口各自恢复；旧单槽键一次性迁移）。

## 第二十一轮状态（2026-10-08，已完成）

recovery-presentation-contract Web 侧已交付并 QA 实证（改动收敛在 app.js v48；详见矩阵第二十一轮）：

1. ✅ 恢复消息按 kind/message_kind 显示「重新核对」+「不会直接执行原提案」说明 + blocked_reason。
2. ✅ can_retry/can_cancel 只信任务回执（旧服务缺字段沿用旧语义；saved 撤回是新操作仅 true 开放）。
3. ✅ 显式重试：两击确认 + 提交前重读 can_retry + POST start 原任务 + 响应丢失只提示重读。
4. ✅ failure_code=execution_limit 固定文案（与后端同文），全模块不再透传 turn.error。
5. ✅ saved 撤回闭环（同 cancel-message 端点；取消后账本生成新 needs_recheck 子卡）。

遗留：①成功 start 转 running 已由 App 同任务 retry 验证（root 报告，705195…）；②execution_limit 文案已补验完成（root 加合成任务 7fcb4e28…：failed+execution_limit、error 不透传、固定说明+保留结果渲染，截图 `round21-execution-limit.png`）。**「来源范围2」排除验收已完成**（root 授权）：前置核验无活动任务→两击零请求→POST exclude→revision 1→2→面板已停止引用→**历史仍可查看（API+UI 双核验）**；「来源范围1」归 App。

### 后续（未开始）

- **密码管理器**：root 设计文档 `docs/plans/pajio-private-credentials-2026-10-08.md`（用户需求，尚未实现）。合同冻结且后端路由就绪前，Web/桌面不做入口、不做假可用占位。

## 第二十三轮状态（2026-10-09，已完成）

选定聊天导入 Web 侧**源码冻结于 chat-import.js v6（四批复核全修＋两处显示收尾；root 桌面 CUA 闭环已通过，批次 chi_93944870… 全链）**：两批复核全修（P1×2 异步边界写越权＋P2×2 size 预检/可验证删除＋接线三修）；全套 223/223；QA 8892 浏览器全链验收并清理自建批次（含关闭真实点击与超大 File 预检复验）；桌面文件选择/确认/删除由 root CUA 接手（root 已完成 iOS 原生两条点击链）。私密远控未实现未提供入口。详见 docs/evidence/pajio-context-20261009/zcode-delivery.md。

## 第二十二轮状态（2026-10-09，已完成）

onboarding Web/桌面已交付至修复终版（独立复核两批共 12 项问题全修＋面板交接：onboarding.js **v7**（会话围栏＋独立票据＋设置→引导进入即关父面板，完成→今天/退出→原页无双模态）、account-deletion v7、pajio.css v18 幽灵面板真因；自套 **200/200**＋独立脚本 14/14；QA 真实复验含面板交接，数据 rev13 基线；**桌面保存闭环 root CUA 实证**：2360×1640 截图实际像素坐标 [1695,1307]（不可除 2）点确认，rev13→14 completed 基线一致——root 记录；QA 库规模＝root 记录 83 表 429 行＋usage 2 表 1 行，勿写 82）。**待 root 桌面复验 v7 面板交接。**教训：**作者 CSS 的 dialog 规则必须带 [open]，否则覆盖 UA display:none 出幽灵面板**；**合成点击/键盘对 WKWebView（尤其 modal 态）不可靠，桌面点击验收用 CUA 实际像素坐标或真人**。遗留：①新空账户自动弹出与 skip 真实点击（qa 是 completed 老账户，单测已覆盖；待 root 隔离 fixture）；②深色跟随系统外观未实测（data-app-theme 直切已验样式）。

## 第十九轮状态（2026-10-08，已完成）

上一份交接中的五项未完成**已全部交付并 QA 实证**（详见 web-desktop-button-matrix.md 第十九轮与 pajio-zcode-delivery-2026-10-07.md）：

1. ✅ calendar-series 完整 UI（新 `series.js`：九动作闭集/系列列表/编辑器/实例面板仅这一次 vs 整个系列/例外/移除恢复/月历紫色事件+周议程序列段；409 双选择）。
2. ✅ 归档/恢复 PATCH request_key 持久幂等 + 两击确认（同 key 重放旧回执不重复归档已实证）。
3. ✅ 任务行点击同快照精确已读（GET /api/tasks/{id} 的 activity_receipt，cancelled 留未读）。
4. ✅ briefing-automation 面板（偏好版本绑定、回执≤7、开启需版本匹配/关闭不要求）。
5. ✅ record-reminders（新 `reminders.js`：双 CAS、life 编辑器+系列实例挂点、如实回执文案）。

另补验：文件编辑真实保存成功链、qa-summary 技能移除成功链（root 停合成任务后）。修复：同视图重渲染月历空白 bug（renderCalendarViews 重建前销毁旧 FullCalendar）。全套测试 **161/161**（第二十轮后见最新轮次记录）。

### 遗留（低优先）

- 系列月视图事件对比度为既有主题 dayMaxEvents 样式，未改主题。
- 自动简报回执列表需服务端 tick 才有数据（QA 现为空属预期）。
- 提醒真机送达属外测（合同边界，Web 已如实文案）。
- 真机系统分享/外部浏览器打开（收藏）与设备验收属 root 候选包（合同声明）。

以下为历史交接内容（**其中「第十八轮明确未完成」五项列表为旧状态，已全部完成**；模式与命令仍有效）：

## 当前工作树状态

- 桌面 Pajio.app 运行中（最近 pid 68347，重启命令见下）；构建需 `CARGO_PROFILE_RELEASE_STRIP=none`（Cargo.toml strip=true 会坏 proc-macro dylib），签名 `codesign --force --deep --sign -` 后 `codesign --verify --deep --strict` 通过。
- 全套 Web 测试 **150/150**：`node --test tests/*-ui.test.cjs tests/web-core-closure.test.cjs tests/web-import-goal.test.cjs`（在仓库根运行）。
- 本轮已写入交付文档：`docs/pajio-zcode-delivery-2026-10-07.md`（第一至十八轮）与 `docs/evidence/pajio-core-20261007/web-desktop-button-matrix.md`（第一至十八轮）。**第十八轮未完成项见下。**

## 第十八轮明确未完成（本轮用户点名要做的）

1. **calendar-series-contract.md 完整 UI**——重复日程创建/系列列表/单次例外（override/cancel/reset）/系列修改（update/archive/restore）。后端单入口 `POST /api/calendar-series`，SeriesCommand 严格闭集（action + 精确字段，多余字段 422）：list{after,include_deleted} / get{series_id,occurrence_key} / query{start,end,timezone,series_id?} / create{request_key,draft} / update{series_id,revision,request_key,draft} / archive·restore{series_id,revision,request_key} / override·cancel·reset{series_id,revision,request_key,occurrence_key,template?}。QA 当前该路由 409（root 正在加载），重启后先 `curl POST {"action":"list"}` 探活再接 UI。系列实例 ID `recurrence_<uuid>_<YYYYMMDD>`。UI 放日历视图（月/周/议程已就绪，见 life.js renderCalendarViews）；「补充日程」入口加「重复日程」；实例点开提供仅这一次/整个系列选择。request_key 经 WearingStore 持久幂等 + revision CAS 409 保留输入。
2. **offline-record-lifecycle-contract.md 归档恢复**——Web 现有「移到最近移除/恢复」是同步操作（PATCH action=archive/restore）；合同的离线队列（record-mutations 本机队列）明确「不涉及 Web/Desktop 本机存储」。**需要做的**：给 archive/restore 补 request_key 幂等（life.js 的 change() 已有 request_key 通道，POST 用了 createKey，PATCH 未带——按合同 PATCH body 加 `request_key`，同 key 重放取原回执）+ 操作确认文案（先说明范围）。409 双选择已有。
3. **task-detail-contract.md 同快照 activity_receipt 精确已读**——activity.js 的 openTask 已在打开 results bucket 时 POST /api/activity/seen；任务列表行的「精确已读」需在任务页行点击时也标记已读（当前只在 activity 面板点击时）。GET /api/tasks/{id} 新增 queued/queue_state/delivery/events/artifacts——root 说任务 GET 同快照 activity_receipt 源码已加、下次 QA 重启生效，「不拿新 version 确认旧结果」。做法：任务页行点击（data-activity-task）后除 openTask 外，若 item.unread 则 POST /api/activity/seen 标记该条已读。
4. **briefing-automation-contract.md**（新增冻结）——GET/POST `/api/briefing-automation`；AutomationSave{revision,request_key,enabled,local_time"HH:MM",timezone,grace_minutes 1-360 默认120,preferences_revision}。挂在简报偏好下方：「每天自动准备简报」时间选择+补做窗口+显式保存；显示自动安排使用的偏好版本 X；最近回执≤7 条（本地日期/状态/briefing 摘要）；关闭不要求偏好版本相同。QA 重启后探活。
5. **record-reminders-contract.md**（新增冻结）——GET/POST `/api/record-reminders/{target}`（target=life_<32hex> 或 recurrence_<uuid>_<YYYYMMDD>）；body{revision,record_revision,enabled,advance_minutes 准时/5/15/30/60/1440,request_key} 双 CAS。挂点：待办编辑器（life-editor 已有 due_at 字段）加提醒开关+提前量+保存；日程编辑器同理（用 start_at）。全天/无时间/已完成/已删除不可开提醒（reason 字段会说明）；回执 status/reason/provider_status 如实显示，不声称手机已展示。重复日程实例「这一次的提醒」绑定 occurrence target。

## QA 8891 约定

- 合成凭据在 `/_qa/manifest`（feishu cli_QASYNTHETIC / QA_SYNTHETIC_SECRET_001 / telegram token / expo push）。所有写操作只用合成数据；root 会用 App 停掉剩余合成任务，届时文件编辑（423→可保存）与技能移除（423→成功链）可在无活动任务状态做真实成功路径验收——**这两项成功链验收仍未做，等 root 通知后立即补**。
- 探活模板：`TOKEN=$(curl -s http://127.0.0.1:8891/api/bootstrap -H 'X-Wearing-Identity: qa' | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')`，之后带 `-H "X-Wearing-Identity: qa" -H "X-Wearing-Token: $TOKEN"`。
- QA 重启由 root 执行（保留数据）；重启后新路由：calendar-series、briefing-automation、record-reminders、任务 GET 同快照。

## 关键架构约束（勿违反）

- 全部新 CSS `html:not(.mobile-host)` 门控；模板字符串禁 `style=`（CSP）与 `onclick=`；动态尺寸走 WearingStore/CSSOM。
- 个人持久存储（request_key/草稿/凭证）一律经 `window.WearingStore`（scoped-store.js：cloud+scope 前缀 / cloud 无 scope 内存 / local 旧键；已带 Storage 兼容接口）。
- 身份切换：epoch 校验 + `WearingViews.reset()` + `WearingPajio.identityChanged`。
- 二次确认模式：`dataset.confirm` 1→确认文案→4 秒复位（全站一致）。
- 409 处理模式：保留输入 + 提示读最新 + 不自动重试（参考 life 编辑器双选择、清单 409）。
- 幂等模式：request_key 经 WearingStore 持久，失败/未知沿用同 key 取回，成功清除；409（同 key 异内容）按服务端真实回执处理。
- 每轮完成后：`node --test tests/*-ui.test.cjs tests/web-core-closure.test.cjs tests/web-import-goal.test.cjs` 全绿 + QA UI 点击截图（IAB，存 docs/qa-web-desktop-20261007/）+ 矩阵/交付文档追加轮次 + 桌面重启（`kill $(pgrep -f "Pajio.app/Contents/MacOS" | head -1); sleep 2; open clients/desktop/src-tauri/target/release/bundle/macos/Pajio.app`，注意沙箱需 dangerouslyDisableSandbox）。

## 验证命令汇总

```sh
# 全套 Web 测试（仓库根）
node --test tests/*-ui.test.cjs tests/web-core-closure.test.cjs tests/web-import-goal.test.cjs
# QA 探活
TOKEN=$(curl -s http://127.0.0.1:8891/api/bootstrap -H 'X-Wearing-Identity: qa' | python3 -c 'import json,sys;print(json.load(sys.stdin)["token"])')
curl -s -X POST http://127.0.0.1:8891/api/calendar-series -H "X-Wearing-Identity: qa" -H "X-Wearing-Token: $TOKEN" -H "Content-Type: application/json" -d '{"action":"list"}'
# 桌面重启（见上）；浏览器验收用 IAB（browser-use control-browser skill）
```

## 待验证 / 未做清单（如实）

- 技能移除成功链（423 时无文件删除已验；无活动任务后的真实移除+回执校验未做，等 root 通知）。
- 文本编辑保存成功链（同上，423 如实已验）。
- calendar-series / briefing-automation / record-reminders：代码未写（QA 路由未挂，本轮先交接）。
- 任务行点击的精确已读：未写。
- 简报偏好保存 409 后的重读流：已实现（自动 loadPreferences），QA 真实 409 触发未做。
- 飞书文件/日历/事件读取：mock 面板渲染已验（第七轮），真实断连重连流未做。

## 会话恢复提示

新会话先读本文件，再读 docs/pajio-zcode-delivery-2026-10-07.md 最后两轮 + web-desktop-button-matrix.md 第十七/十八轮，即可继续。优先顺序按「第十八轮明确未完成」1→5；root 通知 QA 重启或任务停完后随时穿插成功链验收。
