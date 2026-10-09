# 记录离线移除 / 恢复：App 与 ZCode 只读合同

日期：2026-10-08。覆盖现有 life 笔记、待办和日程；不适用于账户注销、日历系列删除或任务清单归档。

## 用户流程

1. 记录详情中的「移到最近删除」先说明范围并确认；已删除详情中的「恢复这条记录」明确发起恢复。断网也能把操作存到本机。
2. 本机写入成功后显示待同步状态。待移除记录仍留在原列表，待恢复记录仍留在最近删除，直到收到可核对回执。原件和未保存编辑继续保留。
3. 网络恢复沿用现有前台同步；记录详情也可「取回这次操作回执」。冷启动的 sending 状态可用原请求继续，不能创建新的恢复请求覆盖结果未知的旧操作。
4. 服务端 409 后显示已读的最新版本，让用户选择针对该版本再次移除/恢复，或保持当前状态。不会自动提高 revision 重试。
5. 如果正文编辑因为远端已删除而冲突，可以明确恢复当前墓碑。正文作为独立本机草稿留下；恢复只恢复服务端正文，不自动把旧编辑盖上去。恢复后仍需核对两份内容再保存。

## 持久队列与 API

复用 `clients/mobile/src/record-mutations.ts` 的 `record-mutations:v1:<scope>`，不增加第二条任务/记录队列。scope 是现有服务地址、账户/tenant 与身份组合。旧 schema 没有 action 的记录/attempt 保持 edit 语义；新 action 只有 `edit | archive | restore`。

归档/恢复 entry 与 attempt 的 patch 必须为空对象，base 必须分别为可用记录 / 墓碑。不能透过 `edit` 的 deleted_at 字段绕过正式 API；已存在其他待确认操作时不能再排入移除/恢复。每身份总上限仍为 100 条。

发送前原子保存冻结的 `action + base revision + patch + generation + request_key`，调用既有：

```http
PATCH /api/life/{life_record_id}
Content-Type: application/json

{"revision":2,"action":"restore","patch":{},"request_key":"persisted-uuid-request"}
```

没有新增服务端端点或数据库迁移。LifeBook 既有事务同时写 life 变更、清单索引与 `life_mutation_requests` 回执。重复同 key/spec 返回原回执；换 action/revision/patch 复用 key 为 409。旧回执重放不会重新改变当前记录，即使该记录后来又删除或恢复。

成功回执必须是同一 ID/kind、原 base revision + 1，且 archive 有合法 deleted_at、restore 无 deleted_at。未核实的成功响应、网络丢回执、本机回执提交失败都保留原 attempt；禁止根据 GET 推断该写入是否成功。已知的 409 才能在用户审阅后重新创建 attempt；原操作尚未尝试时也可先读最新版本并审阅。

回执与队列清理在同一 SQLite batch 提交。本机缓存按最高 revision 合并，所以旧恢复回执不会覆盖更新的墓碑，旧移除回执也不会覆盖后来的恢复；完成提示基于当前 canonical 状态，不依据旧 action 声称记录仍在旧状态。正文草稿始终独立于移除/恢复意图。

## 隔离与边界

- 延续服务端 life 数据的 tenant + identity 可见性；没有新造个人 owner 语义。
- UI 会话按 scope、record ID 与 credential ID 重挂载；切换身份后晚到回执只可归原 scope，不能更新新页面或继续发送后续条目。
- 账户删除复用通用 scope 存储清理与写入 fence。清理后晚到回执不能复活队列/cache；没有账户重新写入例外。
- 明确取消已知冲突仅移除队列意图，保留已存在的本机编辑草稿；未知结果没有取消重建入口。
- 重新整理原件仍要求在线，并且同一记录有任何未确认操作时暂不可执行。
- 本机数据仍受卸载/清除应用数据限制；前台队列同步不等同后台原生常驻执行。

## 根集成与 ZCode

`RecordDetail.tsx` 已直接改为上述操作；Mobile 原有 `RecordMutations.flush`、observe、snapshot、`mutationLabel` 自动适配 action，不需要新增根接线。父列表中若有待移除/恢复的待办，可以禁用完成复选框改善提示；模型已拒绝混入正文/完成变更，因此不会写错。

ZCode 只读本合同、`record-mutations.ts`、`RecordDetail.tsx`、`core.ts` 与服务端 `life.py` / `life_api.py`，据此实现 Web/Desktop 自己的持久存储；不得直接调用 action 后用成功 toast 代替回执恢复，也不得以新 key 自动重新发起未知恢复。不要改 App 源码。

## 合成验证

只使用新的 Memory store、临时 SQLite 和合成记录，无真实用户修改、原生 UI 点击或模型请求。

- 新 `clients/mobile/src/record-lifecycle.test.ts`：11 项，覆盖三类记录移除/恢复、重开/丢回执、旧回执与更新墓碑、409 显式 CAS、草稿/其他身份保留、正文冲突转恢复、未知正文不得替换、损坏队列、成功回执无效、本机事务失败、账户 fence 和冷启动 sending。
- 与既有 14 项 record-mutations、10 项 task-lists 合跑：35 项通过。
- 新 `tests/test_offline_record_lifecycle.py`：6 项（含三类参数），覆盖服务重启回放、更新墓碑、跨身份、action key 绑定、life/清单事务回滚及 HTTP 禁止 deleted_at patch；与 life、life_mutation_receipts、task_lists、capture 回归合跑 70 项通过。
- 全 App `tsc --noEmit` 与三个 App 文件 ESLint 通过。

最终候选包还需 root 统一验证真机断网 → 移除/恢复 → 杀进程重开 → 联网同步，以及另一端更新触发的原生冲突卡。这里的自动测试不替代设备验收。
