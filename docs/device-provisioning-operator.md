# 专属设备供应、验收与维护：运营入口

入口为 `python -m wearing.cloud.device_operator`。这是管理员工具，未注册到 Agent 或公开 API。SSH 目标使用已有受控 config，固定 `BatchMode=yes` 和 `StrictHostKeyChecking=yes`。不向租户进程分发 Proxmox 密钥。

## 已实现的范围

- `inventory`：读取 Proxmox 节点、QEMU 配置摘要、LVM-thin 逻辑分配总量。不会输出 SSH 公钥、密码、IP 配置或完整 VM description。完整归属证明只能写入私有 `--output` 文件。
- `plan`：先查真实账户/身份，再检查 60 秒内的新 inventory、物理核心、完整配置内存、已承诺磁盘、备用恢复副本和设备槽；返回原因、计划散列、inventory 散列。没有 VM 写操作。
- `reserve`：按已查看的 spec/policy 散列重新检查实时容量，原子写入私有 SQLite。相同 request 的相同参数幂等；更改参数、重复 tenant/kind、resource 或 VMID 均拒绝。
- `apply`：再次读取实时资源和归属，只从已审核目录中的完整模板克隆到不存在的 VMID。ownership nonce 与租户/资源归属在 `qm clone --description` 中一并写入。后续用 Proxmox digest CAS 设置固定内存/CPU、禁止 autostart/balloon，清除继承网络与 cloud-init 登录配置。最终必须读回正确归属、资源和停止状态才返回 `staged`。
- `status` / `cancel`：查询本地日志；只可取消从未尝试创建且确认 VM 不存在的 reservation。没有 VM 删除功能。

所有结果均 `product_ready=false`。停止状态克隆还没有独立安全网络、OS 身份、证书、scope 配对及真实控制验收。`verify-delivery` 的 `device_ready` 只确认基础设备和传输服务，不能代替真实 WebRTC 解码/输入及模型工具回执。Firefox 等具体软件的首次使用流程单独记录，Android 基础设备不设置虚构的统一条款确认门槛。

## 准备与执行顺序

使用同一个宿主私有账本目录，所有运营进程共享它。目录 0700、SQLite 0600，FileLock 覆盖 capacity/reservation/provider 调用；宿主另有 flock 在真正克隆前重新检查容量及唯一归属。`spec` 与 `policy` JSON 文件也必须遵循项目 `read_private` 权限约束。

spec 必含 request_id（32 位随机十六进制）、tenant_id、identity_id、resource_id、kind（linux/android）、vmid；默认每设备 2 vCPU、4096 MiB、32768 MiB。`--admission-sources` 指向管理员私有的受信来源目录，不能由租户提交。`plan/reserve/apply` 必须实时查询此目录；缺少目录、SSH 超时、权限不足、元数据不完整、回执过期或账户冻结均拒绝。spec 不接受自行声明的 active 状态。

`device_admission.py` 按 control → tenant → control 顺序核验：控制端以现有独立 operator 数据库角色执行只读事务，复用 `ControlStore.user_available/tenant_editable` 拒绝冻结或已提交注销的账户，要求显式 private ownership、唯一 active owner、成员快照和 route 一致。租户端复用 `load_instance` 检查实例/卷归属及 tombstone，仅通过 SQLite `mode=ro` 查询 `identities.id` 是否存在，不读取消息、任务或记忆。第二次 control 结果必须与第一次相同。原配对 offer/relay 继续负责交付时的 scope 校验。

来源文件格式如下；路径与 SSH 别名由管理员填写，密码不放入此文件。控制 SSH 命令以 sudo 读取服务器已有 root 私有 operator.env 后降权至服务账号；凭据只留在远端进程，不回传、不上日志。租户命令同样降权后读取该服务用户的私有元数据。

```json
{
  "control": {"host":"control-host-alias","root":"/var/lib/wearing/gateway","account":"wearing","python":"/opt/wearing/venv/bin/python"},
  "operator_env":"/etc/pajio/operator.env",
  "tenants": {
    "tenant_example": {"host":"tenant-host-alias","root":"/var/lib/wearing/instance","account":"wearing","python":"/opt/wearing/venv/bin/python"}
  }
}
```

plan 散列绑定 spec/policy 和真实 owner、instance、ownership revision、受信来源摘要；reserve 将该 scope 固定存入私有账本。即使 request 参数不变，真实账户归属变化也需要重新审查，不能把已有 VM 改绑到新 owner。clone/prepare 前后都重新获取证据；期间出现注销则保留停止状态资源并进入 `needs_operator`，不会继续配置、启动或自动删除。跨 SSH 检查不是分布式数据库原子事务，停机隔离与操作后再次核验是这个阶段的收敛边界。

policy 必含 node、storage、templates；模板按 kind 记录 VMID、config_sha256、clean_review_ref、disk_mib。`clean_review_ref` 是管理员审核记录，不是自动清除磁盘内容的证明。审核必须包括无用户浏览器/Android 数据、连接器/DeviceGateway 状态、证书、machine-id 与 SSH host key。未完成审核时 templates 保持空对象，创建会明确拒绝；不要把已登录的试验 VM 加入目录。

下面使用管理员已准备的私有路径。`PLAN_SHA256` 来自先前查看的 plan 输出，不能随意编造：

```sh
python -m wearing.cloud.device_operator inventory --ssh-config "$SSH_CONFIG" --host "$SSH_HOST" --node "$NODE" --output "$INVENTORY_FILE"
python -m wearing.cloud.device_operator plan --root "$LEDGER_ROOT" --ssh-config "$SSH_CONFIG" --host "$SSH_HOST" --node "$NODE" --admission-sources "$ADMISSION_SOURCES" --spec "$SPEC_FILE" --policy "$POLICY_FILE" --output "$PLAN_FILE"
python -m wearing.cloud.device_operator reserve --root "$LEDGER_ROOT" --ssh-config "$SSH_CONFIG" --host "$SSH_HOST" --node "$NODE" --admission-sources "$ADMISSION_SOURCES" --spec "$SPEC_FILE" --policy "$POLICY_FILE" --plan-sha256 "$PLAN_SHA256"
python -m wearing.cloud.device_operator apply --root "$LEDGER_ROOT" --ssh-config "$SSH_CONFIG" --host "$SSH_HOST" --node "$NODE" --admission-sources "$ADMISSION_SOURCES" --request-id "$REQUEST_ID" --plan-sha256 "$PLAN_SHA256"
python -m wearing.cloud.device_operator status --root "$LEDGER_ROOT" --request-id "$REQUEST_ID"
```

## 中断与容量语义

在发送 clone 前先持久记录 `attempted=1`。若回复丢失，重试首先观察 VM：同一随机 owner、停止且未锁定时可恢复配置；VM 缺失时返回 `clone_outcome_unknown_no_replay`，保留资源预算并交运营排查。不能自动再 clone、删除、释放或猜测前一次失败。任何 owner、配置 digest、运行状态不符都拒绝继续。

所有已绑定的停止 VM 仍保留承诺的 CPU/内存。已经启动的 VM 按最大配置占用计算，不能用当前 RSS 或 thin volume 实际占用超售。默认保留宿主 6 GiB、2 个物理核心、20% 存储；每台设备另预留一份等大恢复副本。容量计划不代表已建立真正异机备份。

本模块不会自动停止用户设备。`queue/queue-tick` 在容量不足时保留排队，账户或归属变更时明确阻止。`sleep/wake` 是管理员发起的设备维护流程，完整保留预算；不使用当前 RSS 超卖。

## 早期只读验证（保留历史，已被后续实测推进）

私有部署工作目录 `personal-compute/provision-inventory.json` 和 `provision-dry-plan.json` 保存真实只读结果。宿主为 31,922 MiB/12 物理核心，现有运行配置共 20 GiB/10 vCPU；新增桌面计划因 CPU、桌面槽位、可用内存和未审核模板被拒绝，没有执行 reserve/apply。

`test_device_provisioning.py` 覆盖容量、唯一归属、并发预留、取消/到期和丢回执恢复；`test_proxmox_device_transport.py` 执行实际发往 SSH 的完整 Python 源码，使用受控 `pvesh/qm/lvs` 边界验证原子归属、CAS、最终容量拒绝及无 start/stop/delete。`test_device_admission.py` 使用真实合成 control/tenant SQLite 元数据，覆盖尚未 freeze 的注销申请、账户/租户冻结、成员/实例/卷/身份不符、只读约束、SSH 回执未知、过期与各阶段重新检查，以及 clone 途中冻结后停机保留。

真实 A/B 合成验收账户最初均因缺失显式 ownership 被拒绝。经授权，对照本项目 `setup-identity.py` / `identity-members.py` 的初始化台账、服务器私有主体映射、唯一 active 成员和真实实例/route，使用既有 `AccountDeletionControl.register` 只补这两条 private owner 登记。登记证据 `personal-compute/acceptance-ownership-registration.json` 仅保留 scope 摘要、版本、初始化源码散列与计数；未新增用户、改业务数据或重启服务。

之后 A/B 均通过真实 control → tenant → control 检查，证据位于私有 `personal-compute/provision-admission-audit.json`。当时的运营 CLI plan 在通过账户和 daily identity 后，均因 `capacity_linux_slots`、`capacity_vcpus`、`host_memory_pressure`、`reviewed_clean_template_required` 拒绝，保存于 `provision-admission-dry-plan-a.json` / `provision-admission-dry-plan-b.json`。该轮没有 reserve/apply 或资源创建。这是早期拒绝记录；后续模板审核、配额调整与 B 的真实供应结果见本文末尾。


## 新设备的可重入交付链

1. 同一账本完成 `plan → reserve → apply`，只生成 stopped/owned 克隆。
2. `bootstrap-plan --bootstrap <私有JSON>` 生成确定性 cloud-init、独立 /30 子网和网络租约，计划绑定 owner nonce 和 runtime artifact SHA。`stage-network --bundle-sha256 <已审查值>` 通过配置 digest CAS 只修改这台停止设备，创建 root 管理桥接和规则。宿主每次重载/开机都从 root 私有租约重新生成动态规则；禁止办公网、管理网、跨租户和 IPv6。
3. `boot-device` 在新资源检查后先记录 start 意图，再仅发送一次启动。超时只观察，不重复 start。通过宿主已认证 QGA 读取新 machine-id、cloud-init 完成状态、owner 和管理 NIC 的 MAC/IP；Docker 私有桥不充当管理网卡。
4. `bind-device-ssh --identity-file <运营私钥路径>` 验证 cloud-init 的原始公钥；生成独立 `StrictHostKeyChecking=yes` 配置和 known_hosts。主机公钥只来自已有受信 PVE 的 QGA，不能用 ssh-keyscan 绕过信任。
5. `install-runtime --runtime-bundle <目录> --runtime-installer <文件>` 只在专属、未配对、OS 身份匹配的克隆上工作。bundle 逐字节哈希校验后复制至 root 原子目录；pip 依赖采用离线 wheelhouse 和 require-hashes。原生环境完成后写入 owner/artifact 三字段回执。中断可用相同 artifact 恢复，已配对机器禁止重装。Mozilla apt、Docker image pull、npm ci 仍需要网络，失败不能标记 installed。
6. `enrollment-plan → enroll → enrollment-status` 复用同一 scope，逐步登记 mTLS、connector、private media 与租户 relay，参见 `device-enrollment.md`。阶段发送前写入意图，未知回执必须通过实际状态恢复，不能重播配对。
7. `verify-delivery` 实查隔离、OS、native、mTLS、Agent/human relay 在线后返回 `device_ready`；真实媒体帧、输入和模型工具回执仍需独立可信验收。`delivery-status` 只展示历史状态，不把旧 ready 当当前在线证明。
8. 设备验证通过后，`startup-plan` 生成开启宿主开机自启的 before/after 配置 SHA；运营审查后使用 `finalize-startup --plan-sha256 <值>`。它先保存意图，再通过 owner 和 Proxmox digest CAS 仅设置 `onboot=1`，读回后同事务更新交付总账。若 SSH 回复丢失，只观察目标是否恰为已审查 after SHA；仍显示旧状态时返回 unknown，不自动再次发送。不得直接 `qm set` 造成账本永久陈旧。此步骤不重启设备。

干净模板仅包含经官方文件逐内容比对的 Ubuntu 基础 OS。用户证书、配对、模型密钥、浏览器/Android 登录数据、运行态都不进入模板。新 Android VMID 限于 45535，ADB 绑定 `127.0.0.1:(20000 + VMID)` 并据此计算资源 ID，避免每个云手机都用 5555 导致资源冲突。原已配对设备保持既有 serial。

原始 cloud-init 失败不能手工改成 done。已有的精确 Android 包名错误由 `device_bootstrap_repair` 受控修复：仅接纳那一个已知错误集合，保存原始状态与独立 root 回执，并在每次 boot/SSH 绑定/安装/交付验证时重查 owner、artifact、machine-id、当前内核、包版本和 binder 模块 SHA。原始 `raw_cloud_init_status=error` 与 `bootstrap_repair_verified=true` 分开记录；任何新错误或证据变化继续拒绝。修复回执通过完整临时文件 fsync 后无覆盖原子提交，写入中断不会发布半份回执。

安装上传重试会逐文件核验已传输的目录，只有名称集合、常规文件、属主和 SHA 全部一致才复用；root 安装器仍会再次核验完整 bundle。Android 镜像使用已验证的完整仓库引用及固定 digest，不依赖可变 tag。网络拉取失败保留 `runtime_installing`，不能提前登记已安装或配对。已绑定 artifact 的程序缺陷修复需要另外记录 base artifact、被修复文件旧/新 SHA、前像和实际检查结果；不能静默重写原 manifest 或伪造原安装回执。

## 既有设备登记及安全维护

`adopt-plan/adopt` 将已人工创建且有实际 QGA、native 和租户配对证据的设备登记到同一容量总账。独立 `device_adoptions` 表记录 `manual_adoption` 与配置前像；不伪造 clone 回执，不改网络、磁盘或运行状态。`attempted=1` 只代表运营操作尝试；`apply` 在同事务检查 adoption 后拒绝 clone/prepare。

`sleep` 先设置按资源维护栅栏，阻止新设备命令及人工接管。普通聊天和无设备任务继续。随后核对 relay 没有 queued/executing/unknown、没有活跃媒体、gateway 为 agent_ready、epoch 一致，并在 native OS lock 内复查，停 native 服务后以 ACPI 正常关机。未知任务不当作结束；失败保留冻结，不能自动放开。`wake` 再查 owner/generation/容量，发送一次 start，必须收到新连接的 paired-ready ACK 才恢复；超时不宣称 ready。

这不是内存休眠：磁盘和登录配置持久保存，但不能承诺任意网页未保存输入或 OS 内后台程序不会中断。自动按空闲时间关机尚未启用。A 的两台合成验收设备已分别实际完成 manual_adoption 和单台 sleep/wake，未知启动/关机回执通过观察恢复，未强制关机、清数据或替换历史人类接管 ACK。

## 2026-10-10 两账户实际交付记录

本轮只使用项目已有的私有合成验收账户 A/B，没有操作真实用户数据。A 的 1111 Linux、1112 Android 保留原有安装与配对，通过 manual_adoption 纳入总账，分别实测维护冻结、排空、正常关机、唤醒和新连接 ACK。它们不被计作自动 clone 产物。

B 的 1211 Linux（1 vCPU / 4 GiB）、1212 Android（2 vCPU / 4 GiB）由同一运营账本从官方内容核验的 stopped 模板 9000 完成 reserve、完整克隆、每设备独立网络、cloud-init、QGA 身份证明、SSH 绑定、原生运行时安装与首次 mTLS/relay 配对。两者的 enrollment 均为 verified，owner、artifact、paired scope、Agent 在线、人工接管在线与 mTLS 检查通过。设备基础检查与产品体验验收分开记录；这里不把 `device_ready` 写成 `product_ready`。

容量以实际配置计算：control 1 vCPU / 3 GiB，A/B core 各 1 vCPU / 2 GiB，两账户设备共 7 vCPU / 16 GiB。总计 10 vCPU / 23 GiB；宿主保留 2 个物理核心和 6 GiB，未用低 RSS 超售。每台设备保持完整内存/CPU预留，停止也不会释放给其他用户。

真实首次执行发现并修复了 Android cloud-init 无效包名、固定镜像仓库名称、Node 官方 tar 顶层目录与 libatomic 依赖、媒体服务 CLI 参数和 Linux ImageMagick 依赖。原始失败和原 artifact 均保留；现有 B 的必要修复有 owner/artifact/文件散列绑定的独立回执，未来模板/安装代码已补相应依赖与校验。Linux Firefox 首次设置仍单独报告 `first_run_unverified`，未代用户接受应用条款。

两台 B 设备均已通过审查计划将 `onboot` 设为 1，配置 before/after SHA 与交付账本一致，过程未重启设备。基础设备交付验证使用实时 OS、网络、媒体和原生驱动证据；Linux 同时检查独立 AT-SPI/截图后台，Android 通过同一 NativeAdapter 实际执行只读屏幕尺寸工具，避免 WebRTC/ADB 心跳可用掩盖 Agent 驱动依赖缺失。原生驱动解析修复另外保留变更证据。

私有证据保存在 `personal-compute/`：`b-{linux,android}-{plan,reserve,apply,network,boot,bind-ssh,install,enroll,verify,finalize-startup}.json`、实际失败日志、`b-android-bootstrap-repair-proof.json`、`b-android-node-bootstrap-repair-proof.json`、enrollment helper 修复和 Linux ImageMagick 修复回执。Linux 增强检查曾因已知只读失败需要 review 而保持 pending；两设备的指定只读失败通过既有审核 API 后，`b-linux-verify-native-reviewed.log` 和 `b-android-verify-native-reviewed.log` 均确认实时增强检查通过、无 pending。原失败不改成成功、不重播、不移除门禁。本模块末轮定向回归为 183 passed；总仓回归和公网媒体/模型行为由总体验收证据另记。

这条经管理员审核后执行的供应链已在 B 的新双设备上运行。公开注册自动触发供应、自动空闲关机尚未启用；容量不足会拒绝或保留排队，不能将运营命令的成功描述为开放用户自助开通已上线。
