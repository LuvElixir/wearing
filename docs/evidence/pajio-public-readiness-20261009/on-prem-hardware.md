# 公司专用 PC：硬件盘点与宿主决定

日期：2026-10-09。只读数据采集窗口为 07:50–07:58 UTC（北京时间 15:50–15:58）。目标主机守卫匹配；用户已授权整机重装。本记录只证明 Windows 下的盘点结果及方案决定，不代表 Proxmox 已安装、Linux 兼容性通过、磁盘可靠或服务可对外提供。

## 证据与边界

数据来自私有目录 `.wearing/on-prem/20261009/` 中的以下文件。原始文件包含不宜公开的管理信息，保持私有；本报告只摘录硬件和验证状态，不含 IP、SSH 用户名、序列号、MAC、账号或凭据。

| 私有证据文件 | 本报告使用的内容 |
| --- | --- |
| `windows-inventory.json` | CPU、内存、匿名磁盘 / 卷、链路速率、只读执行状态及主机守卫结果 |
| `windows-platform.json` | Windows 版本、Hyper-V 状态、现有 VM、待重启及远程服务状态 |
| `hardware-detail.json` | 主板、BIOS、DIMM、物理盘与分区对应关系、GPU |
| `health-detail.json` | 可读取的磁盘计数、限定事件源检查和执行策略状态 |

现场执行记录确认：[只读脚本](../../../deploy/on-prem/inspect-windows.ps1)已通过 Windows PowerShell 5.1 原生 `ParseFile` 语法解析、传输前后 SHA 校验，并以仅进程级执行策略运行成功。采集环境报告 PowerShell `5.1.26100.9444`；Machine / User 执行策略未被永久修改。没有运行安装、磁盘自检或压力测试，也没有测速外传。

## 已核实硬件

| 项目 | 实际结果 | 解释与限制 |
| --- | --- | --- |
| CPU | Intel Core i7-12700F；12 物理核、20 逻辑线程；64 位 | 未做持续负载、温度或每租户性能测试；线程数不等于并发用户数 |
| 主板 / BIOS | GIGABYTE B760M D2HX SI DDR4；AMI BIOS F23 | 型号来自当前系统读取，不依据历史机器资料 |
| 内存 | 2 × 16 GiB Kimtigo DDR4；配置频率 3200；安装总量 32 GiB，系统可见约 31.84 GiB | 两槽已占用；读取的 DataWidth / TotalWidth 均为 64，没有本次 ECC 能力已验证的证据 |
| 官方扩展上限 | 该型号 2 个 DDR4 DIMM 插槽，最大 64 GB，单槽最大 32 GB | 可按兼容内存规格替换为 2 × 32 GB；尚未购买、更换或进行稳定性测试 |
| 内置存储 | 唯一内置 `kimtigo SSD 1TB`；NVMe、GPT；约 953.87 GiB | 当前启动盘与系统盘；只有一块 SSD，没有磁盘冗余 |
| 网卡 | 一个物理 Realtek Gaming 2.5GbE 网卡，状态 Up，当前协商 1 Gbps | 这是本地链路速率；公网可用上行、延迟、丢包和长期稳定性均未知 |
| GPU | NVIDIA GeForce RTX 3060，12,288 MiB 显存（12 GiB） | GPU 直通、Linux 驱动和本地模型容量未验证；云模型调用不依赖本机 GPU |
| 当前系统 | Windows 11 Pro，build 26200 | 不据此推断许可证类型或商业托管权利 |
| 当前虚拟化 | Hyper-V 功能已启用；HypervisorPresent 为 true；没有现有 VM；无待重启标志 | 部分 WMI 虚拟化字段为 false，不足以证明 BIOS 虚拟化关闭；Linux / KVM 仍需实测 |
| 当前远程服务 | sshd 为 Running / Auto | 只证明重装前入口可用；重装将终止该环境，恢复依赖现场控制台及新宿主身份核验 |

内存扩展依据[技嘉该型号官方规格](https://www.gigabyte.com/cr/Motherboard/B760M-D2HX-SI-DDR4-rev-1x/sp)及[官方中文手册](https://download.gigabyte.com/FileList/Manual/mb_manual_b760m-d2hx-si_1004_sc.pdf?v=2893adbdb7592c4a6aca5e1020e7a104)。这是主板规格上限，不是升级后实际稳定性或可承载租户数的保证。

## 安装盘范围：C / D 是同一块 NVMe

当前 Storage 数据将以下分区全部映射到物理磁盘 0，即唯一内置 `kimtigo SSD 1TB`：

| 分区用途 | 当前容量 | 盘点时可用空间 |
| --- | --- | --- |
| C | 约 852.67 GiB | 约 527.47 GiB |
| D | 约 100.00 GiB | 约 99.91 GiB |
| EFI / MSR / 恢复分区 | 同盘系统辅助分区 | 不适用 |

**整盘安装 Proxmox 会同时覆盖 C、D 和原 Windows 启动 / 恢复分区。D 不是可保留的第二块硬盘。** 安装前先完成需保留资料的异地备份和恢复抽查；安装器中重新核对型号、约 954 GiB 容量及唯一内置盘，不把安装 U 盘选为目标。若现场目标与记录不一致，应暂停核对，不能凭“磁盘 0”自动清空。

## 健康与可靠性：仍未完成的验证

- Windows 报告该盘 Healthy / Online，当前温度约 43°C。提供方返回的 wear 字段为 0，但 PowerOnHours、读写总错误和不可校正错误等字段为空，**完整 SMART / NVMe 健康与寿命仍未知**；不能把 wear 0 解释成新盘或 100% 健康。
- 指定的 WHEA-Logger、disk、stornvme、Ntfs、Kernel-Power 五类事件源近 7 日未检出记录。这不是全系统无故障证明，也不能替代磁盘、内存、散热和持续运行测试。
- UPS 型号、覆盖范围、运行时长及有序关机未确认。电池列表为空不能证明没有外接 UPS。
- 公网持续上行、CGNAT / 固定公网条件、国内移动网络连通性和公司网络隔离未测；不从 1 Gbps 网卡速率推导公网容量。
- 单 SSD、单主机和单物理网卡都需要明确恢复方案；本机快照不能替代异地备份。目前不承诺高可用、SLA、付费生产许可或并发用户数。

## 决定：Proxmox VE + Ubuntu LTS 独立 VM

采用 Proxmox VE 作为裸机宿主，在其上建立 Ubuntu LTS 控制服务 VM 与每租户独立 KVM VM。理由是本机已明确专用于服务器且可重装，集中管理 VM、控制台、备份和恢复更适合当前操作条件，也保持[每租户独立 VM 产品基线](../../saas-architecture-2026-10-03.md)。普通 Docker / LXC 可在租户 VM 内使用，不能替代跨租户 VM 隔离。[Proxmox 官方能力](https://proxmox.com/en/products/proxmox-virtual-environment/features)

Ubuntu Server + KVM / libvirt 同样能提供独立 VM，是可选宿主路线，但需要自行组织 VM 管理与备份运维；本次不并行落地。安装 Linux 后必须验证硬件虚拟化和真实 VM 启动，不能把 Windows 功能状态当成 Linux 验收。[Ubuntu libvirt 文档](https://ubuntu.com/server/docs/how-to/virtualisation/libvirt/)

现有 Windows Client Hyper-V 只用于内部验证。当前授权来源及适用协议未核定，不能由“Hyper-V 已启用”推出可以对外商业托管；Microsoft 的 Windows 11 OEM 条款有相关用途限制，本次不将其作为付费服务的长期宿主。[Hyper-V 官方说明](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/overview?pivots=windows)、[Windows 11 OEM 官方条款示例](https://www.microsoft.com/content/dam/microsoft/usetm/documents/windows/11/oem-%28pre-installed%29/Useterms_OEM_Windows_11_EnglishGreatBritain.pdf)

## 接下来按证据验收

1. 完成旧资料备份与恢复抽查，核验安装介质；现场按 UEFI USB → Proxmox Terminal UI → 唯一 1TB kimtigo 内置盘操作。网络与凭据从私有安装记录取，不编固定 IP 或密码。详细步骤见[接入文档](../../on-prem-host.md#现场安装步骤)。
2. 安装后核对新宿主身份、Linux 网卡 / NVMe / KVM，取得完整磁盘健康数据，验证备份与一次实际恢复。
3. 建立私有管理边界、公司 LAN 隔离及至少两个租户 VM；同时测试 IPv4 / IPv6 的跨租户、管理面与办公网拒绝访问。
4. 验证任务不依赖开发 Mac 常驻、断网 / 重启后恢复及手机结果通知，再按真实 VM 资源、磁盘增长和公网测量建立容量模型。

本文没有包含或执行远端改动、USB 写入、重装、网络变更或 Git 提交；后续安装与服务可用性需要独立执行证据。
