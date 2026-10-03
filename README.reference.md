# Wearing · 你的个人 Agent

属于你的行动者，也是延伸出去的另一个你。整合成熟 Agent、电脑、手机与社会资源，把亲自走通的步骤做成可复用的软件。

目前交付 **0.2 本地开发版**：中文连续对话、按身份保存的会话和文件、原话持久保存、持续目标与进展、运行与结果核对、电脑和 Android 手机接入。完整 Wearing 角色承担视觉入口；身份、连接和文件位于次级入口。

**2026-10-03 开始按 SaaS 推进：Agent 核心运行在云端，用户电脑与手机作为连接器，云端沙盒承担隔离执行。**每位用户默认一个个人租户，日常/出海等身份属于租户内部。云厂商尚未选择，当前本地服务不能直接暴露公网。实施顺序、隔离边界和真实完成状态见 [SaaS 实施基线](docs/saas-architecture-2026-10-03.md)；上游复用取舍见 [OpenClaw / Hermes 源码复查](docs/research/saas-source-review-2026-10-03.md)。

租户隔离基线：每租户独立 VM/microVM，里面运行自己的 Wearing 服务、Hermes 与私有数据库；公共服务只保留必要的登录、路由、调度和计费信息。另保留独占物理主机路线。虚拟机隔离与物理主机独享分别说明、分别验收。

本地引擎现以 **Wearing 个人模式**运行：独立身份、版本化配置和精简运行入口；复用 Hermes 的 Agent 组件，不启动完整消息 Gateway、定时调度或看板。本地持续目标已通过 Wearing 调度接入；完整记忆、Skills、外部事件仍逐项推进。当前边界见[引擎产品化说明](docs/engine-productization.md)。

## 启动

安装 Python 3.11+ 与 uv 后，在项目根目录执行（macOS / Windows 命令相同）：

```sh
uv sync --extra dev
uv run wearing serve
```

打开 http://127.0.0.1:8765 。未配置 Hermes 时，可以先写下想法，原话保存在本机；页面会明确说明尚未获得真实回应。也可以查看接入步骤、运行检测和导入设备报告。真实执行需要先接通 Hermes 与模型。详细步骤见 [接入指南](docs/getting-started.md)。

本地引擎现可在「连接 Wearing」面板安装、启动和关闭。也可先运行 `uv run wearing engine install`，再运行 `uv run wearing engine model`，通过 Hermes 官方向导选择服务并登录。回到页面点击「启动并连接」，Wearing 自动生成本地连接密钥，不必手工抄填。另一台电脑或已有 Hermes 仍通过原来的连接表单接入。

也可将构建后的 wheel 带到另一台电脑：`python -m pip install wearing-0.2.0-py3-none-any.whl`，然后运行 `wearing serve`。Windows 可用 `py` 替代 `python`。这份代码按可移植方式实现，当前实测主机为 macOS；Windows 实机验收待完成。

## 已实现与待接通

| 范围 | 当前状态 |
| --- | --- |
| 连续对话、原话保存、多轮共享会话、刷新恢复 | 后端与浏览器检查见新的对话验收记录 |
| 长期目标与后续推进 | 保存目标/范围/阶段结果；约定轮次内自动续行；在对话里讨论与补充，聊天可转成目标；支持暂停与人工核对；[使用与边界](docs/personal-continuity.md) |
| 个人记忆与旧对话查找 | 复用 Hermes 的 memory / session_search；跨会话记住与纠正偏好；「一起记着的 → 记着你的」可核对实际条目；[使用与边界](docs/personal-memory.md) |
| Wearing 完整角色与动画 | 独立生成头像与角色资产，六种 720p 无声循环状态，无播放控件，尊重减少动态效果 |
| 本地 Hermes 安装、启动、退出、模型设置 | 固定上游版本，调用官方 PM；macOS 上真实安装、Wearing 个人模式启停与 DeepSeek 对话通过 |
| 原生模型与 API Key 设置 | Wearing 内配置常用服务，保留现有密钥；DeepSeek 保存/重连/调用已实测 |
| 文件空间 | 官方 Filesystem MCP，限定目录内读写；真实模型写入、读回、下载及越界拒绝已验收 |
| Hermes 创建运行、查询、停止、审批 | 依据官方接口实现；协议测试与真实模型多轮通过；真实工具审批/停止仍待设备验收 |
| 断线/重启 | 保留原运行编号；状态不明不自动重发；支持人工核对结案 |
| 结果核对 | Agent 返回后为“结果待核对”；用户写明证据后才记录“已核对” |
| Mac / Windows 检测 | 单文件 Python 脚本；明确检测的是哪一台主机 |
| 手机 | 多设备准备/绑定/暂停入口；Mobile MCP + ADB / UiAutomator2；小米 6X / Android 9 的截图、界面读取、点击、滑动和中英文输入已实测 |
| 电脑控制 | 本机 Mac 的读取、中文输入、点击、截图与接管阻断已实测；Windows 真机待验收 |
| 云端沙盒 | 接入方向保留 Daytona，当前版本尚未执行云端任务 |
| SaaS 基础 | 独立租户 Worker 与 OIDC 会员/实例路由；真实 PostgreSQL 迁移、独立权限角色与 FORCE RLS；两个合成用户实际 HTTP 登录/重启/撤销通过。真实 IdP、生产 TLS、VM 和设备转发待接通 |
| 邮箱、号码、支付、业务平台 | 取得与验收方案在 docs；尚未作为已完成的连接器 |

本地版同一时刻只派发一个运行；运行中或离线时的新消息会保留，可从较早的未发送消息继续。审批透传 Hermes 的现有请求。工具权限由 Hermes 配置决定；任务里的资源偏好不是强隔离。请求停止 Hermes 一轮，不等于所有设备操作已停止或取得独占接管权。

手机操作验收与已知限制见[小米 6X 验收](docs/evidence/android-phone-2026-10-02.md)。

## 数据与开发

对话、执行与进展保存在 `.wearing/wearing.sqlite3`，连接配置在 `.wearing/connection.json`。凭据不回传浏览器，POSIX 文件限制为当前用户；Windows 部署需确保数据目录使用本人账户 ACL。运行目录应当是个人私有目录，不放入共享盘。服务只监听回环地址，不直接暴露公网。

本地 Hermes 源码与工具在 `.wearing/runtime`，独立配置在 `.wearing/hermes`，默认工作目录在 `.wearing/workspace`。安装使用上游提交 `367441274c48a03d12ee9f8d3d9ccd9bc1585392`、源码 SHA-256 和官方 PM 锁文件。运行环境由 PM 提供 Python 3.14；Wearing 自身仍为 Python 3.11+。安装与启动日志仅存本机；Wearing 退出时关闭自己启动的引擎。新配置默认关闭工具，可在设置中启用文件、手机与本机电脑连接器。MCP 目录限制不构成系统级沙盒。产品身份来自 `src/wearing/identity.md`，配置迁移前保留私有备份；上游源码与 MIT 许可证完整保留。

```sh
uv run pytest -q
uv build
uv run wearing doctor --android --output device-report.json
```

[初版验收记录](docs/evidence/alpha-acceptance-2026-10-02.md)与[对话版验收记录](docs/evidence/personal-conversation-2026-10-02.md)区分本地运行、协议测试和实际设备验收。

## 项目资料

- [当前进度总表](docs/progress.md)：已接通、局部验收与待实施分别记录。
- [持续目标使用说明](docs/personal-continuity.md) · [验收记录](docs/evidence/personal-continuity-2026-10-03.md)
- [SaaS 实施基线](docs/saas-architecture-2026-10-03.md) · [上游源码复查](docs/research/saas-source-review-2026-10-03.md)
- [独立租户运行入口](docs/tenant-runtime.md) · [双实例验收](docs/evidence/tenant-worker-2026-10-03.md)
- [OIDC 登录与实例路由](docs/gateway-runtime.md) · [HTTP 双用户验收](docs/evidence/gateway-2026-10-03.md)
- [平台 PostgreSQL](docs/control-postgres.md) · [真实数据库验收](docs/evidence/control-postgres-2026-10-03.md)
- [多云 VM 选型与适配顺序](docs/cloud-vm-selection-2026-10-03.md)：首批六家；`wearing cloud providers/plan` 目前仅离线研究与配置预览，不创建云资源。
- [腾讯云首轮与真实报价](docs/tencent-cloud-first-run-2026-10-03.md)：复用已配置的 `tccli`；`wearing cloud tencent inspect/quote` 可查询中国站账户、机型/镜像与按量/包月价格，尚未创建 VM。
- [整合落地总方案](docs/implementation-blueprint.md) · [产品定义](docs/product-definition.md)
- [电脑与手机接入指南](docs/getting-started.md) · [手机与通信路线](docs/phone-node-plan.md)
- [VI 与品牌资产](design/vi/README.md)
- [OpenAgentCore 研究](docs/openagentcore-review-2026-10-01.md) · [Pro 回复解读](docs/pro-response-review-2026-10-01.md)
- [沙盒选型](docs/sandbox-selection-2026-10-02.md) · [号码与支付资源核查](docs/windows-payment-vi-research-2026-09-30.md)

手机现支持多设备资源列表，每次操作明确指定设备，独立暂停/恢复；中文原生输入框通过 UiAutomator2 3.7.0 单次填写并读回校验。小米 6X / Android 9 已实测；其他 Android、Windows 主机和 iPhone 的验证范围见[兼容性与验收记录](docs/evidence/android-multiphone-2026-10-02.md)。

## 身份

点击字标旁的身份按钮，可以创建、命名、编辑及切换 Wearing 身份。原记录属于「日常」，新身份有独立对话和文件空间。电话、邮箱、支付及新身份的设备连接按实际接入状态显示。实现、迁移和当前边界见 [身份说明](docs/identity-foundation.md)。
