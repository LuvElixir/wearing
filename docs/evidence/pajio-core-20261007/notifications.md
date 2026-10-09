# Pajio 原生进展通知实现 / 2026-10-08

实现代码，不代表真人手机推送验收。全部自动测试使用临时 SQLite 与显式 MockTransport，未发送用户推送。

## 后端接入

- `notifications.NotificationService(store)`，tenant 独立 Store；`install_notification_routes(app, service)` 放在原有认证、身份、CSRF 中间件后。
- lifespan 创建 `stop = asyncio.Event()`、`task = asyncio.create_task(service.run(stop))`；关闭时 `stop.set()`、等待/有界取消 task、`await service.close()`。中断已开始的发送保留 sending，120 秒后归为 unknown，避免重启盲重放。
- `PAJIO_PUSH_ENABLED=1` + `PAJIO_EXPO_PROJECT_ID=<EAS UUID>` 才发送；`PAJIO_EXPO_ACCESS_TOKEN` 可用于 Expo 增强推送安全。默认禁用。
- GET `/api/notifications/status?installation_id=…`
- POST `/api/notifications/register`：`installation_id, expo_push_token, project_id, platform`
- POST `/api/notifications/disable`：当前身份停用；POST `/api/notifications/disable-installation`：退出账号前停用本安装在该 tenant 的所有身份。
- GET `/api/notifications/resolve?event_key=…`：必须以正确身份认证；返回精确 task/identity/server/event。

注册租约受已验证会话有效期限制。云网关传递可信 Unix 到期时间，TenantBoundary 校验有限数值、未来时间及最长 8 小时窗口，再放入 `pajio.session_expires`；通知注册在云 worker 缺失到期时间时返回 401，service 也禁止 cloud owner 退回本地租约。本地模式租约最多 7 天。收集、领取和状态读取都会使到期注册失效，并将待发队列转为 awaiting_registration；同账户有效会话重新登记后重验版本再发送。主动停用、退出和撤销则永久取消队列，不补发。历史无法确认 owner 的注册升级后失效。退出失败不能声称已停用，过期会话无法继续维持推送注册。

账户关联使用经网关认证的 `pajio.storage_scope`，cloud 路由缺少该关联一律401；本地直连固定 local。时段、状态、通知解析按 owner + identity + installation 隔离。设备安装切换到账户 B 时，取消账户 A 旧待发项并增加 generation，B 不能读取或继承 A 队列与时段。`revoke_owner_scope` 是仅 operator 可用的持久撤销 hook，不能通过 App 传 scope 调用；已撤销账户禁止重新登记。旧 token 或同 token 旧 generation 的回执均不能停用新登记。已交给 provider 的请求无法召回。

ActivityBook 实际可确认卡片和 completed_unverified/failed 状态生成 SHA256 稳定 event_key；身份/任务/业务版本共同绑定。首次启用建立现有结果基线，避免补发全部历史。旧卡片/已核对结果在发送前按实际版本取消。去重 outbox 及原子 claim 防止轮询/多进程重复排队；token 轮换后，旧 token receipt 不撤销新 token。

ticket = Expo 已接收；provider_accepted = APNs/FCM 已接收；两者均不宣称设备展示。429、明确未连接和明确限速有限退避；超时/5xx/不完整 ticket 归 unknown 不自动重发。DeviceNotRegistered 停用相同失效 token。receipt 15 分钟后查询，24 小时后未取得归 unknown。

正文固定为进展/确认提示，不含标题、任务文本、个人资料。data 只有 `v=1,type=pajio.task,server_id,event_key,task_id,identity_id`，不含可执行动作/任意 URL。

## 原生接点

`NativeNotificationsPanel.tsx` 导出：

- `<NativeNotificationsPanel connection={connection}/>`：显式系统授权、真实 token 登记、停用、重新检测、系统设置。内部按 scopeOf key。
- `<NativeNotificationSession connection={connection} onError?={...}/>`：已连接身份 lifecycle，前台/原生 token 轮换时同步已开启订阅；不擅自启用。
- `observeNotificationResponses(async target => boolean, onError?)`：返回 cleanup；冷启动及前台点击统一处理。父层须从已有认证连接校验可见身份→正确身份 `NotificationClient.resolve(target)`→打开精确任务，成功后返回 true 才清 last response。
- `disableInstallationNotifications(connection)`：清除账号认证前调用，网络失败不能当作服务端已停用。

`notification-client.ts`：NotificationClient、NotificationTarget、notificationInstallation(storage, randomUUID)。不信任通知传入网址，resolve 回执再次校验 server/identity/task/event。

已 `expo install expo-notifications`，SDK57 ~57.0.22，app.json 加 config plugin。需重新原生构建、同一 EAS projectId、APNs/FCM 凭据。旧 build 使用 requireOptionalNativeModule 降级可读状态。项目及凭据未知时不称可用/已送达。

## 验证

- Python 53 tests（2026-10-08 本轮）：`test_notifications.py` + `test_notification_quiet_hours.py` + `test_notification_owner_review.py`。真实 ASGI 认证/CSRF/tenant/owner/身份、跨夜租约与等待重新登记、安静时段/DST、初次基线、重启/并发去重、旧库迁移、敏感正文排除、确认卡新请求、token和generation轮换、异步发送期间停用/退出/切账户/撤销、ticket/receipt、超时/崩溃/429。
- TypeScript 13 tests：请求方法/headers/CSRF/账号快照，坏回执，安装标识并发持久化，深链绑定，配置前不请求权限，Android channel 顺序，OS 撤权，切身份取消迟到登记。
- 上述 TS 文件 lint 及全 App tsc 通过。

未做：真实设备 APNs/FCM 到达、Focus/省电模式、多账号真人离线推送、原生构建签名。Provider 不能保证 exactly-once 展示，网络未知结果不能伪造为成功。

官方依据：[SDK57 Notifications](https://docs.expo.dev/versions/v57.0.0/sdk/notifications/)、[Expo tickets/receipts](https://docs.expo.dev/push-notifications/sending-notifications/)。
