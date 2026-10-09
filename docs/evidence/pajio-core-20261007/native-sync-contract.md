# App 系统来源单向同步（2026-10-08）

## 用户流程与范围

用户在 `NativeSyncPanel` 主动点“选择系统日历”或“选择提醒事项列表”，完成 OS 权限提示，再逐个勾选列表并点启用。得到读取权限并不自动启用同步。所选来源、开关、安装标识、待上传批次都跟随完整账户 / tenant / identity scope；另一账户、身份或安装不会继承这些选择。

`NativeSyncSession` 仅在 App 前台工作：启用后、回到前台、每 60 秒、点立即更新，以及手动系统编辑回读完成后更新。日历固定读取过去 7 天至未来 30 天，提醒事项包含有日期、无日期、已完成和未完成项。每个来源最多提交 500 项；更大的结果标记为截断并提示。没有 iOS 任意后台同步或 OS 变更游标的承诺。

读取是所选列表的有界快照；服务端只对发生变化的内容写新版本。结果进入现有 `life_records`，由现有 Today/记录界面读取。副本沿用当前身份原有可见范围：这次隔离来源授权和同步队列，不改变“同身份共享记录”的数据模型。

系统原件到 Pajio 是单向同步。修改 Pajio 副本不会回写系统；系统编辑仍走现有原生面板，再读回结果并触发同步。日历编辑保留系统原生编辑器的确认流程。

## 幂等、冲突和缺失

- 映射键为 `identity + trusted owner + installation + source kind + source id + OS external id + occurrence id`。iOS `originalStartDate` 来自 `EKEvent.occurrenceDate`，同一次重复日程改时间时保留原始实例键；普通日程使用 OS id。多个实例独立保存。
- 如果系统或上游账户重建了 OS 标识，无法证明是原对象，就保留旧副本并建立新映射，不凭标题和时间猜合并。Android 缺少原始实例标识的例外不冒充已能完整合并移动实例。
- 每批上传之前先把精确批次与 request_id 写入本机 journal。网络断开、服务已保存但回执丢失时先重放同一批，服务端以 request_id + hash 幂等返回同一结果。内容不变不增加记录版本。
- 映射保存最后应用的 canonical revision。用户、Agent 或其他入口改过 / 归档 / 删除副本后，后续系统读取只保存冲突信息，不覆盖该副本，也不把归档记录复活。当前版本保留本地修改，不提供自动合并。
- 完整快照中没看到的对象只标为 `unseen`，不删除 canonical 记录。来源失去、取消同步、移动日期窗口、系统删除和重复规则变化都不是可靠删除证据。截断快照不产生 unseen 判断。
- 源内容、标题和备注作为数据保存在副本，不增加隐藏授权、任务 principal 或原生执行权限。副本正文明确说明系统来源与单向性质。

## 中断与身份边界

- 点击停止或修改来源时先使旧 generation 失效并 abort HTTP，再持久化新选择。每个异步边界、OS 读取后和上传前再次检查当前连接、前台状态、选择 generation 与 revision。已停止的 OS 读取响应不会继续上传。
- 本机保存选择失败时，本次进程保持采集暂停，直到用户再次成功保存；不会悄悄按旧选择继续。重启后仍以最后成功持久化的设置为准。
- OS 权限检查在采集前后进行。撤权后清掉待上传本机批次并停用本机同步；重新允许后需要用户再次启用。系统 API 调用本身未必能取消，但迟到内容不会落盘上传。
- 已经在服务端提交完成的在途请求不能撤回；停止会阻止后续读取与请求。服务器的 enabled / revision / selected source 校验在同一写事务内执行，已经停用的旧 revision 不会写入。
- 云 HTTP owner 仅使用经网关 / tenant boundary 校验的 ASGI `pajio.storage_scope`；缺失 / 错误 scope 拒绝。body 中的 owner 不被接受。普通本机服务使用 local owner。安装器显式传入部署模式；云模式即使漏挂 tenant boundary 也不会回退为 local owner。
- App 请求携带当前账户 Bearer、expected tenant、identity 与 bootstrap CSRF；响应读完后也复核 active。禁用跳转，错误/不匹配回执保留原队列。

## SDK 57 的提醒日期

已检查 SDK 57 legacy iOS serializer：提醒事项没有返回 `allDay`。因此未知类型的 dueDate 不转换成虚构的具体截止时刻；副本只在备注显示系统日期，并提示到系统提醒事项核对时间/全天设置。只有 SDK 明确返回 `allDay=false` 的提醒才保存 `due_at`。

原生手动操作另见 `native-action-contract.md`：未知日期类型编辑保留原有日期组件；不支持的新全天创建在 OS 写入前拒绝；已有写入的回执可按原 marker 找回。

依据：[Expo Calendar legacy SDK 57](https://docs.expo.dev/versions/v57.0.0/sdk/calendar-legacy/)、[Apple EKEvent occurrenceDate](https://developer.apple.com/documentation/eventkit/ekevent/occurrencedate)，以及本地 `expo-calendar/ios/Conversions/Conversions.swift` 和 `Requesters/CalendarPermissionsRequester.swift`。legacy 对 write-only 日历授权判 denied，不将其当作可读权限。

## 集成接口

服务端在身份中间件之后安装：

```python
from .native_sync import NativeSyncBook
from .native_sync_api import install_native_sync_routes
install_native_sync_routes(app, NativeSyncBook(store), local_devices=local_devices)
```

HTTP 全部为 POST：`/api/native-sync/state`、`/configure`、`/upload`。配置使用 revision CAS 和独立 request_id；上传有精确批次回执，包括 created/updated/unchanged/conflicts/unseen/truncated 和记录 ID。服务端单批总计最多 500 项，客户端按列表独立发送。state 返回当前设置和本安装映射状态。

App 独立模块：

```tsx
<NativeSyncSession connection={connection} isCurrent={()=>current.current===connection} onRecordsChanged={refreshCanonicalRecords}/>
<NativeSyncPanel connection={connection}/>
```

Session 只能随当前业务连接挂载；注销、切换账号、退出时卸载。`isCurrent` 直接核对父组件 current ref，阻止连接已切换而 React 尚未卸载时的旧上传。onRecordsChanged 调用现有 records 同步。Panel 放“系统日历与提醒事项”入口；NativeCalendarPanel 本身不接收连接凭据，只用已有 scope 发送刷新信号，不会自行授权来源。

## 注销与缓存范围

本机 key `native-sync:v1:${scope}` 已被通用 `account-cleanup-model.ts` 的 exact account scope 检出；账户删除围栏阻止旧连接重新写入，清理只删除本账户的设置、批次和备注，不动另一个账户。

服务端新增 `native_sync_settings`、`native_sync_requests`、`native_sync_objects` 三张表，均有 `identity, owner, installation`。个人 tenant 整库注销覆盖这些表与 canonical 副本。共享 tenant 需要按可信 `owner=storage_scope` 清同步三表，并根据 objects.record_id 处理该账户导入的 life_records 及对应 life_changes / mutation receipts；不能凭 identity 删整个共享身份。目前共享 tenant 注册不完整时的注销等待机制继续适用，不宣称已完成这部分生产清除。

## 本地验证及待验收

- 独立同步测试：App 14 项，后端 18 项，使用合成来源 / mock fetch / 临时 SQLite 与 ASGI。
- 联合原生与账户清理 App 测试 50 项通过；typecheck 与本次文件 ESLint 通过。
- 覆盖：显式启用、日程实例、全天未知、截断、持久化失败、回执丢失、跨账户/tenant请求、损坏队列、停止/后台迟到响应、权限撤销、冲突保留、归档保护、重启/并发幂等、旧时间快照、账户围栏与精确清理。
- 仍待：签名安装后的实体 iPhone/Android 系统授权、真实日历 provider 的循环实例、OS 编辑返回、前后台切换、真实弱网。此次未读取真实日历、未创建真实提醒，也未运行真实云端删除。
