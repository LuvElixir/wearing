# 邀请码验收专用 C 实例

截至本次基础服务交付，C 已完成独立 Core 的真实健康检查。此处不代表邀请码已消费、新账号 UI 已验收，或 C 已拥有电脑与云手机；这些由后续独立验收记录说明。

## 实例与来源

- VM 1103，1 vCPU、2048 MiB、32 GiB；全新官方 Ubuntu cloud image 创建，没有克隆 A/B 的 VM、用户目录、数据库、模型配置或凭据。
- 独立租户 `pajio_acceptance_c`、独立 instance ID、machine ID、SSH host key、gateway key 与服务端 TLS leaf key。新主机 SSH 信任由已认证 PVE QGA 返回的公钥建立，没有自动信任 ssh-keyscan。
- 使用独立 pj105 网络；创建前持有共享网络锁并校验原像，应用时重新生成当前动态设备规则。创建后 1211/1212 两份既有网络租约 SHA 均与原像一致。
- Core wheel 从冻结的本地源树构建，SHA-256 `3a3532f628deae568d7b61ce8b1356b0562273654bd8f64609bed6001f9d9456`。安装后逐项核对源文件 SHA。控制面随后独立变更的 join/gateway 不属于 C worker 入口，本次没有重新打包宣称两者一致。
- Hermes 固定 revision `367441274c48a03d12ee9f8d3d9ccd9bc1585392`，官方 PM 管理的 web/messaging/mcp 依赖与 filesystem 安装均真实完成。
- 模型配置来自已授权的本机操作员单一 DeepSeek key，通过内存与 SSH stdin 传入 C，未从 A/B 提取。配置 `deepseek-flash`，独立 10 CNY 累计保守预算与调用次数上限。价格属于操作员估算价目，不是供应商账单；初始基础服务检查没有发起模型推理；后续单次验收见下文。

## 实测边界

| 检查 | 实际结果 |
| --- | --- |
| C localhost `/internal/runtime` | 200，reachable，engine_owned=true |
| Core 进程 | PID 6465，NRestarts=0；后续读回仍 active，约 373 MiB cgroup 内存 |
| 初始数据 | cloud 单一默认身份；任务 0、设备 0、工作区文件 0 |
| 错误租户 / gateway key | 分别 403 / 401 |
| control → C mTLS | 200，reachable；CA 与 IP SAN 校验开启 |
| 无 TLS 客户端证书 | 400，未进入 worker |
| C 主动连接 A/B、control、两台 A 执行 VM、宿主 SSH、公司 PVE | 七项 TCP 连接均未建立，结合已核对的防火墙规则验证隔离 |
| 私有配置 | instance/gateway/owner/model env/config 均 wearing 所有、0600、非符号链接 |

服务自身已 enable/start；VM `onboot=0` 保持创建时状态，本记录不声称宿主重启后会自动启动 C。未重启或修改 A/B/control 的服务。网络探针只是这些固定端点的有限时点验收，不等同于全网隔离形式证明或长期互联网可用性。

## 安装过程中处理的问题

新 venv 最初由过严 umask 形成 root-only 文件权限，服务用户在初始化前被拒绝；确认 C instance 尚不存在后，只调整该新 venv 的文件模式，重新核对全部安装源 hash，随后成功初始化。

官方 codeload 下载过慢以及工具下载超时均保留原记录。只停止本次 C 自有安装 job，使用经过固定 SHA 校验的纯官方归档补齐缓存，再以独立阶段 intent 恢复官方安装器。没有把未完成归档当成功，也没有复制已有用户运行环境。

## 证据与交接

私有证据位于 `.wearing/on-prem/20261009/personal-compute/invitation-entry-20261010/`。`tenant-c-final-summary.json` SHA-256 为 `111383666899d4a00aa450518f46efd6b9f63d2e34eb7733936769190173b287`，索引系统身份、源码、TLS、安装恢复、Core/网络健康和私有权限证明。

交给控制面任务的最小 `tenant-c-route-bundle/` 仅包含登记所需的 instance/owner/gateway 文件及无凭据状态证明，目录 0700、文件 0600。本任务没有登记 route、发行邀请码或修改用户 membership。

新账号注册与邀请码一次性消费由控制面独立记录；本文件下文补充真实模型回执。仍待确认 C 主机冷启动恢复、加密备份及恢复。C 没有分配执行电脑或 Android 云手机，不把空设备列表描述为设备自动开通完成。

## 后续授权验收：新账号模型与自动开机

控制面交付新的 C 账号会话后，先验证其 tenant 为 `pajio_acceptance_c`，并确认 C 没有活动任务、模型调用账本为空，再以一个持久 request ID 仅提交一次合成请求。真实 API 返回 201，最终输出精确为 `PAJIO_INVITE_C_OK`；服务端任务保留真实状态 `completed_unverified`，没有替用户修改为已验收。

| 证据 | 结果 |
| --- | --- |
| 任务 / 引擎终态 | `3f8edd4096fa425584ef9f026d545047` / completed，last_event=run.completed |
| 传输账本观察到的供应商 / 模型 | `api.deepseek.com` / `deepseek-flash` |
| 新增真实调用 | 1 次，state=completed，输入 16,495 tokens、输出 9 tokens；输入中缓存命中 6,144 tokens |
| 交叉核对 | task usage 与独立实例调用账本输入、输出计数一致；Hermes 会话计数 10,351 非缓存输入 + 6,144 缓存输入、9 输出、api_call_count=1 |
| 无工具证据 | 对应持久会话 tool_call_count=0；messages 只有 1 条 user 与 1 条 assistant，tool 消息及 tool_calls 记录均为 0 |
| 费用 | 0.021020 CNY，cost_status=estimated；按操作员版本价目计算，不能视为供应商账单 |

首次验收脚本错误地只接受 HTTP 200，面对正确的 201 因而保存“提交待核对”并停止。没有重发 POST；后续仅 GET 原任务及只读 SQLite 查账完成核对，原失败收据保留。SSE 终态回放此时返回 404，没有用空事件流冒充完整轨迹；无工具结论使用上述匹配 run/session 的持久记录。供应商原始 response ID 未持久保存，用量是调用返回后保存的实测计数，费用仍是估算。

随后按独立授权核对 VM 1103 的名称、owner、instance 与 PVE 配置摘要后，仅将 `onboot` 设为 1。配置差异只有该字段，运行 PID 222225 未变化、既有动态网络租约 SHA 未变化；没有重启 C，也没有改变 A/B、control 或执行设备。本次没有进行宿主重启及 C 冷启动验收。

私有追加证据：

- `invitation-release-20261010/acceptance-c-model-intent.json`、原 `acceptance-c-model-proof.json`，以及 `acceptance-c-model-reconciled-proof.json`、前后账本、持久会话元数据。
- `personal-compute/invitation-entry-20261010/tenant-c-onboot1-proof.json`。

这些补充不会覆盖初始 `tenant-c-final-summary.json`，也不把模型单次成功解释为长期稳定、备份恢复或执行设备开通完成。
