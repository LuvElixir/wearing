# 我的清单：App / 服务端 / ZCode 只读接入合同

日期：2026-10-08。依据 `docs/plans/life-tools-and-native-capture-2026-10-04.md` 的购物/行李/快速勾选及排序定义。

## 已实现范围

- 当前身份可建立空清单、改名、归档、恢复；添加事项、勾选完成/恢复、移动事项、上下调整顺序。
- 清单仍引用同一份 `life_records(kind=task)`。移动不复制任务，其他端打开相同 ID；完成与记录编辑复用已有 life API / App `RecordMutations` 离线队列。
- `task_lists` 仅保存名称与归档元数据，`task_list_members` 仅保存 record ID、所属 list ID 和 position。历史 `list_name` 在首次目录读取时补索引，不改原记录 ID、正文或 revision。旧客户端新增/更改 list_name、完成、归档记录均在同一事务更新索引与 board revision。
- 清单归档不会删除或完成其中的事项，也不隐瞒今天/全部待办里的未完成事项。可以从已归档清单移出事项；向归档清单添加/移入/排序须先恢复。改名同步更新所有记录的 list_name，包括已移除记录的墓碑，不恢复墓碑。
- 服务端目录完整返回最多 500 份清单。App 首屏显示 40 个清单选择项，继续按钮逐批显示；事项每页最多 100 条，继续加载直到最后一页，不再受旧界面 10 项预览限制。完成事项仍可见、可取消完成。

## HTTP

沿用主应用的身份/auth/CSRF 中间件；未新增公开服务、owner 头或跨身份查询。云端身份归属为原有 tenant Store + identity，不能把同一 tenant 内共享数据声称为用户私有。

- `GET /api/task-lists` → `{identity_id, revision, lists}`。
- `GET /api/task-lists/{list_id}/items?offset=0&limit=100[&revision=N]` → `{identity_id, revision, list, items, offset, next_offset}`。
- `POST /api/task-lists/change` → 保存一次操作或取回完全相同的历史回执。

清单元数据为 `{id, name, revision, archived_at, created_at, updated_at, total, open}`。items 是原有完整 life task（含原件/capture 信息），额外带 position。`list_<32hex>` 与 `life_<32hex>` 都是服务端生成的稳定 ID。

提交字段为闭集；action、revision、request_key 每次都必填。这里 **revision 是目录的 board revision，不是单份清单 revision**。

| action | 额外必填 | 可选 |
| --- | --- | --- |
| create | name | 无 |
| rename | list_id, name | 无 |
| archive / restore | list_id | 无 |
| add | list_id, title | content, timezone |
| move | list_id, record_id, record_revision, target_list_id | before_id |
| reorder | list_id, record_id, record_revision | before_id |

before_id 是目标清单里仍可见的参照事项；null 或省略表示移到最后。所有移动/排序同时核对事项 revision。名字 1–80 字符；title 1–200，content 最多 12,000；key 匹配 `[A-Za-z0-9_-]{16,120}`。归一化名称按 casefold 禁止重名，旧接口必须使用已有清单的准确名称。

回执为 `{identity_id, request_key, action, revision, lists, record, changed_records}`。lists 仅是受影响清单；add/move/reorder 含原事项回执，其余 record 为 null。board revision 严格大于提交基线，**不保证只加一**，因为同事务 life 变更也会递增。排序不改任务正文，因此单条 record revision 可以保持原值。

## 幂等、冲突和分页

- 每次显式操作先持久化 UUID key 和冻结 body。服务端 `BEGIN IMMEDIATE` 内核对 board CAS、修改原记录/清单/排序、写回执；任何一处失败全部回滚。
- 同身份同 key 同 body 永远取回原回执，即使清单后来又改名或被归档；改变 body 复用 key 返回 409。list add 使用独立派生的 life 创建 key，避免与旧 life_create 协议碰撞。
- 第二页起必须提供第一页 revision。清单、事项完成/正文/归档状态有变化会拒绝旧分页（409），客户端重新从第一页读取，不能把跨版本页拼接。
- App `task-list-request:<scope>` 保存 schema/request/phase，scope 包含 endpoint、云 user/tenant 和 identity。网络错误、5xx、无效成功回执与本机回执事务失败都保留 pending；只能“取回这次操作回执”，不能用新 key 替代未知请求。
- 400/404/409/413/422 表示明确拒绝；UI 先读取最新清单，再保留原输入并要求再次确认。不会自动推进 revision 再覆写。原目标已不可见时不把输入自动应用到别的清单。
- 校验通过后同一 SQLite batch 写 `task-list-last-receipt:<scope>`、原记录 receipt cache 并清 pending。跨屏实例共用 scope 队列。晚到回执只写原 scope；换身份后不更新新页面。
- 本机还有 RecordMutations 时，清单结构编辑暂不可提交，先同步或打开记录核对冲突。完成按钮沿用该队列，断网保留修改。清单本身不会假称离线完成服务端写入；冷启动离线可恢复未确认操作，需联网读取目录再做新的结构操作。

## App 集成

新增 `clients/mobile/src/TaskListsPanel.tsx`，使用现有 day/night AppTheme、native TextInput/Pressable，无新 native 依赖。父页面用已有任务页 ScrollView 包裹；不要再套内层垂直滚动容器。

```tsx
<TaskListsPanel connection={connection}
  onRecord={item => openExistingRecordDetail(item)}
  onChanged={() => refreshExistingLifeSnapshot()}
  onBack={() => returnToTasks()}/>
```

onRecord 必须打开现有 RecordDetail，以处理正文、完成状态和离线冲突。onChanged 只刷新已绑定身份的父数据，不把服务端写入等同于任务执行。事项管理中的 up/down 是稳定排序；尚未加载下一页时不允许把边界项错误地送到全列表末尾。

服务端 `install_task_list_routes(app, life)` 在已有 life routes 之后挂载。LifeBook 自动初始化索引。MCP 新增 `task_lists` 和 `task_list_change`，经 life_proxy 暴露；engine_runner 与真实发现测试使用同一两项名字。无模型测试调用。

## 数据生命周期

`records.json.task_lists` 导出 id/name/revision/archived_at/created_at/updated_at；`task_list_members` 仅导出同一身份清单与原记录双向可证实的 record_id/list_id/position。请求账本、指纹、board 内部计数不导出。遵循原导出整包 8 MiB / 50,000 行上限，超限报错而不是截断。

账户清除服务按专属 tenant 的实例、数据卷、索引和备份整体清除，不存在需要追加的逐表清除白名单；四张新表在同一个 tenant SQLite 文件内。共享 tenant 沿用 leave_shared，不按猜测的个人归属删表。App 的通用 scope 清理/写入 fence 已覆盖两个新存储键。

## 验证与尚需设备验收

- `tests/test_task_lists.py`：历史迁移、同 ID、归档/恢复/墓碑、移动排序、117 条分页、并发 CAS、原回执重放、账本失败事务回滚、错误排序参照完整回滚、身份隔离、字段/数量限制、MCP、HTTP。
- `clients/mobile/src/task-lists.test.ts`：10 项，回执/身份/字段校验、117 项拼页、冷启动未知结果、同请求重试、无效回执、明确拒绝、local commit 失败、双实例并发、已有离线编辑、账户 fence；与既有 record-mutations 合计 24 项通过。三份新 App 文件 ESLint 和全 App TypeScript 检查通过。
- `tests/test_task_list_data_lifecycle.py`：只用新临时 SQLite/合成目录，覆盖清单与重复日程导出、跨身份污染拒绝、内部请求排除、整包上限、专属账户新表清除及另一 owner 保留。
- 真实 engine 的工具发现测试只启动隔离临时 home，不向模型发送任务。App 按钮的候选二进制/真机实测由 root 统一验收，此合同不声称已做原生 UI 点击验收。

ZCode 可只读上述 App/backend 文件，据同一 API/CAS/回执语义实现 Web/Desktop，不修改 App 源码，不另建任务表或浏览器专属清单副本。

本轮冻结前最终合成回归（2026-10-08）：

```sh
.venv/bin/python -m pytest -q tests/test_task_lists.py tests/test_task_list_data_lifecycle.py tests/test_life.py tests/test_life_mutation_receipts.py tests/test_identity_export.py tests/test_identity_export_documents.py tests/test_capture.py tests/test_native_sync.py tests/test_engine_integration.py
# 126 passed in 11.51s
```

其中新增清单测试 17 项，新增导出/清除生命周期测试 3 项；最后一轮真实隔离引擎发现也通过，已将 task_lists、task_list_change、calendar_series 同时纳入真实工具集断言。未执行模型或真实服务数据动作。
