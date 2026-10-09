# Activity、通知与排队撤回的任务归属边界（2026-10-08）

本包只使用临时 SQLite、真实 ASGI 边界和假的 Expo transport；没有连接模型、推送供应商或操作真实用户数据。

## 已实现

- 云端 Activity 的 owner 只读取经过 TenantBoundary 验证的 `pajio.storage_scope`。缺少该 scope 时列表和已读操作返回 401，原始 header、query/body 不能代替可信上下文。即使云端 installer 没挂 TenantBoundary，也不会回退本机。
- 有 `task_principals` 的任务只对相同 owner 可见；没有 principal 的历史任务保留身份共享范围，不自动登记到当前账户。Activity 的列表、计数、未读、revision、分页全部先投影再计算。分页 order/revision 绑定 owner，不回传 owner 值。
- `seen` 在同一事务内检查所有条目是否可见；其中任意一条不可见则整批拒绝，不会先标记本人条目再报错。已读不启动任务、不更改任务状态、不代表结果核验。历史无主任务继续沿用身份共享已读回执。
- 通知生成 outbox 时按 task principal 筛选设备 owner；claim、最终 handoff 和 resolve 再检查任务可见性。升级前误投到另一 owner 的 pending/awaiting_registration/sending 行会取消为 `TaskNotVisible`；已交给供应商的旧通知不能召回，旧深链也不能据 outbox 绕过归属检查。
- `cancel_message` 先执行 require，再在服务锁和 SQLite 写事务中检查可信 identity/owner，之后才更新 task、handoff、goal queue 和事件。HTTP middleware 仍先拒绝外账户；锁等待后再验避免依赖之前的检查。内部 operator drain 使用显式内部调用路径。
- `calendar_series` 已在真实产品 MCP 的 TOOLS、dispatch、SeriesError 映射中注册，使用同一版本化 series book。

## 证据

以下单次命令 **190 passed**：

```
uv run pytest -q tests/test_cancel_owner_review.py tests/test_message_handoffs.py tests/test_account_deletion_tenant.py tests/test_activity.py tests/test_activity_owner_review.py tests/test_notifications.py tests/test_notification_owner_review.py tests/test_calendar_series.py tests/test_calendar_series_proxy_review.py tests/test_life.py tests/test_task_lists.py tests/test_background_principals.py
```

新增回归包含两个账户同 identity 的 list/detail/seen 一致、跨 owner cursor、整批已读回滚、缺中间件/缺 scope、重启、通知仅投本人、旧误排队隔离、发送前再次核对、撤回前拒绝及等锁期间归属变化。

## 保留边界

此包没有宣布全产品读取面已统一：旧 conversation/search/artifact/export 仍需逐一审查任务内容投影。life_records、明确无主历史内容是否为身份共享数据不能从手机授权反推。真实设备通知到达、App 原生任务详情点击和外部会话撤销仍分别验收。
