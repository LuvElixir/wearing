# Wearing 云端沙盒选型与接入边界

核查日期：2026-10-02。范围：官方文档、仓库元数据及固定提交的文档；未开通服务、创建沙盒、调用模型或实测桌面。推荐进入开发的基线见[整合落地总方案](implementation-blueprint.md)。

## 结论

首版优先验证 **Hermes + Daytona 托管沙盒**。先接官方 MCP，复用沙盒管理、文件、进程与 Computer Use；必要时调用官方 SDK 补缺口。Hermes 自带 Daytona terminal backend 可用于纯命令执行，但不能据此宣称整个桌面也已接通。

E2B Desktop 是云桌面的替换候选。OpenSandbox 是未来自托管候选。首版只接一种云端提供商，其他路线只保留切换条件。OpenAgentCore 继续作为执行管理的研究候选，不成为取得云沙盒的前提。

选择 Daytona 的依据是已有集成入口和所需能力的覆盖面。这是工程起点，不是对成功率、最低价格或用户开户资格的实测结论。

## 核查到的事实

| 项目 | 官方资料确认的内容 | 对 Wearing 的影响 |
| --- | --- | --- |
| Hermes terminal backend | 有 Docker、SSH、Modal、Daytona 等后端；Daytona 的持久模式使用停止与再次启动 | 命令执行先复用；文件保留与进程继续运行分别验收 |
| Hermes MCP | 支持 stdio / HTTP MCP、工具发现与工具筛选 | 可接现成 Daytona 工具服务，无须先写原生 Agent 引擎适配器 |
| Hermes Bot Screen | 当前文档中，Daytona / Modal / Vercel backend 的自动桌面放置被拒绝；指定 gateway 会把桌面放在控制主机 | 不能将 terminal.backend=daytona 等同于“所有操作已在云端” |
| Daytona MCP | 官方工具范围列有沙盒管理、文件、Git、进程执行、Computer Use、预览 | 首先核验实际工具清单、截图返回和同一 sandbox_id 的复用 |
| Daytona Computer Use | 提供桌面操作，并与 VNC 配合；文档列出 Linux 与 Windows | 控制与远程查看复用提供商；Windows 能力不等于 Hermes 原生后端已兼容 |
| Daytona persistence | container 停止保留文件，清除内存；VM 类别另有暂停/恢复 | 首版按文件可恢复设计，进程重启后重新观察；不依赖内存快照作为唯一恢复方式 |
| E2B | 独立 Desktop SDK 有画面流、鼠标键盘；持久化文档描述保存文件与内存 | Daytona 不满足实际任务时开展同任务替换测试，不同时维护两套首发实现 |
| OpenSandbox | 原 alibaba/OpenSandbox 跳转至 opensandbox-group/OpenSandbox；Apache-2.0；有 Docker/Kubernetes、浏览器和桌面示例 | 未来需自营或更强部署控制时复用，承担宿主、网络、存储及运维成本 |

上述是公开文档声明。MCP 协议相容只说明有接入路径，截图能否正确送入所选模型、控制是否稳定、停止后的业务状态能否恢复仍须实际验证。

## 最短接入路径

1. 固定 Hermes、Daytona CLI / SDK 和镜像版本，记录所用云端区域与账户额度。
2. 在独立 Hermes 配置中接入官方 Daytona MCP，读取实际工具清单。优先暴露本轮需要的工具，检查工具调用目标。
3. 建立一个测试 sandbox_id，让进程、文件、桌面与人工查看指向同一实例；将其与 Wearing 的 resource_id 关联。
4. 先完成文件与公开网页任务，再验证停机重启、接管与断线。MCP 若缺少必要能力，用官方 SDK 补该处。
5. 由一个确定的组件管理该沙盒的创建、启动、停止和清理。原生 terminal backend 与额外连接器不能分别创建实例却被界面显示成同一台电脑。
6. 验证每种动作的执行位置。云端任务执行失败时，返回失败与原因，不自动改到用户本机执行。

Daytona 原生终端后端可以作为命令实验的独立对照；只有确定如何共享同一实例、生命周期和占用状态后，才与桌面连接方式合用。

## 首版应使用的资源模型

沙盒按用途选择临时或持久模式；持久云桌面可以是一台长期使用的电脑。另接 Mac/Windows 和手机，是为了补足特定软件、设备与账号环境的实际需要。

- **临时任务空间：** 实验、代码、资料处理；产物导出后释放。
- **持久工作空间：** 保留文件、安装环境与专用浏览器资料；空闲停止，重启后重新验证状态。
- **长期主状态：** 人格、偏好、记忆、任务与资源档案、凭据引用和交付产物，在独立持久存储中保存与备份。

暂停沙盒之后，沙盒内的任务也暂停。对话入口、事件接收与定时唤醒由外部常驻控制服务承担。初期该服务可以在指定开发机运行，持续在线验收时再放到适合常驻的环境。

浏览器资料保存不保证网站登录永不过期；换实例也不能假定地址、会话、连接和第三方服务状态完全相同。必须分别记录文件、登录、进程与业务结果。

## 成本估算

2026-10-02 的 Daytona 公开价格列出 vCPU $0.0504/小时、内存 $0.0162/GiB/小时。以 Linux 2 vCPU、4 GiB 作为估算规格，计算与内存合计：

`2 × 0.0504 + 4 × 0.0162 = $0.1656/小时`

| 活跃时间假设 | 30 天计算与内存估算 |
| --- | ---: |
| 每天 1 小时 | $4.97 |
| 每天 3 小时 | $14.90 |
| 全天运行 | $119.23 |

这是按公开单价的算术估算，不是产品总成本。未包括存储、模型、控制主机及其他适用费用，未计试用额度；规格是否适用需实际任务验证。Windows 另有计价项，本表不适用。

Daytona 按所预留资源和生命周期计费；停止/暂停后仍可能有磁盘费，状态转换期间仍计计算费。因此应核实实际已停止，不能只记录 stop 请求成功。

第一版就记录每任务活跃秒数、规格、模型用量、人工接管和账单差额；预估与实际费用分别显示。支出上限需要在执行前判断，并配合提供商限制与到时停止，不靠模型口头承诺。

## 何时换路线

| 触发条件 | 下一步 |
| --- | --- |
| Daytona 账户、支付、区域或网络条件不成立 | 先核查 E2B 的实际可用性；也可在用户可取得的云主机上使用成熟自托管方案 |
| 云桌面工具、截图或接管可靠性不足 | 用相同任务对照 E2B Desktop，记录全流程成本 |
| 长期高负载使按量费用不合适 | 比较固定云主机与 OpenSandbox，自托管运维时间计入成本 |
| 特定业务需要 Mac/Windows、持久设备环境或手机 | 选择已经验证的专用设备连接器 |
| 需要统一管理多种 Agent 引擎与执行环境 | 再验证 OpenAgentCore 是否减少总体维护工作 |

## 证据和核查限制

- Hermes main 元数据：`00373b537616c96e0ca604b831890a113df07ac0`，提交时间 2026-10-02 06:27:08 UTC。成功读取该提交的 configuration.md 和 bot-screen.md。读取 daytona.py 遇到 HTTP 429；网页源码入口也失败，未完成该模块实现审查。
- OpenSandbox main 元数据：`c7dc78a4090e5de2b9119e9bd93952cae24f87bd`。功能与许可本轮核查的是实时官方仓库首页；未审计运行时代码。
- 托管服务文档是在线版本，不代表公开 GitHub 仓库某一 release 的全部能力。开发时需记录实际 CLI、SDK、镜像和可调用工具。
- 未验证用户注册资格、支付工具、所在网络可达性、试用领取结果或实际运行费用。

官方来源：

- [Hermes 固定版本配置文档](https://github.com/NousResearch/hermes-agent/blob/00373b537616c96e0ca604b831890a113df07ac0/website/docs/user-guide/configuration.md)
- [Hermes 固定版本 Bot Screen](https://github.com/NousResearch/hermes-agent/blob/00373b537616c96e0ca604b831890a113df07ac0/website/docs/user-guide/features/bot-screen.md)
- [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)
- [Daytona MCP](https://www.daytona.io/docs/en/mcp/)
- [Daytona Computer Use](https://www.daytona.io/docs/en/computer-use/)
- [Daytona 持久化](https://www.daytona.io/docs/en/persistence/)
- [Daytona 价格](https://www.daytona.io/pricing)、[计费规则](https://www.daytona.io/docs/en/billing/)
- [E2B Desktop](https://github.com/e2b-dev/desktop)、[持久化](https://docs.e2b.dev/sandbox/persistence)
- [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox)
