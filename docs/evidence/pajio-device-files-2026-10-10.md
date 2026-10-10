# 设备文件通道部署与验收 · 2026-10-10

A/B 两个独立测试账户的 Linux 电脑与 Android 云手机已接通工作区文件收发。四台设备均完成 96 KiB 合成文件的真实双向传递；B 的两台设备另完成 20 MiB 边界传递，设备端与工作区下载端 SHA-256 一致。**这是 API、connector 和设备文件系统验收，App 文件界面端到端验收仍在进行。**

本记录仅整理已有私有回执，没有执行新部署、设备操作、模型调用或传输。只记录文件大小、摘要、状态与源码版本，不含账号凭据、文件正文、输入内容、SDP 或截图。

## 部署范围与版本

部署覆盖 gateway、A/B Core 与 relay，以及四台执行设备的文件模块和 connector。角色清单与原像、候选摘要保存在私有 `source-manifest.json` / `source-manifest-v2.json` 和各 target 的 inspect/deploy 回执；该私有目录不随本文件提交。冻结服务源码没有因 installer v2 扩围。

| 关键文件 | 已部署/使用 SHA-256 |
|---|---|
| `deploy/on-prem/install-device-files.py` | `bd816c3def37b98ac89e0c93aa674a0cd14fa1e55f9074c47f6e74d1c9b8fa98` |
| `src/wearing/cloud/device_files.py` | `63f9cfb6a0cb4f2fcf8b25e81ca209370005f6075d4154af3cf8792fabd93f63` |
| `src/wearing/device_files_io.py` | `c4fe86e1d34c52138528ed6eee979ebb55e96b767922809a806802b8e0ba4ff8` |
| `src/wearing/device_files_native.py` | `2a9f6c94fefa56f843d154566bffdae5f1c130d93736c1f51a886e01741fd7ee` |
| `src/wearing/device_files_broker.py` | `3857525823179485883422bd35fe1987a5c69db9bcc59dcd316bdea7bcdc6ac0` |

installer v2 使用自含的受限元数据读写函数，支持没有 enrollment 模块的历史纳管设备。它校验真实本地配对范围后安装固定 Inbox/Outbox；安装回执明确 `relay_permission_granted=false`，文件授权仍需独立核对，不能把安装成功当作权限已经开放。

| 目标 | 实际部署结果 | 证据文件 |
|---|---|---|
| B Core/relay | activated=true，部署后源码摘要一致 | `core-b-deploy.json` |
| B Linux | activated=true，部署后源码摘要一致 | `linux-b-deploy.json` |
| B Android | activated=true，部署后源码摘要一致 | `android-b-deploy.json` |
| A Core/relay | activated=true，部署后源码摘要一致 | `core-a-deploy.json` |
| 公共 gateway | activated=true，部署后源码摘要一致 | `gateway-deploy.json` |
| A Linux | activated=true，部署后源码摘要一致 | `linux-a-attempt2-deploy.json` |
| A Android | activated=true，部署后源码摘要一致 | `android-a-attempt2-deploy.json` |

A Linux 与 A Android 首次 native 安装均返回 `activated=false`、`CalledProcessError`，并记录 `rolled_back=true`、`metadata_restored=true`。旧调用模块及元数据已恢复；新增加的三个文件模块作为未启用诊断材料保留，因此**不声称安装目录整体逐字节还原**。v2 修复后重新 inspect，使用独立 `attempt2` 回执及备份完成安装，未覆盖首次失败证据。

后端激活实际重启了对应 Core/relay、gateway 或 connector；与另行 Web 静态更新的“不重启”范围不同。connector 新连接需要新的设备确认，不能复用旧 ACK。B Linux 最早一次 preflight 因 `device_not_ready_confirmed` 被拒绝，补齐当前连接确认后才进入文件验收，未绕过门禁。

## 实际传输

测试通过私有工作区上传确定性合成文件并建立快照，再由真实 connector 写入固定 `Pajio/Inbox`，核对原生文件 SHA。随后以独占创建的合成 `Pajio/Outbox` 文件执行真实 list、取回和工作区下载，再核 SHA。没有指定任意设备路径、覆盖既有文件或读取真实用户资料；合成样本保留用于复核。

| 账户/设备 | 大小 | Inbox 与下载 SHA 一致 | 整段往返用时 |
|---|---:|---|---:|
| a-android | 96 KiB | 是 | 6.965 秒 |
| a-linux | 96 KiB | 是 | 9.075 秒 |
| b-android | 96 KiB | 是 | 7.525 秒 |
| b-android | 20 MiB | 是 | 86.366 秒 |
| b-linux | 96 KiB | 是 | 7.393 秒 |
| b-linux | 20 MiB | 是 | 85.900 秒 |

整段耗时包含工作区上传、设备写入、Outbox 列举/读取、导入与下载核验，不是独立链路吞吐基准。20 MiB = 20,971,520 字节，是本轮单文件上限；A 的两台设备未在本轮执行 20 MiB 边界测试。

| 合成样本组 | 字节数 | SHA-256 |
|---|---:|---|
| B 96 KiB | 98304 | `c36a92ec082d6cfa7ea7cb54f1432244a479cd217bb60dbda27e0caf79194535` |
| B 20 MiB | 20971520 | `12d20e7fcd6899253041d42194a1aa27b4748d7bbb3f7d0b8bf8ad6db32d26c9` |
| A 96 KiB | 98304 | `3abc1bd6f648681262fafcc1f6ed148ecf0982dcd52c49a8885bd94fda605b91` |

## 权限与私密接管边界

- **跨账户**：A/B 对向真实会话访问另一账户的设备能力、传递历史、单条 send 回执及设备接管状态，各四个只读请求均为 404；没有发送伪造 owner header 或跨账户写请求。B 20 MiB 回执也通过同样隔离检查。
- **用户私密接管**：四台设备都真实进入 `human_private` 并等设备 ACK；文件 list POST 返回 409，未创建传递记录，原生文件访问栅栏也拒绝。随后显式 safe-screen/scope 双确认交还，均等待到 `agent_ready` 且 `device_confirmed=true`。这些 human 测试没有传输屏幕或输入内容。
- **断连后的设备锁**：四台设备使用已安装的 `agent_fence` 和真实 OS 锁，在隔离 socket worker 断开客户端后继续持锁，worker 退出后释放。它证明该函数及锁在此受限场景的行为，**不是生产守护进程 SIGSTOP、kill、崩溃或持续故障注入验证**。
- **Android broker 身份**：两台 Android 实际连接已安装 broker；即使错误 UID 拥有 socket 的组访问条件，也被 SO_PEERCRED 拒绝。Linux 的证据是 OS 锁测试，不扩写成相同 Android broker UID 测试。
- **未知结果**：验收工具在每次写请求前持久记录 intent；未知只查原 request_id，不自动重发。重启后 journal、不重复提交和 changed-intent 拒绝有离线测试，本轮不声称公网已注入“服务端已提交但响应丢失”的真实故障。

权限依赖可信个人账户归属及设备 owner 锚点；本次对向账户 404 是真实验收。共享/未知 owner 拒绝、路径/符号链接限制等其他边界由定向测试覆盖，不混称为每个边界都做过线上攻击测试。

## 可用性：存在切换窗口 502

持续探针读取已认证 `/api/status`，在本次文档快照时仍运行，未被本文停止。以下是已完成 JSONL 行的固定前缀统计，不是最终总量或长期 SLA：

| 账户 | 起止时间（Asia/Shanghai） | 样本 | 200 | 502 | 最后样本 |
|---|---|---:|---:|---:|---|
| A | 2026-10-10T11:02:20+08:00 → 2026-10-10T11:47:57+08:00 | 2210 | 2205 | 5 | 200 |
| B | 2026-10-10T11:02:20+08:00 → 2026-10-10T11:47:56+08:00 | 2209 | 2204 | 5 | 200 |

A/B 均记录 5 次 502，集中在 Core/relay 与公共 gateway 激活时段，随后探测恢复 200。这是采样事实，不能推算精确停机总时长，也不能写成零中断。快照保留前缀字节数与 SHA；JSONL 后续会继续增长。

## 验证层级与未完成项

冻结 manifest 记录的本地回归：广泛定向 170 passed / 2 skipped；后续 files/owner 26 passed / 3 Linux-only skipped；installer v2 独立 12 passed，installer+files/owner 合并 38 passed / 3 Linux-only skipped。跳过项不算通过；上面的真实 OS 锁与 broker 受限验证补充了部分 Linux 环境证据，仍不等于完整守护进程故障注入。

- App 新包已构建，文件入口、发送确认、取回查看及未知回执出口的真实 UI 验收仍在进行；本记录不能替代该验收。
- 真实 Desktop 登录/远控、Web 静态部署由独立记录跟踪，与本文件通道 API 验收分开。
- 测试没有调用付费模型；不证明 Agent 会自主选择或处理传入文件，也不证明文件已被第三方应用成功使用。
- 文件通道累计配额、清理与长期性能不由此次一次性往返证明；200 MiB 累计历史分配包括失败/未知请求，本轮未验证垃圾回收。
- 当前状态以新的 API/设备回执为准；本记录中的 agent_ready 是测试结束时事实，不保证此后用户未接管。

## 证据索引

私有根目录：`.wearing/on-prem/20261009/personal-compute/device-files-20261010/`。可提交文档只引用文件名与摘要，不复制私有会话、owner 资料、mutation journal 或样本内容。

- `source-manifest-v2.json`：角色清单、installer v2 及回归记录。
- `*-deploy.json`、`*-attempt2-{inspect,deploy}.json`：原像、备份位置、激活/回滚与源码摘要。
- `runs/67e83b3e8e1a4ce8be1a003508c6b547/`：B 96 KiB 及边界拒绝。
- `runs/dc23081f381e846149840bc16184654f/`：B 20 MiB 与跨账户拒绝。
- `runs/f7ccb518f4aa8dc35342ded4ddfdb21f/`：A 96 KiB 与边界拒绝。
- `b-bounded-acceptance-summary.json`：B 后续独立验收窗口汇总；它的“零失败”仅限该窗口，不能覆盖更早的 preflight 拒绝。
- `public-probes-documentation-snapshot.json`：本页固定统计快照，SHA `3fbf1646c2e079886b92fd90c9dfe947509a8b9eb47b26e8f1651a791ab47c56`。
- `backend-evidence-index.json`：逐份回执/证明 SHA 索引，SHA `66ac3dc871a34351234f41843243cbb9ae02eb722f51368aa1144b313142152d`。
