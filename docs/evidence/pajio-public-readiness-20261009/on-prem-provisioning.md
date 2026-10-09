# Pajio 专用宿主与内部虚拟机验收

日期：2026-10-09。本文只记录已执行的服务器基础工作，不代表 Agent Core 已部署、产品已上线或已有可承诺的用户容量。管理地址、管理员公钥、原始日志和备份归档位于受限的本地 `.wearing/on-prem/`，不得提交公开仓库。

## 已完成

| 项目 | 执行与证据 |
| --- | --- |
| 裸机与远程管理 | Proxmox 安装完成；SSH 主机指纹经用户提供的物理控制台照片核对，使用独立管理密钥严格校验连接 |
| 宿主补丁 | 软件更新事务成功，`dpkg --audit` 无未完成项；重启后 `pve-manager/9.2.21`、内核 `7.0.14-22-pve`；无失败的 systemd 单元 |
| 管理入口 | 管理 SSH 与管理 HTTPS 仅允许既定内网网段；关闭 SSH 密码与交互式认证；保留现场控制台恢复方式 |
| 资源 | Linux 识别 i7-12700F / 20 逻辑处理器、约 32 GiB 内存、NVMe、KVM；三台 VM 各预留 2 vCPU / 4 GiB 内存 / 32 GiB 系统盘，关闭 balloon；这不是实际 Agent 负载结果 |
| 系统镜像 | Ubuntu 24.04 LTS 官方 cloud image；GPG 签名及 SHA-256 校验通过，SHA-256 `6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2` |
| 虚拟机 | 9000 为未启动模板；1100 控制服务预留 VM；1101、1102 为租户 A/B 测试 VM；尚无真实用户资料或模型凭据 |
| 隔离 | 每台 VM 独占无物理端口的独立 bridge；不桥接办公 LAN；出站反伪造、内网目的地址拦截与有限出站放行；IPv6 在 guest bridge 禁用，同时保留显式 IPv6 拦截规则 |
| 隔离实测 | 三台 VM 均能连接官方镜像站 HTTPS；访问宿主 SSH/管理端口、办公网关、元数据地址、其他 VM SSH 均超时，且宿主防火墙 DROP 计数增加。宿主侧先验证其他 VM 的 SSH 确实在监听，避免将端口未启动误当隔离 |
| 重启 | 完成宿主重启，三台 VM 按顺序自动启动；防火墙先于 VM 启动；再次完成三台 VM 的连接与隔离实测 |
| 备份恢复 | 租户 A 的压缩备份已复制到 Mac 并校验一致；恢复成独立测试 VM，读回预先写入的测试文件；修复初始化身份后再次备份恢复，无网卡启动也成功读回文件，且保留预期 SSH 身份。两个恢复副本均关闭且断开网络 |

磁盘 SMART：温度 41°C、寿命使用量 2%、介质错误 0、通电 789 小时、历史异常断电 31 次。它只是一份设备报告，不是磁盘长时间压测或断电可靠性保证。

## 验收时发现并修复的初始化问题

修改共用 cloud-init userdata 后，默认生成的 instance-id 发生变化；重启触发重新初始化并生成新的 SSH 主机密钥。严格 SSH 校验拒绝了连接，未通过关闭校验绕过。

修复方法：通过已认证的宿主 guest-agent 通道读取 VM 当前 instance-id 和公钥；为每台 VM 保存独立、固定的 metadata snippet；保留 guest hostname；显式将 qemu-guest-agent 纳入 multi-user 启动目标。再次重启三台 VM后，原有固定公钥校验通过、cloud-init 无错误、网络隔离复测通过。

维护工具：[pin-cloud-init-identity.py](../../../deploy/on-prem/pin-cloud-init-identity.py)。工具在现有三台 VM 上实际运行通过，保护已有 metadata provider，并要求初始化成功及 VM 名称匹配。**创建新租户要分配新的实例身份，不能把另一个租户的 metadata 直接复制过去。**

首次恢复为无网卡副本时，guest-agent 未就绪；随后停止原测试 VM，使恢复副本独占原隔离网段，完成初始化和文件回读。不能将此前的“恢复命令成功”当作启动与数据验收。固定 instance-id 和 guest-agent 启动依赖后，重新创建备份、复制到 Mac 并校验，再恢复为无网卡的 1192：guest-agent 可用，测试文件及原 SSH 公钥都与预期一致，已关闭副本。归档中引用的外部 cloud-init snippets 已随宿主配置一同保存，不能只备份 `.vma.zst`。

## 网络实现与使用范围

- [lab-interfaces](../../../deploy/on-prem/lab-interfaces)：三个固定测试桥，不包含物理端口。每桥仅允许一台运行中的 VM。
- [lab-network.nft](../../../deploy/on-prem/lab-network.nft)：分别处理宿主访问、租户转发、IPv4 NAT；不清空 Proxmox 自己的规则。
- [apply-lab-network.sh](../../../deploy/on-prem/apply-lab-network.sh)：先语法检查，再原子替换专用规则表；systemd 启动依赖确保其先于 VM 自动启动。
- [host-management.nft.in](../../../deploy/on-prem/host-management.nft.in)：将 `MANAGEMENT_CIDR` 替换为经确认的管理网段后使用；仅适用于当前单节点，不包含集群/迁移/SPICE 开放规则。
- [probe-lab-isolation.py](../../../deploy/on-prem/probe-lab-isolation.py)：在 VM 内执行实际连接探测；拒绝连接、超时、错误分别记录。需要同时采集宿主侧正向对照和防火墙计数。

该固定三 VM 规则集是内部验收基础，不是多租户自动开通系统。扩容必须同时生成独立网桥、地址、源地址约束、目的限制和生命周期清理；不能仅 `qm clone` 后接上现有租户 bridge。基础验收时控制 VM 也不能跨 VM 访问；后续业务部署仅开放指定租户的 8443 端口并加双向 TLS 与实例鉴权，见[核心服务验收](core-service-deployment.md)。

IPv6 验收范围为无可用默认路由、宿主 guest bridge 禁用及显式丢弃规则；本轮未进行所有 IPv6 隧道或 hypervisor 逃逸攻击测试。网络隔离不代表宿主管理员无法查看 VM 内容。

## 软件来源与公开上线前剩余条件

无 Proxmox 订阅。安装器的 enterprise-only 源已禁用，使用官方签名 keyring 校验 no-subscription 软件包。官方下载源在此网络中较慢，改用[中科大镜像的 HTTPS 传输](https://mirrors.ustc.edu.cn/help/proxmox.html)，保留 Proxmox 官方签名校验。镜像存在同步时差：本轮官方源曾提供 `7.0.14-23-pve`，实际验证运行的是镜像提供的 `7.0.14-22-pve`，不能称为已追平所有上游更新。

Proxmox 官方将 enterprise 源作为生产推荐，no-subscription 包验证程度不同；当前内部验证没有购买订阅，公开发布前需确定长期更新与支持策略。[官方软件源说明](https://github.com/proxmox/pve-docs/blob/master/pve-package-repos.adoc)

以下为基础验收时的剩余项；当晚核心服务部署、真实模型调用与一轮加密应用备份恢复已完成，最新状态以[核心服务验收](core-service-deployment.md)为准：

1. Agent Core、控制服务、PostgreSQL、真实身份提供方与公网 HTTPS 的部署及两个真实账号的隔离验收。当前 VM 只有操作系统与基础管理组件。
2. 路由器 DHCP 保留/地址冲突防范、持续上行与公网入口验证、公司网络断开恢复；管理面始终不直接暴露公网。
3. 独立异地、加密、定期备份与告警。Mac 上的副本已校验，但不是常驻异地备份方案，也没有数据库应用一致性证据。
4. UPS、来电启动与有序关机演练；单 SSD / 单主机仍是故障单点。
5. 模型 API 额度与成本实测、用户并发容量、磁盘增长、水位与资源限额；不能用 VM 数推导可售用户数。
6. App 外部分发签名、真实通知、账号与数据导出/删除、支持与隐私流程，详见[公开准备度报告](product-gap-audit.md)。

镜像流程遵循[Ubuntu 镜像校验](https://ubuntu.com/docs/public-images/public-images-how-to/verify-image-checksum/)与[Proxmox cloud-init 文档](https://github.com/proxmox/pve-docs/blob/master/qm-cloud-init.adoc)。备份机制参考[Proxmox vzdump](https://github.com/proxmox/pve-docs/blob/master/vzdump.adoc)，本文的通过结论来自实际执行日志，而非文档描述。
