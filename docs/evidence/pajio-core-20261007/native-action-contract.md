# Agent → iPhone 原生能力 · 2026-10-08

这条链路已接入 App 和同一产品 MCP。它使用 iPhone 上已安装的 Expo 原生模块与 EventKit / Core Location，手机是执行端。代码与隔离回归已验证；尚未在真实 iPhone 上完成系统授权和创建记录验收，不能据此声称真机能力已验收。

## 当前范围

| 能力 | 范围与确认 |
| --- | --- |
| `calendar.read` | 用户明确选择的日历，带时区的最长 31 天区间，每次最多返回 100 项 |
| `reminders.read` | 用户明确选择的提醒列表，可选是否包含已完成项，每次最多返回 100 项 |
| `location.read` | 当前前台一次位置；每次手机确认，返回坐标、精度、时间；不启动位置跟踪 |
| `calendar.create` | 在所选可写日历新建一条；手机显示列表、标题、起止、备注并确认后保存 |
| `reminders.create` | 在所选可写提醒列表新建一条，可有明确时间或无截止时间；每次手机确认 |
| `calendar.update` / `calendar.delete` | 引用本任务刚读取的系统记录，每次手机确认；重复日程只处理明确的一次 |
| `reminders.update` / `reminders.delete` | 引用本任务刚读取的非重复提醒，每次手机确认；修改标题、备注、完成状态 |

不包括修改整组重复日程、重复提醒、提醒日期、批量导出相册或后台长期定位。照片仍由已有系统选择器交给用户主动选择。

SDK 57 的 `expo-calendar/legacy` 提醒回读没有 `allDay` 字段，因此提醒返回 `all_day: null` 表示系统未提供，不解释成非全天。当前创建提醒明确拒绝 `all_day: true`，在 OS 写入前阻断。普通提醒核对 ID、日历、标题、备注、截止时间、未完成状态和本次唯一标记；全天日历事件使用有真实回读的事件接口。不能用请求字段补造系统回读。未来全天提醒应先补可验证的原生读取，再开放。

## App 操作

“我的 → 本机能力”里的 `NativeActionPanel` 让用户主动取系统权限、选择列表、保存/停用授权，并查看最近 30 次手机请求。页面打开或聊天开始不会自动索取日历、提醒或位置权限。

`NativeActionSession` 在身份下挂载一次，独立于可见 tab。iOS App 在前台时建立短会话并每 3 秒接收请求；离开前台、切换账户/身份、停用授权或系统权限变化后停止接收。每次写入和每次位置请求都有明确手机确认，通用聊天批准不能代替它。

修改、删除与新建使用独立的默认关闭开关，旧授权不会自动获得修改权限。写入结果不明时，可以“读取当前系统记录”查看原列表内的实际内容，再在系统应用中核对并记录“已手动核对”。这仅解除未核对状态，不修改系统内容，不把结果改为成功，也不自动重做原动作。日程移出原时间范围或系统产生新的单次实例 ID 时，读取页面会保留无法精确定位的说明，不将未找到解释成已删除。

## HTTP 与 Agent

- `GET /api/native-actions/devices`
- `POST /api/native-actions/configure`：设备凭据、策略、revision CAS
- `POST /api/native-actions/connect`、`poll`、`disconnect`：设备凭据与前台连接 ID
- `POST /api/native-actions/claim`：精确 command ID / fingerprint、手机本次决定
- `POST /api/native-actions/result`：原连接、原 command、原结果
- `POST /api/native-actions/history`、`review`

沿用现有登录、identity 和 CSRF。手机凭据只存 SecureStore，使用完整 endpoint / tenant / account / identity 范围派生存储键。凭据不进入 Agent 的工具参数或结果。

Agent 通过 `native_devices` 发现已授权且在线的设备与列表；`native_request` 提交后等待终态；`native_receipt` 只读查看原回执。同一次请求必须保留 request_key。用户文字、列表标题和读取到的系统内容仍是不可信内容，不是新增权限指令。

## 账户和任务绑定

- 云端 HTTP owner 只取受信网关经 TenantBoundary 验证的 ASGI `pajio.storage_scope`，不用 App body / query / 普通头部声明的 owner。
- 手机数据库记录绑定 owner_scope / identity / installation。同 tenant、同 identity 的另一账户不能枚举、配置、轮询、确认、提交回执或核对该手机，即使提供完全相同的手机凭据也被拒绝。
- 正式聊天提交通过 `TaskService.submit_message(..., owner_scope=...)` → `Store.accept_message`，在创建任务与 message_handoff 的同一事务中写入 `task_principals`。同 request_id 的重试不能更换 owner。
- `Store.bind_task_principal(db, task_id, owner_scope)` 供受控任务入口在创建事务中绑定，已有 owner 不可覆盖。结果选择后续任务也应绑定当前可信选择者，而不是借用来源任务 owner。
- NativeActions 在云部署持久保存 require_task_owner 标志。长期运行的 life MCP 重新打开相同数据库也不能退回本地默认授权。派发从唯一活动 task / run 的可信 principal 得到 owner，并与手机 owner 比对。
- 已绑定任务的 `/api/tasks/{id}` 和 `/api/confirmations/{id}` 操作禁止其他 owner 控制。手机号/安装 ID、知道 task ID 或用户说“同意”均不能替代绑定。
- 无账户 scope 的私有云预览仍可普通聊天，但该任务无 principal，云端手机能力失败关闭。新 goal、schedule 只有从可信创建或启用入口持久绑定 source owner，才能传给后续任务；旧无主后台来源不可借当前手机身份获得权限。手机必须仍前台，并逐次确认。
- 带 task principal 的任务、会话输出与派生内容沿用独立的 owner 可见性规则；生活记录、记忆、工作区资料仍沿用产品明确的同身份共享语义。这份手机执行授权不等于完整多人工作区资料隔离。

## 执行与恢复

服务端会话租约 60 秒、命令期限最多 55 秒。任务必须仍是同一 identity、同一 task、同一 run 的活动任务，且授权 revision、连接、lease epoch、原生能力、所选列表均一致。

执行流程是：排队 → 手机确认/范围校验 → 持久 `prepared` → 服务端原子 claim → 本地持久 `admitted` → OS 调用 → 系统回读 → 本地持久 `receipt` → 服务端确认原回执 → 清除本地 journal。任何存储失败都不能跳过前序持久步骤。

同一命令最多允许一次 claim。写入调用没有自动超时重发；原生异常可能发生在已经写入之后，因此保留 unknown。App 中断、失联、任务停止或 MCP 调用取消时，尚未 claim 的请求被取消；已 claim 写入保持结果待核对，读取结果不得继续上传。原生写入已发生时允许原账户、原设备、原连接补交原回执，绝不把它交给新身份。

App 重启只补交 journal 的回执，不再次调用 OS。服务端同回执 hash 幂等，不同回执拒绝覆盖。客户端对精确 task/run/command/policy/结果做回执核对，错配回执不会清掉原 journal。最多每台手机一件未完成或未核对操作。

读取回执限制字段、返回项数、大小、所属日历、日期区间、时区和实际类型。原生返回缺失的数据不能通过宽松 truthy 转换变成已核对事实。

## 修改与删除契约（2026-10-08）

成功读取的原始 `result.data.items` 不会被服务端重写，仍用于手机精确回执核对。服务端在回执外层增加 `references`，每项为 `{record_ref: "native_<32hex>:0", index: 0}`，指向原列表内带有 `snapshot.mutable: true` 的记录。快照包含完整原生序列化记录的 SHA-256、是否重复、事件实例开始时间与可修改标记；哈希覆盖未截断的备注、位置、闹钟、循环规则和系统修改日期。

Agent 参数仅接受下列闭集，不能提供系统 ID、列表 ID、target 或自造快照：

```json
{"method":"calendar.update","params":{"record_ref":"native_<32hex>:0","patch":{"title":"新的标题","start":"2026-10-09T11:00:00+08:00","end":"2026-10-09T12:00:00+08:00"}}}
{"method":"calendar.delete","params":{"record_ref":"native_<32hex>:0"}}
{"method":"reminders.update","params":{"record_ref":"native_<32hex>:0","patch":{"completed":true}}}
{"method":"reminders.delete","params":{"record_ref":"native_<32hex>:0"}}
```

每个请求还必须提供安装 ID 和稳定 `request_key`。引用限同一个可信 task/run、同一设备、当前 policy revision、10 分钟内的成功读取；每个引用只可派生一次操作。原 key 的重试只返回原命令；改用新 key 重放同引用会被拒绝，冲突后须重新读取。服务端从原回执派生 `calendar_id` 与 `target`，构造手机 command，App 再次验证完整字段与所选可写列表。

手机确认后先持久化执行 journal、获得 claim，再读取原记录；完整哈希不匹配时返回 `cancelled/conflict`，不写入。权限和所选列表检查之后，再次读取并比较快照，紧接着调用固定原生函数。事件修改和删除总是传 `{instanceStartDate: <原实例时间>, futureEvents: false}`；全天事件可修改标题和备注或删除，不能在这条链路改变日期。所有重复提醒暂不支持。

SDK 57 legacy 保存事件会重设标题、备注、位置、全天、availability 和 alarms，即使参数省略也可能重置，因此驱动从已核对原记录保留这些字段。提醒只写用户明确修改的完成状态，以及必须保留的标题、备注、位置，不重写日期、全天、循环和闹钟。没有闹钟的事件可能省略 `alarms`，按空数组保留。带地理位置闹钟的事件当前拒绝修改/删除：已安装 SDK 的 serializer 使用 `coord`，写入端读取 `coords`，不能无损回填。

写后更新必须读取实际记录并逐项核对；删除必须成功读取原所选列表及实例时间范围并证明该实例不存在，读取异常不算删除成功。回执包含 `record_ref`、`before_revision`、`operation`、实际 `record` 或 `null`、`absent`；后端再次按闭集、原目标和 patch 验证。已开始的 OS 写入抛错、回读丢失、权限撤销或前台中断均保留 `unknown`，恢复只补交旧回执，不重放 OS 动作。

**并发边界：** EventKit/Expo 不提供原子 compare-and-write。上述机制是写前乐观快照复核和写后验证，不能消除最后一次读取与写入之间其他 App 编辑的极短竞争窗口，也不能声称 OS 原子 CAS。发现写后不一致仍标为结果待核对。完整安全原子更新需原生平台提供相应事务能力。

此次验证为 58 项后端专项和跨 Python→Node App 执行的合成链路、35 项 App 原生专项、全量 TypeScript 类型检查及所改文件 ESLint。覆盖 4 种修改/删除、另一 owner/任务/运行/授权版本、过期/伪造引用、取消/失联、SDK 缺字段与地理闹钟、写前外部改动、丢失回读与 journal 重启。全部使用临时数据库和合成 OS，没有修改真实手机记录；真机 EventKit 实例行为仍需单独验收。

## 手动提醒事项的 SDK 57 边界（2026-10-08）

`NativeCalendarPanel` 使用的 legacy iOS serializer 不返回 `allDay`，因此列表和编辑草稿保留 `null`，不会把午夜日期显示成已确认的具体提醒时间。新建支持未设日期或指定时间；全天创建在系统写入前拒绝并指向系统提醒事项。旧版本已经写入、尚未核对的请求仍可按原 marker 只读找回，字段缺失本身不会导致重复创建或误报保存失败；具体时间模式仍标为未知。

标题、备注、完成/重新打开操作不再把未改变的日期、全天类型、开始日期、循环规则或闹钟重新提交给系统。SDK 的保存函数只有收到日期参数才替换日期组件，因此这样保留既有全天属性。未知类型的日期修改以及移除已有日期由系统提醒事项完成，原生页保留编辑内容。已核对本地 `expo-calendar/ios/Conversions/Conversions.swift:183` 与 `CalendarModule.swift:226` 的行为。

对应 25 项手动日历/提醒与 SDK 真实响应形状测试通过，`tsc --noEmit` 与本次文件 ESLint 通过。仍未在实体 iPhone 上验收，不代表完整双向同步。

## 验证记录

- App：全量 `src/*.test.ts` 当前 428 项通过；全量 `tsc --noEmit` 和 `eslint src` 通过。此数量是本次并行开发快照。
- Native 专项覆盖：权限撤销、前台中断、scope/revision/过期、claim 并发、写入前持久失败、进程中断、回执丢失/错配、重启不重复写、真实 SDK 57 提醒字段形状、跨账户 HTTP 和 Agent、原子任务 owner、工具取消。
- 后端：原生专项、消息交接、life 工具、受固定版本约束的 Hermes 集成、mobile gateway、tenant worker 联合回归 103 项通过（其中原生专项及独立评审 34 项）。
- 日志：`/tmp/pajio-native-full-ts.log`、`/tmp/pajio-native-finish-type.log`、`/tmp/pajio-native-finish-lint.log`、`/tmp/pajio-native-finish-py.log`。测试只使用合成记录、临时数据库和 mock 系统模块，没有创建真实日历/提醒、读取真实位置或发送真实外部消息。

接口依据：[Expo SDK 57 Calendar legacy](https://docs.expo.dev/versions/v57.0.0/sdk/calendar-legacy/)、[Calendar](https://docs.expo.dev/versions/v57.0.0/sdk/calendar/)、[Location](https://docs.expo.dev/versions/v57.0.0/sdk/location/)，并核对已安装 SDK 57 的 iOS 序列化实现。
