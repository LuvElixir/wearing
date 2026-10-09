# 腾讯云首轮部署与试跑

**最新状态（2026-10-04）：**原试验 VM 已正常关机并确认 `STOPPED / STOP_CHARGING`，CPU、内存停止计费，磁盘保留收费，公网 IP 已释放。私人预览与本机云连接器暂停；恢复步骤见 [停机记录](evidence/cloud-pause-2026-10-04.md)。下文保留部署当时的询价与验收记录。

2026-10-03。用户选择腾讯云，并授权复用已安装的 CLI。正常使用是一位租户一台独立 VM；首轮先部署一台验证安装、持续运行与恢复。第二台只在验证两个租户隔离时短期开，不是一个人需要两台电脑。

## 已核实的实际账户与配置

- 本机 `tccli 3.1.125.1` 的 default profile 可成功调用 STS、CVM、CBS、VPC 和余额查询；凭据仍由原 CLI 保管，没有复制进 Wearing、镜像或网页，也没有改动 CLI 配置。
- 香港和新加坡区域可用。所选区域当前按量剩余配额为 60/可用区，包月为 300/可用区；这不是跨区域永久配额承诺。
- 候选是普通硬件虚拟化 CVM，`SA2.MEDIUM4`，2 vCPU / 4 GiB，x86_64，官方干净 Ubuntu Server 24.04 镜像 `img-mmytdhbn`。SA2 查询结果为 UnderStock，因此实际创建前必须再查库存，不能悄悄换成其他价格的机型。
- 两块 `CLOUD_PREMIUM` 云盘各 40 GiB：系统盘与单独持久数据盘。香港二区已验证磁盘与机型组合可用。数据盘指定 `DeleteWithInstance: false`，但这不替代备份或包月到期保护。
- 公网按出流量付费，上限 5 Mbps。云端核心先不运行 GPU 或完整桌面；Mac/Windows 和手机仍是独立连接器。
- 初轮 `RunInstances(DryRun=true)` 验证机型/磁盘；本轮另建 Wearing 专用 VPC、子网、安全组和管理密钥，并对最终配置再次 DryRun 成功，才创建 **一台** 按量 VM。预检和购买分别记录。[官方预检语义](https://cloud.tencent.com/document/api/213/15730)。
- 最初查询两地均没有 VPC；香港 DryRun 后复查得到一套 `Default-VPC`，创建时间位于预检请求窗口。它很可能是首次区域预检自动初始化的默认网络，而非本轮显式调用 CreateVpc；已记录这个账户变化。基础 VPC/子网/路由表本身免费。[VPC 定价](https://buy.cloud.tencent.com/price/vpc)。后续仍明确选择 Wearing 专用网络，不把默认网络当作租户隔离验收。余额为正、没有欠费；不在文档或输出中公开余额与账户编号。

## 同配置真实询价

下面均为当前中国 API 端点、同一 CLI 账户、每台 VM 的人民币报价。系统盘和数据盘已经包含在 `InstancePrice` 内；另查 CBS 得到的磁盘价格只用于核对，不能重复加一次。[询价 API](https://cloud.tencent.com/document/api/213/15726)。

| 区域与机型 | 按量每小时，含两块盘 | 连续 24 小时 | 连续 720 小时估算 | 包月 1 个月，含两块盘 | 公网出流量 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 香港 SA2.MEDIUM4 | ¥0.29 | ¥6.96 | ¥208.80 | ¥155.82 | ¥0.6666/GB |
| 新加坡 SA2.MEDIUM4 | ¥0.30 | ¥7.20 | ¥216.00 | ¥149.66 | ¥0.7901/GB |
| 香港 SA5.MEDIUM4，较充足备选 | ¥0.39 | ¥9.36 | ¥280.80 | ¥205.41 | ¥0.6666/GB |
| 香港 S5.MEDIUM4，较充足备选 | ¥0.40 | ¥9.60 | ¥288.00 | ¥211.26 | ¥0.6666/GB |

720 小时是便于比较的 30 天运行估算，不是账单或每个自然月长度。报价保存完整一/二/三时间阶梯，不能拿第一个小时单价随意推算所有机型整月。当前 SA2 三档单价相同。包月查询明确一个月且不自动续费；正式创建前重新询价，折扣、库存与实际适用条件可变。

这些价格不包含模型调用、额外控制面/数据库/沙盒、快照和可能的 IP 保有费。香港快照官方单价为 ¥0.0002167/GiB/小时，例如实际占用 80 GiB 且保留 24 小时的毛额约 ¥0.416；实际占用、赠送额度和保留时长影响账单。[快照价格](https://cloud.tencent.com/document/product/362/2413)。公网 IP 是否另收保有费依绑定与账户配额条件，不把本次流量报价当成所有 IP 场景的总价。[IP 计费](https://cloud.tencent.com/document/product/213/113023)。

## 首轮收束与购买方式

工程建议：香港一台先按量短测，再在安装、恢复与模型网络路径验证后决定包月。长期常驻优先比较包月；无需把按量测试方式固定成产品唯一方案。用户若希望直接包月，可使用同一配置的一月报价。香港与本地连接延迟仍待实机测量，不能由地域名称推断已验证性能。

按量转包月受实例状态、配额、未支付订单等限制；转换时重新询价并核对实例、系统盘与数据盘的付费方式，带宽不会因此自动转包月。[转换说明](https://cloud.tencent.com/document/product/213/2762)、[数据盘转换](https://cloud.tencent.com/document/product/362/129133)。停机也不等于磁盘、IP 与备份停止收费。没有已实现的硬费用上限，运行估算不能作为强制支出上限。

用户已选择按量短测；本轮在告知 ¥0.29/小时及出流量单价后创建首台。购买使用独立网络、明确安全组和管理密钥，以及持久保存的唯一 ClientToken；下单前再次询价，三档小时价格都不高于接受的 ¥0.29。超时先查原请求，不直接重新购买。这是每小时单价门槛，不是累计费用上限。租户不得取得平台云管理密钥。按量测试结束先排空/备份，再核对停止与保留资源账单；不以销毁实例来模拟停止。

首台验收顺序：独立 VM/卷归属 → 固定 Wearing 发布包与 Hermes 版本安装 → 私有 Worker 健康与真实模型 → 记忆/目标/文件重启保留 → 一致性备份恢复。第二台随后验证两个租户错路由与网络拒绝。真实 OIDC、生产 TLS/mTLS、云端控制面和出站设备转发仍需继续开发；首台启动不会立即让现有 Mac/手机自动连上云端。

## 已落地的 Wearing CLI

```sh
# 这些命令仅查询；不创建、停止或删除资源。
wearing cloud tencent inspect --profile default --region ap-hongkong
wearing cloud tencent quote --profile default --request deploy/vm/tencent-quote-example.json
wearing cloud tencent quote --profile default --request deploy/vm/tencent-quote-example.json --billing monthly
```

适配器只调用白名单查询 API，通过官方 CLI 处理签名和凭据；不经 shell，不打印 SDK 原始错误或账户身份字段，不把密钥放进命令参数。当前仅验收中国站端点/CNY，国际站要单独适配。`account_ref` 是逻辑引用；报价另包含实际账户指纹，并让配置散列绑定账户与请求，不能把散列当成支出授权或云 API 幂等令牌。

报价命令先核实实际账户、可售机型及 CPU/内存、镜像平台/架构/状态/大小、相应计费配额，再询价。未知价格拒绝计算，包月不伪造小时价。输出保留 `creates_resources: false`、`ready_to_provision: false`、`hardware_isolation_verified: false`。

## 本轮真实试跑

已完成一台香港二区 SA2.MEDIUM4 的创建、安装及整 VM 重启验证。客机 `systemd-detect-virt` 返回 KVM；数据盘序列号与云端指定盘 ID 精确匹配，40 GiB 空盘经检查后格式化为 ext4，按 UUID 挂载到 `/var/lib/wearing`。服务配置包含 `RequiresMountsFor=/var/lib/wearing`，不在卷缺失时悄悄写系统盘。

Wearing 0.2 发布 wheel 校验 SHA-256 后安装；Hermes 固定在 `367441274c48a03d12ee9f8d3d9ccd9bc1585392`，源码另有固定校验。租户 Worker 只监听 `127.0.0.1:8765`，由 systemd 管理。云管理凭据未复制进 VM，用户已授权的 DeepSeek Key 只通过 SSH stdin 传入该实例，模型为 `deepseek-flash`；没有迁移本机个人聊天、目标、记忆或设备配置。

实际对话返回“我是 Wearing”，使用原生 memory 保存部署测试标记，通过文件工具创建并读回 `cloud-proof.txt`。一个最大一轮的后台目标随后独立读取文件并核对记忆，进入 `needs_review`，没有继续扩大轮次。整台 VM 重启后，boot ID 改变，systemd 自动启动，数据卷 UUID 保留，全部实际对话/目标记录、记忆内容、验收文件及模型配置校验一致。比较仅排除记忆 API 的 `observed_at`（新读取得到的新时间），未忽略其他内容差异。

安全边界实测：无实例凭据 401、错误租户 403、外来 Origin 403、本地设备控制 API 501。最后仅有一个已验证跳板来源的 `/32` SSH 入站规则；密码登录已关闭。出站拒绝三个 RFC1918 私网范围，只开放 HTTP/HTTPS/DNS。未开放 Wearing 或 Hermes 公网端口。腾讯安全组为有状态过滤器，允许入站连接的回包无需另行放开所有出站端口。[安全组说明](https://cloud.tencent.com/document/product/213/112610)。

本机直接 SSH 的 banner 始终未到达，已验证不是 Wearing/sshd 未启动。为排查曾在确认仅密钥登录后短暂放宽 SSH 来源，验证完立即撤回；最终使用既有 WireGuard 跳板，未改动跳板服务或 VPN。几个公网 IP 检测出口不足以可靠推断实际 SSH 来源，后续安装向导需要处理分流网络与管理通道。

Linux 首次安装发现 bootstrap 的 umask 077 令 root 创建的 venv 对服务用户不可读；已修复为 root 持有代码、wearing 组只读/执行。该 VM 在明确检查阶段后继续安装，没有重跑格式化或替换数据盘。加密冷备份另已验证：37 个文件在独立目录恢复后散列一致、实例绑定保留，SQLite 完整性正常；未启动恢复副本引擎。详细验收见[首台 VM 证据](evidence/tencent-vm-2026-10-03.md)。

操作入口 `deploy/vm/tencent-trial.py` 与客机 `deploy/tenant/bootstrap.py` 已保存；前者是操作者首台验证工具，不是 SaaS 租户自助采购接口。公共 Wearing 查询 CLI 的写接口白名单仍未开放。

## 证据与限制

原始响应、私有 SSH 管理密钥、部署操作账本与备份证据保存在 `.wearing/cloud-trials/tencent-first/`，不随发布包打包。本地测试通过 234 项；18 个 PostgreSQL 实例用例因专用 QA 集群未启动跳过，前轮已有实库验收。本轮未修改数据库层。付费采购边界另外覆盖未知写入结果不重发、报价上涨不购买、成功创建重试不再购机。

当前试验 VM 保持运行，按上述费率继续计费；没有硬累计费用上限，没有快照或第二台 VM。原本地 Wearing 服务未重启，个人任务/消息/目标/身份/记忆和模型密钥前后快照一致，真实引擎仍 reachable。

本轮不是 SaaS 上线：当前仍是私有测试 Origin；真实 OIDC、生产 TLS/mTLS、云端控制面与出站设备转发尚未部署。设备 API 明确返回未接通，现有 Mac/手机没有自动转为云端连接器。普通 CVM 也不等于独占物理服务器；第二租户隔离、全新 VM 从备份重建、跨天/跨周目标和完整账单核对仍需后续验收。

## 后续 S2 状态

上述 S1 验收之后，已在同一 VM 增加独立 HTTPS 443 设备入口，SSH 仍限制到已验证跳板 /32，Worker/Hermes 仍只监听回环。现有 Mac 已通过出站连接器配对手机和电脑，真实云端对话完成手机按键/观察，电脑只读观察也通过。原本未接通设备的描述属于 S1 阶段；当前见[连接器说明](device-connectors.md)及[S2 验收](evidence/remote-device-2026-10-03.md)。私有测试 Origin、真实 IdP/公开网页路由、生产 TLS/mTLS、第二租户及跨天目标等缺口仍存在。
