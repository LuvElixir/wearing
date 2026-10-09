# 记忆移除与遗忘范围审计（2026-10-08）

本次只读检查产品源码和 pinned Hermes 源码；证明使用全新临时 Home 和合成标记，没有读取真实个人记忆正文或调用模型。仅跨账户检索 P0 随后获得 root 授权实现，见 `session-recall-owner-contract.md`。下文遗忘动作仍为建议，未实现。

## 现状和原始承诺

- `PRODUCT.md`“个人记忆与检索”、`docs/personal-memory.md` 定义：Hermes native memory + session_search；完整遗忘尚未实现，不另造向量库。`src/wearing/identity.md` 也明确移除个人记忆不等于删掉全部历史。
- `memory_controls.mutate_memory` 仅 CAS 修改当前身份的 `USER.md` 或 `MEMORY.md` 条目；`set_memory_enabled` 仅改变内建记忆的后续读取/写入标志。两者都没有会话抑制、来源标签或遗忘 journal。
- `MemoryEditor` 已显示“本页只管理当前身份条目；聊天、其他记忆页、文件和已完成任务保留”，清空确认也只承诺本页。这些界限应保留。
- `/api/memory` 由 app token 与 identity 路由保护，转交该 identity 的 Hermes client。并非 owner 私有存储；所有获准访问此身份的账户按既有共享语义管理同一记忆页。没有独立 memory admin/条目作者权限。
- `engine_runner` 写入期间禁止活跃 run；Hermes `MemoryStore._mutate` 原子写文件，已有实例的 frozen system-prompt snapshot 不被重写。后续 fresh store 不再载入移除条目。
- 当前聊天仍续接 owner 的 session。Hermes `api_server_runs` 会从 `state.db` 加载原消息；memory 工具、会话历史与压缩摘要是不同来源。暂停两页 memory 也保留 session_search。

## 实际存储路径

每个 identity 独立 Hermes Home，由 `HermesRuntime.home` 决定；默认身份为 `<data_dir>/hermes`，其他为 `<data_dir>/identities/<identity>/hermes`。

- `memories/USER.md`、`MEMORY.md`：原生当前记忆。
- `state.db` 的 sessions/messages、原生 FTS5/trigram/CJK 索引：历史检索和续接上下文；压缩归档消息仍可检索。
- `sessions/<session>.jsonl` 与内建 DB 修复/备份路径可能保存转录副本。原生 memory 外部漂移检测还可能产生 `.bak.<timestamp>`。本次仅核对代码，不检查真实文件是否存在。
- Pajio `wearing.sqlite3` 的 tasks/messages/events、目标/安排上下文、已生成产物及用户文档是另外的内容来源；当前移除不会删除这些数据。
- 当前 owner 的续接映射在 `owner_conversations`，入场证明在 `task_conversation_sessions`。旧聊天记录和这些执行证明不宜因移除一条 memory 而随意删除。

合成证明：移除 USER 条目后，新 store 内容为空，但先前冻结快照仍包含标记，历史消息未变；原生未加 guard 的 search/read/scroll/browse 均能取回标记。P0 修复现在阻止外部 owner 检索，自己的历史继续可用，故仍不等于遗忘。

## 推荐最小产品动作（待批准）

1. 保留“删除这条记忆 / 清空本页”，明确只是当前记忆。不要改成“彻底忘记”。
2. 增加独立“以后不再引用这段对话”，在用户自己的历史会话入口展示具体范围、identity、会话时间及是否结束当前上下文。按来源整个 session/压缩后继抑制，原历史仍能由用户查看。不能从一段文字推定所有语义同义副本。
3. 对当前正在续接的被排除 session，先停止/等待运行结束，再切换新的 owner conversation generation；禁止旧 run、延迟工具结果或失效恢复任务重新接上旧上下文。暂停或失败时显示“尚未完成”，不得提前显示“已忘记”。
4. 显式选择要移除的共享记忆条目；现有 memory 条目没有 provenance，不能假定某条来自某 owner/某 session。无法判断时提示逐项核对，或仅在用户明确确认后清空所选共享页。不能替其他 owner 清页。
5. 对保留的文件、生活记录、云应用和用户再次主动提供的信息，诚实说明它们仍可被使用。删除文件/历史/备份和账户删除是另外的用户动作。

## 后台可验证机制及拟修改面

- 新增 `memory_forgetting.py/_api.py`：owner+identity 的有界排除账本、generation、request ID 幂等与 CAS；只保存来源 ID/范围/状态，不把被遗忘正文再复制成日志。预览与提交共享同一个 revision，执行人来自可信 ASGI scope。
- `store.py` / `service.py`：owner conversation generation、入场冻结、取消和旧回执 fence。不得只改当前 session_id 而丢弃压缩祖先约束。
- `session_recall_guard.py`：所有四种检索模式都减去同 owner 的排除来源及其后继，直接 ID/scroll 也不能绕过；重启恢复相同范围。
- `engine_runner.py` / `hermes.py`：可信 epoch/结束旧上下文的接线；内建记忆写入 provenance 需要另外的可信源记账，模型口述来源不算证明。当前 memory 编辑沿用 `memory_controls.py` 的 CAS/锁，不绕过原生写入协议。
- `MemoryEditor.tsx`、独立历史范围面板/客户端 model，以及 root 的 Mobile 路由：预览、明确确认、处理中/失败/已完成真实回执；保留现有用户草稿。Web/Desktop 仅给 ZCode 只读合同。
- 若要扩展到任务/目标/简报/文档“停止作为 Agent 来源”，必须逐一接 `life.context`、`goals.context`、`schedules.context`、artifact/file 读取边界，并新增来源证明；在这之前 UI 范围只称“选定会话”。
- `identity_export.py` / account deletion 生命周期：只导出用户可解释的来源控制设置，内部幂等/执行凭据不导出；专属 tenant 清除覆盖账本，共享 tenant 不据身份猜 owner。

验收至少使用两 owner、两 identity 和合成 sentinel：选定来源的搜索/直读/scroll/browse/压缩后继全拒绝；自己其他来源仍可用；他人记录不变；任务正在运行、停止未知、重启、旧回执、相同 request 重试不复活；移除 memory 后已明确保留的来源不能被误报为已经抹除。不能用模型一句“我忘了”作为验收。
