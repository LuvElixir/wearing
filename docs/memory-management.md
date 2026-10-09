# 个人记忆管理

「关于你」对应当前身份的 `USER.md`，「长期记忆」对应 `MEMORY.md`。App 分页读取实际 Hermes MemoryStore 条目，不维护第二份服务器记忆。编辑通过 upstream `_mutate` 的文件锁、重读、外部漂移检查和原子写执行；每次操作验证整页条目的 SHA-256 revision，旧页面不能按过期 index 删除或覆盖新条目。

每页的「使用…」开关实际写入该身份 `config.yaml` 的 `memory.user_profile_enabled` 或 `memory.memory_enabled`。这是后续新任务内置记忆的读取/更新开关，内容文件不会被删除。暂停时用户仍可查看、删除或清空该页；恢复后后续任务重新使用。已有聊天中的内容、会话检索和其他文件不是这两个开关的清除范围，界面明确说明。运行中不允许修改记忆或其设置，避免已冻结的系统提示与配置不一致。

配置修改验证独立 `settings_revision`（当前配置原始字节哈希），复用 `.pajio-skills.lock` 对应的 OS 锁，与技能配置互斥，临时文件 0600、fsync 后原子替换。只改变选中的 bool，保留其他配置字段；错误配置和符号链接失败停止。受管 Hermes 使用自身 `hermes_yaml`，不依赖未安装的 PyYAML/filelock。原生端的设置 revision 为可选，以兼容旧版本的只读显示；旧引擎不显示可操作开关。

编辑草稿按服务地址、身份、目标页保存在手机 SQLite。切换页面、刷新或 409 不丢输入；409 读取最新版，草稿保留在编辑框中。重新应用只允许原始条目原文仍唯一存在时定位到最新 index；原始条目已经变化时，用户只能另存新条目或放弃草稿，不能猜测目标并覆盖其他记录。请求已保存但本机草稿清理失败时会分别说明服务器保存结果与本机状态。放弃草稿是明确按钮，关闭编辑页默认保留。

清空按钮显示「清空本页的关于你/长期记忆」，确认页列出当前身份、页和条数，使用当时 revision。它不会声称删除全部个人数据或对话。

验证：`tests/test_memory_controls.py` 使用临时身份目录与实际固定版本 MemoryStore/系统提示构建，验证暂停不删文件、不注入该页、拒绝内置记忆写、恢复以及限定页清空。`tests/test_engine_integration.py` 在临时账本启动真实受管引擎，验证带/不带连接器、记忆禁用等五种配置的 HTTP 修改与冲突；无模型调用、无用户数据写。`memory-drafts.test.ts` 覆盖冲突定位、重载保留、写入清理顺序与身份分离。

## 用户修改历史与撤销

每个身份的 Hermes HOME 内单独保存 `.pajio-memory-history/user.json` 与 `memory.json`，目录权限 0700、文件 0600。它们只保存用户通过本产品显式执行的新增、修改、删除和撤销，包含修改前后条目、SHA-256 revision、UTC 时间与 `source: user`；客户端传入的 `source` 不会改变来源。当前没有接管 Hermes 模型自动记忆工具，所以接口明确返回 `coverage: user_explicit`，App 应称为「你的修改记录」，不能显示为完整记忆审计。模型或其他受信来源后续写入造成 revision 变化时，旧撤销会失败，不会覆盖新内容。

每页最多保留 20 条最近记录，另有 2 MiB 字节上限；达到上限先移除最旧记录。普通删除仍能从这些记录中撤销。暂停使用保留内容与历史，暂停时不允许撤销恢复内容。**清空本页会同时删除该页修改历史、未完成的历史临时文件、上游已知的 `.bak.<时间戳>` 漂移副本，因此不可撤销。** 其他身份、另一页和聊天记录不在本次清空范围内；这不是磁盘取证意义上的安全擦除，也不代表删除另行配置的外部备份。

写入先取得本页历史锁，再调用原有 MemoryStore `_mutate`；在 upstream 文件锁内重新检查 revision、准备一条 pending 历史，再交由 upstream 原子写原记忆文件。只有 upstream 成功返回后才将历史标为 committed。中途断电或磁盘错误留下的 pending 不会被展示为成功记录，也不会允许撤销；接口的 `unconfirmed_changes` 提醒客户端重新核对当前内容，不自动重放。历史文件和重命名所在目录均 fsync。两份原记忆文件仍是唯一当前状态，没有第二套记忆引擎。

现有 `GET /api/memory`（引擎 `GET /v1/wearing/memory`）每个 `targets.user`、`targets.memory` 新增：

```json
{
  "history": {
    "coverage": "user_explicit",
    "limit": 20,
    "unconfirmed_changes": false,
    "items": [{
      "id": "32位不透明标识",
      "action": "replace",
      "source": "user",
      "created_at": "2026-10-10T00:00:00+00:00",
      "before": ["原条目"],
      "after": ["新条目"],
      "before_revision": "内容哈希",
      "after_revision": "内容哈希",
      "undoable": true
    }]
  }
}
```

`items` 最新在前。`undoable` 同时检查原修改已成功、尚未撤销、当前内容仍与该次修改后相同、该页已启用。前端不能自行根据日期判断能否撤销。撤销沿用现有 `PATCH /api/memory`，发送：

```json
{"target":"user","action":"undo","history_id":"记录标识","revision":"当前页 revision"}
```

服务器再次在 upstream 文件锁内检查当前 revision 与历史 after_revision，验证恢复内容及容量，成功后返回完整最新快照，并新增 `action: undo`、`undo_of: 原记录标识` 的用户修改记录。客户端应直接替换当前列表与 history；409 读取新快照，不重放旧操作。未知、跨身份、已清空、已撤销的记录同样返回 409。旧引擎缺少 history 时不展示撤销按钮。

新增验证包括：实际固定版本引擎 HTTP 修改 → 删除 → 撤销 → GET 读新版，第二次旧请求 409；独立身份 HOME 不能借用另一身份记录；模拟 upstream 锁内并发新写，撤销保留该写；清空仅删除选中页历史及副本；写入失败的 pending 不可撤销；有限历史与 symlink 防护。
