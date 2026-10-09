# Pajio 自有重复日程（2026-10-08）

## 产品范围

根据 `PRODUCT.md` 的自有日历定位，重复安排直接保存在当前身份，无需外部日历账号。系列、单次例外和查询展开分开保存；没有把重复日程批量复制为普通 `life_records`，也不把 Agent 的定时执行任务当作日程。

App 日历的“重复日程与系列”可创建、查看已有及已移除系列。日历或今天页点某次实例后，先从服务器读取最新系列与该实例，再选择“仅这一次”或“整个系列”。只有首次创建成功才切换到已创建的 series ID 页面。已有系列保存后重新回读；回读失败明确说明修改已保存，同时禁用继续编辑，保留重新读取入口。

支持每天、每周、每月、每年，间隔 1–365 个单位；每周可选星期，空选沿用首次日期的星期。终止方式为持续、最多 1000 次或包含当天的最后开始日期。首次日期须属于指定星期；次数与截止日不能同时设置。

- 日期范围 1970–2100 年；“持续”仍受日期范围约束。
- 普通日程保存 IANA 时区和本地墙钟时间，按该时区展开。月末无此日期、非闰年的 2 月 29 日、因夏令时不存在的时间跳过，不消耗 COUNT；回拨的重复时间取第一次（fold 0）。
- 全天日程保留 civil date，结束日不包含在内，不因查看设备时区改变日期。单次日程最长 31 天。
- 一个身份最多 200 个活动系列，一个系列最多 200 个例外。系列列表每页 50 个，显式继续加载。查询窗口为 1–366 天，至多 1000 个实例，超限返回 `truncated=true`；不保证截断结果是全局最近的一千条。
- 当前是日程安排和管理能力；不会自动启用通知、系统日历写入或 Agent 定时任务。没有“此后所有日程”的拆系列操作。

## 系列、例外与版本

`calendar_series` 保存一份规则与模板，`calendar_exceptions` 以原定日期定位单次变更。实例 ID 为 `recurrence_<series uuid>_<original YYYYMMDD>`，单次移动到其他日期后仍是同一个实例。查询会补入从原始窗口之外移入的例外，并按新的日期显示。

“仅这一次”保存完整替换模板；“取消这一次”隐藏该实例；“恢复这次原规则”删除例外，回到当前系列规则。修改整个系列保留已存在的例外内容；若新规则不再包含例外的原定日期，事务拒绝并提示先恢复例外，不静默丢弃或重新归属。移除整个系列保留规则与例外，可从已移除列表恢复。

每次修改均提交全局系列 revision CAS。另一次 App 或 Agent 已修改时返回 409，旧输入保持在本机。App 明确让用户读取最新版本、保留输入并重新核对，之后才使用当前版本保存。恢复本机草稿时比较 `baseRevision`，不自动把旧草稿套到新版本。

request key 与完整请求 hash 在同一 SQLite 写事务保存回执；同编号同内容即使重启仍返回原回执，编号换内容拒绝。App 先持久化精确请求再发 HTTP，失败或结果未知沿用原请求。成功后先清除对应输入草稿，再清请求 journal，避免服务器保存完成后 App 崩溃把旧草稿重新提交为新系列。若本机清草稿失败，原请求 journal 仍在，可恢复核对。该保护不依赖网络正好返回一次。

## 读取与账户边界

系列与普通 life 记录一样采用 identity 可见范围，未宣称共享身份中的日程为个人账户私密。HTTP 从可信中间件的 `request.state.identity_id` 取身份，body 禁止伪造 identity；Agent 从现有受限 life MCP 获取身份。不存在临时借用当前手机账号的逻辑。

App HTTP 使用当前 Bearer、expected tenant、identity、bootstrap CSRF，禁用重定向。读取前、响应 JSON 后、持久化前复核当前连接、注销围栏和 AbortSignal。组件以完整账户 scope、credential ID、系列及实例 key 重挂；StrictMode 每轮 effect 拥有自己的取消控制器。查阅窗口与账号改变时，render 只允许匹配完整 scope / credential / 日期窗口 / 时区的 snapshot 输出，旧范围不会暂时混入新范围。

`useCalendarSeries` 在前台进入、返回前台、手动刷新和成功修改后查询。后台或账户冻结即停止请求。每账户只保留 today 与 calendar 两个范围快照，缓存不是普通 life 记录，离线显示读取时间与陈旧状态，不宣称当前视图包含全部安排。

本机键：

- `calendar-series:v1:${scope}:today|calendar`
- `calendar-series-draft:v1:${scope}:${series|new}:${occurrence|series}`
- `calendar-series-pending:v1:${scope}:${series|new}`

均受现有精确账号清理和删除围栏覆盖；另一个账户的数据不受影响。备注、标题按数据处理，不扩大工具授权。

## 接口与集成

后端：

```python
from .calendar_series import CalendarSeriesBook
from .calendar_series_api import install_calendar_series_routes
install_calendar_series_routes(app, CalendarSeriesBook(store))
```

`POST /api/calendar-series` 接受严格 `SeriesCommand`，动作包括 `list / get / query / create / update / override / cancel / reset / archive / restore`。每个动作只接受相应字段。query 明确提供 start / end / timezone；get 可带 occurrence_key，返回当前 `selected` 实例或 null。MCP 工具名 `calendar_series` 使用同一解析与执行函数，已接入 life_proxy 与引擎工具集合。

App：`CalendarSeriesPanel`、`CalendarSeriesStatus`、`useCalendarSeries`，CalendarPanel 保留来源筛选与原生同步入口并新增 onSeriesCreate。root 已在独立路由集成 App：查询结果仅合并展示，不能写入现有 canonical life 离线缓存；派生实例用 `isSeriesOccurrence` 转入系列面板，不交给普通记录修改。

数据库新增表：`calendar_series`、`calendar_exceptions`、`calendar_series_requests`。身份导出包含前两张表的真实产品字段，不导出内部幂等请求表。个人专属 tenant 的整体实例/卷清除覆盖三表；共享 tenant 的注销仍遵守登记完整性和等待规则，不按 identity 误删共享内容。生命周期测试由 `test_task_list_data_lifecycle.py` 联合覆盖。

## 验证与边界

本地合成验证：重复日程后端 18 项、真实 life MCP dispatch 1 项；原生来源接口 18 项、数据生命周期 3 项合计 40 项通过。App 重复日程模型/请求/持久化 12 项，结合基础日历/视图/原生同步共 45 项。TypeScript 与本次文件 ESLint 已通过。

覆盖月末、闰年、DST 跳过与重复时刻、跨时区/跨日/结束排除、移入远处窗口、单次取消恢复、保留例外、规则遗漏拒绝、CAS、并发创建、回执重放、存储失败、账号冻结/迟到响应、损坏数据和导出/注销范围。

尚未声称实体设备交互与辅助功能验收，也未读取真实日历、发系统通知或修改外部账户。App 字段使用明确日期/时区输入，本次没有新增原生依赖。系统来源单向同步与 OS 编辑回读见 `native-sync-contract.md`，不与自有系列自动双向合并。

## 原生日期输入补齐（2026-10-08）

`CalendarSeriesPanel` 的开始、结束和重复截止日期改用现有 SDK 57 / DateTimePicker 9.1 系统选择器，iOS 滚轮与 Android 系统对话框；无需新增原生依赖。普通流程显示中文日期和 24 小时时间，不再要求输入 ISO 时间。时区默认本机，修改入口折叠到“时区设置”，支持一键采用本机时区。

系列保存的是当地日期/钟点；`SeriesDateField` 用 UTC 作为选择器的中性显示坐标，不把字段转换为 UTC 执行时间，真实 IANA 时区仍保留在原模板中。修改时区保留已选当地钟点；原后端仍校验 DST 和规则边界。未完成草稿中有无效日期时选择器使用安全初始值，只有用户明确选择后才更新字段。

全天结束输入显示“最后一天”并包含当天，保存时转换回后端的结束不含当日约定。普通单日 09:00–10:00 转全天只占一天；午夜结束不多加一天；改回具体时间默认为首日 09:00 至最后一日 10:00，可继续修改。单次/整个系列 CAS、最新实例投影、提醒入口与草稿恢复均保持原调用链。

4 项新增输入语义回归，与系列及月/周/议程共 35 项通过；全 App TypeScript 和本次文件 ESLint 通过。系统选择器真实候选包交互仍由主线程验收，本次未读取或写入真实系统日历。
