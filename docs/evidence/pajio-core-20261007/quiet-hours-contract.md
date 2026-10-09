# 安静时段 · 2026-10-08

App“我的 → 通知”已提供安静时段设置。每个账户/身份/手机独立，默认关闭；用户显式开启、填写开始与结束时间及 IANA 时区后保存。现有通知配置与系统权限仍决定能否真正推送，不因设置时段自动登记 token 或索取权限。

- GET `/api/notifications/preferences?installation_id=...`：identity_id、installation_id、revision、enabled、start_minute、end_minute、timezone。缺省 revision=0、22:00—08:00、Asia/Shanghai。
- POST 同路径：installation_id、revision、enabled、start_minute、end_minute、timezone。复用既有登录/身份/CSRF边界。精确 revision CAS，冲突409；未知/失败回执保留输入，重新读取核对，不能提前显示已保存。
- 服务端持久 `notification_preferences`。发出前计算时段，范围为开始含、结束不含；跨午夜和夏令时按实际 IANA 本地时间。开始=结束拒绝，以免误认为全天或零时长。
- 云端账户关联只取已认证网关经 TenantBoundary 校验后写入的 ASGI `pajio.storage_scope`，不取 App body、query 或普通请求头。数据库主键为 owner_scope / identity_id / installation_id；本地直连固定 local。缺少云端关联返回401，历史无法归属的时段存入 legacy 表，不能继承给下个账户。
- 安静时段内 outbox 保持 pending、attempts不增加、next_at=首个允许发送的UTC分钟、error_code=QuietHours。更改时段只重算 quiet-held 项，不清除 provider 退避和 sending/unknown/ticket。
- 默认22:00—08:00时段长于云端最长8小时会话租约。租约到期时登记失效、未发送队列转 awaiting_registration；App获得有效会话并以同账户重新登记后，仍有效的结果重新参与发送。不会用旧会话在早晨绕过授权，也不会直接丢失夜间结果。租约失效期间的新结果同样保留等待登记。
- 用户停用、退出登录、切换设备所属账户或 operator 撤销账户时，待发及等待登记项永久 cancelled，重新启用不能补发。发送已交接但回执迟到时，由 owner_scope / generation / token / attempts / 原状态共同阻止旧回执恢复已取消项或停用新登记。
- 结束时重读任务版本：旧确认/已检查结果取消，不补发过期内容；其他设备不被安静队列阻塞。任务本身照常运行，App内结果继续可读。
- 已交给推送服务的通知无法撤回；这项能力不等同系统专注模式，也不保证系统展示。没有紧急绕过，所有结果与确认同等延后。

本轮验证：`tests/test_notifications.py`、`tests/test_notification_quiet_hours.py`、`tests/test_notification_owner_review.py` 共53项隔离Python通过。覆盖跨午夜/夏令时、跨夜租约到期与重启后仅发送一次、换账号与撤销、迟到回执、旧库迁移、CAS和HTTP边界。通知客户端与时段17项TS是此前验证，本轮只改服务端与服务端测试。均无真实推送；仍需真实签名App、APNs/FCM配置及真机到达验收。
