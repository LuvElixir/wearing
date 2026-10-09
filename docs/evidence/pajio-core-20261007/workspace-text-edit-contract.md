# 文件夹文档直接编辑与恢复

2026-10-08。供 ZCode 只读 App / 后端代码，对齐 Web、Desktop 文件编辑。实现为 `src/wearing/workspace_text.py`、`clients/mobile/src/workspace-text.ts`、`WorkspaceTextEditor.tsx`；`PersonalHub.tsx` 仅在文件阅读段增加入口和连接参数。旧文件列表、分页、搜索、导入、分享接口不变。

## 范围与产品入口

App 路径：记忆 → 文件夹 → 选择文件 → 编辑文档。支持 UTF-8、最多 64 KiB 的 `.md`、`.markdown`、`.txt`；保留空文档、首尾空白及换行。JSON、HTML、脚本、二进制、非 UTF-8 和超限文件沿用原来的阅读/原件分享方式。

隐藏路径、技能/配置/凭据/运行目录、`SOUL.md`、`AGENTS.md`、`SKILL.md`、`USER.md`、`MEMORY.md` 等引擎文件，以及私钥内容均不开放。逐级拒绝符号链接；拒绝硬链接、FIFO 等特殊文件。这里是用户文件空间文档编辑，不是引擎记忆配置编辑；“关于你 / 长期记忆”继续使用已有记忆修改接口。

导入目录 `imports/` 的文件是校验原件，永不就地覆盖。用户点“确认另存可编辑副本”后保存到 `documents/<request_key>/<原文件名>`，回执提供“打开已保存的副本”；以后编辑该副本才直接写回。原导入路径、inode、字节、SHA 和上传重放契约保持不变。

## 挂载与接口

在 `app.py` 的 workspace import/page 挂载附近追加：

```python
from .workspace_text import install_workspace_text_routes
install_workspace_text_routes(app, store, runtime_for)
```

父任务负责挂载，本模块不改 `app.py`。接口全部使用中间件认证得到的 `request.state.identity_id`；客户端请求体不接受 owner / identity。写接口沿用 CSRF / Origin / 账户边界。

### 读取

`GET /api/workspace/text?path=<相对路径>` 返回：

```text
identity_id, path, text, size, sha256, revision, modified,
save_mode: copy|replace, editable, blocked_reason,
history: [{id, created_at}]  // 最近 20 个已完成保存之前的恢复版本
```

读取最多 64 KiB + 1 字节，核对读取前后文件元数据。`revision` 是文件设备/inode/大小/纳秒修改时间/状态变化时间及 SHA-256 的摘要，不能用界面显示的修改日期替代。`sha256` 校验准确 UTF-8 字节。App 同时校验身份、路径、长度和 SHA。

读取不会启动模型、改动文档或创建恢复版本。若当前身份存在 starting/running/waiting_for_approval/stopping/connection_lost/ambiguous 任务，仍可读，`editable:false` 并显示原因。

### 保存

`POST /api/workspace/text`：

```json
{
  "path": "notes/项目记录.md",
  "text": "核对后的完整文字",
  "base_revision": "读取到的64位revision",
  "base_sha256": "读取到的64位sha256",
  "request_key": "保存前持久化的16至80位编号"
}
```

成功回执：`identity_id, source_path, path, request_key, recovery_id, sha256, revision, size, modified, saved_at, save_mode`。其中 path 为实际保存的文档路径，copy 模式不同于 source_path。App 验证 key、身份、预期路径、摘要和字节数，禁止把任意 200 当成成功。

- 同身份同 key 相同完整请求返回永久原回执；不同内容复用 key 返回 409。
- revision 或 SHA 已变化返回 409，保留用户草稿，不覆盖文档。
- 当前身份有 active task 返回 423，保留草稿，完成或停止后显式重试。
- 读取/保存的范围、编码、大小不合规时拒绝；错误不返回底层绝对路径。
- 服务写入和任务 `reserve_start` 持有同一个 SQLite 写锁。文档最终复核及原子发布期间，任务启动等待锁释放。

## 持久恢复与未知回执

新增 SQLite 表 `workspace_text_versions`，按 `(identity_id,request_key)` 保存请求摘要、来源/目标路径、base revision、修改前完整字节、拟保存完整字节及最终回执。修改前恢复副本在独立事务提交后，才允许更改文件。它属于服务私有数据库，不进入工作区列表，不发给模型。

发布过程使用同目录 0600 临时文件、fsync、逐级目录描述符和最终版本复核。普通文档通过 `os.replace` 原子替换；另存副本通过不覆盖已有目标的 link 发布完整字节。目录发生替换或路径变为链接时拒绝。恢复副本不会因文件写回或回执提交失败而丢失。

如果文件原子发布完成后数据库回执提交失败，同 key 重试只在当前文件与拟保存字节完全一致时补齐回执，不再次写文件。若有后来修改，返回冲突；不能用旧请求覆盖后来修改。成功回执是该次保存的历史事实；App 读最新文档时如发现再次变化，会说明并显示最新内容。

`GET /api/workspace/text/recovery?path=<目标文档>&version=<recovery_id>` 返回当前身份、确切文档的 `{identity_id,path,id,created_at,text,sha256,size}`。只有已完成保存的恢复版本可读取。点击“把此版本放进草稿”只改本机草稿，仍需用户再次确认保存并通过当前文件 revision 检查，才会真正恢复。

这里保护的是经过同一服务的任务与编辑流程。独立命令行进程或外部编辑器不共享数据库锁；系统在替换前再次核对文件版本，但不能把这个实现宣称为对任意外部写进程的全局文件事务。外部批量修改应暂停后再编辑。

## App 草稿、冲突与身份切换

本机 SQLite 键：`workspace-text-draft:${scopeOf(connection)}|${encodeURIComponent(path)}`。保存 base 快照、当前文字和可选 pending 完整请求。每次输入串行落盘；提交先等待之前输入写入，再持久化完整请求后发 HTTP。写盘失败不发送，状态明确显示尚未保存。已确认另存的副本不会因收起编辑再次自动成为待提交草稿。

未知回执先“取回上次保存回执”，请求正文与 key 保持不变；HTTP 409 后“读取最新版并比较”，同时展示最新版全文与用户草稿，标明首次差异行。只有用户点击“按最新版继续编辑，保留我的文字”才更新 base 并保留草稿全文，之后再次点击确认保存。不会自动合并、自动覆盖或默默采用对方版本。

页面按 endpoint / identity / credential / path 隔离，旧页面晚到结果不更新新页面。草稿键符合现有通用账户清理与写入 fence，测试确认注销清理会选中这个键；恢复服务内容仍遵循部署层完整账户数据销毁流程。

## ZCode 对齐要求

只读本轮 App / backend，Web 和 Desktop 自行实现同一入口、字段、copy 模式、恢复预览与确认保存。使用原生/网页纯文本编辑器，不执行 Markdown 中的指令、脚本或 HTML。不要开放 JSON / 配置编辑，不要覆盖 imports 原件，不以文件列表中的 mtime 或 SHA 单字段代替完整 CAS。

接口没有新增费用、供应商调用或原生依赖。Expo 版本仍为 [SDK 57](https://docs.expo.dev/versions/v57.0.0/)，使用现有 Crypto、SQLite、TextInput 和主题组件。

## 验证

- Python `test_workspace_text.py`、`test_workspace_pages.py`、`test_workspace_upload.py`：77 passed。覆盖并发 CAS、身份、CSRF、任务写锁、先备份后发布、丢回执恢复、外部更新冲突、原件上传重放不变、路径/链接/类型/编码/大小边界。
- App `workspace-text.test.ts`、`personal-hub.test.ts`、`workspace-export.test.ts`：34 passed。覆盖草稿顺序落盘、重启、未知回执、回执清理失败、409 比较后重存、copy 路径、哈希与账户清理。
- App 全量 TypeScript 检查和本轮四个文件 ESLint 通过。

所有文件测试使用新临时目录、合成文字或 mock 回执；未读取、编辑真实用户文档，没有执行模型。原生界面/键盘/长文编辑与签名真机验收由主任务统一完成。
