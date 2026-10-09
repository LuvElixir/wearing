# 账户删除：当前实现调查与最小闭环

2026-10-08。只读源码调查，没有读取云凭据、调用提供商、停止服务或删除真实数据。调查目标是确定必须写的代码与可复用边界，不是提供一个“已注销”假按钮。

## 当前结论

**现有仓库没有 tenant deprovision。** `cloud/instance.py` 明确是 immutable instance state，不是 VM provisioner；CLI 只有 tenant init/status/serve/preview/relay/pair-device/revoke-device。`cloud/tencent.py` 只允许官方查询和报价；`deploy/vm/tencent-trial.py` 是特定首台实例部署脚本，不能当成租户销毁服务。

控制面 `tenants` 只有 id；`memberships` 只有 user_id/tenant_id/active，没有 private/shared、owner、删除锁或删除状态。`routes.instance_id` 唯一能避免共用实例路由，但不能证明哪个用户有权删除租户。**仅有一个 active 成员不能证明这是其私有租户**：被停用的原成员、共享租户所有权、代管注册都可能存在。

App“日常/出海”等 `identity_id` 属于一个租户的工作身份，不是平台用户。任务/记录/对话目前只记录 identity_id，没有 author_user_id。故共享成员离开时不能删掉整个 identity，也不能推断哪些消息是这个成员自己的并自动清除。

## 删除范围必须明确

| 服务端登记事实 | 允许的账户注销范围 | 必须保留/先解决 |
|---|---|---|
| 明确 personal，operator 登记 owner_user_id=当前用户，且只有该用户一个成员（含 inactive） | 撤该账号所有会话与成员；完整清除其个人租户实例/数据/副本 | 不误删同用户加入的共享租户；必须核对唯一实例/卷归属 |
| shared，当前用户是普通成员 | 撤该成员访问、个人设备通知注册与账户级凭据，删除个人控制面资料 | 共享任务/文件/会话/身份全部保留；不能清除其他成员使用的应用授权 |
| shared，当前用户是 owner | 先完成明确的所有权转移或组织管理员流程，再注销个人账号 | 不能让“注销本人”隐含销毁组织空间或留下无人可管的空间 |
| legacy/unknown/归属冲突/private 中有其他历史成员 | 可冻结本人访问；数据删除计划必须显示待核对 | 不执行租户/身份/文件删除；由 operator 补足真实归属，不让 App 自报 owner |

外测最短路径是**仅登记明确的单人私有租户**；共享成员注销保留共享空间，未知旧租户不自动擦除。不应先在 UI 允许“删掉全部”然后由后端猜范围。

## 可复用实现与不足

| 现有组件 | 能复用什么 | 还缺什么 |
|---|---|---|
| `ControlStore.grant(...active=False)`、`session()`、`route()` | 停用会员后新会话检查/派发被拒绝 | 这是 operator 入口，不能由 web 角色直接改；缺全部用户会话原子撤销/删除锁、成员版本/归属版本 |
| `gateway.operator_store()`、Postgres RLS/迁移 | 同一数据库独立 operator 角色、web 无修改会员/路由权 | 新 deletion requests 需自己的版本化表/最小权限/RLS；不能把 operator DSN 放公网请求进程 |
| `ControlStore.logout(sid)` | 撤当前一条会话 | 不能覆盖该用户其他设备；创建/切租户与删除要共用数据库锁和冻结检查 |
| `cloud/mobile_auth.py` | 一次性120秒 handoff；登录重新查 active 会员 | 缺新近身份验证标记与可安全查询的注销回执；不能用退出按钮等同注销 |
| `cloud/instance.py load_instance()` | 校验 tenant/instance、private权限、data/instance-owner.json | 缺固定 provider 资源登记、volume/snapshot清单、删除tombstone、防自动重建 |
| `CloudApps.disconnect()` | 先停止本产品读取，远端撤销失败保留 revocation_pending 供重试 | 撤销未完成不能先毁掉唯一 refresh/access token；遗留供应商授权状态单独显示，任务完成不谎报 |
| `MessagingBridge.disconnect()` | 删除本地 bot 凭据、停飞书receiver | 并不撤销提供商 bot token，不应吊销共享 bot；需按所有权区分本产品解绑/提供商撤销 |
| `RelayStore.revoke()` | 阻止新设备连接/动作；未决动作标 unknown | 不能撤回已发生的点击；需等准入命令停止/核对，并删除实例内relay账本/凭据；外部电脑仍可能有配对副本 |
| `NotificationService` | 停用安装、持久outbox取消、session lease | 当前注册仅 identity+installation，无平台user owner；共享成员注销要用可信storage/user scope绑定后撤其所有注册，不能等待8小时lease当立即停用 |
| worker lifespan/runtime.close/systemd | 能结束owned引擎与后台work；worker文件锁 | 必须从operator停worker和relay、禁自动重启并核验整个cgroup/安装子进程；只停Hermes会被下个请求或systemd重启 |
| IdentityExports | 实际可读数据包、有遗漏清单 | 不含所有原件/密钥/日志/备份，不是完整备份，也不证明删除覆盖 |
| SearchBook/WorkspacePager | 当前搜索读同库、游标进程内 | 停worker可清当前游标；未来外置向量索引/对象存储必须纳入登记，不能默认为没有副本 |

Postgres 当前 `wearing_web` 对 users/tenants/memberships/routes 没有 INSERT/UPDATE/DELETE，只有 sessions/oidc_states 的限定读写。复用这一边界，在新迁移中给 web **仅创建/读取自己的删除请求**，operator 消费作业。不能为了注销给 web 原有管理表写权限。迁移须同时更新 postgres 的表/版本/权限断言；SQLite 合成测试通过不能替代 Postgres RLS 测试。

## 最小可交付流程

1. **Plan**：新近登录后由 gateway 已验证用户生成账户范围清单；operator 来源返回个人租户/共享成员/未知归属、版本摘要。App 只显示范围、可先导出、不可逆动作说明。不能传入文件路径、云资源 ID 或伪造 ownership。
2. **Request**：用户明确确认，稳定 request_key＋plan revision 入持久请求。相同key恢复回执；不同计划409。作业记录不含对话/密钥。App显示“已请求”，不是“已删除”。
3. **Freeze**：operator 事务持有用户/相关租户锁，复核全部成员/路由版本；冻结本人登录和全部已有session。个人租户阻止新请求/新任务/新配对；共享租户只撤该成员，不停整个共享worker。取消流式连接与旧handoff重新兑换后的登录。
4. **Revoke and drain**：逐个身份停调度/目标、取消待发通知、撤受控设备、停止消息接收、撤本租户应用授权。供应商不可达时本产品访问已冻结、状态为撤销待重试，不销毁重试所需私密凭据。记录已准入但未确定的动作，不保证已执行动作回滚。
5. **Stop**：operator按登记实例停止/禁用worker与relay服务，验证pid/cgroup/文件锁、所有安装/执行进程退出。加入实例tombstone，禁止自动恢复到旧卷或从备份恢复后重新上线。
6. **Erase live storage**：在确认停止后，只使用服务端固定实例/卷登记核对tenant、instance、卷serial，再清完整私有卷/主库/WAL/导出/原件/identity homes/日志/记忆/skills/cache/relay；一份租户完整清除优于不停服按表DELETE。不能把filesystem unlink说成底层物理擦除。云盘保留策略是 DeleteWithInstance=false，删除VM不等于删除数据盘。
7. **Copies and provider**：已登记快照、对象版本、备份、供应商grant分别得到回执。存在待到期副本时返回“主数据已清除，备份保留至…”，不返回彻底删除completed；供应商未撤销同理。外部用户设备已下载的副本明确不能从服务器远程擦除。
8. **Finalize**：确认个人租户全部步骤终态后移除其路由/worker credential与membership；共享空间不变。删除/pseudonymize本平台user与issuer/subject映射，不操作用户全局Apple/Google/飞书账号。仅保留必要不含PII的job凭证/统计与明确到期策略。注销状态查询使用限定凭证或再验证用户身份，不能持旧通用session访问业务接口。

## 可并行实施包与合成验收

- 控制面：归属登记、冻结状态、计划revision、请求/阶段回执迁移、operator消费（重复/重启/并发grant与logout）。原数据库操作必须有真实事务与Postgres RLS。
- Worker/instance：固定归属停止和tombstone、relay/通知/外部凭据撤销适配、私有卷清除器（隔离临时目录），禁止软链/路径替换/挂载变化/运行中删除；未接云提供商只能待配置，不伪报清除。
- App：预览范围、确认、稳定请求恢复、阶段状态、导出入口、最终清本机scope及全部设备凭据撤销状态。未挂服务前不增加能点出假成功的按钮。
- 测试最低集合：单人个人租户 A 删除而 B 完整保留；共享普通成员不伤其他人；最后 active 成员但unknown/inactive peers不删；owner未转移拒绝；重复请求/中断恢复；计划后新增成员409；服务未停/外部撤销失败/备份未过期均不completed；旧HTTP/WSS/推送/设备token拒绝；路径穿越/symlink/实例不符拒绝；供方超时不重复销毁；不读取任何真实凭据。

此调查没有让任何真实账号、实例或文件进入删除流程。先补归属与持久流程，再接提供商执行器；不会以“数据库删一行＋清本机登录”交付账户注销。
