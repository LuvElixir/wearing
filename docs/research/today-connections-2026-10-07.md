# Today 连接能力与 App 落地核查

核查日期：2026-10-07。依据：用户本轮 Today 真机截图、Today 官方产品与隐私说明、Apple 与 Expo SDK 57 文档，以及 Wearing 当前源代码。截图中的个人资料、公司信息和对话仅用于理解界面，不作为 Wearing 的示例数据。

## 可以确认什么

用户截图说明 Today 已把聊天、图文简报、任务/定时、记忆和个人页组织在同一个轻量底栏中；聊天用左上角任务状态和回复后的短状态条表达正在执行/记忆变化；设置再集中提供应用、设备、技能、聊天工具等入口。这些是界面事实，不能仅凭入口数量推断每一个连接都已完成真实操作。

Today 官方介绍说明其长期记忆可查看、修改和删除，简报围绕一天的重要变化组织，连接器按应用授予和撤销权限。这支持“用户能读懂 agent 记住了什么、离开后回来能看到进展”的产品方向。[Today 产品说明](https://today.ai/articles/blog/what-is-today)

它的隐私页明确写出了 iOS HealthKit 接入：按授权类别读取，使用后台交付，同步到 Today 云端；撤销权限停止后续收集，已同步内容的删除是另一项动作。因此它不是仅靠对话文字猜测健康状态，也不是所有个人上下文都只留在手机上。[Today 隐私说明](https://today.ai/privacy)

尚未确认：Today 各连接器的内部实现、是否都使用 CLI、agent 文件夹对应的真实文件格式、后台进程隔离方式、每个连接器的实际可写范围。公开营销文章不能当作这些实现细节的证据。官网旧文章仍说免费、以后可能推出付费，而用户当日截图已有 Pro 会员卡；本轮不据旧文章判断现行套餐和价格。

## 苹果原生能力如何接

| 能力 | Apple 提供的路径 | Wearing 要做什么 |
| --- | --- | --- |
| 日历、提醒事项 | EventKit 访问系统事件存储；事件有只写和完整访问，读取事件/提醒需要完整访问，系统不提供单独的只读授权档位 | App 内可以承诺并实现“仅用于读取简报”，但系统权限描述必须真实；按需请求、选择需要的日历、记录同步时间，写操作单独交代。参考 [EventKit 访问说明](https://developer.apple.com/documentation/eventkit/accessing-the-event-store) |
| 位置 | Core Location，经用户允许后获取；前台 When In Use 和 Always 是不同权限 | 首先做用户主动请求附近地点时的前台定位；连接页展示真实授权状态。参考 [位置授权](https://developer.apple.com/documentation/corelocation/requesting-authorization-to-use-location-services) |
| 照片 | 系统 PhotosPicker 只交付用户选择的照片；全面查询图库是 PhotoKit 的另一种访问范围 | 优先保留“选照片交给 agent”的最小链路，不把选过一次照片写成“全图库已连接”。参考 [PhotosUI](https://developer.apple.com/documentation/photosui) |
| 健康 | HealthKit 需要独立原生能力、分类授权与同步实现 | 当前 Expo Go 不能因为列表有健康图标就宣布接通；需要原生构建与独立验收。Today 自身使用 HealthKit 是其隐私页明确披露的事实 |
| Apple 邮件、备忘录 | iOS 的 MessageUI 是撰写并由用户发送邮件/短信的界面，并非邮箱读取器；macOS 可以用 Apple Events/Scripting Bridge 控制支持脚本的应用 | 用户截图中 Apple 邮件、备忘录旁有电脑标识。由 Mac 伴随端提供这些能力是合理解释，但不是已查明的 Today 内部实现。Wearing 应区分“本机能力”和“需要连接 Mac”。参考 [MessageUI](https://developer.apple.com/documentation/messageui)、[Scripting Bridge](https://developer.apple.com/documentation/scriptingbridge) |

“iPhone 24 小时可用”的产品文案不能等同于 iOS 给任意 App 永久在线、任意远程控制权限。Apple 的后台框架按任务类型授予运行机会；云端 agent 可以持续工作，手机的本地能力仍受系统运行和权限条件约束。Wearing 应显示设备的最近在线时间和具体能力，而不是无依据承诺全天候控制。[Apple 后台任务](https://developer.apple.com/documentation/BackgroundTasks)

## 云端连接为什么可以很多

一个连接器可以由四层组成：用户授权 → 服务商接口 → agent 工具适配 → 结果和撤销状态。它不要求第三方都有 CLI。例如飞书官方直接提供 HTTP API，使用 `tenant_access_token` 或 `user_access_token`，可读范围还受用户/应用和接口权限共同限制。CLI 可以封装这些 HTTP 请求，MCP 可以把它们以工具形式提供给 agent；二者都不会自动获得额外的数据权限。[飞书消息 API 的凭据和权限说明](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/list)

因此，Wearing 可以复用已有 CLI/MCP 来降低接入成本，但产品层仍需要完成每种服务的登录回调、凭据存储、权限范围、失效处理、最后同步时间和真实动作结果。当前电脑已登录某个 CLI，不等于每一位 App 用户都已连接该服务。聊天机器人连接还涉及入口身份映射和消息送达，不只是展示一个应用图标。

建议连接页采用与参考一致、用户易懂的三组：**本机 / 云端 / 其他设备**。每项给出真正的动作和状态：选择照片、允许定位、去授权、重新连接、需要 Mac、需要安装版。已授权与已验证成功分开判断；显示数量由真实配置计算。

## 记忆文件夹：可读产品，而不是暴露整个服务器

Today 官方确认可检查记忆；截图进一步展示了主题文件夹和文件计数，但没有证明其服务器使用 Markdown 或某一种文件系统。[Today 的记忆说明](https://today.ai/articles/blog/what-is-today)

Wearing 已有可直接利用的基础：

- `src/wearing/engine_runner.py::memory_snapshot()` 读取 agent 本身使用的 `USER.md` / `MEMORY.md` 存储，并返回 user、memory 两组条目。`GET /api/memory` 通过当前身份的引擎读取这份数据，没有第二个独立记忆写入器。
- `GET /api/workspace` 和 `/api/workspace/file` 提供当前身份专用文件空间的目录清单与下载，路径校验拒绝越界与符号链接。它是工作文件空间，并非自动等同于记忆目录。
- 引擎状态已探测 `skills_list`、`skill_view`、`skill_manage` 工具是否可用；“能执行技能工具”不等于 App 已有完整技能管理 API。

近期可以把真实记忆展示成“关于你 / 长期记忆”文件卡，点击阅读原条目，显示本次读取时间。要做主题文件夹，可先按真实条目归类呈现并保留来源映射；不能把推断分类重新写回 agent，当作用户已经确认的事实。工作文件浏览另接现有 workspace 接口。编辑/删除能力应写回同一份源记录，保持 agent 下次使用的内容与用户看到的一致。

## 当前开发形态能做到哪一步

读取 `clients/mobile/package.json` 时，App 为 Expo `~57.0.26`。已安装 ImagePicker，未安装 Calendar / Location / HealthKit 模块。

| 交付层次 | 可以落实的内容 | 需要补的依赖或闭环 |
| --- | --- | --- |
| 本轮 App 界面 | 去掉重复进展和含糊操作；稳定不缩放的聊天；搜索/设置；柔和背景、卡片与输入栏；由真实状态驱动的任务提示；记忆与文件阅读；设置能力分组 | 以现有 API 为数据来源，保留真实语音和草稿恢复；未接入内容不要用假数据伪装已连接 |
| 现有 Expo Go | 系统选图已具备基础；`expo-location` 前台定位、`expo-calendar/legacy` 日历/提醒可在兼容 Expo Go 中验证 | 需安装匹配版本、检测模块可用性、用户实际授权和数据接线；选图需验收“选中→上传→agent 能使用”全链路。**SDK 57 legacy Calendar 页面明确 Included in Expo Go，导入须用 `expo-calendar/legacy`。** [SDK 57 ImagePicker](https://docs.expo.dev/versions/v57.0.0/sdk/imagepicker/)、[Location](https://docs.expo.dev/versions/v57.0.0/sdk/location/)、[Calendar legacy](https://docs.expo.dev/versions/v57.0.0/sdk/calendar-legacy/) |
| 自有 development build | 新版 Calendar class API、后台定位、HealthKit 等进一步设备能力 | **SDK 57 Calendar 根导入的新版 API 当前不支持 Expo Go / Snack，要求 development build；这条限制不适用于上行 legacy API。** iOS 后台定位同样要求 development build。装包后仍须逐项授权和真机验收。[SDK 57 Calendar](https://docs.expo.dev/versions/v57.0.0/sdk/calendar/) |
| 后端连接与主动执行 | 云端连接器、持久定时工作、图文简报生成、推送、跨设备续做 | 逐个供应商授权和执行回执；简报需真实来源和更新时间，加载态说明当前步骤，失败后可恢复；不能将新卡片样式当作整条功能已完成 |

## 本轮设计落点

1. **聊天**：顶部只留一个任务入口；回复后的短条表达已发生的事件。仅当真实任务创建或记忆源变更后出现对应提示。具体待用户决定的事情写在内容里，不能在每条回复下面机械堆“核对结果”。
2. **今天**：按信息价值展示少量图文简报。首张说明今天应关注什么，后续卡片有时间、来源、变化与下一步；内容不足时给真实空态。日历仍可在今天页进入，不把阅读范围限制成本周。
3. **任务**：任务/定时两页；任务卡清楚说明事情、当前阶段和是否需要用户动作；推荐定时项点开后应看到可编辑的明确安排。
4. **记忆**：个人理解摘要 + 用户可读的文件/条目。更新提示能跳到实际变更，不只闪一个装饰标签。
5. **设置**：会员卡可以作为账号状态容器；本地开发阶段用真实身份和当前连接状态，不显示虚构 Pro、余额或到期日。下方集中放应用、设备、技能和聊天入口。
6. **品牌**：按用户最新方向让旧 mascot 退出主界面；保留临时产品名用于识别，整体材料、字号、留白和图标统一。参考 Today 的舒适感与信息组织，不复制其 Kiwi 资产或暗示属于 Today。

App 完成且可验证后，再让 ZCode 只读 App 的组件、token、状态映射和交互约定，改 Web/桌面端；避免三端各自实现不同的产品语义。

## 本轮实施补充

研究后已新增 `clients/mobile/src/NativeConnections.tsx`：按需读取未来 7 天真实日历，勾选条目后放入聊天草稿；前台单次定位后可明确带入；选照片接回现有系统选择流程。页面初次打开及回到前台只检查权限，权限撤销后清空预览。模块缺失会给真实不可用状态。读取与带入均不自动发送消息，也不写入系统日历。

配套模型测试覆盖重复日历事件、仅导出显式选择、无效定位数据；这证明数据整理逻辑通过，不代表已经在用户 iPhone 上完成原生权限弹窗和数据验收。安装依赖由主实施流程负责；真实设备验证由 App 集成后的验收继续完成。
