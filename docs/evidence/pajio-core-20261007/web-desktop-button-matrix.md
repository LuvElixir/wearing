# Web/Desktop 按钮闭环矩阵 · 2026-10-07

ZCode 独立审计范围：常规 Web（127.0.0.1:8765）与 Desktop（Pajio.app，同一 Web 前端 + 原生连接页）。App-host 分支原样未动。状态图例：**浏览器实测**＝本轮真实浏览器点击验证副作用；**代码+测试**＝处理器与接口已在源码与测试覆盖，未逐一点击；**WKWebView 待 Root**＝桌面像素待 Root CUA 复核；**阻碍**＝依赖不在本轮范围。

## 顶栏与导航

| 按钮 | 处理器 | 真实接口/动作 | 副作用测试 | 状态 |
| --- | --- | --- | --- | --- |
| 字标「Pajio」 | life.js setView | 视图切换 chat | pajio-web-ui #2 | 浏览器实测 |
| 身份胶囊 | app.js showIdentities | GET /api/identities；切换 switchIdentity 重载会话 | test_identities（后端） | 浏览器实测（双身份隔离已验） |
| 五入口 聊天/今天/任务/记忆/我的 | life.js setView | 视图路由（今天/任务/记忆/我的渲染真实接口数据） | pajio-web-ui #2 | 浏览器实测 |
| 搜索 | views.js openSearch | 页内查找零请求（计数/上下处/完成） | pajio-web-ui「search never calls APIs」 | 浏览器实测 |
| 设置齿轮 | app.js showSettings | GET /api/runtime /api/model /api/computer /api/phone | test_api 等 | 浏览器实测 |
| 导航任务徽标 | app.js renderGoalUpdates | GET /api/goal-updates | test_goal_updates | 代码+测试 |

## 聊天

| 按钮 | 处理器 | 真实接口 | 副作用测试 | 状态 |
| --- | --- | --- | --- | --- |
| 发送 | app.js submit | POST /api/conversation（request_id 防重、delivery 回执校验） | conversation-submissions-ui、native-composer-ui | 浏览器实测（历史会话来回） |
| 发送失败/离线 | turnMarkup delivery-note | 保留草稿 +「连接 Pajio」入口 | app.js receipt 校验路径 | 代码+测试 |
| 回到最新 | scrollToLatest | — | — | 浏览器实测 |
| 先停一下 / 重新查看 | turnActions | POST /api/tasks/:id/stop /refresh | — | 代码+测试（真实任务页存在） |
| 审批选择（确认卡） | app.js data-choice | POST /api/tasks/:id/approval | confirmation-ui | 代码+测试 |
| 桌面操作确认/暂停 | data-desktop-decision | POST /api/devices/input-approvals | test_desktop_input | 代码+测试 |
| 结果不明 resolve 表单 | data-resolve | POST /api/tasks/:id/resolve | — | 代码+测试 |
| 附件/研究/产物打开 | artifacts.js / research.js | GET /api/artifacts / 研究来源 | artifact-ui、research-ui | 浏览器实测（文件面板） |
| 唯一进展入口（含 52px 小熊） | activity.js open | GET /api/activity → openTask 定位对话 | activity-ui | 浏览器+WKWebView（Root 已验布局，动效待 Root 复核 pid） |

## 今天（views.js renderToday）

| 按钮 | 处理器 | 真实接口 | 副作用测试 | 状态 |
| --- | --- | --- | --- | --- |
| 分区任务行 | data-activity-task → WearingActivity.openTask | GET /api/activity → 会话定位/keep 详情 | web-core-closure（防误触） | 浏览器实测 |
| 今日安排行 | life.js data-life-open | 打开真实记录编辑器 | — | 浏览器实测 |
| 图文简报 | data-briefing | 仅准备可编辑草稿（不伪造生成） | pajio-web-ui 空态断言 | 浏览器实测 |
| **更新今日概览 ↻（本轮新增）** | data-today-refresh | 清缓存重读 GET /api/activity+/api/life | web-core-closure #1（断言缓存清除+重渲染） | 浏览器实测（apiCallsDelta=1） |
| **补记一条记录（本轮新增）** | data-quick-capture → WearingLife.quickCapture | 进入真实补记表单并聚焦 | web-core-closure #2 | 浏览器实测（view=capture、表单可见、聚焦） |

## 任务

| 按钮 | 处理器 | 真实接口 | 副作用测试 | 状态 |
| --- | --- | --- | --- | --- |
| 任务行 | data-activity-task | 同上 | — | 浏览器实测 |
| 刷新 ↻ | data-tasks-refresh | GET /api/activity?limit=20 | pajio-web-ui 分页断言 | 浏览器实测 |
| 加载更多 | data-tasks-more | GET /api/activity?cursor=…（409 保留+转刷新） | pajio-web-ui appendActivityPage vm 测试 + 接口实测（limit=3 翻页、篡改 422） | 浏览器实测 |
| **持续推进的事 · 目标与定时（本轮新增）** | data-open-keeps-entry | openPanel(keeps) + loadKeeps（GET /api/goals、/api/goal-updates、/api/schedules） | web-core-closure #3/#4（openPanel+loadKeeps 调用、失败反馈） | 浏览器实测（面板开、4 个真实定时、目标诚实空态） |
| 待办勾选/行 | life.js | PATCH /api/life/:id | test_life | 浏览器实测 |
| 新建（各视图） | life-add → openEditor | POST /api/life | test_life | 浏览器实测 |

## 目标与定时（keeps 面板，本轮起 Web 可达）

| 按钮 | 处理器 | 真实接口 | 状态 |
| --- | --- | --- | --- |
| 记下一个目标 / 表单提交 | app.js | POST /api/goals；control resume | test_goals | 代码+测试 |
| 目标行/详情、暂停/继续/结束/核对 | data-goal / data-goal-action | GET/POST /api/goals/:id/control | test_goals、test_goal_* | 代码+测试 |
| 定时：添个安排/保存/详情 | schedules.js | POST /api/schedules 等 | test_schedule_events | 浏览器实测（4 条真实定时渲染） |
| 进展已读 | data-seen-updates | POST /api/goal-updates/seen | test_goal_updates | 代码+测试 |
| 记忆纠正（keeps 内） | data-correct-memory | 草稿带入聊天 | — | 代码+测试 |

## 记忆 / 我的 / 外观

| 按钮 | 处理器 | 真实接口 | 状态 |
| --- | --- | --- | --- |
| 记忆纠正这条 | views.js | /api/memory 数据 → 草稿 | 浏览器实测（跨身份 available=false 诚实回执） |
| 查看全部文件 | data-open-files | GET /api/workspace + artifact 库 | 浏览器实测 |
| 我的：账户/能力/数据/身份分组 | data-me-action | showSettings/showIdentities/files/appearance（真实面板） | 浏览器实测 |
| 外观三态 | data-theme-option | appearance:v1 持久化 + data-app-theme | 浏览器实测（日/夜/系统+刷新保留） |
| 衣橱预览/穿上保存 | data-outfit-preview/save | wardrobe:v2:web:{identity} 显式保存 | 浏览器实测（含身份隔离） |
| 陪伴形象/简洁标记 | 已随 App 移除 | —（历史 symbol 存档按 bear 保留衣服） | pajio-web-ui 断言 | 浏览器实测 |

## 设置与设备（app.js）

全部按钮接真实接口：runtime install/start/stop、模型保存（/api/model POST）、执行服务连接（/api/connection）、文件空间启用（/api/workspace/enable）、手机准备/接入/暂停/恢复（/api/phone*）、电脑准备/授权/接入/接管（/api/computer*）、设备配对全流程（/api/devices/offer|pair|permissions|control|reviews）、桌面审批（input-approvals）、联网能力与文件状态读取。后端测试：test_runtime/test_model_settings/test_phone/test_computer/test_device_* 全绿。状态：代码+测试；浏览器实测（本机真实状态渲染：引擎运行中/模型 DeepSeek/电脑已接入/手机 1 部离线）。**未接入/无权限处均显示具体状态与下一步（如「先准备连接器」「需系统授权」），无假已连接**。

## 补记录与搜索

| 按钮 | 处理器 | 真实接口 | 状态 |
| --- | --- | --- | --- |
| 记下（表单） | life.js submit | POST /api/life（request_key 防重、媒体走 capture 上传） | test_life、test_capture | 浏览器实测 |
| 图片/说一句/录音文件 | capture.js | /api/life/assets 上传 | test_capture | 代码+测试 |
| 类型切换/时间/整理开关 | life.js | 本地表单态 | — | 浏览器实测 |
| 记录编辑/移除/恢复/聊聊 | openEditor/archive/restore/talkAbout | PATCH /api/life/:id action | test_life | 浏览器实测 |
| 最近移除 | life-trash | 视图切换 | — | 浏览器实测 |
| 搜索上一处/下一处/完成 | views.js | 页内 | pajio-web-ui | 浏览器实测 |
| 紧凑输入入口 | compact-entry | 回聊天续用同一草稿 | — | 浏览器实测 |

## Desktop 原生（clients/desktop）

| 按钮 | 处理器 | 真实接口 | 状态 |
| --- | --- | --- | --- |
| 连接 Pajio | connection.js → connect_server | server verify + 持久化 + 导航 | cargo test 9/9（endpoint 握手/重定向/大小限制/凭据隔离） |
| 连接设置/记一下/退出 | 菜单+托盘+全局快捷键 | 单实例/快速捕获事件 | 代码+构建；单实例转发实测（旧预览存活） |

## 阻碍与未验证

- 聊天发送失败重试的**断网现场**未在浏览器模拟（不做假离线）；回执与排队路径由 app.js receipt 校验与测试覆盖。
- 桌面 WKWebView 全部像素（含动效熊、海报回退）以 Root CUA 为准（本轮已重启进程待复核）。
- 外部 OAuth/会员计费无接口，按钮不存在也未新增；能力目录只显示真实状态。
- 云端部署相关按钮（cloud 分支）在本地实例不可达，状态为代码+后端测试。

## 本轮新增/修复汇总

1. 任务页「持续推进的事」入口（此前目标/定时面板在 Web 无主入口——其按钮全部位于被隐藏的 review-panel）。
2. 今天页显式刷新按钮（清缓存重读）。
3. 今天页「补记一条记录」入口（此前 capture 视图 Web 近乎不可达）。
4. 副作用测试 `tests/web-core-closure.test.cjs`（4 项：缓存清除+重渲染、quickCapture 调用、openPanel+loadKeeps、loadKeeps 失败反馈），全套 **111/111**。

## 第二轮 · App 合同对齐（RecordDetail / TaskManagementPanel / MemoryLibrary）

对照只读合同逐项核查 Web/Desktop 现状：

| 合同点 | Web/Desktop 现状 | 本轮动作 |
| --- | --- | --- |
| 笔记/待办内容修改 | life.js 编辑器已有（标题/内容/分组/截止/完成） | 无需改 |
| 日程开始/结束时间编辑 | 编辑器 event 字段（datetime-local/全天切换）已有 | 无需改 |
| local draft | sessionStorage 每记录草稿 + 恢复提示已有 | 无需改 |
| **409 最新版对照 + 保留我的输入/采用最新内容** | 原仅有单向「用最新版本重新编辑」 | **本轮实现双选择**：并排显示最新版本内容 + 「保留我的输入」（仅换最新 revision，字段不动）/「采用最新内容」（弃旧草稿载入最新）；最新版已删除时诚实收起并指向最近移除 |
| PATCH action archive/restore | 已有（编辑器「移到最近移除」+ 最近移除视图「恢复」，带撤销） | 无需改 |
| 最近删除 | Web 自己的 trash 视图 + 恢复闭环 | 无需改 |
| POST /api/captures/{id}/retry | capture.js `data-capture-job-retry` 已有（仅 failed/paused 显示） | 无需改 |
| 目标 pause/resume/cancel/note/complete + 历史 task 直达 | keeps 面板已有（data-goal-action/data-goal-turn，revision 控制） | 无需改 |
| 定时 pause/resume/cancel/修改 | schedules.js 已有（revision PATCH action） | 无需改 |
| 记忆内文件搜索/图片预览/系统分享 | App 原生能力；Web 文件面板为只读列表+下载 | **未移植**（浏览器无系统分享；图片预览/搜索如实记为未实现，不假装） |
| 同步记录入口 | Web 无离线队列概念（在线页），桌面连接页 auto-connect | 无需改 |
| 技能/聊天渠道管理 API | 后端无管理接口 | 不推断为已启用（矩阵沿用诚实状态） |

**新增副作用测试**（web-core-closure 第 5–7 项）：保留输入断言 revision 换新且字段/编辑器不被重开、采用最新断言弃草稿+重开编辑器、最新已删除断言诚实收起不复活。全套 **114/114**。

**真实数据浏览器实测**（真实 409：先开编辑器→并发 PATCH→旧表单保存）：错误提示与「查看最新版本」出现 → 并排面板含并发内容与双按钮 → 「保留我的输入」保留我的标题 → 重存「笔记 已保存。」→ 服务端终态 revision 3、我的标题生效（并发内容按用户明确选择被覆盖，符合合同）。归档清理路径同轮验证。证据图 `pajio-core-409-choice.png`。验证产生的 3 条笔记已归档进「最近移除」（可恢复，无硬删除 API）。

## 第三轮 · 文件导入与目标幂等（workspace import / GoalBook request_key）

### 已实现（Web）

| 能力 | 实现 | 副作用测试 | QA(8891) 实测 |
| --- | --- | --- | --- |
| 文件导入 | `POST /api/workspace/import?name=&request_key=`（raw bytes ≤20MB、身份+Token、失败重试沿用同一 key、回执四项核对 request_key/sha256/path/size，对齐 App importReceipt） | web-import-goal #1–#3（字节、同 key 重试、回执拒绝） | **路由未挂**（见阻碍） |
| 文件名搜索 | 文件面板搜索框过滤当前列表，计数 `「词」命中 X/Y 个`，200 截断如实标注 | — | ✅ 「测试」命中 2/4 |
| 打开/下载 | 每行「打开」（inline）+「下载」（attachment）真实链接 | — | ✅ 打开 200 |
| 交给 Pajio | 行按钮带真实路径回聊天预填草稿（不自动发送） | — | ✅ 草稿含路径 |
| 目标幂等创建 | 表单 spec 指纹 + 失败重试同 key（重放回原目标反馈「未重复建」）、成功即重置；`request_key` 随 POST | web-import-goal #4–#5（key 稳定/字符集/重置、body 携带） | **QA NewGoal 模型滞后**（见阻碍）；真实 GoalBook 幂等由后端 test_goal_delegation 覆盖 |
| workspace 响应兼容 | `capability` 缺失时路径栏显示「当前服务未提供路径信息」，列表照常 | — | ✅ QA 4 文件渲染 |

### 阻碍（需 Root 处理 QA 脚本）

1. `docs/evidence/pajio-core-20261007/qa-server.py` **未挂载 `POST /api/workspace/import`**（返回 409「QA 合成环境未启用此能力」）——真实后端 `workspace_upload.py` 已有但正式服务未重启，导入链路当前只能在真实后端单测层验证（tests/test_workspace 相关），端到端待 QA 路由补齐。
2. QA `NewGoal` 模型 `extra='forbid'` 且**无 `request_key` 字段**——Web 表单的幂等创建在 QA 会 422。真实后端 `goals.py` 已支持（同 spec 重放回原目标、异 spec 409），由 `test_goal_delegation` 覆盖。

两处补齐后我可在 8891 完成导入端到端与目标重放同 id 的实机验收。QA 实测中导入失败显示服务真实 detail，未假装成功。8765 未写任何测试数据（此前 3 条验证笔记保持归档可恢复）。

## 第四轮 · 简报/技能/消息/记忆编辑（真路由接入）

| 能力 | 实现 | 副作用测试 | QA(8891) 实测 |
| --- | --- | --- | --- |
| 持久简报 | `briefings.js` + `#brief-panel`：GET 版本列表（状态八态映射）、POST `{date,timezone,request_key,base_version}`（journal 发出前持久化、未知结果同 key 取回、回执五项核对）、前台 5s 轮询/后台停、成果经 artifact 打开、任务直达、来源快照行；今天页按钮不再预填聊天 | web-import-goal #6（journal 生命周期/回执核对/轮询/活跃态） | ✅ 面板开、第 1 版「已排队」、创建进入「正在整理…」、来源快照显示 |
| 技能目录 | 我的→技能：GET `/api/skills`（installed+catalog 固定版本）、PATCH `/api/skills/enabled`（id/enabled/revision）、POST `/api/skills/install` | web-import-goal #7（真实方法/路径/revision 随体） | 路由未挂 → 面板如实显示服务 409 文案（不假装目录） |
| 聊天工具 | 设置→聊天工具：GET `/api/messaging`、PUT 配置（Telegram token / 飞书 app_id+secret）、PATCH 启停、DELETE 断开（revision）；**凭据仅存在于表单内存，提交即清空密码字段，无任何持久化**；断开需二次确认 | web-import-goal #7（PUT/PATCH/DELETE 体；凭据零存储断言） | 路由未挂 → 如实 409 |
| 记忆直接编辑 | 记忆页：GET 带 `revision` 才显示编辑/删除/添加；PATCH `/api/memory` `{target,action,revision,index,content}` 精确增改删；409 保留表单输入并提示读最新版；无 revision（当前 QA）自动回退纠正草稿路径 | web-import-goal #8（精确体/门控/409 留输入） | QA 未暴露 revision → 门控回退（App 同款 `supported` 判定） |
| 目标创建幂等（修复） | `source_task_id` 仅在有值时携带（此前 null 触发 QA `extra=forbid` 422） | — | ✅ 201 / 同 key 重放同 id / 异 spec 409（真实 GoalError 文案） |

**QA 端到端补全**：导入（201→回执四项核对→同 key 重放同路径→异内容 409→列表可见）与目标幂等（同 id 重放/409）全部通过。本轮还修复：views.js 模块级渲染函数误置于 renderMe 作用域导致整模块加载失败（浏览器暴露，切片测试未覆盖——已记录该测试盲区）。

待 Root：QA 挂载 `/api/skills`、`/api/messaging`、`PATCH /api/memory`（含 GET revision）后，我补三项实机验收。

## 第五轮 · 飞书个人账号 + 设备面板对齐核查（2026-10-08）

| 能力 | 实现 | 行为测试 | QA(8891) |
| --- | --- | --- | --- |
| 飞书个人账号（与聊天机器人分开） | `cloud-apps.js` + 设置面板「飞书个人账号」段：PUT 配置（App ID/Secret/范围，**凭据仅表单内存、finally 清空、零持久化**）、POST authorize/poll/check、DELETE 解除（二次确认含撤销提示）；授权页仅官方 feishu.cn 链接（同 App `officialFeishuUrl` 门）；authorizing 态显示用户码+倒计时+按 interval 自动轮询；connected 态列能力授权矩阵 + 文件夹钻取/文档分页全文/日历/未来 7 天事件（GET files/document/calendars/events） | web-import-goal #9（真实路由动词与体、官方链接门、零持久化、无自动授权、409 重试入口） | 路由未挂 → 面板如实显示服务 409 + 重试按钮（手动驱动验证；QA 身份非 daily，showSettings 走身份分支——真实服务 daily 正常） |
| 设备配对/权限/控制 | Web 设置面板已有且对齐 `device-management.ts` 全套真实动作：offer 检查（already_paired 禁选）、pair（request_id）、permissions（revision 模式）、control（expected_generation）、input-approvals、reviews；409 保留当前内容 | 既有 test_device_* 系列后端测试 + app.js 布线 | QA 未挂 /api/devices（合成环境无设备）；真实服务路径此前已验收 |
| 记忆字段更正确认 | Web PATCH `/api/memory` 使用 `target/action/revision/index/content`（与当前代码一致；无 base_revision/entry 残留） | web-import-goal #10（字段名断言 + 无残留断言） | — |

**接口缺口（待 Root 挂 QA 路由后我补实机验收）**：`/api/cloud-apps/feishu*` 全组、`/api/devices*`、`/api/skills*`、`/api/messaging*`、`PATCH /api/memory`（含 GET 暴露 revision）。均已按真实合同接线并配行为测试，QA 未挂载处如实显示服务返回，未做假联调。

## 第六轮 · 设置身份门修复 + 待核对决定 + 用量页（2026-10-08）

| 能力 | 实现 | 行为测试 | QA(8891) 实测 |
| --- | --- | --- | --- |
| 设置对所有身份开放 | `showSettings` 移除非 daily 重定向（身份管理保持独立入口=身份胶囊/身份面板）；skills/memory/cloud-apps/messaging/usage/decisions 对每个身份可用 | web-import-goal #13（无 showIdentities 重定向断言） | ✅ qa 身份点设置直接打开面板，身份面板未弹（截图 `pajio-qa-identity-settings.png`） |
| 待核对的决定 | `decisions.js` + 设置新段：GET `/api/confirmations`；仅 `can_resume && needs_recheck` 显示「重新核对并继续」；POST `{revision,request_key}`，request_key 以 身份+卡片+revision 持久（跨失败重试不换键、成功清除）；回执严格校验 `authorized:false` + task + 五种 delivery；完成后回对话定位 | web-import-goal #11（门控/键持久/严格回执/decision_id 格式） | ✅ 路由 200，空态「没有等待核对的确认」如实 |
| 用量页 | 设置新段：GET `/api/usage`；trial/not_enabled 如实区分；金额未知显示「金额未知（未接入计费，不显示为 0 元）」，绝不出现 0 元；本身份累计与剩余次数/并发/音频秒数 | web-import-goal #12（诚实文案 + 无假 0 元断言） | 路由未挂 → 如实 409 |
| 飞书个人账号（QA 扩展后复验） | 同第五轮 | 同第五轮 | ✅ 状态渲染「已配置应用，待授权」+ 能力矩阵（未点击授权，遵守不发起真实授权） |
| 聊天工具（QA 扩展后复验） | 同第四轮 | 同第四轮 | ✅ Telegram「未配置」如实渲染 |

## 第七轮 · QA 点击验收（合成凭据）+ 决定键修正 + 记忆 v2（2026-10-08）

QA 8891（PID 60648）全 MockTransport，使用 `/_qa/manifest` 合成凭据完成 UI 点击验收，未填真实凭据、未访问真实授权链接：

| 流程 | 结果 |
| --- | --- |
| 飞书个人账号 | 配置态 → 点「连接飞书（官方授权）」→ Mock 即连 → 「已连接：QA 合成飞书账号」+ 双能力已授权 → 读取云文档（列表）→ 打开文档全文（合成内容如实标注 MockTransport）✅ |
| Telegram | 未配置 → 填合成 token/用户 → PUT 配置成功且**token 字段提交后立即清空** → 启用（listening）→ 停用 → 二次确认断开（回到未配置）✅ |
| 技能 | 目录渲染 → 安装（真实文件复制）→ 启停按钮可用 ✅ |
| 记忆 v2 | revision 门控全开（编辑/添加/清空）；添加真实 PATCH 成功；**离页草稿**（sessionStorage 按 身份+分区+条目）实测保存；并发后旧 revision 保存 → **409 输入保留** + 「记忆已有更新，请读取最新版后再修改」；清空（二次确认 → 真实 clear → 诚实空态）；set_enabled 门控（QA 未暴露 settings_revision → 启停按钮不显示，同 App）✅ |
| 待核对决定 | QA 合成 decision 渲染（卡片+状态）；「重新核对并继续」点击成功；**request_key 成功后仍保留**（sessionStorage 实测存在）——同 scope/卡片/revision 永远同键，迟到重放不会创建第二次恢复 ✅ |

修正：决定 request_key 成功后不再清除（对齐 App 注释语义）；新增 `execution_unknown` 状态标注「需核对原结果（不可恢复，只能查看）」——该状态 can_resume 必为 false，永不显示恢复按钮。记忆 v2 新增：`clear`（二次确认）、`set_enabled`（暂停二次确认/恢复直执行，`settings_revision` CAS 随请求，409 对比最新）、离页草稿（成功清除、409 保留）。测试断言收紧（messaging 凭据零持久化范围限定到其渲染区）。全套 **127/127**。

## 第八轮 · 数据导出 + 服务端文件分页搜索 + 用量验收 + 决定键 localStorage（2026-10-08）

QA 8891（PID 66072）真实路由点击验收（全合成数据）：

| 能力 | 实现 | QA 点击结果 |
| --- | --- | --- |
| 带走我的数据 | `data-exports.js` + 设置新段：GET 列表找回（`exports` 回执键兼容）、POST `{request_key}` 幂等（**localStorage** 按身份持久键，跨标签页/关闭后同键）、下载链接带认证头同源、SHA256/大小/剩余有效期/遗漏明细逐条呈现（`pajio-data-*.zip`/64 位 sha/15MiB 上限校验后才渲染） | ✅ 列表找回此前副本；UI 创建生成真实 ZIP（GET 200 application/zip 1.8MB，unzip 验证含 records.json/media/results/manifest/README）；同键二次创建**未产生第三份**（幂等）；遗漏/SHA 区块显示；键为纯 UUID 持久 localStorage |
| 文件全量搜索/分页 | 文件面板迁移 `GET /api/workspace/page?query=&cursor=&limit=200`：**服务端**文件名搜索（350ms 防抖）、opaque cursor 续页（「继续查找」）、scan_id 变化自动清列表重读（409 同路径）、`complete` 才显示「已完整读取」/否则如实显示扫描进度；**移除旧 200 项客户端 filter** | ✅ 初始「已完整读取 5 个文件」；搜「简报」→ 服务端命中 1 个且全匹配；清空恢复完整列表 |
| 用量 | 上一轮已实现，本轮 QA 路由挂载后验收 | ✅ 真实 `not_enabled`：「用量统计未启用 · 金额未知（未接入计费，不显示为 0 元）」+ 资源限额/并发如实渲染（未伪造配额启用） |
| 决定 request_key | 迁移 localStorage（scope/card/revision 粒度），移除成功清除路径 | ✅ 键纯 UUID、localStorage 持久、成功保留 |

测试：新增导出（回执形状/幂等键/遗漏/无凭据）、文件分页（服务端 query/cursor/scan 重读/350ms/完整措辞/客户端 filter 已移除）、决定键（localStorage/成功保留）断言；全套 **130/130**。

## 第九轮 · P0 账号隔离 storage_scope + 跨对象关键词搜索（2026-10-08）

**P0 账号隔离**（新 `scoped-store.js`，全部个人持久存储改道）：
- 可信 `bootstrap.storage_scope`（64hex）绑定后才初始化个人存储：草稿/发送流水（app.js 延迟创建）、语音回执/原生草稿流水（now.js）、衣橱（pajio.js）、简报 journal、决定 request_key、导出 request_key、记忆离页草稿——全部经 `WearingStore` 取键。
- cloud + 有效 scope：localStorage 键加 `pajio:{scope}:` 前缀（A/B 同 origin 同 identity 互不可见）；同 scope 重登同键稳定。
- cloud 无 scope / 伪造 scope（非 64hex）：仅内存，不读写 localStorage、不读旧无 scope 缓存、不迁移旧云草稿。
- 账号/租户变化：清空内存态 + 推进身份纪元作废在途请求。
- local（本机私有开发）：沿用旧键兼容（不作为云降级）。
- 行为测试：A/B 同源隔离、同账号重登稳定、pending（bootstrap 失败）零 localStorage 触碰 + 旧缓存不可见、伪造 scope 回落内存。QA 实测 local 兼容（衣橱保存走旧键、记忆草稿可用）。

**跨对象关键词搜索**（对齐 search-contract）：搜索浮层新增「跨对象」分区——GET `/api/search?q&kind=all&limit=20&cursor`（250ms 防抖、查询变化丢弃迟到结果、「继续查找」续页）；typed 深链：task→openTask、record→打开对应视图编辑器、message→`/api/search/messages/{id}`→定位任务；命中显示类型标签与片段。当前对话内定位仍零请求。QA 实测：搜「搜索验收」命中消息+记录（类型标签正确），点记录深链打开笔记编辑器（截图 `pajio-qa-global-search.png`）。

测试：全套 **132/132**（新增 scope 行为 2 项；搜索断言更新为双模式合同）。

## 第十轮 · scoped-store 复核修正 + 诊断面板 + 搜索真实检索复验（2026-10-08）

**复核修正**（Root 两点）：
1. memory 适配器已含完整 Storage 接口（getItem/setItem/removeItem 包 Map）；实测无 scope 时输入经内存适配器**保留到本次页面**且**零 localStorage 写入**（QA 双探测通过）。
2. `bind` 收紧：**仅 `deployment === "local"` 沿用旧本机键**；cloud 无/伪 scope、unknown/undefined/失败形态一律 `cloud-memory`，不回落 local——行为测试逐形态断言（undefined/null/'unknown'/''/'local?'）。

**诊断面板**（新 `diagnostics.js` + 设置新段，对齐 diagnostics-contract.md/App NativeDiagnosticsPanel）：打开设置时用户可见地生成（只读 `GET /api/diagnostics`，至多 5 秒 probe）；摘要行（服务/运行环境/引擎探测五态/设备 not_observed 不推断在线/最近任务 items+truncated）+ 完整 JSON 预览 + 下载 JSON + 重新生成；无上传、无假提交按钮；错误时如实显示并保留重试。QA 实测：真实回执渲染（synthetic/observed/未配置/未观测/6 项任务）、下载与预览在位（截图 `pajio-qa-diagnostics.png`）。

**关键词搜索真实检索复验**（8891 重启后）：搜「搜索验收」命中消息+记录两类（跨对象分区），记录深链此前已验。

测试：全套 **132/132**（scope 测试扩展 unknown/undefined/内存保留/remove；无新增 UI 内联样式）。

## 第十一轮 · 复核修正（bind 原始值 / 诊断白名单投影）+ 安静时段（2026-10-10）

| 修正/新增 | 实现 | 行为测试 | QA |
| --- | --- | --- | --- |
| bindScopedStorage 原始值 | `WearingStoreBind(bootstrap.deployment, bootstrap.storage_scope)`——不再在 app.js 兜底 `"local"`；fail-closed 判定唯一收敛在 store | 集成测试：6 种真实 bootstrap 形态（missing/empty/unknown/cloud-no-scope→cloud-memory；cloud+scope→scoped；local→local）直接驱动 store 模块联动断言 | ✅ QA（local deployment）store.mode=local |
| 诊断白名单投影 | `diagnostics.js` 重写：移植 App `diagnosticsSnapshot` 投影（schema/枚举/上限/日期/引用格式全验证；**永远新建对象**）；导出 JSON 是投影而非服务端原样；AbortController 切身份取消在途；Blob URL 下载后 revoke（pagehide 亦清理） | 伪造字段测试：夹带 token/路径/原始错误文本/日志通道字段全部不进投影；devices>30 拒绝；身份不匹配拒绝 | ✅ QA 真实回执投影渲染（含「有任务需核对进展」如实提示；预览标注「白名单字段」） |
| 安静时段 | `quiet-hours.js` + 设置新段：GET/POST `/api/notifications/preferences?installation_id=`（安装级稳定 ID）；revision CAS（409/失败保留输入重读后由用户再保存）；开始=结束拒绝；文案明确「推送延后」不声称已推送/已静音 | 方法/体/CAS/相等拒绝/不宣称推送效果断言 | QA 未挂路由 → 如实 409（待 Root 挂载后补实机） |

注：`offline-record-edits.md` 当前不存在于 docs/evidence/pajio-core-20261007/（已列出全部文件核对）；Web 现有记录编辑已具备 request_key 幂等（life API 合同）与 409 双选择，待合同文档就位后按其逐项对齐。全套 **135/135**。

## 第十二轮 · 草稿误报真缺陷修复 + 安静时段文案 + 记录编辑幂等（2026-10-10）

| 项 | 实现/根因 | QA 真实 UI 证据 |
| --- | --- | --- |
| 草稿误报"只能留在当前页面" | **根因**：`WearingDrafts` 期待 Storage 接口（getItem/setItem/removeItem），而 WearingStore 只暴露 get/set/remove → drafts 内 `storage().getItem` 抛错被 catch → onError 误报。修复：WearingStore 补 Storage 兼容接口（同样走 scope 前缀）。 | ✅ 输入「QA 草稿保留验证」→ 无警告；切到今天再回聊天 → 草稿恢复；**整页重载** → 草稿恢复（localStorage 键 `wearing-chat-draft:v1:qa:chat::`）；cloud 无 scope 模拟 bind → 内存可用、**零 localStorage 泄漏**、无警告 |
| 安静时段文案对齐 | awaiting_registration 语义：「通知登记到期时，需要重新登录并开启通知」；「时段结束后只发送仍有效的进展，过期内容不补发」；「保存不保证手机已经显示」 | 待 Root 重启 QA 后实机（API 已挂，等新代码加载通知） |
| 记录编辑 request_key 幂等 | life.js 编辑提交带固定 attempt（同 base revision+patch 同键，成功即清；网络失败重试重放完全相同请求）——对齐 offline-record-edits.md 服务端 `life_mutation_requests` 合同 | ✅ 保存成功；服务端同 spec 重放返回原回执（200） |

注：offline-record-edits.md 明确「当前实现不涉及 Web/Desktop 的本机存储」——Web 侧本轮落地的是其**服务端幂等合同**（request_key + CAS）；完整本机离线队列（本地事务写入/退避重试/待同步状态）按合同属 App 本机实现，Web 如需补列为后续任务。全套 **136/136**（新增 Storage 接口回归 + drafts 联动 + 安静时段文案断言）。

## 第十三轮 · 安静时段 QA 实机收口（2026-10-10，QA PID 19872）

全流程真实 UI 点击（自有安装 ID `14c434f1-…`，未调真实推送）：

| 步骤 | 结果 |
| --- | --- |
| 默认态 | 关闭 · 22:00–08:00 · Asia/Shanghai · revision 0；帮助文案含「只发送仍有效的进展」「需要重新登录并开启通知」「不保证手机已经显示」✅ |
| 开启+改时+保存 | 23:30–07:00 保存成功；反馈=「已保存。安静时段结束后会发送仍有效的进展；通知登记到期时，需要重新登录并开启通知。」✅ |
| 整页重载 | enabled=true · 23:30–07:00 持久恢复 ✅ |
| 并发 409 | 服务端并发保存后旧 revision 提交 → 409「通知时段已在别处修改，请重新读取后核对。」且**表单输入（21:00/06:00）完整保留** ✅ |
| 重读 | 重新打开设置 → 自动重读到最新（23:00/51? revision=2），用户再决定 ✅ |
| 关闭 | 「已关闭安静时段。」enabled=false ✅ |

证据图 `pajio-qa-quiet-hours.png`。全套 **136/136**。本轮无代码改动（上一轮已实现），仅实机验收。

## 第十四轮 · 技能移除 + 结果选项 + 可见品牌残留清理（2026-10-10，QA PID 23615）

| 能力 | 实现 | 行为测试 | QA 真实 UI 点击 |
| --- | --- | --- | --- |
| 技能移除 | 我的→技能→已安装行「移除」→ 预览（名称/包修订/操作编号，GET removal）→「确认移除」（POST remove 四字段精确提交）→ 严格回执校验（removed===true、id/operation_id/recovery_id 一致、snapshot.installed 不再含该 id）→ 刷新目录；失败保留同一 operation_id 重试；423 如实提示「任务正在执行，完成后再来确认」 | web-import-goal #22（预览/四字段/严格回执/snapshot 消失/423 文案/同操作重试） | ✅ 预览显示「移除技能「qa-summary」」+ 操作编号；确认后 **423 如实返回**（QA 有活动任务），技能仍在列表、零文件被移除（截图 `pajio-qa-skill-remove-423.png`）；成功路径由后端 26 项测试 + Mock 行为测试覆盖，QA 上不强行停任务 |
| 结果选项 | artifact 面板新增**原生**选项区（iframe 保持 opaque sandbox，无 postMessage/桥）：选项列表 → 点击展开完整 instruction →「确认选择，继续处理」→ POST choices（固定 request_key 按身份+结果+选择经 WearingStore 持久，未知结果同请求取回；严格回执校验）；已有选择显示「已排队，尚未执行/已保存，等待开始」（queue_state 判定，201≠已执行）；新版本入口阻止旧版选择；409 保留选择与输入 | web-import-goal #23（原生 only/固定 key 持久/严格回执/排队诚实文案/新版本阻止/无桥断言） | ✅ 合成 artifact 显示两个选项（先整理摘要/先做比较表）→ instruction 预览（「不发送、不付款」）→ 确认提交成功 → 重开显示「已有选择：先整理摘要。后续任务已排队，尚未执行。」（截图 `pajio-qa-artifact-choice.png`）；QA 不执行模型，仅排队 |
| 可见品牌残留 | `face.js` aria-label Wearing→Pajio、`character-poster` alt 更新、`叫一下 Wearing`→Pajio；协议头 X-Wearing-*/存储键 wearing-* 等内部兼容名保留 | face-ui 更新 | ✅ |

全套 **138/138**。QA 数据未动（选择结果为 QA 合成流转，未调真实模型/推送）。

## 第十五轮 · 账户注销（Web 可独立部分）· 2026-10-10

| 项 | 实现 | 行为测试（合成存储/传输） | QA |
| --- | --- | --- | --- |
| 入口与范围展示 | 设置→「注销账户」段：GET plan（gateway 凭据）→ 严格回执校验（tenants/action 枚举/64hex revision/16-120 key/pdr1. 前缀回执）→ 渲染空间范围 + 归属未就绪 blockers + 三类 action 文案（对齐 App） | validPlan 伪造字段拒绝 | QA 网关未挂路由 → 如实「当前入口未提供账户注销能力」+ 重试（截图 `pajio-qa-deletion-honest.png`） |
| 凭证先存 | plan 到达即把 request_key/plan_revision/receipt_token/origin 经 WearingStore 按账户键持久——**先保存后提交** | save/load 往返 | — |
| 独立重新验证 | plan.reauth_required → 「重新验证身份」（POST reauth CSRF 空 body → authorize_url 跳转；回调更新浏览器 session，对齐合同 Web 分支） | — | — |
| 固定 key 提交 | POST request 恰四字段 `{request_key,plan_revision,receipt_token,confirm:"DELETE"}`；202 → 查询；**非 202/失去响应不盲目重提，先用保存凭证查询同一申请** | 源码断言（恰四字段 + 失响应查询文案） | — |
| 状态门控 | completed 仅 `state=completed && code=verified && data_erased=true`；waiting 白名单 11 码；not_submitted 如实 | validStatus 三态拒绝（data_erased=false 非 completed、非 verified 非 completed、waiting 白名单） | — |
| 已登出只读 | status 查询只用 `Authorization: Bearer <receipt_token>`，不依赖业务 session | — | — |
| 缓存围栏 | 受理/查询到已提交即清理**仅含当前身份标记**的草稿/语音回执/原生草稿键；注销凭证保留、其他账户键不动 | 围栏测试：本账户键清、other-account 键保留、凭证存活 | — |

QA 未挂 `/auth/account-deletion/*`（404）——按指示不做假联调；真实 UI 仅验证如实降级。全套 **139/139**。

## 第十六轮 · 账户注销复核修正（2026-10-10）

按 Root 复核逐项修正 `account-deletion.js`：

| 复核点 | 修正 | 行为测试 |
| --- | --- | --- |
| accountMark=identityId 误删 | **围栏改为 gateway origin + user_id**（user_id 仅来自可信 plan 回执 `user_[a-f0-9]{32}` 校验）；`isOwned` 精确匹配 `|user_<id>` / `:user_<id>:` / `:user_<id>|` 归属段，禁止宽松 includes；旧无归属凭证仅保留展示 | 同 identity 不同账户键（`daily`）不被清理；带 user_id 段的键被清理；凭证存活 |
| reauth 按钮无 id | 渲染改为 `id="deletion-reauth"` / `id="deletion-confirm"` / `id="deletion-confirm-input"`，监听器绑真实 id | 直接驱动真实 click/input 事件（vm element listeners） |
| POST 缺 CSRF | 对照 `gateway.py unsafe_allowed`：POST 携带 `x-wearing-csrf` 头（值来自服务端 `pajio-csrf` cookie，本页只读）；GET 不携带 | 测试断言 POST 请求头精确值来自 cookie |
| value_started 宽松 / plan 可带 null | `pdr1.` 前缀 + 至少 16 字符；**任一必需字段（request_key/plan_revision/receipt_token/user_id）缺失或不合法 → 整份 plan 拒绝**（不再返回 null 字段对象） | 非 pdr1 token、短 key、identity id 冒充 user_id 均拒绝 |
| status 白名单 | 对照 operator 契约 11 个 waiting 码 + `completed=verified+data_erased:true`；未知 state/码/不匹配 request_key → 拒绝（不假成功） | 未知 state、跨 request_key、data_erased=false+completed 全拒绝 |
| submit 异常不查询 / not_submitted 文案 | submit 网络异常 catch 后**始终 queryStatus 同一申请**；not_submitted 显示「服务尚未收到这次注销申请，**本账户业务可以继续使用**」并解除冻结 | 掉响应（request throw）→ fetch 序列 plan→request→status；workAllowed 恢复 |
| 只删 localStorage 无业务围栏 | 冻结门 `WearingDeletion.workAllowed/freezeAccountWork/unfreezeAccountWork`：受理后 app.js 主轮询 return、发送表单直接拒绝（notice）、life.js 18 秒轮询跳过；`registerWorkGate` 停在途工作；重载 `start()` 先查保存凭证恢复状态页 | 三处门断言 + 工作门停止/恢复 |

QA 实拍：网关未挂路由 → 如实「Not Found」+ 重试（截图 `pajio-qa-deletion-v5.png`）。全套 **143/143**（注销 5 项新测试含真实事件/CSRF/掉响应/围栏/门）。

## 第十七轮 · 六项注销复审修复 + 简报偏好/文本编辑/健康历史（2026-10-10）

**注销六项修复**（对照 zcode-review-next.md 与真实 gateway 源码）：

| 复审点 | 修复 | 测试 |
| --- | --- | --- |
| CSRF 假 cookie | 改为 `GET /auth/session` 取 `csrf` 字段（gateway.py:417 真实协议），无 cookie 假设；缓存复用 | fetch 序列断言 session→POST 且头值来自 session 回执 |
| scoped 键围栏 | `clearAccountCaches` 按 `pajio:<storage_scope>:` 精确前缀清理（真实业务键形态）；local 模式不清理任何键（旧凭证保留限制）；其他 scope/local 键不动 | scoped harness：本 scope 清、他 scope 保留、local 键保留、凭证存活 |
| saveFence 吞错 | 返回持久结果；失败如实「注销查询凭证未能保存在本机」且**不进入提交路径** | quota-throw harness：无确认按钮、错误可见 |
| 生产冻结门 | `workGeneration` 代数提升 + rememberComposer 持久写回前查冻结（旧异步不写回）+ `start()` 在业务轮询前恢复 submitted 状态页（app.js initialize 接线）+ 设置入口独立 `openPanel()` | generation 断言 + app.js 三处门断言 |
| not_submitted 死循环 | 「重新查看注销范围」→ 真实 `refreshPlan()`（重建凭证），不再 queryStatus 循环 | 源码断言 |
| 契约校准 | plan 四必需字段（含 user_id 严格 32hex）任一缺失整份拒绝；status 白名单 11 码 + completed 仅 verified+erased；未知回执拒绝 | 三态拒绝测试 |

**新合同接入**（QA 8891 真实路由点击验收）：

| 能力 | 实现 | QA 实拍 |
| --- | --- | --- |
| 简报偏好 | 简报面板偏好区：GET/POST `/api/briefings/preferences`；interests/priorities/sources(1-5)/max_items(1-3)；revision CAS + request_key 持久幂等（409 重读最新版）；来源状态区分 authorized≠读取 | ✅ 偏好加载（revision=1、五来源含飞书未连接）、表单全字段（截图 `pajio-qa-prefs-text-health.png`） |
| 文本编辑 | `workspace-text.js` + 文件行「编辑」入口：GET 读取（revision/sha/历史）；POST 保存（base_revision+base_sha256+request_key 持久）；409 保留草稿+「按最新版继续编辑」显式选择；recovery 只填草稿；imports 另存副本提示 | ✅ txt 因活动任务 editable:false → **如实显示 423 原因、无保存按钮、文字可读**；html 类型如实不支持（截图 `pajio-qa-text-health-v2.png`） |
| 健康历史 | 诊断段扩展：GET `/api/diagnostics/history`（samples/events 分页、覆盖率说明、读取不探测）；支持包 POST `/api/diagnostics/exports`（category + request_key 幂等、回执严格校验 id/sha256/filename、下载+24h 有效期、不声称已发支持） | ✅ 历史渲染含样本与事件；支持包创建 `pajio-diagnostics-*.json · 53.7KB · SHA256 …`（截图 `pajio-qa-health-export.png`） |

全套 **147/147**。8765 未动；QA 只用合成数据。

## 第十八轮 · 清单/日历视图/任务操作（2026-10-10，QA 保留数据重启后）

| 能力 | 实现 | 行为测试 | QA 点击 |
| --- | --- | --- | --- |
| 我的清单 | `views.js renderTaskLists` + 任务页挂载：GET `/api/task-lists` / `/{id}/items?offset&limit&revision` / POST `/change`（board revision CAS + request_key 持久幂等 + 回执 revision 严格递增校验）；create/rename/add/archive/完成切换（复用 life API）；清单 40 逐批、事项 100 分页、第二页带 revision；归档二次确认；409/失败如实保留输入 | web-import-goal #34 | ✅ 「我的清单（2）」两清单（待办/QA 原生清单验收）；打开事项列表「待办 事项」1 条；新建表单在位（截图 `pajio-qa-lists-tasks.png`） |
| 日历月/周/议程 | `life.js renderCalendarViews`：月视图沿用 FullCalendar；周视图固定周一–周日；议程从所选日期起连续 30 天跳过空日；跨日日程「此前开始/延续至次日」标签；跨日按记录 ID 去重；每批 100 条显式继续；视图偏好 sessionStorage 持久 | web-import-goal #35 | ✅ 月（FullCalendar 在位）→ 周（nav + 条目）→ 议程（条目渲染）（截图 `pajio-qa-calendar-views.png`） |
| 任务停止/撤回 | 任务行内按钮：active（starting/running/waiting_for_approval）显示「停止」（POST stop）；仅 `queued && queue_state !== cancelled` 真实队列回执显示「撤回」（POST cancel-message）；两键均两击确认；无内联事件处理器（CSP） | web-import-goal #36 | ✅ 1 个停止按钮（active 任务）、0 个撤回（无排队任务）——撤回按钮只在真实回执允许时出现 |

全套 **150/150**。QA 数据保留原状（读取+UI 渲染为主，写操作只做清单 create/rename 等可逆结构操作于既有合成清单）。日历系列（calendar-series）与离线归档恢复（offline-record-lifecycle）的 App 端 Web 侧对齐按合同要求属服务端已有接口——系列修改/例外 UI 与离线队列完整闭环待 Root 确认 App 完成后再对齐（当前合同明确「当前实现不涉及 Web/Desktop 的本机存储」的部分已由现有 409 双选择覆盖）。

## 第十九轮 · 五项合同完整接入 + 两项成功链补验（2026-10-08，QA 8891 新路由挂载后）

| 能力 | 实现 | 行为测试 | QA 点击/实拍 |
| --- | --- | --- | --- |
| 重复日程完整 UI | 新 `series.js`（window.WearingSeries）：单入口 POST `/api/calendar-series` 九动作闭集；系列管理列表（含已移除+恢复、每页 50 显式继续）；系列编辑器（频率/间隔/星期/次数/截止互斥、全天、时区折叠、例外列表+恢复原规则）；实例面板「修改仅这一次（override）/取消这一次（cancel）/恢复原规则（reset）/查看整个系列」；移除整个系列二次确认；月视图 FullCalendar 紫色事件（不可拖拽）+ 周/议程原生「重复日程」区段合并展示（只读投影不写 life 缓存）；request_key 单槽账本先持久后发、失败沿用同 key 取回、已知 400/404/409/422 换新 key；409 双选择（保留我的输入/采用最新内容） | series-ui #2–#5 | ✅ API 预验证（create/query/override/cancel/CAS 409/同 key 重放原回执/例外遗漏拒绝）+ UI 全周期：创建每日系列→月历显示→实例改期（服务端联动调整提醒锚点 08:30→13:30 实证）→越窗改修订触发 409→读最新→保留输入→重存成功（rev6）→移除→已移除列表→恢复→取消这一次→恢复原规则（截图 `round19-calendar-series-events.png`/`round19-series-manager.png`/`round19-occurrence-reminder.png`） |
| 归档/恢复持久幂等 | `life.js change()`：archive/restore 的 PATCH body 带 `request_key`，键 `pajio-life-action:v1:<identity>:<id>:<action>:<revision>` 经 WearingStore 先持久后发、成功清除；「移到最近移除」/最近删除「恢复」均两击确认（范围文案） | series-ui #6 | ✅ fetch 间谍实证 PATCH 体 `{revision,patch:{},action,request_key}`；**同 key 重放旧回执不重复归档**（记录保持恢复态 rev3、回执仍 rev2）；撤销链完整（截图见编辑器） |
| 任务同快照精确已读 | `activity.js openTask`：结果渲染完成后 GET `/api/tasks/{id}` 取 `activity_receipt`，仅仍在前台/账户有效时确认该精确版本；队列已取消（receipt null）保持未读；不再拿列表版本确认旧正文 | activity-ui #4（新增 2 例：回执版本≠列表版本、cancelled 留未读） | ✅ 任务页点击未读行 → 调用序列 GET activity → GET tasks/{id} → POST seen（实拍）→ 服务端核对 adacc682 已读、其余两条保持未读（截图 `round19-tasks-after-read.png`） |
| 每天自动简报 | `briefings.js`：偏好区内嵌「每天自动准备简报」details；GET/POST `/api/briefing-automation`；时间/补做窗口（30/60/120）/时区折叠；「自动安排使用偏好版本 X」与当前偏好版本对比提示；needs_resave 提示；最近回执≤7（本地日期/状态/简报摘要）；request_key 先持久；开启需偏好版本匹配（409 如实）、关闭不要求 | series-ui #7 | ✅ UI 开启 08:00/120 分钟 → 回执「下一次 2026-10-09T00:00:00+00:00」；偏好版本不匹配 409 与关闭保存均 API 预验证（截图 `round19-brief-automation.png`） |
| 具体时间提醒 | 新 `reminders.js`（window.WearingReminders）：GET/POST `/api/record-reminders/{target}`（target 闭集 life_32hex / recurrence_uuid_日期）；revision+record_revision 双 CAS；提前量准时/5/15/30/60/1440；request_key 持久+未知沿用+已知错误换新 key+成功后 GET 核实；status/reason/provider_status 如实显示（「不代表手机已展示」）；全天/无时间/已完成/已删除如实不可开；挂点：life 编辑器（待办截止/日程开始）+ 系列实例「这一次的提醒」（occurrence target） | series-ui #5 | ✅ 待办编辑器显示已安排（16:45）→ UI 改提前 60 分钟保存成功（16:00、journal 清除）；occurrence 提醒面板已安排态与改期联动实证（截图 `round19-life-editor-reminder.png`） |
| 文件编辑成功链（补验） | 既有 workspace-text.js | — | ✅ root 停合成任务后真实保存成功：「Web 编辑成功链验证」内容服务端持久化（text/revision/sha 回执） |
| 技能移除成功链（补验） | 既有 skills-remove 流 | — | ✅ qa-summary 预览（包修订+操作编号）→确认移除→列表变「已停用｜安装」（真实移除，423 阻断已消失） |
| 日历重渲染修复 | `renderCalendarViews` 重建容器前销毁旧 FullCalendar 实例（同视图数据更新时空网格 bug，视觉抽查发现） | series-ui #6（compile 测试兜底语法） | ✅ 同视图两次 openView 后网格与 11 个事件仍渲染（修复前空白） |

全套 **161/161**（新增 `tests/series-ui.test.cjs` 8 项 + activity-ui 2 项；含全部触达模块 vm.Script 编译测试，防 regex 测试漏语法错误）。8765 未动；只用合成 QA。

## 第二十轮 · 链接收藏 + 对话引用范围 + 系列多槽账本（2026-10-08，QA 新路由重启前先交付实现与测试）

| 能力 | 实现 | 行为测试 | QA 点击 |
| --- | --- | --- | --- |
| 链接收藏 | 新 `bookmarks.js`（window.WearingBookmarks）：GET `/api/bookmarks?query=&archived=&limit=30&cursor=`（字面搜索≤120、双列表 active/archived、签名游标 409→刷新重读、累计≥300 提示缩小搜索）；新建 POST /api/life（record 带 url、request_key 先持久）；编辑 PATCH（patch:{title,content,url}，url 清空→null 移除收藏属性仍保留笔记、409 读最新+输入保留、同 attempt key 重放）；归档/恢复两击确认+request_key；「打开网页」渲染前重验 URL、`target=_blank rel=noopener noreferrer`；validateUrl 与 App bookmark-url.ts 同规则（纯函数导出可测） | bookmarks-ui 8 项：校验 24 例（scheme/控制符/凭据/@%端口/长度）+ harness 3 流（创建幂等、409 输入保留+未知同 key 重放 rev 对齐、两击归档带 key） | ✅ QA 实证（2026-10-08，PID81367）：列表/搜索过滤/伪协议拒绝/新建（默认标题=主机名、journal 清）/409 读最新保留输入后 rev2 重存/归档→已归档列表→恢复（rev3→4 链）/url 清空保存移除收藏属性（服务端确认仍为 note rev6）/「打开网页」noopener 新标签实开（截图 `round20-bookmarks-list.png`） |
| 对话引用范围 | 新 `conversation-sources.js`（window.WearingSources）：GET `/api/conversation-sources?offset&limit&snapshot`（每页 20、续页同 snapshot、变化 409→第一页重读不拼快照）；范围预览（标题/开始时间/入场消息数/当前状态/效果说明/历史保留）；两击「确认停止引用」、取消不发请求；POST exclude 闭集四字段、revision 用页面快照版、request_key 先持久；回执严格校验（revision+1/excluded/history_retained/request_key 回显）；未知结果保留 journal、开面板自动同请求取回+「取回原操作回执」；4xx 清为 rejected 须重读重选；无恢复引用如实文案 | bookmarks-ui 3 项：闭集体/snapshot 校验/两击首击不发/未知重放同 body 同 key/journal 清 | ✅ QA 只读实证：两条合成来源渲染（标题/开始时间/入场消息数/状态）、「来源范围2」预览（效果说明+历史保留+无恢复文案）→取消「没有发出任何请求」；fetch 间谍证明全程零 POST（截图 `round20-sources-list.png`/`round20-sources-preview.png`）。排除 POST 已于 2026-10-08 补验（root 授权）：「来源范围2」两击确认（首击零 POST）→ POST exclude（journal 确认后才写、成功即清）→ revision 1→2、excluded=true、面板「已停止引用 · 22:49」；**排除后历史核验：API 与聊天 UI 双重确认两条来源消息仍可查看**（截图 `round21-sources-excluded.png`） |
| 入口接线 | views.js：我的「数据与身份」组新增「链接收藏」行（me-action=bookmarks→WearingBookmarks.open）；记忆页新增「对话引用范围」区段（data-sources-open）；index.html 双 side-panel + 脚本（bookmarks/conversation-sources v1） | bookmarks-ui shell 断言 + 冒烟：两页入口渲染、三模块加载无错 | ✅ 冒烟+验收复核通过 |
| 系列多槽账本（可靠性修复） | series.js：journal 键 `pajio-series-pending:v1:<identity>:<action>:<series|new>:<occurrence>`；同意图（忽略 request_key 指纹相同）沿用原编号重放完全相同请求；换内容先尽力结算同槽旧账；管理/编辑器/实例三入口各自恢复 create / update·archive·restore / override·cancel·reset 槽；旧单槽键一次性迁移；恢复后按当前视图重绘 | series-ui 多槽断言（slotOf/指纹复用/三入口/无单槽注释） | 已有第十九轮全链路 + 本轮回归 |

全套 **170/170**。QA 8891 新路由（bookmarks/conversation-sources）待 root 保留数据重启——**收到探活消息前不做点击验收**，本轮以 vm harness 行为测试 + 无写冒烟为准。8765 与真实账号未动。


## 第二十一轮 · 恢复请求用户展示与 saved 撤回（2026-10-08，recovery-presentation-contract）

| 能力 | 实现 | 行为测试 | QA 点击 |
| --- | --- | --- | --- |
| 恢复消息「重新核对」 | `app.js turnMarkup`：`message.kind==="confirmation_recovery" \|\| turn.message_kind==="confirmation_recovery"` 双通道识别（真实账本投影，不猜提示词）；saved 草稿按钮文案「重新核对」代替通用「继续这句话」；说明文案「这次重新核对还没有开始；点按钮并再确认一次后才会送出，不会直接执行原提案」；未开始原因（`turn.blocked_reason`）以 muted 段展示 | recovery-ui #2/#5（识别正则、恢复不出现「继续这句话」） | ✅ 真实材料实证：resume（全新 request_key）造出 draft saved 恢复任务，会话渲染「重新核对：QA 保存这份测试笔记？」+ 未开始说明 + blocked_reason（旧任务无账户归属的真实原因）+ 双按钮（截图 `round21-recovery-draft.png`） |
| 能力字段门控 | 开始按钮：`can_retry===false` 隐藏（旧服务缺字段沿用「继续这句话」旧语义）；saved 撤回：仅 `can_cancel===true` 开放（新操作，旧服务不开放）；queued 撤回：仅 `can_cancel===false` 显式关闭（旧 queued=true 兼容）；saved 原因展示 `turn.blocked_reason` | recovery-ui #5（b 旧服务兼容/c can_retry=false+d queued 四形态） | ✅ fetch 间谍实证：两击确认首击零任务请求（仅页面后台轮询 GET /api/conversation）；4 秒自动复位两按钮 |
| 显式重试（开始） | 分发器：start 需两击确认；提交前 GET `/api/tasks/{id}` 重读 `can_retry`（读不到只提示重读不提交不自动重试）；POST `/api/tasks/{id}/start` 用原任务；响应丢失仅提示「开始请求的结果未知；请重新查看这条，不要重复点击」 | recovery-ui #4 | ✅ 调用序列实证 `GET /api/tasks/{id}` → `POST /{id}/start`；QA 旧任务缺账户归属被服务端安全门拒绝——notice 如实显示完整原因、无伪造成功/无自动重试/任务保持 draft（合同「排队、未提交、运行状态不明保留原语义」路径）；**成功转 running 需 root 补可归属材料（遗留）** |
| saved 撤回（新能力） | 两击确认「再点一次确认撤回」→ 同一端点 `POST /api/tasks/{id}/cancel-message` | recovery-ui #4（同端点断言） | ✅ 闭环：两击 → POST cancel-message → 任务 stopped、能力字段归 false、会话「这条已撤回，没有开始执行。」、按钮移除；取消后账本生成新 needs_recheck 子卡（decision_24fac0ed…，root 的 App 材料完好） |
| 固定失败文案 | `failureText(turn)`：`failure_code==="execution_limit"` →「已达到本轮执行上限，现有结果和查看记录已保留；这件事尚未完成。」（与后端 EXECUTION_LIMIT_MESSAGE 同文）；failed 无码 → 通用失败说明；connection_lost/ambiguous → 连接说明；**全模块不再出现 `turn.error` 透传** | recovery-ui #3/#5（e 三形态 + raw error 不出现） | ✅ 补验完成（2026-10-08，root 隔离 QA 加入合成任务 7fcb4e28…「QA 合成失败展示：本轮执行上限（未调用模型）」）：服务端投影 failed+failure_code=execution_limit、error 字段缺失（不透传）；聊天视图渲染固定说明「已达到本轮执行上限，现有结果和查看记录已保留；这件事尚未完成。」+ 保留结果输出，无内部错误泄漏（截图 `round21-execution-limit.png`；未发生真实模型超限） |

全套 **176/176**（新增 `tests/recovery-ui.test.cjs` 6 项：编译门/识别与门控正则/不透传/分发器/turnMarkup 行为 5 形态/版本号）。app.js v48。QA 材料：本人全新 request_key 经真实 resume 端点创建（x-wearing-token 会话），取消仅作用于本人造的合成任务；8765 未动。


## 第二十二轮 · 首次认识流程（onboarding-contract，2026-10-09）

| 能力 | 实现 | 行为测试 | QA 点击 |
| --- | --- | --- | --- |
| 六步点选初始偏好 | 新 `onboarding.js`（window.WearingOnboarding v4）：见个面/日常/应用/兴趣与表达/带上资料/确认偏好；枚举与上限同 App；草稿（WearingStore `onboarding-draft:v1`）与确认（POST completed）分离；completed 编辑翻页零 POST、最终确认才提交（CAS rev）；skip=全空 skipped 不伪装；返回链「上一步/退出初始设置」；设置「初始偏好」入口 + maybeOffer（recommend_onboarding 且 draft 才弹、404 静默、每身份纪元一次） | onboarding-ui 12 项（编译/接线/文案/draft 先持久后发/completed 零 POST/409 双选择+较新守卫/未知同 key 同 body 重试+改意图拒绝/skip 全空/晚回执采用更新/epoch 围栏/纯函数/close 不回写回归） | ✅ 合成 profile rev3 全流：老账户不弹/设置入口/确认页摘要逐字一致/completed 编辑零 POST（fetch 间谍）/稍后继续+草稿恢复/带外 409→双选择→保留本机→rev5 成功→进入今天/终态还原原始值 rev7、journal 全清；六张截图 round22-onboarding-*；两个实测暴露的真缺陷已修+回归（close 回写草稿、返回链缺失） |
| 来源真实状态 | 日历如实「网页端不读取系统日历；请在手机 App 中连接」；飞书仅 apps 含 feishu 时出现，分支读真实 /api/cloud-apps/feishu（六态如实文案、已配置才可授权、官方域名校验、无开发者凭据表单、不声称已读取）；确认页摘要实时读取；404 文案对齐 App「这台服务还未提供初始偏好设置」 | onboarding-ui 文案断言（含无 App Secret 字面） | ✅ 确认页「飞书 · 尚未连接」「日历 · 在手机 App 中连接」如实呈现（截图 sources 页） |

全套 **200/200**＋独立复现脚本 **14/14**（/tmp/pajio-onboarding-web-independent-review.cjs，真实加载 scoped-store/account-deletion）。修复链：独立复核 1+4+5 项（A1 撤销中优先/B1 pending.body/B2 持久核实/B3 fresh 检查点/B4 单选直换/C5 规范化/C6 入口优先/C7 注销冻结/C8 围栏/C9 晚回执守卫）→ v5 引入票据共享 P1×2（loadFeishu/save 共用 generation 致 busy 永锁；保存中重开同病）→ **v6 会话围栏＋load/save/feishu 独立票据**；account-deletion v7 清理补 onboarding 两键；**pajio.css v18 修 `.ob-panel` 覆盖 UA `dialog:not([open])` 的幽灵面板真因**（生产与隔离实例均复现并消除）。QA 真实复验：未知结果→整页刷新→重试同 key（rev→8）、409→保留本机→保存→刷新零冲突、单选直换、点击序枚举序落库、飞书确认页不锁 busy；终态 rev13=原始基线。**桌面隔离验收**：独立 identifier 构建（/tmp 目录）自动连 QA 8891，设置入口＋面板完整渲染（AXPress 真实点击）＋幽灵面板消除；**确认保存闭环由 root CUA 实证**（2360×1640 实际像素坐标 [1695,1307]，rev13→14 completed 基线一致）；root 指出的「设置面板挡住今天」交接缺陷已修（onboarding.js v7 进入即关父面板，回归＋浏览器验证），待 root 桌面复验。新空账户自动弹出/skip 真实点击待 root fixture。详见 docs/evidence/pajio-onboarding-20261009/zcode-delivery.md（终稿取代早前被推翻的验收表述）。


## 第二十三轮 · 选定聊天导入（chat-imports 合同，2026-10-09，QA 8892）

| 能力 | 实现 | 行为测试 | QA 点击 |
| --- | --- | --- | --- |
| 选定聊天导入 | 新 `chat-import.js` v2（window.WearingChatImport）：解析器逐行移植（严格 ZIP/UTF-8/路径/CRC/全部上限，本地 fflate 0.8.3 vendor＋license）；本机预览（20 条分组/作者单选/附件声明未导入/重复警告）零网络；幂等确认（pending journal 先持久成功才 POST、重试先查 receipts/{key}、404 才补交、回执严格校验、deleted 不重发、未知保留同键）；批次详情逐消息来源编号；删除两步＋范围说明＋409 如实；入口×2（设置＋文件面板，进入即关父设置）；搜索 kind=chat_import 标签「聊天来源」＋深链；注销冻结门/身份围栏/独立票据；account-deletion v8 补两键清理 | chat-import-ui 17 项（真实 fixture 解析/五种拒绝/预览零网络/先持久后发/未知同键不重发/deleted/重复+删除+409/身份切换/冻结/P1-1×2/P1-2×2/交接/隔离） | ✅ QA 8892 全链：注入合成 ZIP→预览零 POST（spy）→选本人→确认（先查回执）→刷新读回→详情（来源编号）→搜索命中 chat_import→拦截 POST→未知结果（重复点击仅 1 次尝试）→刷新→同键重试成功→两步删除→列表清零；截图 round23-chatimport-*。**桌面隔离实例（8892）面板完整渲染＋交接；文件选择/确认点击未验**（WKWebView 合成输入不派发，留 root 实际像素坐标流程），分别记录 |

全套 **225/225**（保留 200 基线＋25 项）。两批复核全修：P1×2（异步边界后的存储/网络写前复核围栏；关闭/冻结/换身份作废票据并释放 busy；未知提交保留同请求键）＋P2×2（File.size 预检零读取即拒；journal 删除可验证＋discard 如实失败）＋接线三修（嵌套入口/关闭按钮未接线/文件父面板交接）。**Web 源码冻结于 chat-import.js v6**（含 root 桌面闭环后两处显示收尾：面板正文内边距/长内容滚动、导入时间本地可读）；浏览器复验含关闭真实点击（160ms 动画时序）与超大 File 预检。桌面文件选择/确认/删除 **root CUA 已验收通过**（真实 NSOpenPanel→预览零 POST→确认 chi_93944870…→读回→详情→两步删除→关闭，2026-10-09）。私密远控未实现未提供入口。详见 docs/evidence/pajio-context-20261009/zcode-delivery.md。


## 第二十四轮 · 真实设备远程接管 + 桌面公开登录（2026-10-10，remoteqa20261010）

| 能力 | 实现 | 行为测试 | 验收 |
| --- | --- | --- | --- |
| Web 远程接管 | 新 `remote-device.js` v4（能力白名单一律 ===true，缺字段/字符串/1 零输入）：状态机/transport/offer/首帧/显式开始操作/双确认交还逐项对齐 App；本地 session 对象捕获＋单调代数＋身份冻结；输入按 touch/keyboard/pointer/scroll 白名单＋黑边拒绝＋滑动 50..1000ms 协议截取；password 私密输入（超长保留不截断、重绘保草稿焦点、reset 清 DOM）；隐藏/window-hidden/离线/换身份/注销冻结立即停止，无自动重发；入口按 phone.*/computer.input 显式白名单 | remote-device-ui 14 项（239/239 全套）＋复核方 repro 4/4（v4 复跑） | 真实公网 A/B 归 root（本包已冻结待验）；8892 无私网路由——unsupported 如实，未冒充 |
| 桌面公开登录 | endpoint.rs：verify 仅对严格匹配正式服务接受 401 引导（TLS 默认校验不放宽、302 不跟随）；main.rs 主窗口导航允许官方 IdP 固定 realm（仅当连接正式服务；查询串允许、userinfo/fragment/端口拒绝）；默认地址改正式；本机 loopback 兼容不变；IdP/远程页零原生 IPC | Rust 13/13（伪装域名/端口/userinfo、错 issuer/路径、401 分支、自定义严格、本地兼容） | 真实登录由 root 验（QA 包 `/tmp/pajio-desktop-remote-qa-target/debug/bundle/macos/Pajio Remote QA.app`，预置正式地址，未启动避免抢设备） |

三批复核修复全记录于交付文档。**attempt 2（终复审 P2）**：恢复全设备独立暂停/恢复入口（observe-only/files-only/旧 connector 均可用，control_pending 禁用，原 /api/devices/control 流程不变），远程接管并列白名单；入口回归 5 项（实际 render 提取），全套 **244/244**；新冻结 hash 见交付文档（v4 证据未改动）。详见 docs/evidence/pajio-desktop-remote-20261010/zcode-delivery.md。**attempt 3（WK 阻断诊断）**：remote-device.js v5——全部停止原因固定可区分文案＋阶段标记＋严格诊断白名单（DOMException.name 枚举＋数字 HTTP 状态；原始 message/SDP/ICE/URL/body 零泄漏）；门禁/期限/重试不变；全套 245/245。
