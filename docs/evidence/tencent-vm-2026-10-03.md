# 首台腾讯云 Wearing VM 验收

2026-10-03 17:41 CST。用户选择按量短测；正式创建前已告知当前 ¥0.29/小时（连续 24 小时 ¥6.96）及公网出流量 ¥0.6666/GB。随后另授权复用现有 DeepSeek Key 进行真实对话。没有创建第二台 VM、快照、对象存储或云数据库。

## 真实环境与发布

- 香港二区，SA2.MEDIUM4，2 vCPU / 4 GiB，官方 Ubuntu Server 24.04 x86_64；40 GiB CLOUD_PREMIUM 系统盘和 40 GiB 数据盘。数据盘 `DeleteWithInstance=false`。
- 一位试验租户、一台 CVM、一份私有卷、一套 Wearing/Hermes；未复用共享 Hermes gateway 做租户隔离。客机返回 `kvm`，不能据此宣称独占物理主机或完成双租户红队验收。
- 已创建专用 VPC、子网、安全组与 SSH 公钥；最终网络配置 DryRun 成功后再次核价，使用唯一且持久保存的 ClientToken 创建一次。操作状态先落盘再发请求；结果不明确时拒绝重复购买。
- Wearing wheel SHA-256：`090b2dcf9af6fe7d1f9e2154b54ffe6861f625d3a78c7318022bb93660b656cf`。Hermes 版本：`367441274c48a03d12ee9f8d3d9ccd9bc1585392`，源码下载另有固定校验。
- 腾讯云 TAT 已在线。SSH 主机公钥通过该账户管理通道取得后锁定；最终使用已有 WireGuard 跳板，仅允许经过实际 SSH 验证的单个来源 IPv4 /32。
- 客机磁盘序列号精确匹配云端指定数据盘，确认大小/无分区/无文件系统/未挂载后才格式化；按 UUID 挂到 `/var/lib/wearing`。systemd 服务包含 `RequiresMountsFor`，租户进程为 wearing 用户，代码由 root 持有，服务组仅可读/执行。
- 云管理密钥和原本机个人数据未迁移。仅用户授权的 DeepSeek Key 通过 SSH stdin 配置到本实例，使用 `deepseek-flash`。不把 Key 放进 CLI 参数、TAT、发布包或公开日志。

## 实际结果

| 验收 | 结果 |
| --- | --- |
| 身份与模型 | 真模型回答“我是 Wearing”，成功完成工具调用 |
| 文件 | 创建 `cloud-proof.txt`，读回 `wearing-cloud-verified-20261003`；SHA-256 `512fc2f6dbf2d3790da1b905424692be25eb774663039fb80575db6c2bea088d` |
| 记忆 | 原生 memory 保存该部署验收条目；memory API 实际读取到，未伪造用户偏好 |
| 持续目标 | 最大一轮的测试目标由后台推进，实际读取文件并核对记忆，`used_steps=1`、`needs_review`；停在既定边界 |
| 访问边界 | 无凭据 401；错租户 403；外来 Origin 403；本地设备 API 501；正确实例凭据 200 |
| 整 VM 重启 | 云 API 重启后 boot ID 改变；数据卷与 systemd 自动启动正常，Wearing 所属引擎 `reachable` |
| 数据保留 | 对话视图 2 项（用户消息 + 目标轮次）、目标记录、记忆内容、文件和模型配置均与重启前一致；仅排除动态 `memory.observed_at` |
| 冷备份 | 服务排空并停止后通过 SSH 取私有状态包，开发机加密保存为 846604 字节，解密校验通过 |
| 隔离恢复 | 在 VM 的独立验证目录恢复 37 个文件，逐一比对 SHA-256；实例绑定一致，SQLite integrity_check=ok，tasks=2/messages=1/goals=1/goal_steps=1。没有启动恢复副本引擎或覆盖原实例 |
| 恢复原运行 | 备份后重新启动原服务，健康与持久记录再次通过，保持运行 |
| 本机保持 | 日常 tasks=5/messages=4/events=17/identities=2，目标与记忆仍为 0；模型/凭据及所有原记录前后快照一致，8765 引擎仍 reachable |

备份排除可重新安装的 `data/runtime`、`data/hermes/installs`、`data/hermes/cache`。首次备份包含 uv 依赖缓存，传输超时；服务在 finally 中恢复运行，后经核实缩小范围才完成。这不是丢弃个人状态。加密密钥仅保留开发机私有目录，不放进 VM 的备份。私有证据位于 `.wearing/cloud-trials/tencent-first/runtime-proof.json` 和 `backup-restore-proof.json`；原始响应、管理密钥、模型配置和密钥派生校验不公开、不打包。

Linux 首装曾在 venv 服务用户访问权限上停止：umask 077 导致 root 的目录仅本人可读。已经修复部署脚本并对本机按阶段继续安装，没有重放格式化。直接 SSH 的 banner 因本机网络路径不通；排查时先关闭密码登录，短暂的宽来源规则已撤回，最终只留已验证跳板 /32。没有改动原 VPN 或跳板服务。

## 当前边界与费用

这是一台正在运行的私人云端试验实例，持续按量计费，没有累计硬费用上限或自动关机。系统/数据盘包含在上述 ¥0.29/小时里，公网出流量、模型额度另计，报价不等于已结账账单。

当前网页仍使用原本地 Wearing，云端采用固定本地试验 Origin。真实 OIDC、公共 TLS/mTLS 入口、云端控制面及 Mac/Windows/手机出站连接器尚未部署。全新 VM 从备份重建、第二租户隔离、跨天/跨周目标、最终账单核对都未验收；冷备份解密与文件恢复不能冒充完整容灾。

源码回归 234 passed / 18 skipped（专用 PostgreSQL QA 集群本轮未启动，数据库层未改动，前轮实库验收保留）。腾讯报价与采购边界用例 26 项通过，包括未知写入不重发、涨价不购买、成功创建不重复购机。发布包构建成功，新部署脚本编译与包内路径检查通过；私有部署目录排除。最终 wheel 所有成员内容与实际部署 wheel 一致（压缩元数据不作为代码差异）。
