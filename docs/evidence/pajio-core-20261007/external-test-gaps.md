# Pajio：对外测试能力矩阵

更新于 2026-10-08。本文件按当前源码与隔离验收更新；`button-audit.md` 是最初审计快照，不能继续据其判定已补齐的按钮仍缺失。代码与合成测试通过不等于真机、生产环境或外部服务验收通过。

产品依据仍为 `PRODUCT.md`、`DESIGN.md`、`docs/plans/app-first-experience-2026-10-06.md`、`life-tools-and-native-capture-2026-10-04.md`、`ios-personal-alpha-2026-10-06.md`、`now-intent-entry-2026-10-06.md`、`product-standard-review-2026-10-06.md`、`voice-streaming-2026-10-07.md`、`product-brand-ux-strategy-2026-10-07.md`、`product-validation-kit-2026-10-07.md`，以及 `docs/connector-service.md`、`device-connectors.md`、`personal-continuity.md`、`personal-memory.md`。名称 Pajio、睡衣小熊、C 图标、五入口和 App 优先采用用户后续决定；历史视觉和开发机状态不覆盖当前事实。

## 当前判断

本轮已把原来大量“去聊天询问”的入口接成实际操作：记录编辑与冲突、文件导入/分页/原件分享、目标和定时创建、图文简报与结果选择续办、系统日历/提醒、手机原生命令队列、记忆管理、技能安装/启停/移除、飞书应用、聊天渠道、设备控制、通知登记与持久事件、过期确认恢复、数据导出、搜索、脱敏诊断。系统分享扩展、私有收件箱、逐文件导入、聊天待用文字、链接收藏与对话引用范围已接入 App；Android 选图页面被系统回收后的恢复也已补齐。这些是软件实现范围，不替代新原生包与真机验收。

**尚不能宣布可以直接邀请外部用户。** 仍需真实签名包、有效公网常驻实例与 IdP、两个独立租户的端到端验证，以及通知/云应用/设备的真实授权与到达证据。首轮人数未定，iPhone 为主，也含 Android；Apple Developer 尚未开通；Android 已生成内嵌 JS 的 ARM64 独立测试 APK，并以保留数据的安装命令成功装到 MI 6X，但使用 Android Debug 测试签名，尚未完成真机功能验收。账户注销已有控制面、gateway、App 主入口与受限生产 adapter 软件；真实资产登记、专用凭据、外部撤权与实际清除仍未验收，共享空间按用户撤权和聊天机器人上游撤权还存在软件边界。本机日历/提醒已有前台单向同步，健康历史和诊断导出已实现；自有重复日程、任务清单、离线归档恢复、自动简报、单条日程/待办提醒、链接收藏和对话来源排除已有软件实现；双向同步与支持收件仍未完整接通。对话来源排除只控制后续上下文与检索，不等于历史、备份或其他副本彻底删除。已完成的软件不再列作“尚无实现”。

### 状态标记

- **I**：对应软件已实现，可能仍需本轮原生点击/回归；不是市场验证或对外测试通过。
- **B**：仍需软件开发；**C**：本人/提供方的真实授权、凭据、身份、付费或签名；**V**：真实环境验收缺口。
- **P0**：外测交付/安全门槛；**P1**：本轮核心能力；**P2**：产品完整性或后续远景，不能展示为已经可用。

## 全部产品能力

| 业务承诺／入口 | 当前源码与实际接通范围 | 剩余工作与验收边界 | 状态／优先级 |
|---|---|---|---|
| 新用户登录、身份与退出 | `cloud/mobile_auth.py` 一次性 PKCE handoff；gateway OIDC/原生会话/退出；`session-protocol.ts`、`native-session.ts`、`CloudSessionPanel`、SecureStore、Bearer/租户绑定已接；WebView 会话有固定租户校验 | 正式 IdP/回调域、真实两用户首次登录、过期重登、退出后旧凭据拒绝；本机 LAN 配对只供开发，不算账户系统验收 | I+C+V／P0 |
| 独立云实例持续运行 | tenant worker、gateway、控制面、私有卷与租户边界已有；原生 WSS 路由已新增 | 当前云实例不在线，见下方最新事实；常驻部署、HTTPS、备份恢复、第二租户隔离、关 Mac/杀 App 后继续运行尚需实证 | I+C+V／P0 |
| 正式 iPhone 安装 | Pajio 显示名、C 图标、原生 SDK57 构建、模拟器安装路径已有；模拟器持续更新候选包 | 目前 **0 valid codesigning identities**，没有新签名外测包证据；用户于10月8日确认Apple Developer尚未开通。外测人数未定，iPhone为主、也含Android；Apple/EAS归属、分发、干净安装和升级保留数据要验收 | I+C+V／P0 |
| 正式 Android 安装 | 本人批准SDK许可后完成隔离JDK17/官方SDK安装，Gradle debug与release构建成功；ARM64独立测试APK内嵌4113模块，无需Metro，签名v2及16KB对齐检查通过。23:13以标准文件安装成功装到MI 6X（Android9/API28），系统回读0.2.0/versionCode1。未改iOS工程 | 使用Android Debug测试签名，正式发布签名/升级保留数据及权限/分享/通知/返回/Activity回收真机验收仍待完成。5项Expo patch建议统一冻结后再做双端构建；Android短期LAN HTTP开发配对目前被原生网络策略阻止，需要有效HTTPS或隔离QA专用转发 | I+C+V／P0 |
| 文字输入、草稿和回执 | 原生 composer、对话桥、持久 message handoff/outbox、同 request ID 恢复与队列已有 | 正式云会话全链、长中文编辑、杀进程/断响应的原生回归；排队与执行完成必须区分 | I+V／P1 |
| 语音输入 | 豆包 Seed-ASR 2.0、边录边传/文件回退已接；用户确认过一次真实识别。gateway `WebSocketRoute`、tenant WSS 与私有 Host 校验本轮已补 | 正式账号 Wi-Fi/蜂窝、来电/后台/耳机/连续短句、末尾词；至少 40 条语料统计数字错误与 p50/p95。单次识别不代表性能验收 | I+C+V／P1 |
| 图片、音频、原件 | 相机/选图/音频导入、私有原件、capture retry、Outbox关联与现有记录回执；Android `getPendingResultAsync` 恢复已接，打开选图前持久绑定账户/身份/草稿，固定媒体ID去重、原件完整性核对及注销围栏 | 真机拒权/部分照片权限/后台重开/Activity回收；恢复只回原草稿、不自动发送。SDK消耗式pending读取到JS持久化之间再次进程死亡、系统清除缓存仍可能丢失结果，不假报保存成功；相机等原生能力仍需签名包验证 | I+V／P1 |
| 通用文件导入 | `workspace_upload.py` 20 MB 真实导入，身份隔离、幂等、原文件不覆盖、原子发布；App DocumentPicker/本地请求恢复/实际回执已有 | 两份真实测试 PDF/Office 导入→模型确实读取→比较结果来源可打开；上传回执不等于模型已理解文件 | I+V／P1 |
| 文件列表、搜索、分享 | `workspace.py WorkspacePager`、`workspace_api.py` 服务端文件名搜索、200+分页、绑定 scope 的安全 cursor、目录变化409；原生预览/系统原件分享与“读这份文件”明确带路径草稿；UTF-8 Markdown/txt编辑、CAS、恢复历史与冲突比较已有原生成功验收 | 大目录/慢磁盘原生体验；多 worker 需路由粘性或共享游标。内容搜索仍经 Agent 读取，不冒称文件内容已建立全量索引 | I+V／P1 |
| 系统分享输入 | `share-intake.cjs`、iOS Share Extension + App Group、Android SEND/SEND_MULTIPLE 已实现；App 私有队列、预览/选身份、显式导入与聊天待用文字已接线。所有附件逐个 `uploadWorkspace`，保存精确回执后生成 `organize=false` 笔记；待用文字显式追加现有草稿，支持切换/移除待用副本、稳定请求 ID 与重启去重 | 需要包含扩展的新原生包与 App Group 签名；真机 Safari/照片/Files、冷暖启动、取消、杀进程、Android URI 授权、多文件失败重试与换身份验收。4 文件、单个15 MiB、合计30 MiB、文字12000单位；不会自动发送或运行模型。Android SDK 无原生事件 ID，同时抵达的相同分享可能合并 | I+C+V／P1 |
| 自有日程 | event/revision、全天处理、月/周/30日议程、来源筛选、100条追加加载、创建/编辑/归档/恢复；CalendarPanel 已挂 App | 自有每日/周/月/年规则、结束条件、单次例外/取消/恢复与系列CAS已实现；App 已点通每周3次、只改本周不改下一周、原生日期选择器与全天单次修改；更多时区边界仍待验收 | I+B+V／P1-P2 |
| 待办、笔记、记录 | 基础CRUD、任务完成/重开、归档/恢复、详情草稿、409冲突、记录关键字检索已接；清单分组、排序、跨清单移动/移除及双分页已实现 | App已点通清单创建、加事项、完成、归档、恢复；两台真实设备并发与离线重启仍待验收。链接收藏已独立列下行，不再作为未扩展字段 | I+V／P1-P2 |
| 链接收藏 | 原life笔记增加可选URL、独立标题/备注；收藏列表/字面搜索/签名分页、创建/编辑/归档/恢复、离线队列、CAS、未知回执原键重试；系统分享显式“收藏链接”、全局搜索与Agent life工具共用原记录。App导航与详情已挂线 | 新iOS候选在模拟器已点通中文编辑/保存/归档/恢复及显式打开Safari；实体手机系统分享与两设备冲突待验收。仅保存HTTP(S)链接和用户内容，不自动抓网页/标题/预览，也不把普通笔记里的网址自动变成收藏 | I+V／P1 |
| 已有记录离线修改 | `record-mutations.ts` + `record-sync.ts`：按 scope 的持久 patch 队列、稳定请求 key、revision、回执合并、显式保留本机或远端、远端 tombstone 不复活；root/个人能力 agent 正在完成原生回归 | 队列已扩展显式 edit/archive/restore，并保留原 revision/attempt key；App已点通联网归档/恢复。跨进程断网恢复与两台真实设备冲突仍待验收 | I+V；边界 B／P1 |
| 本机系统日历 | 原生读取/系统编辑器、显式选择来源、前台60秒读取、外部对象与实例映射、幂等批次、CAS冲突保留；副本进入 life_records | 过去7天到未来30天的单向快照，每来源500条；不推断缺失为删除，不回写系统。双向同步未实现，真实系统权限/跨设备仍待验收 | I+B+C+V／P1 |
| 系统提醒事项 | iOS原生管理、版本/草稿恢复、Agent原生队列、显式所选列表前台单向同步已实现 | SDK57不返回allDay时保留未知，不伪造精确截止时间；真实列表/日期/前后台回读仍待验收，双向和任意后台同步未实现 | I+B+C+V／P1 |
| 位置与照片 | 系统选取/单次定位、权限检查、用户预览后入草稿，身份切换迟到结果保护；Agent 可经原生队列请求用户每次确认的前台单次位置 | 相册仍由用户主动选择；不能任意后台读位置/批量相册。结构化地图接续与真实系统权限/前后台回归仍待验证 | I+B+C+V／P1 |
| 云 Agent 使用手机原生能力 | 持久原生队列、每次写入/位置确认、租约/claim、系统回读/journal、未知结果核对；新goal/schedule source及后续step/occurrence继承可信创建owner，撤销手机授权仍拒绝 | 当前NativeActionSession/Panel只对iOS开启，Android不能宣称同等云Agent原生执行能力；真iPhone授权/回读/弱网验收仍待完成。旧无主后台源必须重新创建，重试不会补授权。已有系统记录修改/删除必须引用本任务读取结果、手机逐次确认、写前快照复核及写后回读；重复日程仅单次。重复提醒、提醒日期修改、地理闹钟及任意iOS后台执行仍不支持 | I+B+C+V／P1 |
| 目标持续推进 | GoalBook/Coordinator、revision、轮次、等待条件；原生创建、详情、暂停/继续/补充/完成、增轮；稳定创建请求 key | 真云多轮/跨日/重启，改条件后旧步骤不得继续；达到预算的模型实际拒绝证明 | I+V／P1 |
| 定时安排 | schedule API create/edit/pause/resume/cancel；原生表单、时区、单次/周期、陈旧 revision、创建丢回执恢复已接 | 5 分钟后真实跑一次→改时旧时间不跑→杀 App 后通知；外部事件来源持续同步另需实现 | I+V；外部事件 B／P1 |
| 跨小时决定与恢复 | DurableConfirmations + confirmation guard：原卡持久、过期 needs_recheck、唯一只读恢复 task、新卡再核对、单次 permit；App 原生恢复卡已接 | 恢复写入仅 life/goal/schedule 的受控原子 revision 工具；任意终端/外发/付款/设备输入不在恢复许可集合，不能宣称通用持久工作流已经完备 | I+B+V／P0-P1 |
| 离开 App 后收到通知 | expo-notifications、设备登记/停用、持久 event/outbox、ticket/receipt、失效 token 撤销、会话期限 lease、精确身份/task 深链与冷启动接线已有。安静时段、可信账户 owner 隔离、generation、operator 撤销及到期 `awaiting_registration` 恢复均已实现 | EAS project/APNs/FCM/签名、真实设备到达；有效会话重新登记后只发送仍有效的等待项，主动停用/退出/换账户的旧项不补发。拒通知时 App 内仍能回看；provider receipt 不是手机已显示 | I+C+V／P0 |
| 按记录时间提醒 | 具体日程与有截止时间的待办、单次重复日程提醒已接原通知队列；时间改变重算，完成/归档/取消原事务停用，恢复不重启旧提醒；owner、revision、稳定请求、安静时段与通知深链已有测试 | 原生设置与真实签名设备通知到达分别验收；全天或无时间不猜默认时刻，不声称已支持整个系列批量提醒 | I+C+V／P1 |
| 今天图文简报 | 日期/时区/版本/来源、真实任务/artifact、历史；兴趣/关注重点/来源/首屏重点数量revision偏好与未知回执恢复已接。原生已保存来源和重点数量并重开核对 | 每日自动简报已接既有调度器，固定时区、补做窗口、同账户同日去重、关闭App后由服务执行；正式模型/来源、跨日实证仍待验收。偏好是内容要求，不是工具权限边界；QA不是模型输出 | I+V／P1 |
| 跨对象搜索 | `SearchBook`/`search_api.py` 按身份完整数据库搜索 task/record/message，签名分页、取消旧查询、精确问答/记录/任务深链；文件页承接服务端文件名查询 | 语义/全文索引未实现；目前数据库字面搜索有1.5秒预算，超时可见503，不返回假空；大数据量索引仍需后续工作 | I+B+V／P1-P2 |
| 原生结果查看与分享 | artifact client/API、原生结果入口、授权下载、sha256/大小核验、系统分享、HTML sandbox；root 已挂载 | 真机 PDF/HTML/媒体、来源/旧版、返回原草稿/滚动位置；生成脚本无权自动取得 App 权限 | I+V／P1 |
| 在结果内作选择并继续 | `artifact_choices.py` + `ArtifactChoicePanel` 在产品原生区显示最多8个结构化选项，预览完整要求后确认；选择、后续任务/message handoff、可信 task owner、事件在同事务持久化。App 提交前保存请求，丢回执同 key 取回，版本/身份/活动任务冲突拒绝 | HTML 保持 opaque sandbox，无任意工具或凭据桥。201只说明已排队；新任务保留原结果/任务来源，不重跑原 run。仍需原生点击、断网/重启及真实模型按选择上下文执行验收；选择不授予付款/外发等许可 | I+V／P1 |
| 记忆读取和管理 | `/api/memory` GET/PATCH、memory_controls revision/add/replace/remove、原生编辑回执；已有启停与条目管理 | 真实 Hermes 新会话使用更新结果的证明；移除当前记忆不等于历史对话/检索/备份彻底遗忘，后者仍是软件任务 | I+B+V／P1；删除 P0 |
| 对话引用范围 | 记忆页入口、本人连续会话分页、范围预览与显式停止引用已挂线；同owner+identity来源根与压缩后继排除，后续聊天换新上下文、排队任务重新绑定、目标raw source同样受控。双CAS、稳定请求、账户围栏、导出设置及引擎`sources-v1`能力检查已实现 | App来源范围1与Web来源范围2已各自完成预览/确认/排除，revision 0→1→2，历史保留可查看；真实引擎尚未据此重启/验收。旧引擎不能带来源policy继续启动任务。历史原文/FTS/备份、已保存记忆/文件/目标报告及其他对话转述保留；首版无恢复引用，不声称语义擦除或彻底遗忘 | I+V／P1；彻底删除B／P0 |
| 云端应用连接 | CloudApps/NativeCloudAppsPanel：飞书配置、权限、官方授权、续期、检查、撤销；文档/wiki、文件夹分页、日历/日程读取与 Agent 工具已接 | 正式飞书应用 scopes/本人 OAuth，真实读取撤销；目前只读，不伪装日程写入。邮件/其他云应用尚未实现 | I+B+C+V／P1 |
| 技能管理 | SkillLibrary/API/SkillsPanel：实际已安装/目录、内容、版本、启停、安装、移除预览/二次确认/完整回执与刷新。移除将当前身份包原子移至恢复目录，配置与整包 revision CAS；保护活跃/排队任务、自动加载、内建来源、嵌套包与软链 | 模拟器已对合成技能完成停用→移除→重新安装且保持停用；实体手机、来源/授权审计、安装失败恢复仍需验证。一键恢复/自动清理恢复副本尚未提供；普通文档导入不会自动安装技能 | I+B+V／P1 |
| 聊天工具连接 | MessagingBridge、Telegram/飞书，凭据验证、允许用户、启停/断开、状态、去重与原身份会话 | 用户 bot/app 凭据、真实入站→同会话回包、飞书长连接/重连、断开后拒绝；QA receiver 是模拟，不能冒充已真实投递 | I+C+V／P1 |
| 执行设备管理 | NativeDevicePanel 对接实际 offer/pair/control/permissions/input-approvals/reviews；配对文件、暂停/恢复/撤销、未知动作核对；本机电脑/手机与云 relay 分流。iPhone 原生队列另见上行，已有实现 | 真 Mac/Android 的配对→观察→可控测试窗口→暂停/断网不重放；iPhone 的范围、前台限制和真机验收独立记录，不以 relay 测试代替 | I+C+V／P1 |
| 设备常驻与安装 | Mac LaunchAgent、Windows计划任务、私有凭据与动作账本已有 | 签名安装/升级、非开发者引导、Windows真机、Mac重启恢复与轮换仍需软件及真实验收 | I+B+C+V／P1-P2 |
| 试用限额与用量 | UsageBook 持久模型/ASR 次数、音频时长、并发预占、已花/未知分离；guard 实际包装支持的模型调用；NativeUsagePanel/API | 正式环境显式启用 PAJIO_TRIAL_LIMITS；实际支持模型/ASR达到限额停止新调用。当前是调用/时长限额，不是供应商金额账单或平台全局计费 | I+C+V；金额 B／P0-P2 |
| 运行观察与支持 | 原探针/脱敏快照 + 定期HealthMonitor、最近7天持久采样/问题/恢复、可信owner投影、用户手动检查、24小时诊断导出；App已实际读取历史、检查状态、预览未发送的JSON报告 | 真环境杀引擎/断设备/断网、跨进程恢复待验证；采样不代表连续在线率。支持工单收件尚未接入，分享由用户选接收人 | I+B+V／P0 |
| 数据与隐私 | IdentityExports + NativeDataPanel 当前身份可读 ZIP；注销已有可信 ownership/冻结、0002迁移/RLS、gateway 新近 OIDC/PKCE、限定回执凭证、HTTP/WSS 在途撤权。App 注销入口、本机按账户清理、限定凭证查进度及 waiting/completed 精确终态已接线。独立 operator 接持久作业、tenant tombstone/撤权/drain、固定 Tencent API 与读回证据；支持显式登记的专属按量 CVM/CBS/普通同区域快照 | 当前无真实注销/云资源清除证据；实际资产/存储完整性登记、专用凭据、保留政策及真机清理/查询需验收。共享空间按用户外部撤权、聊天 bot 上游凭据撤销未齐；在途未知动作、额外存储、回收站/保留快照阻止完成。waiting/completed 仍需新包原生验收；受理/冻结均不等于删除完成 | I+B+C+V／P0 |
| 密码与代理登录（10月8日新增需求） | 已完成 [私密凭据方案](../../plans/pajio-private-credentials-2026-10-08.md) 和独立源码/官方资料审查：秘密留在保险库，由隔离组件填充，Agent仅得状态 | 保险库、原生安全管理、可信目标、独占登录租约与旁路隔离尚未实现；需防同UID终端、CDP、截图、AX、预植监听。未满足时由本人登录，不展示可用的私密自动填充 | B+V／P0隔离、P1能力 |
| 品牌、日夜、衣橱 | Pajio、睡衣熊、八套衣服与动画、移除简洁标记、C 图标，源码与模拟器证据已有 | 签名包实际图标/名、低端帧率、减弱动态、Dynamic Type、深浅对比原生验收；不得以视觉完成代替能力交付 | I+V／P1 |
| 电话、支付/收款、沙盒 | 原产品中的后续资源方向，当前未完整接入 | 产品电话/邮箱、支付/收款平台、sandbox 各自权限/账本/真回执；不把模拟下单、到登录页或已有命令行当业务完成 | B+C／P2 |

## 本轮可复核证据

最新原生验证见 [native-acceptance-20261008.md](native-acceptance-20261008.md)。以下“本轮最新检查点”由root在23:13安装验收后更新；其余早期PID、表数与测试数只代表当时检查点。

- **本轮最新检查点**：整个App **682/682**测试通过；全量TypeScript与ESLint通过后，最后TaskDetail受控失败枚举追加再次通过全tsc及所改文件lint。新版iOS Release构建并安装模拟器；收藏中文编辑/保存/归档恢复/显式打开、恢复任务同任务重试与停止、来源范围1排除后持久读回及合成执行上限的固定失败文案均已实际原生验收。Android配置插件精确loopback与禁备份专项测试通过。以上使用合成QA，未据此声称真实引擎通过。
- QA：`http://127.0.0.1:8891/`，22:38再次保留数据重启（exec会话89695），同一隔离目录 `/private/tmp/pajio-core-qa-jf1qwuko`，保留**82张非内部表**行数基线且无减少、integrity_check=ok，新增收藏/对话来源GET路由返回200。来源页有**2条合成会话**，不是真实用户或模型历史，此次未再次seed。PID23615/53表、`qa-support.md`中的PID6448/45表均是旧检查点；本轮不把表数或GET200称为逐行内容审计、真实引擎调用或端到端功能完成。
- 真实路由/合成传输：`tests/test_qa_support.py` 13项；本轮诊断8项后端、9项TS；搜索8项后端、5项TS由搜索agent提供。QA+诊断+搜索共29项Python通过；本agent诊断TS、相关lint和全App tsc通过。root此前225项核心Python与367项TS通过是此前集合，不能将不同轮次相加成一个未跑过的全量结果。
- 较早的路由挂载快照：[api-route-audit.md](api-route-audit.md) 与 [api-route-inventory.json](api-route-inventory.json) 记录18个 installer、127个 HTTP/WebSocket 路由及1个静态挂载，无重复或遮挡。该快照早于 native-actions、技能移除、结果选择与 gateway 注销扩展；其中“尚未实现”的段落及路由数量不能当成当前全量审计。本次未重跑全路由枚举。
- 注销证据分层：[account-deletion-contract.md](account-deletion-contract.md) 的22项测试只证明作业核心与临时合成文件清除；其“未挂 gateway/未做控制面迁移”是历史状态，已由较新的 [control 契约](account-deletion-control-contract.md) 和 [gateway 契约](account-deletion-gateway-contract.md) 更新。后两者记录私有 Unix-socket PostgreSQL 迁移/RLS检查与模拟 OIDC/在途撤权回归。[operator 契约](account-deletion-operator-contract.md) 进一步记录可执行生产 adapter 的固定资源范围、tombstone、撤权/drain、云 API 独立读回和未接通的 shared/bot 边界；其开发验证使用临时库与假 Tencent CLI，没有真实云变更。不以源码或模拟回执宣称真实身份供应商或云资源已删除。
- [原生命令](native-action-contract.md)、[技能移除](skills-remove-contract.md)、[结果选择](artifact-choice-contract.md)、[系统分享](../../../SHARE-INTAKE-CONTRACT.md)、[通知](notifications.md) 与 [安静时段](quiet-hours-contract.md) 记录各自软件范围、隔离验证与未验收边界。系统分享合同中的 root 接线清单已落实至 `Mobile.tsx`、`VoiceComposer.tsx`、`share-chat-drafts.ts`；原生候选包已使用Xcode模拟器标准临时签名重新构建，系统分享的App Group已实际可用；不是设备分发签名。本轮不将各份合同的测试数相加成一次全量结果。
- [文件分页](workspace-pages.md)、[简报](briefings-contract.md)、[结果查看](artifact-panel-contract.md)、[持久确认](durable-confirmations-contract.md)、[搜索](search-contract.md)、[诊断](diagnostics-contract.md) 保留各自契约。Web/Desktop 的 [button matrix](web-desktop-button-matrix.md) 是 ZCode 端侧记录，其中网页 UI 点击不替代 App 原生点击或手机授权。
- [链接收藏合同](bookmarks-contract.md)、[对话引用范围合同](conversation-source-controls-contract.md)记录新能力的数据语义、owner/identity范围、幂等/冲突与未完成的真实验收。合同中的早期全App测试数和“待root挂线”条目以本页最新检查点为准；root挂线已经完成，两项新增原生流程见最新验收记录。收藏完整响应体的超时/账户切换中止已补回归；对话来源排除保留历史，不是彻底遗忘。
- [Android交付检查](android-delivery-check.md)：隔离候选`/tmp/pajio-android-review-XKwtST`最终Android JS导出4113模块/8.6 MB、prebuild与32个Expo模块解析通过；选图恢复及邻接73项TS、3项分享插件测试通过。此后用户明确同意官方SDK许可，独立安装并校验JDK17与官方SDK，完成Gradle构建及MI 6X安装回读。独立APK位于 `~/Downloads/Pajio-test-20261008/`，SHA256 `1ca187b67c55dfdc10a9e83c7b4d8b97110ec2585d7f7f0876cd2edf47f7d4e3`；未完成Android真机功能验收，未使用付费构建。安装包详情以该检查文件为准，此局部测试集合不与682项全App测试相加。
- QA 搜“搜索验收”：all返回问答+笔记两项，task返回一项，`message_id=5`能取准确问答；foreign identity 请求404。`/api/diagnostics`返回`deployment=synthetic`、`engine_probe=not_configured`，没有将模拟环境假报模型在线。
- QA日志、manifest中明确 synthetic/no-model；没有外部 socket、模型、推送、真实授权或设备操作。它证明 API 与 UI 所需资源契约，不证明供应商或设备能力。

## 必须保留的外部事实与门槛

以下为 root 在本轮的只读实查结果，不来自旧文档：

1. `security find-identity -v -p codesigning` 当前返回 **0 valid identities**。模拟器 BUILD SUCCEEDED 不等于有签名外测包。
2. 官方 `tccli` 读取原实例：**InstanceState=SHUTDOWN，StopChargingMode=NOT_APPLICABLE，LatestOperation=IsolateInstances / SUCCESS**。这不是10月4日历史 STOPPED/免费停机事实的延续；不能据此宣称当前已运行、无收费或可以直接恢复。需要核对该账号实例可恢复条件和账单/资源归属后处理。
3. 尚无本轮正式 OIDC、公网双租户、APNs/FCM 真机通知到达、正式飞书/聊天渠道真实投递的新完整证据。代码可先完成，外部授权不能用说明卡替代，也不能伪造已经授权。
4. 用户已确认Apple Developer尚未开通；首轮人数未定，iPhone为主且包含Android。Android源码没有EAS projectId/Firebase配置；本轮独立APK使用测试签名，不能视为正式发布签名。推送需要匹配项目、FCM/APNs和后端provider配置。模拟器Release包不能给iPhone用户安装，Android已安装不等于真实云账号及通知可用。

## 剩余软件实施包

系统分享接收、手机原生命令队列、技能移除、结果选择续办、安静时段、账户owner隔离、链接收藏、对话引用范围和Android选图恢复已移出“没有实现”的清单。它们的原生构建、真实权限、网络中断与供应商验收仍按上表逐项完成。

| 包 | 独立可做的软件工作 | 不依赖外部账号即可完成的测试 |
|---|---|---|
| P0 数据控制 | 主入口、本机账户清理、控制面冻结与受限生产 adapter 已有；继续完成 shared 按用户外部凭据归属/撤销、Telegram/飞书 bot 上游撤权及明确保留政策。不支持的存储/备份布局需要专门 adapter，不能从完整清单中省略 | 中断/重启/计划变化后不误删；旧HTTP/WSS立即拒绝；已接收后台动作须另证停止；共享空间/其他账户保留；本机清理与受限查询凭证存活、逐阶段证据到终态一致 |
| P1 原生能力补全 | 后台owner继承已完成并有236项相关回归；系统记录修改/删除的软件与58项Python、35项TS合成回归已完成；Android选图恢复已实现。继续实体手机队列与SDK57全天提醒未知值验收；Android云Agent原生执行尚未开启，若纳入首轮范围需独立实现和验证 | 无主任务/身份切换失败关闭；权限、列表和revision冲突不写；不借用当前手机账户给后台任务授权；Activity回收与注销/换账户迟到结果不串草稿 |
| P1-P2 连续性 | 前台单向系统同步、月/周/议程、重复日程、任务清单、离线归档/恢复、自动简报与单记录提醒已接；双向同步与跨日真实运行验收继续推进 | 相同外部对象更新/删除不复制；撤权后停止；时区/重叠/重启同一状态；远端 tombstone 不复活 |
| P0 运维闭环 | 持久健康历史、问题/恢复事件和脱敏导出已接；服务自动采样已启用，原生读取/即时检查/报告预览已点通；支持收件与真实故障演练仍需推进 | 杀合成engine/断relay/断网络得到不同状态；只存必要类别与ID，用户明示发送才上报 |
| P1-P2 产品完整性 | 文件/跨对象内容索引、更多云应用与邮件、设备安装/升级引导、记忆历史/检索/备份的彻底遗忘策略；链接收藏与对话来源排除已有实现，不再重复列为待开发 | 明确范围与授权、旧链接/缓存失效、索引删除、重装/升级与不覆盖其他账户；来源排除要用真实新引擎验证，不以检索屏蔽或新上下文代替彻底删除 |

## 最短外测验收顺序

1. iPhone和Android各自取得可分发签名包并完成干净安装/升级保留数据；不预设测试人数。真实独立账号下，两个租户以相同文件名/同文任务分别操作，互换编号/链接/会话均不可越权。
2. 测试PDF＋语音→可编辑文字→稳定task回执；断网/丢响应/杀App后只保留一份任务。文件200项以后仍能分页查到。系统分享从Safari/照片/Files及Android对应应用到收件箱，核对取消、多附件失败重试、冷启动与选身份；待用文字追加后不覆盖已有草稿、不重复带入。Android选图启用系统Activity回收场景，照片只能恢复到原账户原草稿；收藏显式保存、离线重试、归档恢复、系统打开分别验收。
3. 关 Mac、杀App、切蜂窝后云任务继续；新结果或待决定触发实际设备推送，点开准确身份/任务；拒通知仍能在App内找到。
4. 目标多轮与5分钟安排→修改旧条件失效→服务重启回原run；超时确认只能重新观察、再发新卡，断回执不重复外发。结果选项确认后取得同一后续任务回执、真实模型读取正确上下文；技能用专用测试包完成安装/停用/移除，运行中保护与恢复副本核对。
5. 系统测试日历/提醒、授权飞书资料、一个真实消息渠道、Mac/Android执行设备各自完成一次“读取→允许范围内操作→撤销/暂停→重试受阻”的闭环。Agent 手机请求另验前台确认、系统真实回读、强退/丢回执后不重复写入、切账户不接收旧请求；不用普通日历按钮点击代替队列验收。
6. 断设备、杀引擎、断手机网络分开验收；导出脱敏诊断可定位任务且无私密正文。对话来源排除需真实新引擎验证：本人选定来源及压缩后继不再检索/注入，新聊天和原排队任务使用新上下文，其他账户与未排除来源保留；用户历史仍可读。账户数据导出/删除边界另按真实实现验收，不把停止引用当删除完成。

Web/Desktop 仍由 ZCode 只读 App 契约与代码实现。Codex App 验收与 ZCode 各端验收独立记录，不让截图或共享后端测试替代端侧点击结果。
