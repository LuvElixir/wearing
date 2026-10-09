# App 日历视图与来源筛选（2026-10-08）

## 当前可用流程

今天页保留图文简报、简报偏好与系统来源同步入口。独立 `CalendarPanel` 提供月、周、议程三种日程视图；只读取 canonical `kind=event` 记录，不把定时 Agent 任务混入日历。

- 月视图沿用现有月历，选日期后显示当天日程。
- 周视图固定星期一至星期日，包含没有安排的日期；前后翻页每次七天。
- 议程显示从所选日期开始的连续三十天，跳过没有安排的日期；前后翻页每次三十天，不产生间隙。
- 全天按 civil date 判断；普通日程按本机时区判断重叠。跨日安排在相关日期分别展示，但总日程数按记录 ID 去重。午夜结束的日程不再占用下一天。
- 日程排序为全天优先，再按实际时间先后。跨日卡片使用“此前开始 / 延续至次日 / 24:00”说明，避免把前一天开始时间冒充当天开始时间。
- 每次先渲染一百个日期条目，显式“继续查看”每次追加一百。卡片点开传递原记录对象，后续编辑仍由既有 revision / 离线队列处理。
- “补充日程”回调传递所选日期；“管理系统日历与同步来源”回到既有系统面板。这个版本没有引入新的原生依赖。

## 来源的事实依据与上限

`POST /api/native-sync/index` 使用空 JSON body；云端只能从可信 `pajio.storage_scope` 取得 owner，用户不能通过 body 指定 owner、安装或身份。它返回当前身份和账户的来源映射，不改变记录本来的身份可见范围。

响应包含 `checked_at`、`limit=1000`、`truncated` 与至多一千条 `records`。服务端 SQL 最多读取一千零一条，用第一个超限结果判断截断，不全量返回。按最近观察时间排序；每条仅含 canonical record ID、来源不透明 key、来源标题、来源类型和 synced / unseen / conflict 状态。安装 ID、原生外部 ID 与账户凭据不返回。

来源 key 由安装、来源类型与列表 ID 确定，同名列表不被错误合并。来源标题从显式选择的列表元数据写入新 `source_title` 列；旧数据库原地补列，旧映射未知标题只显示“系统日历 / 系统提醒事项”。不解析用户备注来猜来源。

“全部来源”显示全部现有日程；指定来源按服务端映射筛选；“其他记录”表示没有当前账户的来源标记，可能是手动添加、其他导入、其他账户共享的记录或截断之外的记录。界面明确显示一千条来源上限与缓存时间，不声称“其他记录”都是手工日程。筛选只影响当前视图，不改变同步开关或删除任何记录。

来源索引通过当前业务连接刷新，包含 Bearer / expected tenant / identity / CSRF 检查。前台返回刷新，后台取消请求，异步响应复核当前连接；迟到缓存不覆盖已开始的新读取。网络失败保留上次索引，显示来源待更新并可手动刷新。

## 本机隔离与集成

视图与来源选择分别保存在 `calendar-view:v1:${scope}`、`calendar-sources:v1:${scope}`。使用现有通用账户 scope / 删除围栏，不在账号之间借用缓存。索引解析拒绝超限、重复记录 ID、未知类型和损坏字段。缺失的旧来源筛选保持“上次选择的来源”，由用户主动切换到全部。

集成接口：

```tsx
<CalendarPanel
  connection={connection}
  records={records}
  selected={selectedCalendarDate}
  today={todayCalendarDate}
  isCurrent={() => current.current === connection}
  onSelect={setSelectedCalendarDate}
  onRecord={editRecord}
  onCreate={day => createEventAt(localDateTime(day, 9))}
  onNative={openNativeCalendar}
/>
```

`selected`、`today` 为 `CalendarDate | null`；其他回调分别接收 `CalendarDate`、`RecordItem`。父组件必须在注销或切换账户时卸载当前业务面板，并让 `isCurrent` 立即核对 current ref。根组件接线由 root 完成，独立模块不修改 Mobile 或 PersonalHub。

## 验证与剩余范围

本地合成测试：日历基础、视图与来源、原生同步共 33 项通过；后端同步和来源索引 18 项通过。覆盖跨年、闰日、夏令时 civil 翻页、跨午夜、本机时区、同名不同来源、精确来源映射、截断提示数据、旧数据库补列、云端 owner / 伪造字段、账号缓存围栏与分页条目计数。TypeScript 与本次文件 ESLint 通过。

尚未声称真机视觉和辅助功能验收。系统重复日程已有逐实例同步；Pajio 自有重复日程已由独立系列模型接入，例外与“仅本次 / 整个系列”编辑见 `calendar-series-contract.md`；派生实例只合并显示，不写入普通 life 记录。前台系统同步范围、编辑回读、权限与实体设备验收见 `native-sync-contract.md`。
