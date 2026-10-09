# nanoMuse 对 Pajio 的复用研究

检查时间：2026-10-10（Asia/Shanghai）。固定提交 [`903a8eafdf20b7d9d6f3f78351580993a325e3ee`](https://github.com/nano-muse/nanoMuse/tree/903a8eafdf20b7d9d6f3f78351580993a325e3ee)，版本 1.0.0。源码只读检查，未安装或运行其 Agent、测试、演示。已有测试文件不等于本轮实测通过。

## 判断

nanoMuse 的价值是把个人 Agent 的记忆、主动任务、设备能力、审批、轨迹和首次体验做成同一个产品。Pajio 值得借鉴这些机制。它主要让同一用户已有设备运行各自 Agent，再通过 relay 协作；不是每个租户自动创建云电脑/云手机的托管平台。Python MuseAgent 与桌面 DeepSeek Harness 是不同执行路径，不能合并计算为一套 runtime 的成熟度。

## 证据与取舍

所有源码路径均相对上述固定提交。

| 领域 | 实际证据 | Pajio 决策 |
|---|---|---|
| Agent loop | `nanomuse/agent/core.py:389–545` 有限步数、工具 gate、运行中消息插入、最终会话保存；`docs/harness.md:260` 桌面另用 Harness | 保留已接通 Hermes，引入有价值的行为与测试场景 |
| 设备能力 | `web/src/screens/DevicesScreen.tsx:165–184,313–337` 由能力和在线状态控制界面 | 采用同类能力驱动 UI，避免伪可用按钮 |
| 任务轨迹 | `harness/dsh-nanomuse/src/client/Trajectory.tsx:156–237` 步骤、缩略图、当前动作 | 接现有事件/回执，私密接管不留帧 |
| 记忆 | `nanomuse/memory/store.py:240–297,314–374` 关键词/CJK、可选向量、变更历史/撤销 | 补 Pajio 变更记录和撤销，保留原存储归属 |
| 整理 | `memory/consolidate.py:148–166,169–230` 合并/删除预算和词汇校验 | 词汇校验不能证明语义真实；不能自动把推断当事实 |
| 后台主动性 | `server/service.py:1919–1954` 安静时段、忙碌延后、每 tick 一个目标 | 复用 Pajio 调度、加来源和安静反馈，不另建 ticker |
| 事件触发 | `triggers/store.py:115–120,200–213` 去重；`service.py:1728–1761` fired 在内存派发前保存 | 参考事件键；仍须持久领取/恢复，不能假定崩溃不丢工作 |
| 成本 | `cloud/nanomuse_cloud/service.py:1425–1509` 调用前预留，之后结算；`config.py:182–220` 区分缓存等费用 | 优先补调用前额度约束，不能只有结束后统计 |
| 上下文连接 | `nanomuse/channels/` 有飞书/钉钉/企业微信/Telegram 机器人通道；connector catalogue 为配置目录 | 机器人渠道不是读取个人所有历史；未验证抖音/小红书/B站收藏画像导入 |
| 首次体验 | `NanoMuseFirstRun.swift:55–70` 状态跳过；`NanoMuseFeed.swift:327–410` 命名后生成首份内容 | 保持 Pajio 选择题优先；用已授权来源生成真实首份价值 |

## 不能直接解决的关键问题

### 云电脑、云手机与流畅远程接管

`harness/desktop/src/operator-server.ts:1–137` 是 loopback 随机端口与 Bearer 的本机截图/执行桥。`operator.ts:159,285` 明确拒绝 Wayland，Linux X11 有真实截图和输入实现。`nanomuse/computer/coords.py` 的统一坐标和图片预算值得参考。

`cloud/nanomuse_cloud/hub.py:1–34` 是同账号出站 WebSocket RPC；截图/文件可作为 base64 JSON 中转。不能将 README 的“文件留在设备”理解为这些请求端到端加密。`BrowserViewer.tsx:12–25,88–110` 每秒刷新截图，以 HTTP 点击/键盘/滚动操作浏览器，不是低延迟完整桌面视频。iOS `NanoMuseReach.swift:60–185` 提供委派、命令、单次截图，没有完整远程触控表面。

`nanomuse/agent/holds.py:73–99` 接管锁在内存中按 thread/tool 保存；`:195–214` 超时会解除 Agent 发起的 hold。Pajio 必须保留设备级持久 scope/session/epoch，失联保持暂停，明确交还后恢复。不能照搬其超时恢复。该判断是设计适配比较，不是已复现的漏洞报告。

浏览器演示的 MobileGym 是模拟手机，不能作为云 Android 运行国内 App 的证据。所检查的运行时/云端/部署路径没有用户 VM 创建、资源配额、休眠和云手机调度实现。

### 密码保险箱

`vault/vault.py` 使用 Fernet、占位符、文本结果脱敏。`sentinel/gate.py:328–364` 当前通用生产工具不接受 secret，主要用于邮件/日历/模型配置。不是任意密码框的安全填充，也没有由文本脱敏自动覆盖截图的保证。默认 key 在本地 vault 附近，同用户文件权限不等于独立安全域。Pajio 的私密输入与可信填充需继续单独实现。

### 首次内容和全天候执行

iOS Feed 用用户/全局记忆、近期日记和目标的有限摘要生成内容，未实现自动读取全部社交账号。首次内容标记在成功前写入（`NanoMuseFeed.swift:331–337`），Pajio 应以真实产物回执决定完成并允许失败重试。`NanoMuseScheduler.swift:216–255` 前台执行到期工作，后台主要通知，不证明 App 关闭后的全天候模型任务。

## 许可证与直接上游

`NOTICE`、`pyproject.toml`、`THIRD_PARTY_NOTICES.md`：nanoMuse 自有 runtime/cloud/web/desktop 为 **GPL-3.0-or-later**，手机来自 OpenMinis GPL。GPL 允许商业使用；分发覆盖程序或衍生版本时需履行相应源码/许可证义务。仅在服务器使用与向用户分发 App、前端 JS、镜像的情况应分别判断，不能用“放独立进程”自动认定没有义务。参见 [GNU GPLv3](https://www.gnu.org/licenses/gpl.en.html) 与 [GNU FAQ](https://www.gnu.org/licenses/gpl-faq.en.html)。

MobileGym 默认演示数据为 **CC BY-NC 4.0**，不用于 Pajio 商业产品数据。品牌、图像、默认演示数据也不随代码许可自动可用。

直接评估以下原始上游，固定版本、保留通知，不能把 nanoMuse 的改写视作原始上游许可：

| 上游 | 固定检查版本 | 可取模块 / 限制 |
|---|---|---|
| [UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop/tree/3ac2cb8d946d78d5ff92ad17b318eaafa18c178c) | `3ac2cb8d`，Apache-2.0 | operator-nut-js/action-parser；原代码有输入日志，集成要去除；mock 测试不等于 Ubuntu VM 验收 |
| [Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM/tree/86f55382982fb054e8fc98ca80609dff8a2cdc3c) | `86f55382`，Apache-2.0 | ADB 输入/截图；默认接管只是终端等待，截图失败黑图和共享临时路径需调整 |
| [OpenMuse](https://github.com/CopilotKit/openmuse/tree/1ac68f3909f2478ab6280883f1ab5ea65eb5719d) | `1ac68f39`，MIT | ComputerBackend、磁盘持久/闲置休眠；实现 Proxmox driver，不直接沿用 E2B 公网流 URL |
| [MemGUI-Bench](https://github.com/lgy0404/MemGUI-Bench/tree/3fb01b6cc0d13e287c67f488c76f449df7d65558) | `3fb01b6c`，MIT | 后续 GUI 评测和模型适配参考，不进入首轮托管/远控基础设施 |

## 执行

按 [交付清单](../plans/pajio-personal-compute-delivery-2026-10-10.md) 推进。先把实际设备、控制权和 App 接管做通，再把主动内容、记忆与成本机制接上；不整体迁移 runtime，也不以仓库热度替代产品验收。
