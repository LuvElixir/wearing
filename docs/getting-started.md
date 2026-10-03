# Wearing 0.1 接入指南

更新：2026-10-02。控制端是本地 Wearing 对话页面，执行端运行 Hermes 与设备工具；两者可同机，也可分开。当前 Wearing在开发电脑上，用户的闲置 MacBook Air 是另一台电脑。第一台手机为 Android 9 小米 6X，可 USB 连接，不插实体 SIM。

## 1. 选择各部分的运行位置

| 设备 | 计划接入方式 | 当前证据与待验收 |
| --- | --- | --- |
| macOS Apple Silicon | Wearing + 官方 Hermes + 电脑工具；USB 接 Android | 开发 Mac 已实测 Wearing 与 Hermes 安装/接口启停；DeepSeek 多轮对话与 USB Android 基础控制已实测，桌面控制和目标 Air 待实测 |
| macOS Intel | 先核查 Hermes darwin-x64 包 / CLI；也可将主 Agent 放在其他主机 | 官方安装页和平台页表述不一致，后者列出 x64 bundle；Air 芯片与实际发行包需验证 |
| Windows | Wearing + 官方 Hermes Windows 安装路线；本机 ADB / 手机工具 | 官方有原生安装路线；需验证实际 Windows 版本、驱动及桌面会话，当前未实机测试 |
| Android 手机 | 电脑端 ADB + Mobile MCP + UiAutomator2；scrcpy 保留人工接管候选 | 小米 6X / Android 9 的截图、界面读取、点击、滑动、原生字段中文和英文输入已实测；无需 Root，长期稳定性仍待验证 |
| iPhone | 独立 iOS 连接器，以成熟工具的真机授权与平台条件为准 | Mobile MCP 提供 iOS 路线；签名、驱动、Mac 依赖及目标 App 逐项实测，首版未接通 |
| 云端沙盒 | Hermes 调用 Daytona 官方 MCP / SDK | 与本地设备共存；首版未分配实例，生命周期与费用待验收 |

统一的是资源描述和用户流程，具体驱动按平台选择。兼容性台账记录 OS / 芯片 / 工具版本 / 设备 / 操作范围与实际证据，不能用一个“支持手机”标签代替验收。

依据：[Hermes 安装](https://hermes-agent.nousresearch.com/docs/getting-started/installation/)、[平台支持](https://hermes-agent.nousresearch.com/docs/getting-started/platform-support)、[Mobile MCP](https://github.com/mobile-next/mobile-mcp)。

## 2. 在目标电脑先做检测

在页面右上角「连接 Wearing」下载 `wearing-doctor.py`，拷到实际执行电脑。它仅使用 Python 标准库，不安装框架、不改变设备授权。Python 需 3.11+。

macOS：

```sh
python3 wearing-doctor.py --android --output device-report.json
```

Windows PowerShell：

```powershell
py wearing-doctor.py --android --output device-report.json
```

将生成的 JSON 导入工作台。报告含 OS、架构、命令是否存在、检测到的手机型号/序列号与 ADB 状态，不含账号密钥。报告只是该时刻的记录。当前 Wearing的「检测当前这台电脑」与目标电脑报告分开显示。

## 3. 在合适的执行主机准备 Hermes

### 同机运行：使用 Wearing 集成安装

在项目根目录运行：

```sh
uv run wearing engine install
uv run wearing engine model
uv run wearing serve
```

也可在页面的「连接 Wearing → 在这台电脑开始」点击安装。常用服务可以直接展开「模型与 API Key」，选择服务、填写模型 ID 和密钥并保存，再点击「启动并连接」。已有密钥留空即可保留；实际可用性以第一轮真实回应为准。其他服务、自定义地址或 OAuth 登录保留 Hermes 官方终端向导。页面展示的完整命令固定当前数据目录，适用于自定义 `--data-dir`。安装失败可以重试；具体日志在数据目录下 `runtime/install.log`。模型未配置时明确提示登录，不创建空的模型运行。

Wearing 固定并校验官方源码 `367441274c48a03d12ee9f8d3d9ccd9bc1585392`，由 Hermes PM 安装工具和锁定依赖，不直接对 Hermes 执行 pip install。此版本使用 PM 管理的 Python 3.14，安装隔离在项目数据目录。Wearing 负责本地进程、随机回环端口和独立连接密钥；不会添加系统登录启动项。

2026-10-02 已在开发 Mac 上验证实际安装、DeepSeek 鉴权和多轮对话。当前使用 Wearing 个人模式直接托管 Hermes 的 API 适配器，不启动完整 Gateway；身份、接口及裁剪边界见[引擎产品化说明](engine-productization.md)。初始不启用工具；在连接设置中点击「启用文件空间」后可使用独立目录内的文件工具。连接成功也不代表已经具备电脑/手机控制能力。Wearing 关闭时结束自己启动的引擎；运行中的事项需先停止并核对，才能从页面关闭引擎。

### 另一台电脑或已有 Hermes

使用 [Hermes 官方安装页](https://hermes-agent.nousresearch.com/docs/getting-started/installation/)对应平台的方法，先检查安装器和版本。记录 `hermes --version` 与实际工具版本，使用 `hermes setup` 配置本人模型来源，运行 `hermes doctor`。不要把模型密钥写进项目仓库。

在 Hermes 配置的环境中设置 `API_SERVER_ENABLED=true` 和自己生成的 `API_SERVER_KEY`，再启动 `hermes gateway`。默认接口端口 8642。具体环境文件位置随安装方式不同，以该版本官方说明为准。保持只监听本机，通过 SSH 隧道供另一个本地控制端访问。

同机运行时，在 Wearing「连接 Wearing」填写 `http://127.0.0.1:8642` 与 Hermes API Server 密钥，点击「连接 Wearing」。两机运行时，先使用已经授权的 SSH 连接建立隧道（把占位符替换成实际执行主机，不直接复制）：

```sh
ssh -N -L 127.0.0.1:8642:127.0.0.1:8642 USER@EXECUTION_HOST
```

密钥只保存在控制端个人数据目录。工作台确认接口可达后，先执行一个明确指定目录的文件任务，查看 Hermes 的实际工具和位置，再核对输出文件。成功后再测试浏览器、截图与交互，不一次开放所有业务动作。

当前 HTTP 适配依据 [Hermes API Server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)及[程序化集成](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration/)。初期核查提交 `00373b537616c96e0ca604b831890a113df07ac0`；本次安装与接口健康检查固定到 `367441274c48a03d12ee9f8d3d9ccd9bc1585392`，同时复核其 runs 接口和 session_id 历史恢复实现。

## 4. 小米 6X / Android 9 首次接入

1. 在手机上由本人开启开发者选项和 USB 调试，USB 连接执行电脑，在手机上确认电脑的 RSA 授权。
2. 在 Wearing「连接 Wearing → 你的手机」点击「准备手机连接器」。程序准备 Google 官方 Platform Tools 37.0.1 、固定版本 Mobile MCP 1.0.7 与 UiAutomator2 3.7.0 原生输入组件，复用 Hermes PM 的 Node 环境；不需自行配置 MCP JSON。Windows 如未识别设备，仍可能需要厂商 USB 驱动，当前未实机验收。
3. 页面区分未发现、未授权和离线；从列表选择要交给 Wearing 的手机并点击「接入这部手机」。绑定会保存序列号与稳定资源编号，掉线时不改用其他手机。首次接入时本地引擎会加载连接器，随后新增手机可动态发现；引擎未启动时先点击「启动并连接」。
4. 小米 6X 实测还必须由用户打开「USB 调试（安全设置）」才能点击和输入：普通 USB 调试可以截图和读元素，但输入被系统拒绝。该用户已完成开启，本次无需插卡、Root 或额外 APK。其他机型条件按实际提示核验，不自动解锁设备。
5. 开始时使用不改变系统配置的操作，例如“在设置里搜索 Wearing123，并读回确认”。测试结果：Wearing 通过真实 DeepSeek 模型执行启动设置、滑动、点击、英文输入和读回；独立截图也显示相同字符串。中文可用 mobile_set_text 填写可识别的原生输入框，并读回确认；支持范围按实机验证。
6. 每张手机卡片的「暂停」立即拦住后续工具调用，包括读取。已经发出的动作可能仍会返回，不等同于操作系统级接管锁。「恢复」启用这部手机，不影响其他已接入的手机。保持手机解锁；拔线、锁屏、USB 重连和长期稳定性还需分别实机验收。

当前采用 Mobile MCP 的 legacy ADB 路线以接入 Android 9。默认驱动的前台应用名查询不支持，已从工具表移除；改用 UI 元素确认页面，应用发现使用实际可用的应用列表。中文填写使用 UiAutomator2 的原生字段接口；首次使用会推送并短暂运行官方 u2.jar。没有安装 APK 或修改手机输入法。

已准备 UiAutomator2 的设备优先使用有时限的原生界面读取；动态页面超时或只返回系统控件时，改用截图确认，不依据缺失的元素推断应用状态。未准备原生组件时仍使用 Mobile MCP 的基础读取。读取失败不会重放点击或输入。

测试手机的应用初始化按单个应用完成：启动并观察 → 处理已授权的首次引导 → 到达可用首页或记录登录卡点 → 核对结果后再切换应用。新协议须在看到具体页面后取得同意；确认过的同一协议不重复询问。登录、验证码及具体交易分别处理。手机重启或掉线后先确认当前页面，不能把断线前的点击自动再做一遍。

调节测试机的动画、亮屏等设置前保存原值，并读回确认。小米 6X 此次把电脑 USB 供电报告为 AC，因此只设 USB 常亮未生效；需要核查实际供电类型和 `mStayOn`，不能只看设置写入成功。拔线后的息屏策略与充电常亮分开配置。此经验不直接套用到其他机型。

人工远程画面/接管 UI 尚待接入，scrcpy 保留候选。Open-AutoGLM 保留为视觉控制候选，不是当前硬依赖。完整证据见[Android 实机验收](evidence/android-phone-2026-10-02.md)。

## 5. 首个通用验收流程

- 连接 Hermes → 说明意图和执行主机 → Hermes 真实运行 → 获得文件或测试 App 结果 → 独立核对 → 写入核对记录。
- 运行中断开控制端网络，再恢复：应继续查询原运行，不重新派发。
- 运行中重启 Wearing：应恢复原运行引用；未知状态显示待核对。
- 请求停止后，等 Hermes 报告结束，再检查子进程与设备动作。手机代理已有同一 OS 用户下跨数据目录的分设备操作锁与暂停闸门，但不能把“本轮已停止”当成所有软件的执行路径已暂停。
- 云端能力后续逐项接入并验证成本和资源回收。任务中的“电脑优先”是调度意图，真正的工具访问范围由 Hermes 配置决定。

Wearing 后端协议测试使用模拟 HTTP 响应，本地 Hermes 安装和接口检查使用真实进程；真实 DeepSeek 多轮对话及 Filesystem MCP 写入、读回、下载和目录边界已有验收；小米 6X 基础操作已实机验收；目标 Air、Windows 和云端沙盒仍待实测。实际版本与证据持续记录在 `docs/evidence/`。

## 6. 第一份文件

连接设置中的「文件空间」会准备官方 Filesystem MCP；首次安装后自动恢复原来已运行的本地引擎。随后可以在对话中说：“把这个想法整理成 Markdown 文件，并读回确认。”文件位于数据目录下的 `workspace`；右上角「文件」显示实际产物并提供下载。当前文件操作只覆盖这一个目录，写入同名文件会覆盖原内容，尚无历史版本。它不是完整的电脑控制或云端沙盒。

实测文件及独立验收过程见[本轮证据](evidence/files-and-model-settings-2026-10-02.md)。测试使用独立对话数据库，主对话未加入测试消息。
