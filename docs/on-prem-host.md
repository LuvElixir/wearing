# 用公司闲置 PC 承载 Pajio：接入准备

2026-10-09。当前只有方案与只读检查脚本，尚未重装、修改公司网络或部署服务。已获得整机可重装的授权；仍须先确认实际目标机、磁盘和可恢复备份。历史设备资料不能替代本次检测结果，也不据此承诺能容纳多少用户。

## 建议选择

**优先评估裸机 Proxmox VE，在其上为每个租户建立独立 KVM 虚拟机；Ubuntu Server + KVM / libvirt 是可选方案。** 这是为了保持现有[每租户独立 VM 的产品基线](saas-architecture-2026-10-03.md)，不是要求用户购买特定厂商服务器。

| 路线 | 适合本次的理由 | 条件与代价 |
| --- | --- | --- |
| Proxmox VE 裸机 + KVM VM | VM、磁盘、控制台、备份与启动顺序可集中管理，适合少量物理宿主的操作者 | 安装会改写所选磁盘；需硬件兼容、补丁和备份运维；一台 PC 仍是单点 |
| Ubuntu Server + KVM / libvirt | 沿用 Ubuntu 运维和自动化，独立 VM 边界不变 | 需自行组织 VM 生命周期、网络、防火墙、备份和监控；采用 system 实例而非个人桌面 session 充当常驻服务 |
| 普通 Docker / LXC 容器直接分租户 | 可在某个租户自己的 VM 内组织应用 | 共享宿主内核，不作为本项目跨租户 VM 隔离的替代品 |

Proxmox 官方区分 KVM 完整虚拟化与共享宿主内核的容器；其生产建议包括可靠硬件、客体所需内存、快速冗余存储等。普通 VM 仍信任宿主管理员与 hypervisor，不是对宿主也保密的机密计算，不应叫作每人独占物理机。[虚拟化能力](https://proxmox.com/en/products/proxmox-virtual-environment/features)、[硬件要求](https://proxmox.com/en/products/proxmox-virtual-environment/requirements)

Ubuntu 官方要求先检查硬件虚拟化，并提供 `kvm-ok`、libvirt system VM 和自启动等路径。Windows 读到的标志只用于预判；安装 Linux 后仍需核对 KVM、磁盘 / 网卡驱动、实际 VM 启动与隔离。[Ubuntu libvirt 文档](https://ubuntu.com/server/docs/how-to/virtualisation/libvirt/)

## 现在先做的三件事

1. 确认是哪台电脑、是否有人现场、已有的可信远程入口；远程连接保留主机密钥校验，不能猜测公司网段或扫描找机器。
2. 在目标 Windows 上运行下列只读脚本，得到脱敏硬件摘要。普通权限先试；缺项明确记为未知，不自动提权、装依赖或更改 BIOS。
3. 明确每块盘是否可清空、旧剪辑 / 工作资料的异地备份和恢复抽查结果、USB 启动与断网后本地控制台路径。完成这些后再制作对应硬件的具体重装盘计划。

### 只读检测

脚本：[deploy/on-prem/inspect-windows.ps1](../deploy/on-prem/inspect-windows.ps1)。使用 Windows PowerShell 5.1 或更新版本，在已核对的目标机上运行：

```powershell
powershell.exe -NoProfile -File .\inspect-windows.ps1

# 已知目标的远程运行可加守卫；不匹配在硬件查询前立即拒绝。
powershell.exe -NoProfile -File .\inspect-windows.ps1 -ExpectedComputerName LUCKYLOADING111
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

初次编写时当前 Mac 没有 `pwsh` / `powershell` / `dotnet`，尚未通过 PowerShell 运行时解析或目标 Windows 执行。静态检查不能替代该验证；远程返回真实结果后另存验收记录。

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

本轮未执行重装、购买硬件、设置地址 / VLAN、防火墙、隧道或备份；具体盘和网络计划等实时检测与现场条件明确后落实。官方资料于 2026-10-09 查阅，部署时重新核对选择版本的支持与升级路径。
