# Wearing 多云 VM 选型与接入

2026-10-03。用户最新确认：同时考虑用户自有云账户的一键部署，以及 Wearing 代建和运营的托管服务；海内外主流厂商都应进入适配范围。默认一位租户一套独立 VM 内的 Wearing/Hermes/私有数据，设备仍是连接器。用户已选择腾讯云并授权使用现有 CLI。已完成目录、离线预览及腾讯云真实账户发现/按量与包月询价；一台香港按量 VM 已完成 Wearing/Hermes 安装、真实模型/记忆/文件/单轮目标、整机重启保留和加密冷备份隔离恢复校验。**该私人试验实例正在付费运行，完整 SaaS 尚未上线**。

## 先覆盖谁

下表是研发目标，不是“已经支持”的产品列表。只在实际账户完成全流程验收后，才开放该厂商的部署入口；每个账户环境和区域单独记录验收，不能用一个区域成功代表全球可用。

| 优先级 | 服务商 | VM 产品 | 复用候选 | 本次依据与状态 |
| --- | --- | --- | --- | --- |
| 首批覆盖 | 阿里云 | ECS | `aliyun/alicloud` Provider | [RunInstances](https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-runinstances)、[官方 Terraform 支持](https://www.alibabacloud.com/help/en/ecs/developer-reference/terraform/)；API/部署方案已研究，插件与真实云链路未验收 |
| 首批覆盖 | AWS | EC2 | `hashicorp/aws` Provider | [RunInstances](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_RunInstances.html)、[幂等规则](https://docs.aws.amazon.com/ec2/latest/devguide/ec2-api-idempotency.html)；API 已研究，真实链路未验收 |
| 首轮实际验收 | 腾讯云 | CVM | `tencentcloudstack/tencentcloud` Provider | [RunInstances](https://www.tencentcloud.com/document/product/213/33237)、[上游实例资源](https://raw.githubusercontent.com/tencentcloudstack/terraform-provider-tencentcloud/master/website/docs/r/instance.html.markdown)；首台私人链路已验收，第二租户与完整恢复待测 |
| 首批覆盖 | 华为云 | ECS | `huaweicloud/huaweicloud` Provider | [CreateServers](https://support.huaweicloud.com/intl/zh-cn/api-ecs/ecs_02_0101.html)、[上游 VM/卷资源](https://raw.githubusercontent.com/huaweicloud/terraform-provider-huaweicloud/master/docs/resources/compute_instance.md)；首台私人链路已验收，第二租户与完整恢复待测 |
| 首批覆盖 | Microsoft Azure | Virtual Machines | `hashicorp/azurerm` Provider | [CreateOrUpdate](https://learn.microsoft.com/en-us/rest/api/compute/virtual-machines/create-or-update)；创建语义已研究，模块与真实链路未验收 |
| 首批覆盖 | Google Cloud | Compute Engine | `hashicorp/google` Provider | [instances.insert](https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/insert)；创建/停止语义已研究，模块与真实链路未验收 |
| 后续扩展 | 火山引擎 | ECS | Provider/官方 SDK 待选 | [RunInstances](https://docs.volcengine.com/docs/ecs/RunInstances-Createsinstances?lang=en)；已查创建入口和快照限制，完整恢复/计费待核实 |
| 后续扩展 | 百度智能云 | BCC | Provider/官方 SDK 待选 | [创建实例](https://intl.cloud.baidu.com/zh/doc/BCC/s/2k3rau7n4-intl)、[创建快照](https://intl.cloud.baidu.com/zh/doc/BCC/s/0jwvyo7c0-intl)；已查创建和幂等入口，完整恢复/计费待核实 |
| 后续扩展 | Oracle Cloud | Compute | Provider/官方 SDK 待选 | [启动实例](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/launchinginstance.htm)；初步纳入，完整适配研究待做 |

用户选择腾讯云作为首轮，复用本机现有 tccli。香港和新加坡均已返回 AVAILABLE，官方 Ubuntu 24.04 x86_64 镜像、候选规格与配额均已现场查询；香港 SA2.MEDIUM4 已按量创建一台并完成私人核心试跑，当前 ¥0.29/小时，公网出流量与模型另计。报价与具体边界见[腾讯云首轮](tencent-cloud-first-run-2026-10-03.md)。其他五家仍属适配目标，没有因目录收录而宣称可部署。

## VM 规格怎么挑

第一轮候选采用 Linux/x86_64、Ubuntu 24.04、2 vCPU / 4 GiB 内存、40 GiB 系统盘与独立 40 GiB 持久数据盘，按量购买；暂不依赖 GPU、Spot、嵌套虚拟化或内存休眠。模型推理仍使用已有云端模型服务。

这些数字是待测起点，不是已验证最低规格。预览允许更小配置做实验。第一轮先测安装/升级峰值、单 Worker + Hermes 的长期目标负载、文件下载、唤醒时间、持久化与故障恢复，再调成 1C2G、2C4G 或其他档位。macOS 空闲进程 RSS 不能代替 Linux VM 的容量测试。ARM、其他 Linux 镜像和实例家族分别验收，不因 SDK 支持就默认可用。

Agent 核心 VM 不承担用户的全部桌面工作。Mac/Windows 桌面和手机仍通过连接器接入；云端浏览器/代码执行沙盒是另一个可独立计费的资源。核心运行在 Linux，不要求连接器或用户手机使用 Linux。云端核心、桌面资源、手机号、支付账号分别获得并分别验收。

## 账户、区域与租赁模式

每个部署绑定 `provider_id + account_ref + account_scope + region + tenant_id`，由平台可信记录解析实际账户和凭据；用户提交的配置不是授权。`account_ref` 只是逻辑引用，不能包含 AccessKey、密码、模型密钥或登录 cookie。

- 用户自有云账户：用户直接付云费，以专用项目/资源组及受限授权交给 Wearing 管理这套实例。
- Wearing 托管账户：平台创建实例并承担云费，产品账单另向用户计费；租户 Worker 不得到平台云管理凭据。
- 独占物理主机：后续单独档位，不能把普通 VM 宣传成独享物理服务器。

AWS `aws` / `aws-cn` 属于独立账户分区；Azure 公共环境和中国环境有不同管理端点。阿里/腾讯/华为的国内站与国际站账户、结算、区域能力也要分别核对，不能只替换一个 region 字符串就宣称兼容。这里的 `china-site` / `international-site` 是 Wearing 的配置分类，不是宣称所有厂商采用相同 IAM 分区机制。[AWS 中国账号要求](https://www.amazonaws.cn/en/about-aws/china/faqs/)、[Azure 中国服务与端点](https://learn.microsoft.com/en-us/azure/china/concepts-service-availability)。

网络要同时验证模型服务、软件/镜像下载、用户浏览器和电脑/手机出站连接四条路径。区域的延迟、流量费、产品可用性和账户资格共同决定选型，不按“国内/海外”标签直接自动挑选。

## 统一流程保留厂商差异

公共生命周期是：发现账户/区域/规格与镜像 → 完整报价 → 明确支出授权 → 幂等创建 → 私有数据卷 → 初始化 Wearing → 健康/实例归属检查 → 用户与设备绑定 → 持续运行 → 排空/备份 → 停止/恢复 → 更新 → 退出与回收。

腾讯首轮先复用已安装的官方 tccli；后续可复用 OpenTofu 与成熟 Provider 管理 VM、卷、网络和快照，Wearing 只做配置、权限、操作账本、预算与恢复协调；云 API 的签名、登录和常规 SDK 不自行重写。OpenTofu 通过 Provider 插件管理不同系统。[官方插件机制](https://opentofu.org/docs/language/providers/)。具体 Provider 版本、license、锁文件、校验和及 OpenTofu 兼容性需在各模块验收时固定；本次没有安装或执行这些插件。

OpenTofu 管声明式资源；运行时启停、异步任务查询与专用备份恢复，可以按提供商能力调用受限官方 SDK。不要用删除资源模拟停止，也不能每次恢复都销毁旧实例。每套部署状态独立保存并加锁，导入用户已有实例需要独立核对资源归属，不能把整个用户云账户纳入 state。

| 差异 | 本次发现 | Wearing 的处理 |
| --- | --- | --- |
| 创建完成 | AWS/阿里/腾讯创建入口、Azure PUT、GCP operation、华为 job 各自有完成规则 | 创建请求被接受不等于安装完成；分别记录云任务、VM 状态和产品健康 |
| 重试 | AWS/阿里 ClientToken，GCP requestId，华为 X-Client-Token，百度 ClientToken；Azure 已有资源 PUT 可能更新 | 先持久保存操作与参数，重试复用幂等语义；超时先核对原请求，不能直接再下单；Azure 创建避免覆盖已有 VM |
| Azure 停止 | Deallocate 释放计算资源，与单纯关机不同 | 明确调用停机策略，读取实际状态，保留费用单列。[官方 Deallocate](https://learn.microsoft.com/en-us/rest/api/compute/virtual-machines/deallocate) |
| 阿里/腾讯停机 | 经济停机/STOP_CHARGING 有计费和磁盘适用条件 | 不把所有 Stopped 状态算成计算费为零，恢复前查库存。[阿里规则](https://www.alibabacloud.com/help/en/ecs/user-guide/economical-mode)、[腾讯规则](https://intl.cloud.tencent.com/pdf/document/213/12541?lang=en) |
| AWS/GCP 保留费用 | 实例停机不等于磁盘、地址和快照免费 | 计算、磁盘、备份、IP、流量分别计账。[AWS 生命周期](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html)、[GCP 停机](https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/stop) |
| 备份与恢复 | VM 重启、云磁盘快照、业务一致性备份、恢复到新 VM 是不同流程 | 排空 Agent/设备动作，完成数据库一致性备份与文件清单，再做云快照；恢复验证真实数据与凭据，不以快照完成替代 |
| 产品/区域限制 | 华为 VM/卷加密能力依区域；火山文档的快照恢复受云盘类型限制 | 按具体产品/区域记录能力，不制造一个“所有云一样”的布尔开关 |

“自主性、常驻与持续目标”要求活跃任务期间保持核心可用，不能为了省钱反复让用户等待冷启动。只在无运行、写入排空且外部唤醒链路已可用时评估停止；停止核心前确认持续目标和通知由谁接续。平台调度仍是独立待实现环节。

## 当前代码入口

`cloud/providers.json` 保存研究目录与首轮/首批/后续顺序，`cloud/placement.py` 提供离线 VM 配置预览：

```sh
uv run wearing cloud providers
uv run wearing cloud plan --request deploy/vm/selection-example.json
```

示例文件不含账户密钥；改成真实逻辑引用也不表示已获得账户授权。输出明确标记 `planned`、`ready_to_provision: false`、`quote: null`、`creates_resources: false`、`hardware_isolation_verified: false`。它不是 OpenTofu 的云 plan，不访问账户、不读取云 CLI 登录信息、不检查实时区域库存，也不产生资源。配置散列只用于比较配置，不能作为支付授权、云 API 幂等令牌或恢复证据。

腾讯云新增 `wearing cloud tencent inspect` 与 `quote`，复用现有 tccli 做实时读取，输出不含云密钥；支持中国站人民币的按量/一个月包月报价。这个入口没有购买/启停/删除接口，也不接到 Agent 工具或租户网页。另有不接入 Agent/网页的操作者部署脚本，首台安装、重启和部分备份恢复已经验收；完整生命周期待后续测试。见[腾讯云首轮](tencent-cloud-first-run-2026-10-03.md)。其他厂商与 OpenTofu 模块仍待实现。

## 第一轮真正的退出条件

先完成腾讯云闭环，其他五家使用相同验收清单逐家加入：实际账户最小权限与撤销；创建请求不重复扣费；独立 VM/卷/网络；固定 Wearing/Hermes 安装；两用户错路由拒绝；真实记忆/文件/目标重启保留；一致性备份恢复到新实例；设备重连且不重复动作；实例/磁盘/IP/快照账单核对；用户退出时保留或导出其数据并核对所有剩余资源。

腾讯云首台已按用户选择的按量方式运行；第二台只在双租户隔离或全新 VM 恢复验收时另开。当前已有 VM、云盘及公网出流量费用，模型另计；其他地区与账户仍逐一验证。整个工程状态见[进度表](progress.md)。
