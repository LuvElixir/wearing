# 每用户 Linux + Android：运营创建与容量准入

状态：已有可测试的运营容量账本、只读预演与停止状态 VM 创建/配置传输；本轮仅执行真实宿主只读 inventory/plan，没有 reserve/apply、额外创建 VM 或改变现有归属与网络。尚无公开开机、配对交付或休眠 API；用户端不得出现“立即获得两台始终在线设备”的承诺。

## 当前代码边界

- `cloud/instance.py` 固定 Agent 实例及私有数据卷归属，不负责 VM 创建。
- `cloud/placement.py` 是云选型预览，明确 `ready_to_provision=false`。不能把它当成已实现 Proxmox 调度。
- `cloud/device_setup.py`、`cloud/relay.py` 和连接器已提供资源 offer、绑定、能力范围、租约；新增设备应继续走这些路径。
- `device_gateway.py` 和私密媒体保留用户/Agent 控制互斥。创建、唤醒与休眠只管理设备生命周期，不另建一套输入权限。
- `cloud/device_provisioning.py` 使用现有 `Record`/`Identifier` 类型实现私有事务账本、容量预留和中断恢复；`cloud/proxmox_devices.py` 是固定动作 SSH 传输；`cloud/device_operator.py` 是独立运营入口，未接公开路由或 Agent 工具。只创建已停机的完整克隆、移除继承网络/引导凭据，返回 `staged` 与 `product_ready=false`。使用方式见 [运营命令与边界](../device-provisioning-operator.md)。
- 模型额度与设备资源分别计量。设备有空位不表示模型预算充足；模型调用先走现有额度检查，不把设备时间虚构成供应商 Token 账单。

## 试运行资源预算

现有文档实查：宿主 31,922 MiB RAM、i7-12700F、953.9 GiB NVMe；控制 VM 4 GiB，两台 Agent VM 各 4 GiB。数值来自先前部署记录，执行下一次分配前必须重新读取宿主资源。

| 项目 | 初始保留预算 | 准入规则 |
| --- | --- | --- |
| 宿主与峰值余量 | 6 GiB | 不分配给新用户，不以 swap 代替 |
| 控制服务 | 4 GiB | 固定保留 |
| 现有两台 Agent | 8 GiB | 在真实负载/恢复测试前不缩小 |
| 一台 Linux 执行 VM | 2 vCPU、4 GiB、32 GiB | 单活跃桌面槽 |
| 一台 Android 执行 VM | 2 vCPU、4 GiB、32 GiB | 单活跃手机槽 |

合计约 26 GiB。当前只准入 **1 个活跃桌面槽 + 1 个活跃手机槽**，每个槽绑定实际所属用户。两套完整用户设备同时运行需要约 34 GiB（含当前核心与余量），超过现有 RAM；不能因为空闲桌面实测约 1 GiB 就超售。资源预算不是压测结论，也不是永久免费服务承诺。

后续更多用户需要独立持久卷/设备记录，再开发排队与唤醒；当前模块不因停机自动释放已绑定设备的内存/CPU 保留。每增加一套设备至少预留 64 GiB 配置容量，并额外计入快照和备份；按 thin volume 实际占用估算“还能创建多少人”不安全。当前实现对每个设备另保留一份等大恢复副本、4 MiB cloud-init 盘和至少 20% 磁盘余量；达不到则停止新建。备份不能只放同一 NVMe。

2026-10-10 真实宿主只读预演：31,922 MiB RAM、12 个物理核心；五台运行 VM 共配置 20 GiB RAM、10 vCPU。预演增加一台 4 GiB/2 vCPU Linux 设备时，需求为 24,576 MiB/12 vCPU，运营上限为 25,778 MiB/10 vCPU；同时触发桌面槽位、瞬时可用内存和未审核干净模板拒绝。结果 `admitted=false`，没有资源创建。32 GiB 宿主目前不能按“每个外部用户再送一台始终在线 PC 和手机”继续加人。

## 运营创建：一个幂等请求，一套唯一归属

为每次创建保留私有 manifest：请求 ID、账户/租户/身份 ID、Agent 实例 ID、设备 kind、随机 resource ID、VM ID、卷 ID、网络段/地址、镜像散列、代码 release、connector ID、配置摘要及当前阶段。manifest 不保存配对短码、私钥、密码或媒体。相同请求重试只恢复原资源；参数摘要变化时拒绝，禁止悄悄再创建一套。

1. **核对账户归属**：控制层用户/租户均 active，无删除冻结；身份属于该租户。查询最新宿主资源，预留磁盘、内存和对应设备槽。后续每个不可逆阶段前重新检查冻结状态。
2. **复制干净模板**：模板只有 OS、已核验软件及固定版本驱动；不得带浏览器 profile、Android `/data`、machine-id、SSH host key、租户证书、连接器状态、DeviceGateway 数据库或媒体票据。已登录的试验 VM 绝不能改名克隆给其他用户。
3. **生成本设备身份**：VMID、MAC/IP、系统 host key、machine-id、Xauthority 或 Android 数据盘都独立；持久卷记录 tenant/resource owner，挂载前比对。不能按显示名称或用户名推断归属。
4. **先隔离后开机**：独立网络/VM，默认拒绝到管理网、办公网、其他租户及控制数据库；只放行明确需要的出口与本租户 mTLS 入口。IPv6 同样覆盖。ADB/X11/Proxmox 不公开，Android 特权容器只在该用户独立 VM 内运行。
5. **安装与健康检查**：Linux 使用专用非登录用户、X11/Xfce/AT-SPI/native helper；Android 使用固定 digest、独立 `/data`、回环 ADB。只上传运行需要的软件，不上传模型钥匙或整个租户 Agent 数据。
6. **原协议配对**：运营端产生限时 offer/bundle；连接器注册 resource ID、kind、methods；私密媒体绑定 tenant/identity/connector/resource；成功 ACK 后才将设备置 ready。现有 `connector-id.json`、DeviceGateway 和 relay 必须使用同一个 resource ID。
7. **验收后交付**：本地 native fixture、Agent observe/input、App 私密接管、交还、新帧、断线暂停分别通过。条款与账号登录由真实用户在私密接管完成。设备卡片只展示已验收能力；未通过的远控/第三方应用标记尚不可用。
8. **失败收敛**：保存操作回执和资源编号，把未确认状态标为 blocked/needs_operator；不删除未知归属卷、不重复付款/创建、不重放输入。仅归属和创建回执齐全的空临时资源可按清理流程释放。

## 运行准入与状态

新增控制面设备生命周期状态应独立于现有输入控制权：

`requested → reserved → provisioning → booting → ready → draining → stopped`

上述是完整交付状态规划。当前账本实际状态为 `reserved → cloning → configuring → staged`，异常进入 `needs_operator`；从未尝试创建的 reservation 可 expired/cancelled。`(tenant_id, device_kind)`、`resource_id`、VMID 唯一，换 identity 也不能多占同种设备。即使换了本地账本，宿主已存在的 ownership marker 仍会阻止重复 tenant/kind、resource 或 request 绑定。模板磁盘由完整 clone 独立分配。删除走现有账户冻结与资源清单；当前模块没有删除、开机或停止动作，任务队列/Agent 不持 Proxmox 管理凭据。

- 仅 `ready` 且实际 connector/native/media 健康的能力可执行。
- 新任务先检查所属、冻结、设备槽及模型额度；无容量则明确“设备排队中”，显示可取消，不伪装正在操作。每用户同种设备一个唤醒请求，重复点按幂等。
- 排队采用先来先服务并按用户公平轮转；用户主动接管优先于尚未开跑的后台任务，但不能抢走其他用户正在私密接管的实例。
- 初期运营调度即可：真实测量后再开发自动 Proxmox worker。不得把后台任务列表数量映射为 VM 创建数量。
- 实例运行分钟记录于控制面，空闲不持续截图/调用模型。视频仅在被观看或私密接管时发送；没有先压测就固定允许多路编码。

## 休眠、恢复和维护

只有无执行任务、无 in-flight 原生动作、无人工会话、无即将到期调度且用户已知道后台提醒会暂停，才能进入 draining。暂停新入队，提升/失效旧输入许可，等待动作回执、保存应用状态后正常关机，确认 Proxmox stopped 才释放内存槽。超时留在 needs_operator，不直接杀掉有未保存输入的桌面。

恢复必须再次验证磁盘归属、证书/连接器绑定，更新连接代次并检查真实 UI。用户私密接管或故障前的 paused 状态保持暂停；新连接/重启不得自动授权 Agent 接着输入。浏览器/Android 登录状态可以持久保存，但 cookie、本地文件和账号内容不会进入基础镜像。

## 打开更多名额前的验收门槛

- 两用户 scope、私密媒体、文件、账号、网络、旧票据和重放拒绝，测试必须有正/负对照。
- 任务执行中接管、媒体掉线、App 后台、Agent 中断、重启/断电恢复均保持权限与动作结果一致；未知执行结果不重放。
- 至少覆盖真实浏览器复杂页面和 Android 已宣称支持的 App；逐项记录安装、登录、输入、视频/图像和后台兼容性。
- 记录冷启动和恢复时间、P95 输入至画面延迟、卡帧率、断线率、内存峰值、CPU/编码占用、磁盘增长、上行带宽与 API 用量。目标先作为待测指标，不填写虚构达标数值。
- 48 小时稳定运行按真实经过时间记录；备份至少恢复到一个新实例并验归属。运营限额的提高需要这组证据，不靠单次 health=200。

当前主要未实施项：账户 active/frozen 与身份归属的自动控制层接线、已审查干净模板目录、隔离网络/设备身份 bootstrap、生产级睡眠/唤醒编排、宿主压测和长期记录、第二套设备隔离演练。运营入口只信任管理员提供的目标账户信息，不应被公开接口直接调用；配对仍走原控制层 scope 校验。现有 Linux 服务/原生驱动的实际结果见 [Linux 桌面验收](../evidence/linux-desktop-native-2026-10-10.md)。
