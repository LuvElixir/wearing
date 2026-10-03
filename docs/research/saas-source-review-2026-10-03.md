# Wearing SaaS：OpenClaw / Hermes 定点源码复查

核查日期：2026-10-03。范围是运行隔离、设备连接、持久状态、记忆、Skills、主动任务与沙盒生命周期。不是全仓审计，也未运行这两个最新提交。

用户随后提高了隔离要求：最终方案使用每租户独立 VM/microVM，并保留独占物理主机档位。下面的 container cell 是 OpenClaw 源码事实，不代表 Wearing 采用其默认隔离级别；以 [最新实施基线](../saas-architecture-2026-10-03.md) 为准。

## 版本与证据

| 项目 | 本次固定源码 | 与现有 Wearing 的关系 |
| --- | --- | --- |
| OpenClaw | `87af5763bbc0bd1febc08d78eedc7fafd9eb5225` | 研究参考，未安装为运行依赖 |
| Hermes | `4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a` | 最新源码研究，不代表已升级 |
| Wearing 正在使用的 Hermes | `367441274c48a03d12ee9f8d3d9ccd9bc1585392` | 保留现有固定版本，升级需要独立兼容性验收 |

通过官方 Git HEAD 和完整 tree API 定位路径，下载 32 个相关源码/文档/许可证文件，下面记录实际检查过的重点。下载清单和 SHA-256 见 [source manifest](saas-source-manifest-2026-10-03.json)，原始快照在本地忽略目录 `.wearing/research/saas-2026-10-03/`。部分 raw 请求遇到 HTTP 429，缺失文件使用同一提交对应的 Git blob API 补齐。只读取代码，没有执行上游安装脚本。

## OpenClaw：应该吸收的设计

| 设计 | 源码证据 | Wearing 的落地判断 |
| --- | --- | --- |
| 每个租户独立运行实例 | [`buildCellContainerArgs`](https://github.com/openclaw/openclaw/blob/87af5763bbc0bd1febc08d78eedc7fafd9eb5225/src/fleet/cell-profile.ts#L249) 为 cell 设置独立挂载、网络、回环端口、CPU/内存/PID 限额、cap-drop 和 no-new-privileges | 复用这种运行边界。多身份、多会话不能充当 SaaS 的租户隔离 |
| 设备是独立节点 | [`runNodeHost`](https://github.com/openclaw/openclaw/blob/87af5763bbc0bd1febc08d78eedc7fafd9eb5225/src/node-host/runner.ts#L185) 使用设备身份、node 凭据与 Gateway 连接，处理连接候选及恢复 | 本地安装连接器；Agent 核心在云端。Mac 上的 USB 手机成为连接器管理的独立资源 |
| 配对授权能撤销、变更 | [`verifyDeviceTokenInWorker`](https://github.com/openclaw/openclaw/blob/87af5763bbc0bd1febc08d78eedc7fafd9eb5225/src/infra/device-pairing-tokens.kernel.ts#L74) 检查配对、角色、撤销、授权范围与代际；同文件有 rotate/revoke | 设备证书/令牌与用户登录分开；重配对后旧连接、旧动作不能继续生效 |
| 能力声明和实际许可分别计算 | [`resolveNodeCommandAllowlistInternal`](https://github.com/openclaw/openclaw/blob/87af5763bbc0bd1febc08d78eedc7fafd9eb5225/src/gateway/node-command-policy.ts#L307) 综合平台、已批准命令及 allow/deny | 界面根据真实设备能力显示可用项；设备宣称支持某动作并不自动取得执行授权 |
| 结果绑定原连接 | [`NodeInvokeStreamController.getPending`](https://github.com/openclaw/openclaw/blob/87af5763bbc0bd1febc08d78eedc7fafd9eb5225/src/gateway/node-registry.invoke-stream.ts#L293) 校验请求、node、connection、时限与当前权限 | 延迟回包、重连后的旧结果不能覆盖新任务；请求超时不能直接推断动作没发生 |
| 主动任务仍走同一 Agent 对话链路 | [`runHeartbeatOnce`](https://github.com/openclaw/openclaw/blob/87af5763bbc0bd1febc08d78eedc7fafd9eb5225/src/infra/heartbeat-runner-run.ts#L30) 先准备/判定跳过，再构建有来源的上下文并分发 | 对话、定时、邮件、设备事件都要带来源进入 Wearing；安静时不无意义生成消息 |

两个不能直接照搬的地方：

- Fleet 是实验性单宿主生命周期管理器，官方文档明确不提供共享消息路由，且不支持远程 Docker/Podman runtime endpoint。它可以参考或作为独立比较方案，不能当成已经具备注册、计费、云编排的完整 SaaS。[固定版本说明](https://github.com/openclaw/openclaw/blob/87af5763bbc0bd1febc08d78eedc7fafd9eb5225/docs/gateway/multi-tenant-hosting.md)
- [`node-pending-work.ts`](https://github.com/openclaw/openclaw/blob/87af5763bbc0bd1febc08d78eedc7fafd9eb5225/src/gateway/node-pending-work.ts#L11) 这里的 pending 队列保存在进程内，不能把这份队列当成 Wearing 的持久业务任务账本。此判断只针对这个模块，不代表 OpenClaw 所有任务都不持久化。

## Hermes：保留并重新接回的能力

| 设计 | 源码证据 | Wearing 的落地判断 |
| --- | --- | --- |
| 持久记忆与个人资料 | [`MemoryStore`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/tools/memory_tool_store.py#L88) 管理 MEMORY.md / USER.md、写入锁、漂移检测与会话快照 | 继续复用上游记忆机制；在其外明确租户共同偏好与身份私有记忆，不从零造向量记忆框架 |
| 记忆生命周期 | [`flush_pending`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/agent/memory_manager.py#L602)、会话结束/切换/压缩 hook | 云端 Worker 休眠前要停止接新任务、排空写入，再确认持久状态；强杀进程不等于保存成功 |
| Skills 的分层发现 | [`_skills_dir`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/tools/skills_tool.py#L67)、[`_skill_search_dirs`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/tools/skills_tool.py#L173) 区分当前 profile、项目目录、外部目录 | 复用加载/查看能力；Wearing 接入包可用上游 Skill 格式，但共享目录只读，用户扩展限制在自己的隔离环境 |
| 运行请求去重 | [`RunIdempotencyStore`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/gateway/platforms/api_server_run_idempotency.py#L53) 用 scope + key + 请求指纹事务预留 | 保留上游机制，稳定映射 Wearing task/run；磁盘失败会回退内存，SaaS 启动检测必须拒绝把这种状态当持久去重可用 |
| 定时触发归属与断点处理 | [`scheduler_tick`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/cron/scheduler_tick.py#L18) 文件锁与 admission；[`scheduler_ownership`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/cron/scheduler_ownership.py#L68) 判定实际 tick owner；[`occurrences`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/cron/occurrences.py#L1) 记录具体触发时刻 | 保留“谁负责触发、哪一次发生”的设计。云端统一调度后不再启动第二套同任务 ticker；文件锁不能直接充当跨宿主分布式锁 |
| Hook 可执行自定义代码 | [`hooks.py`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/gateway/hooks.py#L29) 按 profile 找 handler.py 并加载执行 | 同一 Python 进程切换 profile 不构成不可信租户隔离；插件/Skills/Hook 在租户 Worker 内，平台控制服务不加载用户代码 |
| 已有 Daytona 执行后端 | [`DaytonaEnvironment`](https://github.com/NousResearch/hermes-agent/blob/4e3fcd5cd7e40c37cb6f9a21a76fc57a7361957a/tools/environments/daytona.py#L24) 自己创建/查找/启动，按 task_id 命名，设置 auto_stop_interval=0；cleanup 同步文件后 stop 或 delete | 可学习 SDK 调用，但 SaaS 首接由 Wearing 服务端统一拥有沙盒生命周期；不能把平台 Daytona 主密钥交给 Worker，再让终端后端和 MCP 各自创建一份 |

本地 `profile.py` v5 仅开放文件/手机/电脑工具，关闭项目 Skill 发现及 background review/curator；`engine_runner.py` 不启动 GatewayRunner、cron ticker 或渠道入口。现有对话延续与按身份保存 Home 已实现，但不能据此宣称长期记忆编辑、主动推进、跨入口连续体验已经完整。

## 技术取舍

1. **保留 Hermes 作为首版运行核心。** 已有真实模型、文件与设备集成，当前研究未发现必须切换引擎才能解决的硬缺口。最新主干研究不自动触发升级。
2. **吸收 OpenClaw 的节点与运行隔离设计。** 已实现最小的 Wearing 设备指令契约；不把整个 OpenClaw Gateway 叠在 Hermes 前面。跨项目协议不是直接兼容的，Node 源码有较深 Gateway 依赖。
3. **按需验证替代引擎。** 如果 Hermes 在稳定远程运行、记忆保存、事件恢复上的适配成本明显高于 OpenClaw，再用同一套任务验收做对照；设备和业务账本不绑定某个引擎。
4. **沙盒走官方 SDK，资源权归服务端。** Daytona 的 VM 产品是首接候选，其他供应商通过同一生命周期接口替换。其官方文档区分共享宿主内核的 container 与独立内核的 VM；必须核实实际取得的产品类别，不能混称硬件隔离。生命周期与桌面动作分开验收。此轮核实官方[隔离](https://www.daytona.io/docs/en/isolation/)、[持久化](https://www.daytona.io/docs/en/persistence/)和 [Computer Use](https://www.daytona.io/docs/en/computer-use/) 文档，尚无真实账号实测。
5. **分布式长任务采用成熟工作流系统。** 首选 Temporal 承接唤醒、等待、取消和恢复；Hermes 保持自己的 Agent 循环。Temporal 重放不能使一次手机点击天然幂等，副作用仍需指令去重与结果核对。[官方任务语义](https://docs.temporal.io/tasks)

两仓本次根许可证均为 MIT。当前只借鉴设计，没有复制其实现进新模块；后续复制代码须保留原作者、许可证及对应依赖 notices，不能把仓库根许可扩大解释为所有资产、模型和服务的许可。
