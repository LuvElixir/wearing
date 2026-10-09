# 用公司闲置 PC 承载 Pajio：接入准备

2026-10-09。目标主机已重装为 **Proxmox VE 裸机 + Ubuntu LTS 独立 VM**，并完成经物理控制台核对主机身份的密钥管理接入。已创建一台控制服务测试 VM、两台租户测试 VM，完成首轮网络隔离和备份恢复实测。这里的 VM 是内部验收环境，尚未部署真实用户的 Agent 服务；公开服务、用户容量和长期稳定性尚未验收。后续执行证据见[宿主与虚拟机验收记录](evidence/pajio-public-readiness-20261009/on-prem-provisioning.md)。

完整脱敏结果见[本机硬件与安装决定](evidence/pajio-public-readiness-20261009/on-prem-hardware.md)。原始盘点、网络参数和登录资料保留在私有安装记录中，不放入公开仓库。

| 已核实项目 | 结果 | 对安装的影响 |
| --- | --- | --- |
| CPU / 内存 | i7-12700F，12 核 / 20 线程；32 GiB，2 × 16 GiB DDR4-3200 | 两个内存插槽已占用；尚未进行 VM 容量测试 |
| 主板 | GIGABYTE B760M D2HX SI DDR4，BIOS F23 | 官方上限 64 GB；升级到 64 GB 需替换为 2 × 32 GB，不是再加两条 |
| 系统盘 | 唯一内置 `kimtigo SSD 1TB` NVMe，约 953.87 GiB | **C、D 都在这一块盘上；整盘安装会同时覆盖两者** |
| 网卡 / GPU | 一块 Realtek 2.5GbE 网卡，当前协商 1 Gbps；RTX 3060，12 GiB 显存 | 上行、办公网隔离、Linux 驱动与 GPU 用途均需另验 |
| 重装前系统 | Windows 11 Pro，build 26200；当时 Hyper-V 已启用且无现有 VM | 此行保留安装前盘点，不代表当前运行系统 |

内存规格来自[技嘉该型号官方规格](https://www.gigabyte.com/cr/Motherboard/B760M-D2HX-SI-DDR4-rev-1x/sp)。内存升级尚未执行。Linux 下已读取 NVMe SMART：介质错误 0、寿命使用量 2%、历史异常断电 31 次；这不是持续 I/O 或断电恢复验收。UPS 和公网持续上行仍未测。

## 建议选择

**本机采用裸机 Proxmox VE，在其上为每个租户建立独立的 Ubuntu LTS KVM 虚拟机。** 这保持现有[每租户独立 VM 的产品基线](saas-architecture-2026-10-03.md)。Ubuntu Server + KVM / libvirt 仍是未来可选的宿主方案，但本次不同时维护两套宿主方案。

| 路线 | 适合本次的理由 | 条件与代价 |
| --- | --- | --- |
| Proxmox VE 裸机 + KVM VM | VM、磁盘、控制台、备份与启动顺序可集中管理，适合少量物理宿主的操作者 | 安装会改写所选磁盘；需硬件兼容、补丁和备份运维；一台 PC 仍是单点 |
| Ubuntu Server + KVM / libvirt | 沿用 Ubuntu 运维和自动化，独立 VM 边界不变 | 需自行组织 VM 生命周期、网络、防火墙、备份和监控；采用 system 实例而非个人桌面 session 充当常驻服务 |
| 现有 Windows 11 Pro + Hyper-V | 可供内部短期 VM 验证 | 本次不作为面向付费租户的长期宿主；Windows 授权来源及适用协议未核定，不承诺商业托管许可、生产支持或并发能力 |
| 普通 Docker / LXC 容器直接分租户 | 可在某个租户自己的 VM 内组织应用 | 共享宿主内核，不作为本项目跨租户 VM 隔离的替代品 |

Proxmox 官方区分 KVM 完整虚拟化与共享宿主内核的容器；其生产建议包括可靠硬件、客体所需内存、快速冗余存储等。普通 VM 仍信任宿主管理员与 hypervisor，不是对宿主也保密的机密计算，不应叫作每人独占物理机。[虚拟化能力](https://proxmox.com/en/products/proxmox-virtual-environment/features)、[硬件要求](https://proxmox.com/en/products/proxmox-virtual-environment/requirements)

Ubuntu 官方要求先检查硬件虚拟化，并提供 `kvm-ok`、libvirt system VM 和自启动等路径。Windows 读到的标志只用于预判；安装 Linux 后仍需核对 KVM、磁盘 / 网卡驱动、实际 VM 启动与隔离。[Ubuntu libvirt 文档](https://ubuntu.com/server/docs/how-to/virtualisation/libvirt/)

Windows Client Hyper-V 具备虚拟化能力，并不自动赋予 Windows 商业托管权利。Microsoft 的 Windows 11 OEM 条款对服务器用途和商业托管有具体限制；当前机器适用哪种协议尚未核定，因此只将现有 Windows 环境用于内部验证。[Hyper-V 官方说明](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/overview?pivots=windows)、[Windows 11 OEM 官方条款示例](https://www.microsoft.com/content/dam/microsoft/usetm/documents/windows/11/oem-%28pre-installed%29/Useterms_OEM_Windows_11_EnglishGreatBritain.pdf)

## 现场安装步骤

1. **先落实恢复路径。** 目标机与唯一内置盘已核实。确认旧 C / D 资料的异地备份及恢复抽查完成，保留现场显示器、键盘和安装记录。重装会终止现有 Windows SSH；不能指望该连接跨重装继续工作。
2. **使用已校验的安装 U 盘。** 安装介质的下载、写入、目标外置盘核对及校验由负责介质的操作者完成；拿到完成记录后再启动。本文件不表示 U 盘已完成制作。
3. **从 UEFI USB 启动。** 在现场启动菜单选择该 U 盘的 UEFI 入口，进入 `Install Proxmox VE (Terminal UI)`。不要仅因安装建议就关闭 Secure Boot；按所选安装版本的支持情况处理。
4. **核对安装目标。** 安装器中的目标应是唯一内置 `kimtigo SSD 1TB`，约 954 GiB；排除安装 U 盘。若型号、容量或内置盘数量与盘点不一致，先停下核对。**不能把 D 盘当成独立备用盘；C / D 同属这一块 NVMe。** 文件系统及分区按安装记录选择，单盘不具备镜像冗余。
5. **照私有记录填写参数。** 主机名、管理地址 / 前缀、网关、DNS、管理员联系方式和凭据从私有安装记录取；不在现场猜地址或照抄示例密码。管理员密码直接在本地设置并放入受控密码库，不放进公开证据。
6. **确认摘要后安装。** 再次核对整盘覆盖范围、目标型号及管理网络参数。完成后按提示重启、移除 U 盘并从内置盘启动；在现场控制台确认实际管理地址，不能以旧 Windows SSH 可达作为成功依据。
7. **先恢复私有管理，再建服务。** 从可信管理设备核对新宿主身份及证书 / SSH 主机密钥。重装后密钥变化需独立核实，不能直接绕过校验。验证 KVM、存储、驱动、补丁来源和备份恢复，再创建 Ubuntu LTS 模板及租户 VM。

Terminal UI 与图形安装器使用相同安装逻辑，适合减少图形兼容性问题；所选目标盘会被重新分区。具体版本的安装行为以[Proxmox 官方安装文档](https://github.com/proxmox/pve-docs/blob/master/pve-installation.adoc)为准。

## 保留的只读盘点方法

以下方法用于盘点复核或后续新增主机，不自动执行安装。普通权限先试；缺项明确记为未知，不自动提权、装依赖或更改 BIOS。

### 只读检测

脚本：[deploy/on-prem/inspect-windows.ps1](../deploy/on-prem/inspect-windows.ps1)。使用 Windows PowerShell 5.1 或更新版本，在已核对的目标机上运行：

```powershell
powershell.exe -NoProfile -File .\inspect-windows.ps1

# 已知目标的远程运行可加守卫；不匹配在硬件查询前立即拒绝。
powershell.exe -NoProfile -File .\inspect-windows.ps1 -ExpectedComputerName EXPECTED-HOST
```

不要为运行脚本永久修改执行策略。如果公司策略阻止它，由操作者按现有软件 / 脚本管理流程处理。脚本默认只写标准输出；如需文件，由操作者明确保存到自己的受控目录，并先检查内容再分享。

输出包含 CPU 型号 / 核心数 / 虚拟化标志、内存、Windows 版本与 build、物理磁盘容量和系统盘标记、卷容量 / 可用空间、可取得的只读磁盘健康计数、网卡报告链路速度。没有主机名、账号、序列号、MAC / IP、磁盘卷标、业务文件内容、密码、恢复密钥或 Wi-Fi 资料；不上传、安装、测速、扫描网络、启动磁盘自检或修改系统。查询失败只输出固定状态，不输出可能含路径或主机名的原始错误。

Storage 命令在 Windows 故障转移群集中可能作用于集群；脚本在发现本机装有 `ClusSvc` 或无法确定时跳过高级磁盘读取，只保留本机 WMI 摘要。网络、虚拟和存储池磁盘不请求可靠性计数。[Microsoft Storage 命令说明](https://learn.microsoft.com/en-us/powershell/module/storage/get-storagereliabilitycounter?view=windowsserver2025-ps)

**解释结果时：** `unavailable`、`unknown`、空数组和 `null` 都不是通过；网卡 1 Gbps 不是上行带宽；Windows 显示虚拟化 false / null、尤其已有 hypervisor 时，应复核 BIOS 和 Linux；“Healthy / OK”也不能代替磁盘寿命、读写与恢复验证。报告中的匿名卷序号不对应磁盘号；真正安装时必须现场重新对照容量与物理盘，不能直接拿本报告自动格式化。

### 只解析语法，不执行查询

开发端若没有 PowerShell，可在目标 Windows 先执行以下原生解析检查，再运行脚本。解析器不会执行脚本：

```powershell
$pajioTokens = $null
$pajioParseErrors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path (Get-Location) 'inspect-windows.ps1'),
    [ref]$pajioTokens, [ref]$pajioParseErrors
)
if ($pajioParseErrors.Count -gt 0) {
    $pajioParseErrors | ForEach-Object {
        [pscustomobject]@{ error_id = $_.ErrorId; line = $_.Extent.StartLineNumber }
    }
    throw 'Pajio inspection script has syntax errors; do not run it.'
}
'Syntax parsed; hardware inspection has not run.'
```

2026-10-09 已在目标机的 Windows PowerShell 5.1 中通过原生 `ParseFile` 解析及传输前后 SHA 校验，随后使用仅进程级执行策略成功完成只读运行；未永久更改 Machine / User 执行策略。硬件结果及证据分层见[硬件记录](evidence/pajio-public-readiness-20261009/on-prem-hardware.md)。这证明脚本能在该目标环境运行，不代表 Linux 安装或磁盘健康验收已经通过。

## 上行与稳定性怎么测

脚本**不测速、不外传**。运营者先确认公司宽带是否允许此用途、办公高峰可用上行、是否有固定公网地址 / CGNAT，以及停电和网络维护情况；这些不是从设备型号能得出的结论。

经公司网络负责人同意后，人工选择可信测试端点（优先自有测试服务器），使用合成数据测不同时间段的持续上行、延迟、抖动、丢包和长连接稳定性；记录端点、时段、时长和方法。不要上传公司文件作为测试载荷，不把测速页显示的短时峰值当作稳定容量。涉及第三方测速或新装测速工具时另行明确端点与数据传输范围。

## 重装后应形成的结构

```text
用户 App -> 受认证的公网入口 / 网关
                       |
                  受控加密连接
                       |
公司独立服务器网段 -> 入口 / 控制服务 VM
                       +-> 租户 A VM -> 自己的状态与设备凭据
                       +-> 租户 B VM -> 自己的状态与设备凭据

管理人员 -> 私有管理网络 -> hypervisor
备份任务 -> 公司以外的独立备份位置
```

- **公司 LAN 隔离。** 租户 VM 不直接桥接到办公电脑 / NAS 所在网段；单独服务器 VLAN / 物理网口或等效边界，默认拒绝跨租户、办公 LAN 与管理面访问，仅放明确需要的目标。DHCP / DNS 等按设计显式允许。管理网与租户网分别控制 IPv4、IPv6；仅有 NAT 或 VLAN 标签并不等于访问已被阻止。
- **管理入口独立。** Proxmox 管理页、SSH、数据库和宿主 API 不直接开放公网；Agent 和租户拿不到 hypervisor 管理凭据、宿主目录、其他 VM 磁盘或全局备份密钥。固定内网地址优先通过受管理的 DHCP 保留或经网管分配的静态地址，不擅自占用地址。
- **出站隧道只是候选。** 可评估 Cloudflare Tunnel 承载 HTTP / WebSocket 产品入口，或用 WireGuard 到受控公网网关承载专用网络；仍需 Pajio 自己的 OIDC、租户路由和实例认证。隧道不是授权边界，也不解决公司停电。需验证国内实际连通、长连接、上传限制和提供商条款后选型，不把隧道连到整个办公网。Cloudflare 官方说明其连接器建立出站连接，无需给源站公网入站端口。[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)、[Ubuntu WireGuard](https://ubuntu.com/server/docs/how-to/wireguard-vpn/)
- **磁盘与备份。** 在备份可恢复后再做磁盘健康 / 温度 / 磨损与实际 I/O 检查；状态缺失按未知处理。可按硬件条件设计镜像等冗余，但 RAID / 镜像和本机快照均不是异地备份；保留公司以外、独立权限、加密且定期恢复抽查的副本。定义能接受的丢失时长与恢复时长，再决定备份频率。Proxmox 官方有 VM 备份恢复机制，具体存储方案仍依实际硬件选择。[Proxmox 备份与恢复官方文档镜像](https://github.com/proxmox/pve-docs/blob/master/vzdump.adoc)
- **断电与 UPS。** UPS 同时覆盖主机及必要网络设备；测实际负载与可用续航，并实现低电量时 VM 有序关闭。恢复供电后的 BIOS 自动开机、网络 → 存储 → 网关 / 数据库 → worker 的顺序和健康门槛均需演练；不要把“来电自动开机”当作任务已恢复，也不直接拔电测试正在使用的盘。
- **单机边界。** 单台消费级 PC 无高可用保证；内存、磁盘、网络、断电、维护都会影响全部租户。暂不承诺租户数或 SLA。资源先留宿主与控制服务余量，再用真实每租户 RSS、CPU、存储增长、I/O 和网络测量做容量模型；不把逻辑线程数直接当用户数，不超售内存起步。GPU 不是调用云模型的必要条件，有 GPU 也不代表已能提供本地模型服务。

## 与公开准备度衔接

公司 PC 解决的是一种算力来源，不自动解决[公开准备度报告](evidence/pajio-public-readiness-20261009/product-gap-audit.md)中的真实登录、分发签名、通知、额度、数据删除和用户支持。

接入后按顺序验收：宿主与盘确认 → 备份恢复 → Linux / KVM → 两个租户 VM 和双向越权检查 → 有鉴权公网入口 → 关闭开发 Mac 后任务继续 → 物理手机结果通知 → 断网 / 重启恢复 → 单租户导出和删除不影响另一租户。公开之前同时验证 tenant VM 无法访问公司网 / hypervisor；部署没有通过这些步骤时只称“主机已准备”或“局部链路通过”。

本文保留安装前的操作指南；当前执行进度以[独立验收记录](evidence/pajio-public-readiness-20261009/on-prem-provisioning.md)为准，不能把内部 VM 基础环境验收当作真实租户服务验收。官方资料于 2026-10-09 查阅，后续部署仍需核对选择版本的支持与升级路径。

## 核心服务部署进度（2026-10-09 晚）

真实 OIDC、PostgreSQL、HTTPS 和两个租户 Agent Core 已部署；真实模型与文件任务、跨账号拒绝、服务重启和应用备份恢复已通过，详见[业务服务验收](evidence/pajio-public-readiness-20261009/core-service-deployment.md)。公开注册尚未开放；这不替代 App 分发、物理设备接入、通知及长期运营验收。
