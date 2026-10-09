# Pajio App 功能按钮审计（开发前基线）

日期：2026-10-07，Asia/Shanghai。审计范围：`clients/mobile/src` 当前正式入口 `/`、连接入口 `/connect`、App 引用的同源嵌入页和后端路由。只读检查源码、已有测试与 6 个本地 GET 请求；没有触碰用户数据，没有发消息、创建任务、录音、授权或通过 UI 操作。

**本文件是静态审计和接口可用性基线，不是真机逐按钮通过报告。** 当前工作树正在并行开发，下列行号/行为描述对应本次检查时点；修复后的证据应另记，不能把问题列表直接改成“全部通过”。`/experience` 和 `/voice-lab` 是独立预览/验收入口，不把演示回执计为正式能力。

## 结论与修复优先级

未发现可以据静态证据确认的 P0 数据串身份缺陷。发现以下 P1 功能闭环缺口：

| 编号 | 问题与用户后果 | 源码证据 | 修复/验收要求 |
|---|---|---|---|
| P1-01 | “同步记录”入口不可达。开发配对保留的普通 pending 队列提示“点同步后发送”，却没有能打开该 Sheet 的按钮。新建一条记录会间接 flush，但不应要求用户先造新记录。 | `Mobile.tsx:69,128,139,197,329,360`：`menu` 初值 false，只有 `setMenu(false)`；默认 `allowPending=!connection?.development`。 | 增加可达同步入口，显示待同步数/结果；离线→恢复连接→显式同步既有队列，不新增记录。 |
| P1-02 | 记录修改发生 409 后，输入虽保留，但继续保存始终使用旧 revision，原页没有取最新版本/合并途径。 | `Mobile.tsx:301-306` `saveEdit`；`synchronize` 只更新 records，没有更新 detail；`core.ts:261`。 | 保留编辑与最新记录并排核对/明确重新应用；禁止自动覆盖新版本；连续点击与切身份回执不得误导航。 |
| P1-03 | 点具体持续目标/定时条目仅打开通用 Web 列表，丢失所点 id；App 没有原生详情与控制，无法据此保证每项可管理。 | `PersonalPanels.tsx:46,60-61` `onManage:()=>void`；`Mobile.tsx:337`；`web/now.js:46-58`。 | App 选中详情保留 id/revision；原生暂停/恢复/结束/编辑接已存在接口；独立验收冲突、超时、切身份。 |
| P1-04 | 附件整理失败/暂停显示“可重试”，但记录详情完全没有重试动作。 | `Mobile.tsx:45,342`，`core.ts` capture 类型不含 id；后端 `capture_api.py:38` 已有 retry。 | 读取 capture id，明确“重试整理”；只在真实可重试状态显示；已有编辑保护与不重复上传原件。 |
| P1-05 | 记录 CRUD 不完整：只能新建、查看、编辑文字、勾待办；没有归档/恢复，也不能修改已有日程时间。 | `Mobile.tsx:301-306,342`；`core.ts:261`；`life_api.py:15-19,41` 支持 edit/archive/restore。 | 原生编辑覆盖 kind/time，归档可恢复，仍保留 revision 并发控制。不要用硬删除代替后端已有可逆归档。 |
| P1-06 | 非文本文件原件闭环未接：原生页只读小文本；“到文件页查看原件”不带具体路径，只开 Web 下载列表。服务以附件流返回，WebView 没有显式下载/分享处理。 | `PersonalHub.tsx:126-139`；`Conversation.tsx:70-114`；`web/app.js:286`；`app.py:740-744`。 | 不直接判定所有平台下载必失败，但不得宣称已可用；需 App 原生按所选文件下载、预览/系统分享，真实鉴权、过期和离线验证。 |

P2 缺口与边界：

| 编号 | 发现 | 证据与建议 |
|---|---|---|
| P2-01 | “技能”目前只是执行引擎状态说明，“聊天工具”明确是未连接说明。并非可安装技能/授权聊天工具的功能。 | `PersonalHub.tsx:195-201`；前端不得用静态卡片冒充目录或授权；先确认后端契约。 |
| P2-02 | “应用账号”只有已/未接入状态，没有 OAuth/凭据接入；登记设备没有详情/控制。 | `PersonalHub.tsx:180-194`；当前 `/api/identity.accounts=not_connected`。设备云端接口存在，但本地部署会返回 409，不能不分部署接。 |
| P2-03 | “带上你的资料”打开只读文件列表，没有上传通用文件；聊天加号称“照片或文件”但只给拍照、选图、补记记录。 | `PersonalHub.tsx:99`；`Mobile.tsx:367-371`；`IntentComposer.tsx` 加号 label。应接 DocumentPicker 与上传契约，或明确入口实际含义。 |
| P2-04 | 今日“图文简报”只准备一段消息，未产生简报文件/摘要结果专用呈现。 | `TodayPanel.tsx` `onDraft(...)`。这符合“准备消息”现有无障碍标签，但不等于自动生成/定时投递通过。 |
| P2-05 | 原件图片无 onError/retry，音频仅捕获同步 play/seek 异常，没有明确处理异步载入失败；可能仅白块/无反馈。 | `RemoteOriginal.tsx`。应在断网/404/过期真实检验。 |
| P2-06 | 记录页补录音在后台停止，但离开 capture 屏本身不显式 stopVoice。 | `Mobile.tsx:197-204` 对 AppState 有停止，`setScreen`/tab 没有。录音期间用户可返回其他页，麦克风可能继续到 180 秒。 |
| P2-07 | 初始 stored connection 解析/存储错误后 `ready` 始终 false，之后手动 connect 未 setReady(true)，补记保存会一直 disabled。 | `Mobile.tsx:181-192,285-294,327`。需要启动失败后的可恢复初始化而非只能重开 App。 |
| P2-08 | NativeConnections 获取位置无 UI 超时/取消；iOS 定位长期不返回时本页其他动作被 busy 锁住。 | `NativeConnections.tsx:125-151`。按原生API可取消性设计有限等待与重试，不伪造坐标。 |
| P2-09 | 记录保存/勾选缺少同一记录同步锁；重复点击可能一成功、一冲突，最后出现“未确认”却已成功。 | `Mobile.tsx:295-306`。目标/定时也需要单操作锁，不能仅依赖 rerender 后 disabled。 |
| P2-10 | 字体/缩放已在 Native ScrollView 与嵌入页限制页面手势，Dynamic Type 保留；但系统无障碍缩放不应被当作产品 bug。 | `Mobile.tsx:312`；`Conversation.tsx:73`；`web/mobile-host.js:7-14`。需双指实测页面不能任意缩放、字体仍可读。 |

## 逐入口矩阵

“已连线”只代表源码有实际 handler 与相应能力，不代表本审计已点击验收。“嵌入”代表仍由同源 WebView 实现。

### 聊天、语音与导航

| 按钮/入口 | Handler 与能力 | 当前边界/证据 |
|---|---|---|
| 底部 聊天/今天/任务/记忆/我的 | `BottomNavigation.onSelect → Mobile.selectTab → router.setParams` | 5 项真实路由；切页保留 RetainedConversation；`Mobile.tsx:71-89`。 |
| 顶部小熊/进展 | `ActivityReview.onOpenChange(true); refresh()` | GET activity，原生 Modal，历史/待处理分组；只展示实际状态。 |
| 关闭进展、刷新、结果项 | `onOpenChange(false)` / snapshot.refresh / `onOpenTask(task_id)` | 结果项按 id 跳嵌入对话/详情，Web `activity.js:50-79` 成功打开后才 seen。 |
| 搜索对话 | `ReviewRequest{target:'search'} → WearingHost.openSearch` | 嵌入当前已载入对话 DOM 搜索；不是全身份历史搜索。 |
| 搜索上一处/下一处/完成 | `navigateMatch` / `closeSearch` | 无匹配 disabled；切页关闭；`web/mobile-host.js:53-128`。 |
| 设置 | `setScreen('settings')` | 原生 SettingsHub。 |
| 返回 | `Mobile.goBack` | 记忆文件层级、衣橱、设置、记录专门分支；Android BackHandler。 |
| 切换文字/语音 | `IntentComposer.onKeyboard` | 原生 TextInput 与长按手势，不借助系统键盘听写。 |
| 长按语音/上滑取消/无障碍启停 | `HoldVoiceGesture → useVoiceInput/VoiceSession` | 流式 PCM、原件保留、松开才带入文字；已有单测覆盖启动竞态、背景、取消、身份隔离。真实语音识别正确率不在本次审计。 |
| 继续识别录音/带入已识别文字 | `voice.retry()` | 显式重试；识别失败不自动反复计费；`voice-session.test.ts`。 |
| 发送 | `VoiceComposer.send → command(kind:'send')` | seq/page/context guard；用户明确动作；offline/empty/sending禁止。发送后是否 Agent 正确执行仍需业务验收。 |
| 恢复本机草稿 | `edit(current + recovery.text)` | 不直接覆盖现有草稿；版本化备份清除，`native-draft-backup.test.ts`。 |
| 聊天相机 | `onCapture → capture + photo(true)` | 实际跳补记页，拍照后须“记下”；不是原生聊天多模态附件。功能成立但交互与普通聊天附件不同。 |
| 加号→拍一张/选择照片/补记一条 | `photo(true/false)` / capture | 有真实照片选择；无通用文件选择，见 P2-03。 |
| 重新打开对话 | `Conversation.retry → web.reload()` | 服务错误、12s慢加载、进程终止可重试；配对过期要求重新配对。 |
| 收起提示 | `setMessage('')` | 仅隐藏消息，不删除原件/队列。 |

### 今日、日历与记录

| 按钮/入口 | Handler 与能力 | 当前边界/证据 |
|---|---|---|
| 更新今日概览 | `useActivitySnapshot.refresh` | 只更新 activity；日程来自 Mobile 15秒同步 records，并非该按钮直接刷新全部来源。 |
| 今日结果/任务/等待处理项 | `onTask(task_id)` | 同一任务 id 跳转；保留 stale 标记，不把历史写成最新。 |
| 完整日历/今日事件 | `setScreen('agenda')` / `open(record)` | 日历只显示共用 records，不自动读取苹果日历。 |
| 准备图文简报 | `prepareMessage` | 安全追加编辑草稿，用户再发送；见 P2-04。 |
| 日历/笔记 tabs | `setScreen('agenda'|'notes')` | 真实列表。 |
| 上个月/下个月/今天/日期格 | `moveMonth` / `setSelectedDate` | 日期算法已有 calendar tests（跨月、全天、时区）；选日期后筛 records。 |
| 手动补充日程 | 修改 capture kind/start/end 后跳 capture | 保留原草稿文字，设置所选日期 09:00；不能创建重复空事件。 |
| 记录行 | `open(item)` | 展示当前 snapshot；未通过单条GET刷新，可能过时。 |
| 拍一下/选图/说一句/说完了 | `photo` / `recordVoice` / `stopVoice` | 权限、媒体大小、最多4份；同步锁、身份/页状态检查；录音文件本机保存。 |
| 原件移除 | `changeForm(media.filter)` | 从草稿引用移除，本机文件未即时删除；可恢复与清理策略需单独定义。 |
| 笔记/任务/日程类型 | `changeForm(kind)` | 使用 canonical kind，实际支持事件起止时间。 |
| 起止时间 | `TimeField.onChange` | native date/time picker；保存时 end>start 校验。 |
| 让 Pajio 整理原件 | form.organize | 入队传服务器组织开关；未勾时保留原件，不调用整理。 |
| 记下 | `save → Outbox.enqueue → synchronize(true)` | 幂等 id、原件先保存、队列与清草稿原子batch；离线可保留。 |
| 再试一次（本机队列 attention） | `outbox.retry → local → synchronize(true)` | handler 缺 catch，应补存储错误提示；普通 pending 没这个入口，见 P1-01。 |
| 同步记录 | `refresh → synchronize(true)` | 代码存在但入口不可达，P1-01。 |
| 完成/重开待办 | `toggle → api.update({completed})` | 在线请求、revision；缺重复点击锁，P2-09。 |
| 保存修改 | `saveEdit → api.update` | 仅 title/content，P1-02/P1-05。 |
| 接着和 Pajio 聊 | setChatRecord + conversation URL life_record/revision | 真实记录上下文；页面 key变化会重建 WebView，草稿由context隔离。 |
| 原录音播放/暂停 | `RemoteOriginal.AudioOriginal.toggle` | 鉴权源与播放状态；异步失败未完整处理，P2-05。 |
| 整理失败重试/归档/恢复/改时间 | **没有入口** | 后端已有 retry/archive/restore/edit 能力，P1-04/P1-05。 |

### Agent任务、目标、定时

| 按钮/入口 | Handler 与能力 | 当前边界/证据 |
|---|---|---|
| 任务/定时 tab | `setTaskTab` | goals 是子页，无独立 tab，但由“持续推进的事”进入。 |
| 刷新任务/重试/加载更多 | `AgentTaskList.manualRefresh/loadMore` | cursor冻结第一页、409提示刷新、scope与generation guard；activity-pages tests。 |
| 具体任务卡片 | `onTask(task_id)` | 嵌入定位具体turn或loadKeep；保留原任务id。 |
| 空列表“交代一件事” | `prepareMessage('帮我处理这件事：')` | 只追加草稿、不执行空白任务。 |
| 持续推进的事 | `setTaskTab('goals')` | GET goals映射；具体条目丢id，P1-03。 |
| 目标/定时每项与管理 | `OngoingPanel.onManage` | 通用嵌入 keeps panel；定时只scroll到section，P1-03。 |
| 四种推荐安排 | `ScheduleSuggestions.onDraft` | 可修改请求，用户发送后才交给Agent；不是直接创建成功。 |
| 创建/改动/暂停/恢复/结束定时 | App **未原生实现**；嵌入 `schedules.js`有完整form与PATCH | 后端 `/api/schedules` POST、`/{id}` GET/PATCH已存在；当前后台服务必须持续运行、结果回对话，不能承诺推送。 |
| 目标创建/补充/继续/暂停/完成 | App **未原生实现**；嵌入 keeps/task交互 | `/api/goals` POST + `/{id}` GET + `/{id}/control` POST。 |
| 任务确认/停止/继续处理异常 | 嵌入 conversation/task cards | 后端 `app.py:843-870` 的 start/cancel-message/refresh/stop/approval/verify/resolve；需原生桥接真实状态而非重复执行。 |

### 记忆、文件、设置、连接、衣橱

| 按钮/入口 | Handler 与能力 | 当前边界/证据 |
|---|---|---|
| 刷新记忆 | `MemoryLibrary.refresh` | memory与workspace allSettled；区分没读到和0条，按endpoint+identity remount。 |
| 关于你/长期记忆/查看记忆 | router memorySection | 真实 `/api/memory`，无伪造人物内容；available=false有错误/重试。 |
| 纠正这条/补充记忆 | `memoryCorrectionDraft → prepareMessage` | 用户可编辑再发送；不会直接改原记忆；已读entry节选标注。 |
| 文件夹/子文件夹/文件/返回层级 | workspaceEntries + router params | 当前接口最多200文件，truncated诚实提示；safeWorkspacePath防越界。 |
| 小文本预览/重新读取 | `PersonalHubApi.textFile` | ≤256KB whitelist，实际GET/身份头；不会执行HTML/JS。 |
| 到文件页查看原件/资料与文件/文件空间 | `onFiles → openReviewTool('files')` | 目标文件路径没有传递；嵌入下载未经真机验证，P1-06。 |
| 带上你的资料 | 同通用files列表 | 不具备通用上传，P2-03。 |
| 连接常用应用 | `setScreen('settings')` | 只进设置总页，不直接到 apps；泛化跳转但没有静默。 |
| 聊聊你的近况 | `setScreen('conversation')` | 保留当前草稿，不注入空提示。 |
| 连接应用/设备/技能/聊天工具 | router hubSection | 应用只读状态、设备只读登记、技能/聊天工具占位，P2-01/P2-02。 |
| 照片/系统日历/位置（设置） | `onNative` | 三者都进同一个本机能力页面，没有定位到具体卡片；仍可操作。 |
| 允许日历/读取日程 | `readCalendar` | 点击才请求权限，读取未来7天并预览；不自动传服务器。 |
| 全选/取消全选/单条日程 | `setSelected` | 可选择本次带入内容；撤销权限后清结果。 |
| 日程带入对话 | `addDraft('calendar')` | 二次权限核验，长度校验，用户再发送。 |
| 获取一次位置/位置带入 | `readLocation` / `addDraft('location')` | 一次Balanced定位，显示坐标、精度、时间；不背景跟踪；P2-08。 |
| 打开系统设置 | `Linking.openSettings` | 权限不能再弹时提供真实恢复入口，错误可读。 |
| 选择照片（本机能力） | capture + `photo(false)` | 实际picker，保存原件；不直接遍历相册。 |
| 连接与身份/身份chips/连接Pajio | `connect → bootstrap → activateConnection` | 保存旧草稿、读取目标draft后才曝光新identity；重置详情/活动；正常HTTP仅loopback，开发LAN需短token，私人HTTPS支持。 |
| `/connect`验证并连接/暂不连接 | bootstrap只读验证 + storage.put + router.replace | 开发配对只给原生，过期/失配可读报错；无自动发送历史队列。 |
| 浅色/深色/跟随系统 | `setPreference` | 持久化成功后变更；失败保留旧值并可重试。 |
| 衣橱入口/8套试穿/就穿这套/返回/重试 | `preview` / `WardrobeSession.save` / load | 预览不改已选、明确保存、scope隔离、失败保留旧服装；重复保存锁。动画不算业务状态变更。 |

## 已有测试证明什么

未在本审计重复跑整套测试；只读查看测试代码。已有 `voice-session`、`voice-stream`、`hold-voice`、`native-composer`、`native-draft-backup`、`sqlite-store`、`mobile-capture-lifecycle`、`activity-store/pages/presentation`、`calendar`、`personal-hub`、`nativeConnectionsModel`、`wardrobe` 等测试，覆盖协议校验、去重、原件保留、内存/存储错误、背景竞态、身份隔离和日期算法。**这些测试不能替代UI入口可达性、设备权限真实结果、WebView下载、系统分享、真实ASR延迟与后台任务结果验收。**

已有保护应保留：

- `web/now.js:14-44` 的外部草稿是 append + pending journal + received receipt；不会悄悄替换现有内容。
- `NativeDraftBackup` 清除精确版本，不会把新输入被旧回执擦掉。
- Capture先保存原件/草稿，Outbox原子提交，identity切换前持久化；服务断连只试队列第一项，不每条反复请求。
- `VoiceSession` 不在挂载时开启麦克风/重新识别；身份切换后结果留旧scope。
- native memory/file parser区分 unread/unavailable/empty；不编连接数据。
- Agent任务分页保留cursor对应快照；新第一页不能与旧历史拼接。

## 本地服务只读观测

仅 GET `http://127.0.0.1:8765`，身份头 `daily`；不记录 token/文件内容/用户日程。

| 接口 | HTTP | 脱敏观测 |
|---|---|---|
| `/api/bootstrap` | 200 | version 0.2.0，deployment local，configured true，2个身份。 |
| `/api/runtime` | 200 | running true，product.applied true，model.state configured。 |
| `/api/identity` | 200 | 2个登记设备，accounts not_connected，phone/email contacts not_connected。 |
| `/api/capture/capabilities` | 200 | OCR apple-vision；transcription doubao-seedasr-2；录音上传能力 recorded-utterance；原件private；最大15MiB/180秒。该接口不单独证明流式websocket或实际ASR通过。 |
| `/api/workspace` | 200 | 2份文件，truncated false。 |
| `/api/schedules` | 200 | 0项安排，execution service_required，delivery conversation。 |

## 建议本轮验收顺序

1. 修复可达同步、记录编辑冲突/时间/归档恢复/整理重试，再测离线与跨身份。
2. App原生目标/定时详情及控制，使用现有服务revision契约；选择项保持到详情，禁止通用列表替代。
3. App原生文件浏览/下载/分享，普通文档上传单独补实际契约；不把打开Web列表作为验收。
4. 技能/聊天工具/云应用先按真实后端能力明确可用与待接入边界；未实现不要假装可授权。
5. 才进行每个按钮的模拟器截图与可控测试数据验收；物理权限、照片、录音、系统分享另行真机验收。

ZCode 分工边界：Web/Desktop开发可只读App源码复用行为定义；App源由主代理维护。嵌入聊天的 `web/mobile-host.js`、`now.js`、原生composer协议属于跨端契约，修改需核对 App 行为，不能让 Web 重构替换掉 native-host接口。

## 记录编辑实现后的独立测试（同轮追加）

主代理随后实现 `RecordDetail.tsx`、`record-editor.ts` 与 record/update/archive/restore/retry API。本审计代理只新增测试，未改这些实现。

- `record-editor.test.ts` 14项：date-only保持、带offset时间仅改文字时不动时间、实际改时的顺序/ISO、单端改时、空白/12000字边界、200字标题、patch不改状态/revision、dirty判断；以及同key跨卸载读写排队、不同身份互不阻塞、失败释放、旧队列结束不能删除新队列4个并发案例。
- `record-api.test.ts` 15项：真实调用参数的GET/PATCH/POST、URL编码、identity与Bearer/CSRF头、精确revision/action、归档恢复版本、403仅刷新并重试一次、409不自动覆盖、缺身份不写、null/错误id/残缺回执拒绝、网络与非JSON错误。所有数据与fetch transport均为合成，未调用真实写接口。
- 已执行 `tsx --test src/record-editor.test.ts src/record-api.test.ts`：**29/29通过**。
- 已执行这两个文件的 ESLint：exit 0；App `tsc --noEmit`：exit 0。
- 只读复核促成按key共享草稿队列，以及恢复归档时保留未保存的编辑；这些通过测试/代码审查证明，不替代归档/冲突/恢复的模拟器操作验收。
- 以上不改变前文“开发前基线”性质，其他功能闭环需由主代理补独立验证。
