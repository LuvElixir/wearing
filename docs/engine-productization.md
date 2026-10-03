# Wearing 执行引擎的产品化边界

更新：2026-10-02。当前采用固定版本 Hermes 的组件，Wearing 拥有身份、运行入口、能力接入和产品体验。

## 已落地

`identity.md` 是身份设定的唯一来源。启动时写入独立运行目录的 `SOUL.md`，替换上游默认身份；同一份内容随请求传递，覆盖旧会话缓存和外部兼容引擎的场景。用户询问底层时明确说明 Hermes/Nous Research 的来源，日常交流使用 Wearing 的名字。旧会话与用户自行配置的外部引擎仍需单独验收，不能仅凭请求说明保证所有模型行为。

`engine_runner.py` 直接托管固定版本的 `APIServerAdapter`。它沿用 Hermes 的 AIAgent、模型鉴权、会话存储、幂等运行、审批和停止实现，不再启动完整 `GatewayRunner`。适配器属于上游组件集成点，不是稳定的独立 SDK；升级版本必须重新跑兼容性验收。

当前提供健康检查、能力查询和 runs 的提交/查询/事件/停止/审批/steer 接口，以及受同一连接密钥保护的只读 `/v1/wearing/memory`。通用聊天兼容接口、模型管理、会话管理、技能市场、Jobs、群聊入口、跨 profile 路由均未开放，能力声明同步收缩。Wearing UI 尚未消费 SSE/steer，保留接口用于后续接入。

不启动 Telegram/Discord 等消息机器人、cron 调度、看板工作进程、完整控制台。关闭自动技能整理、额外模型生成标题和后台自我改进调用。profile v6 接回原生 memory 与 session_search；跨会话保存、纠正和重启读取已有真实模型验收。自动清理历史关闭，避免无意删除用户记录。

## 保留、裁剪与延后

| 层 | 处理 |
| --- | --- |
| 身份、关系与交互 | Wearing 自己定义，持续真实对话验收 |
| 模型协议、压缩、会话、执行循环 | 复用 Hermes，避免重写 |
| 设备与资源 | Wearing 管理设备、连接状态、授权、能力与证据；按需挂接成熟工具 |
| 群聊、看板、频道、通用 Dashboard | 不随 Wearing 启动；常用 API Key 模型在 Wearing 内设置；其他服务保留官方 CLI 向导 |
| 调度与主动行为 | 当前不启动上游调度器；Wearing 已提供本地持久目标调度，完整事件与硬预算待实现 |
| 工具 | API 默认提供原生 memory / session_search，可选启用 Filesystem MCP 六项工具、手机连接器十一项工具及 computer_use；CLI 不加载 MCP；其他已配置 MCP 不会自动合并 |
| 上游源码及依赖 | 保留固定、已校验的源码和许可证；没有大规模删除磁盘目录或宣称安装包已瘦身 |

当前通过官方 PM 的 web/messaging/mcp extras 安装依赖，包内仍有未运行的模块。待 API 适配层兼容性稳定，再研究最小依赖清单并比较体积和启动耗时。先收缩运行范围，避免未经依赖核查删除核心引用。

## 配置与升级

`profile.py` 管理版本化产品配置，只修改其拥有的字段，不改模型、密钥、记忆文件、已有会话和自定义无关字段。变更前在私有 `hermes/wearing-backups` 中按内容哈希备份；再次运行内容不变时不重复备份。用户自定义过的身份文件触发明确冲突，不静默覆盖。配置备份可能包含敏感信息，不应提交或公开。

引擎绑定回环地址并使用随机 Bearer 凭据。Wearing 仍保留原始 `run_id` 和 `session_id`，模型完成后记录为 `completed_unverified`，外部结果的核验是独立步骤。

## 下一阶段顺序

1. 本轮已完成原生模型/API Key 设置与文件目录连接器，详见[验收记录](evidence/files-and-model-settings-2026-10-02.md)。
2. 下一步接浏览器/电脑控制：能力发现、指定执行主机、受控测试页面上的操作、回读和人工接管。
3. 独立电脑节点与 Android 节点：资源编号、能力发现、独占控制、离线恢复和人工接管。小米 6X 的基础控制已验收；另一台 Air 与 Windows 仍待实机验证。
4. 将邮箱、号码、支付等走通的步骤转为可复用连接流程；云端沙盒保留按需辅助地位。

这份顺序是当前实施安排，不代表后续设备或账户能力已完成。

## 文件能力与模型设置 v2

常用服务的 API Key 设置通过 `model_bridge.py` 在 Hermes 的受管 Python 中运行，复用官方模型选择、凭据检测和配置写入。API Key 通过子进程标准输入传递，不进入命令参数或 API 响应；表单留空保留已有密钥。模型 ID/凭据校验在写入前执行，保存失败恢复原配置。正在执行或状态不明的任务会阻止切换。运行中的本地引擎在保存后重启并重新连接；其他服务、自定义地址与 OAuth 仍走本地向导。DeepSeek 实际调用已验收，其他列出的提供商尚未分别实测。

文件连接器采用官方 `@modelcontextprotocol/server-filesystem@2026.8.31`，通过 Hermes MCP 发现、筛选和调用。安装复用 Hermes PM 的 MCP extra 与 Node/npm，npm 包及依赖固定在 lockfile；不运行 npm lifecycle scripts。允许目录固定为本数据目录下 `workspace`。开放 `read_text_file`、`write_file`、`create_directory`、`list_directory`、`get_file_info`、`list_allowed_directories`；Hermes 的工具描述助手可能额外出现，但不会扩大文件访问范围。启动引擎时检查文件工具发现结果。

文件区提供实际目录列表和附件下载，HTML 等文件也强制下载，不作为页面执行。文件工具会覆盖同名文件；尚未实现文件版本历史、上传/导入或逐次写入审批。目录限制属于该 MCP 服务的访问限制，并非操作系统级沙盒。Windows 分支已按官方 PM 的 npm 布局实现，但尚无 Windows 实机证据。


## 手机连接器 v4

使用官方 Platform Tools 37.0.1、Mobile MCP 1.0.7 与 UiAutomator2 3.7.0。九项基础工具以 Mobile MCP legacy ADB 为基础，其中界面读取在原生组件就绪时优先使用 UiAutomator2；另增设备列表和原生输入框填写。`android.py` 负责固定下载、校验和授权发现，`mobile.py` 负责资源注册，`phone_proxy.py` 做路由与暂停检查；没有另写手机 Agent 循环。

原生观察采用单次 8 秒 RPC 等待，辅助进程等待 15 秒，超时后的终止清理另设上限；失败请求截图，不在旧驱动的读取超时后启动第二个可能竞争的 UI 自动化会话。只返回系统控件的结果带 `limited` 提示，需要再看截图。新路径的代码与回归测试已通过；手机重启后，真实 MCP 设置页三次读取为 1.1～3.1 秒，美团首页一次 2.8 秒，全部成功。样本较小，不作为所有应用的速度或长期稳定性承诺，详见[应用初始化记录](evidence/app-initialization-2026-10-02.md)。

`phone.json` 使用 schema_version 2：devices 按稳定 resource_id 索引，保存设备序列号、平台、系统与 enabled。旧单设备记录可以读取，在首次更新时迁移，新增手机保留其他手机。模型先调用 mobile_list_devices，随后每个操作必须明确传 resource_id；原始 device 参数不会开放。指定设备断开后不会选择其他设备。连接器已经加载时，新增手机和恢复使用不再重启引擎。

每次调用重新检查注册记录、暂停和 ADB 在线状态。操作锁按用户目录与设备编号保存，所以同一 OS 用户的多个 Wearing 数据目录共享设备锁；不同手机的锁互不阻塞。它不阻止用户本人、其他软件或其他 OS 用户操作。暂停只拦住新动作，不能撤回已经发出的动作。

mobile_set_text 在独立 Python 环境内短暂启动官方 u2.jar（端口 19008）。验证唯一聚焦、可编辑、非密码、有资源 ID 的原生输入框，并核对 expected_text。使用锁定依赖的单次 setText 传输，写入后读回全文核对；不会提交，不更换输入法，不安装 IME APK，不需要 root。异常不会自动重试写入，结束时关闭自身启动的服务。WebView、自绘输入框、无稳定标识字段和密码字段尚不支持这条路线。

工具日志只保存 action_id / resource_id / 工具名 / 时长 / 状态；不记录输入文字或界面内容。工具返回仍为 returned_unverified；字段读回成功单独保存 native_text_readback 的验证时间，不等同于业务成功。模型任务保留 completed_unverified，需要独立核对。日志尚未自动关联 task_id。

未开放安装卸载、位置修改、Shell、批量执行及应用语言修改。前台应用名查询不受旧驱动支持，继续移除。原生填写的依赖和私有传输 API 已固定版本、锁哈希、包含 MIT 许可，升级需要重新验收。

实机与自动化测试范围见[多设备与中文输入验收](evidence/android-multiphone-2026-10-02.md)。

## 应用引导处理

日常欢迎页和介绍默认快速通过，打开应用以到达可使用页面为完成标准。同一任务中明确授权的应用引导与系统权限请求连续处理；新协议的实际接受和超出授权范围的权限保留一次具体确认。规范写在统一 `identity.md`，每次提交 instructions 都读取当前文本，覆盖已有会话缓存的旧行为。它是模型行为规则，不是点击级强制权限系统。[情景验收](evidence/onboarding-interaction-2026-10-02.md)。

## 2026-10-03 持续目标

新增 `goals.py` 保存目标、修订、回执和定时等待，继续通过原 TaskService → Hermes runs API 执行，不加入第二套工具循环。普通对话获得本身份的目标摘要；用户修订与模型报告分开存储，完成仍需人工核对。详见 [使用说明与限制](personal-continuity.md)。本地轮次额度不等于云端成本限额。
