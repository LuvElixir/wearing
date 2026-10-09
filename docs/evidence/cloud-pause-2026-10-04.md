# 腾讯云试验机暂停记录

操作日期：2026-10-04。用户本轮要求：近期开发用不到云端时，先停按量运行。本次只操作原腾讯云香港 Wearing 首台试验 VM，没有新建、销毁实例或磁盘。

## 停机前

- 官方 CLI 核对实例为 `POSTPAID_BY_HOUR / RUNNING`，TAT agent 在线。
- 原私有入口检查：引擎可达，云端网页启用；6 条任务、4 条消息、2 个目标、2 个目标步骤、1 个身份。
- 运行/未决任务数为零；前后记录和关键文件哈希保持一致。
- 本机连接器停止时没有进行中的设备动作，CLI 最终返回 `desired=stopped / process_running=false / active_actions=0`。

以上记录和哈希检查不是全量备份或从备份重建验收。云盘保留是本次保存已有数据的方式。

## 实际结果

使用腾讯云 `StopInstances`，参数 `StopType=SOFT`、`StoppedMode=STOP_CHARGING`。只发送一次，操作请求/响应保存在私有目录，不盲目重试。

2026-10-04 12:28:38（Asia/Shanghai）通过官方 API 读取：

| 字段 | 结果 |
| --- | --- |
| InstanceState | STOPPED |
| StopChargingMode | STOP_CHARGING |
| LatestOperation | StopInstances |
| LatestOperationState | SUCCESS |
| 公网 IP | 已释放 |
| 系统盘 | 40 GiB，保留 |
| 数据盘 | 40 GiB，保留；DeleteWithInstance=false |

CPU、内存按此模式停止计费，磁盘继续计费。保存的 ¥0.29/小时是运行时计算与两块磁盘合计旧报价，不能当成此次全部节省金额。未在本轮取得停机后磁盘分项账单，不提供猜测金额。依据：[腾讯云关机不收费](https://cloud.tencent.com/document/product/213/19922)、[StopInstances](https://cloud.tencent.com/document/api/213/15743)。

本地原连接器已持久停止；`com.wearing.cloud-tunnel.tencent-first`、`com.wearing.cloud-preview.tencent-first` 已 disable 并卸载运行，保留 LaunchAgent 文件和配对资料。18865 / 18866 云端入口暂停。旧 8765 本地页面仍返回 HTTP 200，未更改其服务。

私有证据：`.wearing/qa/cloud-pause-20261004/` 的实例前后快照和 summary；`.wearing/cloud-trials/tencent-first/` 的一次性请求/响应与部署状态。共享文档不包含 IP、凭据或密钥。

## 何时恢复

原型、本地日历、前端、事件协议和桌面打包暂不需要开机。进入跨天云任务、真正外部事件回调、远端设备恢复、跨网络推送或 SaaS 验收时，再告知用户并恢复原实例；本次没有安排自动开机。

恢复顺序：

1. 核对原账户和实例 ID，从原实例启动，等待 RUNNING；记录开始计费时间。释放计算资源后再开机可能受当时资源可用性影响。
2. 读取新公网地址。通过已认证云侧通道检查主机公钥，不关闭 SSH 校验，也不复用旧地址冒充同一主机。
3. 同步更新私有隧道地址和已验证 known_hosts；检查 relay 证书与新地址匹配，再更新原配对的 endpoint。保持原租户、连接器身份、权限和动作账本。此地址迁移目前还需操作者处理，尚非一键恢复产品能力。
4. 核对服务、数据卷、原记录及文件；先恢复私人预览，再显式启动原连接器。两个已 disable 的 LaunchAgent 需要 enable 后 bootstrap；连接器使用与原登记相同的 Python 路径执行 `python -m wearing.cli connector service start --root <原绝对路径>`。
5. 对暂停期间过期的定时工作重新判断；不补跑旧点击、不自动重发消息或执行旧订单。验证手机/电脑在线、原授权状态及未明结果后继续。

本次暂停不改变每租户独立 VM 的生产架构，也不构成所有云账单归零。
