# App 文件分页与服务端查找 / 2026-10-08

App 文件夹使用新服务端分页接口。超过 200 份文件可以继续加载；文件名查询进入服务器当前身份的工作区及指定子目录，扫描超过旧版 2000 项限制时仍可继续，不再将前 200 份的本地筛选冒充全部搜索。

## 接口与语义

- `install_workspace_page_routes(app, store, runtime_for)`：新独立模块 `src/wearing/workspace_api.py`，返回 `WorkspacePager`，在主 App 生命周期退出时 close。旧 `/api/workspace` 与 list_files 保留兼容。
- `GET /api/workspace/page?directory=&query=&cursor=&limit=200`：每页最多 200 份文件。返回 `files,truncated,complete,scan_id,page_cursor,next_cursor,directory,query,scanned,phase`。`phase=checking/scanning` 都不代表搜索完毕。
- `GET /api/workspace/metadata?path=…`：直接读取选定路径的元数据，不再从前 200 项中寻找文件。后续预览/打开原件维持认证读取。
- 搜索仅比较文件名，大小写不敏感并兼容 NFC/NFD Unicode 名称，不读取文件内容。原有“按内容查找”入口明确交给 Agent 阅读。

## 分页边界

扫描使用保存进度的 scandir 游标，每次至多 2000 个扫描/复查步骤，正常本地磁盘约 120ms 时间预算（单次内核文件调用不能被此预算中断）。已扫描的目录在续页前按 inode/mtime/ctime 分批复查；变更返回 409，客户端清除失效列表并重新读取。它是观察到的目录列表，不声称原子文件系统快照。

游标是 256 位随机不透明引用，不包含路径、凭据或可修改偏移量。服务端绑定身份、配置工作区、根 inode、目录、查询和页大小；跨身份/工作区/查询无法复用。每次扫描保留最后两页用于网络重试，不会重复推进。扫描空闲 5 分钟、服务重启或容量淘汰后返回可恢复的 409。

最多保留 8 个扫描、总打开目录栈有界（最多 48 个 frame；scandir 会持有附加 fd），单栈最多 32 层，已观察目录最多 10000。超出明确要求缩小范围，不回报“查完且没有结果”。游标保存在当前进程；多 worker 部署需要路由黏着或未来改共享索引，当前 tenant 单 worker 可直接使用。

每一级目录经 dirfd + O_NOFOLLOW 打开，排除 symlink、FIFO、非普通文件；重新从根核对文件路径，避免跟随被替换的子目录。没有修改/执行文件操作。

## App 行为

`personal-hub.ts` 严格解析分页回执与请求参数、校验续页链和扫描 ID、合并真实结果；连接身份快照固定，凭据仅在 header。搜索 350ms 防抖；新查询、目录切换或卸载中止读取，迟到结果不能覆盖当前界面。未检索完会显示检查进度和“继续查找”，只有 complete 才能显示“没有找到”。

文件打开使用精确 metadata，支持分页后第 201 份及之后的文件，也支持导入后立即进入详情。超时、目录变更、游标过期均有重新读取入口。

## 验证与 QA

- `tests/test_workspace_pages.py` 9 项：457 份完整分页、2206 项搜索、不完整空页、目录范围/文件名匹配、同游标重试、身份/工作区绑定、目录变更、穿越/symlink/FIFO、过期/淘汰释放句柄、小预算复查恢复、真实 ASGI 请求。
- 连同旧 workspace 测试（排除调用真实本地 Hermes 的那项）、通知与 QA：46 项 Python 通过。
- `personal-hub.test.ts` 17 项，加通知 13 项，共 30 项 TS 通过；相关 lint、全 App tsc 通过。没有声称原生 UI 点击已全部验收。
- QA 已挂同组 workspace 路由、真实 IdentityExports 与 `UsageBook(root, enabled=False)`；服务端禁用真实外部调用。导出测试生成真实合成 ZIP、幂等返回同包、排除凭据；usage 返回真实 `not_enabled`，不伪造配额启用。
- 8891 保留 `/private/tmp/pajio-core-qa-jf1qwuko`，最新 PID **66072**。新增接口 live GET 全 200。原库 45 张表的全部旧行保留，integrity_check=ok；8765 PID 79991 未动。
- 备份 `before-workspace-1791393491.sqlite3`，逐行保留与 live 检查证据 `workspace-restart-acceptance.json`，均在上述 QA 临时目录。

SDK/控件依据：[Expo SDK 57](https://docs.expo.dev/versions/v57.0.0/)、[React Native TextInput](https://reactnative.dev/docs/textinput)。
