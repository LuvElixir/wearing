# 账户删除控制面契约

2026-10-08。范围是可信登记、请求、冻结、状态回读；没有提供商删除或数据擦除实现。

## 公共接口

`AccountDeletionControl(ControlStore(web_url))`：

- `preview(session)`：session 必须由 gateway 验证。返回 schema、user_id、tenants、blockers、revision、ready。tenant 项含 classification、registry_revision、member_digest、instance_id、action。无登记默认 ownership_unknown；不会从一个活跃成员推断私人所有权。
- `request(session, request_key, plan_revision)`：key 为16–120位字母/数字/下划线/连字符，revision为64位SHA256。相同用户/key/revision恢复同一回执；不同key或revision不能覆盖已接受请求。请求与所有权登记/成员修改/登录/切换共享短事务锁，变化后的旧计划409。
- `status(user_id, job_id=None, request_key=None)`：两个定位字段必选其一，未找到返回None。调用者必须先验证用户会话或gateway签名的限定状态凭证，不能把未认证的客户端user_id传入。本人状态在业务冻结后仍可读取。

回执包括 id、user_id、request_key、plan_revision、state、code、created_at、updated_at、tenants摘要、data_erased。新请求为 `awaiting_operator / adapter_unconfigured`。当前所有回执的 `data_erased=false`，本模块没有设置completed的入口。

**请求持久入库即成为账户冻结条件**：已有所有业务session失效、重新登录/切空间/查询业务route失败，operator也不能给该用户重新grant。私人空间的计划阻止其他用户加入或重新绑定route。无需给web管理users/memberships的权限即可立即冻结。已有网络流由gateway持续会话检查关闭；已经执行的后台任务/设备动作仍需后续operator drain，不能声称请求受理等于任务停止或数据删除。

gateway负责新近OIDC验证、CSRF/Origin、确认和预存status-only凭证。ControlStore保存可信 `auth_time`（旧会话为None），不接受客户端提供该时间作为重新验证。

## 操作者接口

`AccountDeletionControl(ControlStore(operator_url, operator=True))`：

- `register(tenant_id, classification, owner_user_id=None, expected_revision=None)`：classification为private/shared/unknown，前两者必须显式owner且owner确实在全部成员（含inactive）中。首次revision=None；更新必须匹配现revision。不接受客户端路径/VM/盘参数。instance来自既有控制面固定route。
- `freeze(job_id)`：在与grant/bind/login/request同一锁下重新计算完整计划，且逐字结构比较持久plan。冻结用户、标记其private tenants frozen、撤该用户所有session和membership；shared其他成员与route不变。重复freeze幂等。仅返回 `frozen / adapter_unconfigured`，没有文件或云API调用。

登记摘要随operator grant/bind在同事务更新，任何成员状态变化（包括inactive）会改变revision。shared owner必须先完成真实所有权转移；unknown/缺instance/历史其他成员均阻止提交。

请求受理至operator freeze之间，相关shared空间的成员/归属管理暂时锁定，以免已冻结账户的已确认计划被并发grant改成永远过期；其他成员的业务route始终可用。freeze完成仅撤该成员后，shared成员管理恢复。私人空间管理持续锁定，不能重建访问。

## PostgreSQL 与迁移

- 0001已固定初始六表定义，不再import运行时metadata；新库顺序执行0001→0002，旧0001库保留账户/会话并升级到0002。旧账户的所有权不自动登记。
- 0002新增ownership、deletion_requests，users/tenants deletion_state以及session auth_time。
- web对ownership只SELECT，按本人成员关系RLS；对requests仅本人SELECT及六个申请字段的列级INSERT。不能写state/code/updated_at，不能UPDATE/DELETE/TRUNCATE，也没有扩大原会员/route管理权。operator保留独立角色。
- 请求之后，sessions的RLS WITH CHECK也禁止为该用户重建会话。新表全部ENABLE/FORCE RLS；启动校验新版本、policy集合与精确列权限。
- 短写事务使用PG advisory_xact_lock(8247991102)，SQLite回归用BEGIN IMMEDIATE；锁内没有网络/外部删除动作。

## 验收与仍需接通

SQLite控制面测试覆盖立即冻结、跨用户状态隔离、shared保留、历史inactive成员、旧计划、幂等、登记竞态、完整计划篡改与重启。

真实PG测试只在新建本机私有Unix-socket QA集群运行，无TCP：`.wearing/qa/account-delete-control-334bbc1153`。覆盖fresh和0001升级、原控制面权限与OIDC、本人申请/跨用户拒绝、普通角色不能伪造completed、冻结后SQL重建session拒绝、grant/login竞态。该目录只含本次合成账号/数据，不升级既有集群。

后续operator执行器必须接持久DeletionJobs、固定服务/资源登记、通知/native账户撤销、外部授权撤销、worker/relay停止及tombstone、数据盘/快照/备份与最终回执。本模块只完成控制面冻结，不能把awaiting_operator或frozen显示为已注销完成。
