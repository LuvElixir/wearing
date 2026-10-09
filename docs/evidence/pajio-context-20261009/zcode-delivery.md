# ZCode Web/Desktop 交付 — 选定聊天导入（2026-10-09）

分工：ZCode 负责 Web/桌面；App 与 Python 后端只读未改（Codex 冻结，720 App 测试＋3 分享插件＋199 后端回归由 Codex 侧通过；iOS 原生验收 root 进行中）。独立合成 QA `http://127.0.0.1:8892/`（identity qa，Codex 启动；合成 ZIP `/qa-fixture/chat.zip`）。生产 8765、真实微信资料、其他真实账号全程未触碰；未部署、未 Git push；未写 Codex memory。

## 已实现

- **`src/wearing/web/chat-import.js` v6（Web 源码冻结点）**（window.WearingChatImport）：
  - **严格解析器移植**（自 chat-import-parser.ts，逐行对齐）：仅 ZIP / UTF-8 TXT；BOM/LF/CRLF；非法编码、未知格式、无效日期、路径穿越/链接/嵌套压缩、重名与 Unicode 别名、加密/ZIP64/未知压缩、目录-本地头不一致、越界区块、CRC 不符全部拒绝；1 KiB 块间让出线程；上限 15 MiB 文件 / 384 KiB 聊天文字 / 16 KiB 单消息 / 500 消息 / 50 作者 / 500 项 / 30 MiB 展开 / 倍率 200 / 512 KiB 请求。ZIP 优先唯一 `聊天记录.txt`，否则唯一 TXT，多候选不自动选。**附件仅声明未导入，不解压、不上传、不猜归属。**
  - **本机预览**：消息 20 条一组展开、作者单选「哪一位是你」（默认不指定）、时间范围照原文件（不推时区）、附件名/数量列为未导入、重复导入警告（列表 source_sha256 比对）；**预览阶段零网络请求**（QA 实证）。
  - **幂等确认**：pending journal（`chat-import-pending:v1:<identity>`，`{identity,pending:{key,request}}`）先持久成功才 POST；重试先 GET `/api/chat-imports/receipts/{key}`，404 才补交原请求；回执严格校验（schema/identity/request_key/import_id/status/created_at）；`deleted` 回执不重发；未知结果保留同请求键；无状态错误不泄漏原始传输文案（统一「操作结果尚未确认」）。
  - **批次详情/删除**：列表分页（20/页，游标）；详情逐消息展示来源编号（message-N）；删除两步确认＋范围说明（来源正文与检索索引移除；已生成回答、另存记忆、已下载文件不自动清除）；409 活动任务如实提示。
  - **P2×2 修复（第二批复核）**：pick 在 arrayBuffer/SHA-256 前先查 `File.size`（伪造 2 GB File 零读取即拒）；journal 删除可验证（scoped-store.remove 改返回布尔；**remove===true 为删除成功的必要条件**，读回仅附加核验——localStorage 整体被拒（remove/get 同抛 SecurityError）时不再误报已移除），discard 失败如实提示、预览保留、重开一致出现，不谎称已移除。
  - **接线三修（第二批复核）**：文件面板「导入选定聊天」按钮曾嵌套在「导入文件」按钮内（无效 HTML）→ 独立兄弟按钮；面板右上关闭按钮曾无事件处理器 → 已接线（点击/Esc/cancel 全路径）；入口交接同时关闭设置与文件两个父面板。
  - **生命周期（独立复核 P1×2 修复后）**：epoch+generation 会话围栏与 load/op 独立票据；**每个异步边界（文件读取/digest/解析/GET 回执/POST/清 journal/DELETE）之后、任何存储或网络写之前都复核围栏**；关闭面板/注销冻结/换身份立即作废在途 operation 票据并释放 busy；注销冻结（workAllowed/registerWorkGate）期间不写 journal、不发请求；身份切换 reset；journal 按账户+身份隔离（WearingStore）。
  - **入口与交接**：设置「导入选定聊天」＋文件面板「导入选定聊天」（聊天附件入口的 Web 对应）；进入即关父设置面板（无双模态叠加）。跨对象搜索 `kind=chat_import` 标签「聊天来源」并深链到批次详情（不当任务跳转）；默认 kind=all 兼容旧三类。
- **`src/wearing/web/vendor/fflate/`**：fflate **0.8.3** UMD 本地固定版本副本（33 KB）＋MIT LICENSE＋README——与 App 依赖同版本，无 CDN 运行时。
- **`account-deletion.js` v8**：clearAccountCaches 补 `chat-import-draft:v1`/`chat-import-pending:v1`（账户隔离清理，他账保留）。
- **`app.js` v52**（switchIdentity 增加 `WearingChatImport?.reset()`）、**`views.js` v16**（搜索 chat_import 分支）、**`index.html`**（面板/双入口/vendor 脚本/chat-import.js?v=2）、**`pajio.css` v19**（门控 ci-* 样式）。

## 独立复核修复记录

第一批（P1×2，行为复现）： chat-import.js＋app.js api＋scoped-store＋fflate 在 Node VM 行为复现两个 P1（复核人只读未改）：

1. **P1-1（pick 存储写越权）**：ZIP 最后一次 yield 后无 active 复检，pick 在解析完成后直接 retain——读取途中切账号/身份/reset 会把旧聊天写入新身份的 `chat-import-draft:v1:other` 并出现在 ui.draft。修复：readEntry 循环后复检 active；pick 在 arrayBuffer/digest/parse 每个边界后、retain（存储写）前复检围栏，失效即中止且不落任何 journal。
2. **P1-2（confirm 网络写越权）**：GET 回执挂起期间关面板或注销冻结，GET 返回 404 后仍 POST 并清 journal（current 只守显示）。修复：confirm 在 GET 前、GET 后、POST 后清 journal 前逐点复核围栏；close() 与面板 close 事件作废 opTicket/loadTicket 并释放 busy（未知提交保留同请求键，重开续查）；clearMissing/removeBatch 同样在网络与存储写前复检。

第二批（P2×2＋接线，行为复现）：3. pick 缺 File.size 预检；4. discard 无视 remove 失败＋scoped-store.remove 吞异常；5. 入口按钮嵌套、关闭按钮未接线、未关文件父面板。

第三批（P2 删除边界，真实 scoped-store 复现）：6. localStorage 整体被拒（remove/get 同抛 SecurityError）时 writeJournal(null) 仅看读回仍误报已移除——**修复：remove===true 为删除成功必要条件，读回仅附加核验**，并补「存储整体被拒」回归。测试挂起 Promise 按实际请求 URL 匹配的多路释放列表。

第四批（root 桌面闭环后的两个显示收尾）：7. `#ci-body` 无内边距——正文/按钮贴左缘、长详情被圆角切边 → 补 `padding:6px 22px 16px`＋`overflow-y:auto`（pajio.css v20，与 header 22px 对齐，仅此面板）；8. 列表裸显 ISO 时间戳 → 「导入于 2026/10/9 13:23」本地可读格式（**消息原时间仍按原文件展示、不推时区**）。

## 已运行验证

**测试**：`node --test --test-timeout=15000 tests/*-ui.test.cjs tests/web-core-closure.test.cjs tests/web-import-goal.test.cjs` → **225/225**（保留既有 200 项基线＋chat-import-ui 25 项（含存储整体被拒不误报、导入时间本地可读不裸 ISO 的回归）（含 P2-1 超大 File 零读取即拒、P2-2 删除失败不谎称、关闭按钮接线、双入口交接、无嵌套按钮渲染审计）：编译门/接线（本地 fflate 无 CDN、无远控字面）/真实 fixture ZIP 解析（附件声明未导入）/TXT＋五种拒绝 fixture（nested/path-traversal/ambiguous/bad-date/case-alias）＋非法 UTF-8＋未知扩展/预览零网络/先持久后 POST＋回执校验/未知结果保留同键且重试先查回执不重发/deleted 不重发/重复警告＋删除两步＋409/身份切换围栏/注销冻结/P1-1×2（切身份不写他账 journal、解析末次 yield 复检）/P1-2×2（关闭/冻结期间 GET 返回后不 POST 不清 journal）/设置交接/身份隔离）。

**QA 8892 浏览器真实点击**（仅自建合成批次，结束后全部删除，服务端 remaining 0）：

- 选择→**预览零 POST**（fetch 间谍：仅 1 次列表 GET；3 条消息/2 位作者/时间范围/附件未导入/本人单选）；截图 `round23-chatimport-preview.png`。
- 选本人→确认导入（调用序列含先查回执）→ 批次 chi_9439…（3 条消息、self_author=测试用户）→ journal 双清。
- **整页刷新读回**：批次在列表、无残留草稿；再次预览同文件出现重复导入警告。
- **批次详情**：作者/本人/来源批次号/逐消息来源编号（message-N 3 条）/附件未导入说明。
- **搜索**：`kind=all` 命中 chat_import（target.kind=chat_import、import_id 正确），Web 标签「聊天来源」＋深链分支（单测覆盖）。
- **未知结果链**：拦截 POST→「操作结果尚未确认」＋pending journal 保留；**重复点击确认仅 1 次 POST 尝试**（busy 门）；**整页刷新→pending 框→重试**（同请求键 GET 404→POST 成功，journal 清）。第二批由此产生（同内容不同 key，后端按 key 幂等，如实记录）。
- **删除两步**：范围说明→确认移除→「已移除这批聊天来源」→列表清空；截图 `round23-chatimport-list.png`。
- **P2/接线复验（v4）**：文件入口独立按钮并关闭文件父面板；关闭按钮真实点击（160ms 动画时序）面板关闭、Esc/cancel 同效；移除本机预览成功路径；伪造 size=2 GB 在任何读取前被拒（浏览器＋单测双证）。

**桌面隔离验收**：独立实例（identifier `io.luckyloading.pajio.desktop.chatimportqa20261009`、数据目录 `/tmp/pajio-desktop-qa2-data-20261009` 预置 connection.json 指向 8892、复用 `/tmp/pajio-desktop-qa-target-20261009` 增量构建）。结果见下节。

## 桌面结果（隔离 Pajio Context QA.app，2026-10-09）

- 构建：`tauri build --debug --bundles app --config`（productName "Pajio Context QA"、identifier `io.luckyloading.pajio.desktop.chatimportqa20261009`、`appDirectoriesOverride=/tmp/pajio-desktop-qa2-data-20261009` 预置 `connection.json={"url":"http://127.0.0.1:8892/"}`；复用 `/tmp/pajio-desktop-qa-target-20261009` 增量构建）→ 产物 `/tmp/pajio-desktop-qa-target-20261009/debug/bundle/macos/Pajio Context QA.app`。生产实例（PID 28685）全程未动。
- **已验证（桌面壳内）**：启动 auto-connect(8892)→AX 树确认 QA 身份页面；AXPress 真实点击「连接与设置」→设置完整渲染（288 元素，含「导入选定聊天」区段）；AXPress 点击入口→**面板打开且完整渲染**（截图逐字核对：标题/说明/「选择聊天 ZIP 或 TXT」/上限文案）且**父设置面板已关**（交接，无双模态；v4 起同时覆盖文件面板父级）；modal 态 WKWebView AX 树塌缩（已知局限，以截图核对）。
- **未验（桌面壳内）→ root 接手**：文件选择（原生 NSOpenPanel）与确认/删除的点击闭环由 root 以 CUA 接手验收（避免双端同时操作；root 已在 onboarding 轮实证实际像素坐标可行）。隔离实例保留运行（`/tmp/pajio-desktop-qa-target-20261009/debug/bundle/macos/Pajio Context QA.app`，连 8892）。同一保存/删除链已在浏览器对同一服务全量验收，分别记录、不互相等同。
- **root 已完成 iOS 原生两条真实点击链**（文件导入、Share Extension→收件箱→预览→取消），证据在本轮目录——App 侧记录，不属本文。
- **root 桌面原生闭环已通过**（2026-10-09，CUA 实际像素坐标）：NSOpenPanel 真实选合成 ZIP→预览零 POST→选测试用户→确认 POST（05:23:36 UTC，批次 chi_93944870a13d452a9fb8b752fb0dd3c4）→实例重开读回→详情 message-1..3→两步删除（05:26:12）→空列表→右上关闭成功。本轮末尾两个显示问题（正文贴边/裸 ISO）即由该验收发现，已修（见第四批）；root 另写 desktop-ui-check.md。

## 未验项（如实）

- 真实微信分享入口与各版载荷（合同明确仅合成验证；WeChatBridge 格式为社区解析器实证，非腾讯兼容承诺）。
- 换身份真实点击（QA 8892 仅 qa 一身份；围栏与隔离由单测/VM 覆盖）。
- 删除回执重放恢复防护的服务端行为（后端回归覆盖；Web 已按 deleted 回执不重发）。
- 分享收件箱/Android provider 路径属 App；Web 无此链路。
- 私密远控：未实现，未提供任何远控/远程登录入口（本面板与全部 Web 无相关按钮）。
