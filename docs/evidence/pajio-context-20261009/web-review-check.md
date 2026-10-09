# Web 聊天导入独立复核

日期：2026-10-09。范围：`src/wearing/web/chat-import.js`、`scoped-store.js` 以及调用处的账号/身份围栏。复核只读产品源码，使用合成文本、合成 ZIP、内存存储与模拟 API；没有访问真实聊天、设备、8765 服务或生产账户。

## 结论与版本

本次独立审计发现的两个 P1 和两个 P2，在下列行为路径上已修复。最后一项“get/remove 同时抛 SecurityError”已单独复验通过。这个结论针对列出的源文件和边界，不表示整个产品已通过安全审计或远程真机能力已完成。

最终复核 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `src/wearing/web/chat-import.js` | `474fd74303ba03661bb0b978c105f6174acec6f59b4f47b9b8f1324272acd320` |
| `src/wearing/web/scoped-store.js` | `1007e59a5f8d9167aa00fd40be5b1ccaf3d5ca8f879f53b42d94cc0590ee4845` |

最终异常复验前后两文件哈希一致。后续如有列表日期格式或面板布局修改，这份证据仍绑定以上版本；不得将新哈希自动当作同一验收版本。

## 行为复现与修复核对

审计使用 Node VM 执行真实导入模块；账号切换、请求与解析测试同时加载真实 `scoped-store.js`、从 `app.js` 提取的实际 `api()`、实际 vendored fflate。DOM、网络响应和文件内容为合成夹具。检查实际存储键、网络请求计数和可见状态，不以源码字符串出现某个词作为通过依据。

| 原问题 | 原行为复现 | 修复后独立结果 |
| --- | --- | --- |
| P1：ZIP 最后一次让出线程后切换账号/身份 | 在最后一个 1 KiB 分块 yield 暂停，A→B、换 identity 并 reset 后恢复，A 的正文写入了 B 的 scope/identity 存储键 | 恢复后 `keys: []`、`draftVisible: false`。解析末尾与 `retain()` 前均再验证当前操作 |
| P1：回执 GET 在途时关闭面板，404 返回后仍 POST | close 后旧 confirm 继续上传并清除 journal | 显式 close、原生 dialog close 分别复验：`postAfterBoundary: 0`，保留 2 条 journal 和同一个 request key |
| P1 同一漏洞：回执 GET 在途时账户注销冻结 | work gate stop 后旧 confirm 仍 POST 并清 journal | `postAfterBoundary: 0`，保留 journal 和同一个 request key；恢复核对不会创建新请求键 |
| P2：超大 File 在完整读取后才校验体积 | 声明 2 GB 的合成 File 的 `arrayBuffer()` 被调用，可能在 15 MB 检查之前耗尽内存 | `arrayBufferReads: 0`，直接给出 15 MB 上限提示；未实际分配大文件 |
| P2：删除本机预览失败却提示成功 | remove 失败被吞，界面清空，持久行仍在，重开恢复旧预览 | remove 失败时不出现成功文案；显示失败、保留 draft 和持久行 |
| P2 补充边界：get/remove 同时被浏览器安全策略拒绝 | 仅检查 readback 会把被 `get()` 吞掉的异常当成 null，误判删除成功 | 最终版本要求 `remove() === true` 且 readback 为空；同时拒绝时保持预览并明确报错，详见下节 |

原始问题版本：`chat-import.js` = `790595853f7621aae2cde007f6038a383dc4c1e4847d0fc19b41aa69dc769c1e`；`scoped-store.js` = `9d9fdcffd3548fd4eecd804bae64d917580403a0afec403bc7fbee2f1175caca`。

前五项修复行为复验的 `chat-import.js` 版本是 `552bf68df3fec38cccd6b499f305ebc2380b669464b8726c38fa855e14a08597`；`scoped-store.js` 与最终版本相同。最终源文件再次核对仍保留 File 前置大小检查、每个 await 后的 epoch/generation/ticket 检查、receipt GET 后的检查、close 与 reset 票据失效、注销冻结 generation 更新。此次按分工不重复执行全部前五项。

## 最后边界：真实 scoped-store 同时拒绝读写删除

在最终两份真实模块上执行独立 VM 检查：绑定合成 cloud owner（64 位十六进制 scope）；选择只有“合成作者 / 合成正文”的 TXT；确认本机预览存在；随后令底层 `localStorage.getItem` 与 `removeItem` 同时抛出 `DOMException(..., 'SecurityError')`；调用真实 `discard()`。

实际结果：

```json
{
  "event": "storage_get_and_remove_denied",
  "notice": "",
  "error": "本机暂时没能移除这份预览，请稍后再试；原文件不受影响。",
  "persistedRows": 1,
  "draftVisible": true
}
```

这验证了真实 `WearingStore.get()` 吞异常返回 null 时，真实 `WearingStore.remove()` 的 false 仍阻止误报成功。对应实现为 `chat-import.js:169–180` 的 `writeJournal()` 与 `scoped-store.js:28` 的布尔返回。

另运行仓库新增的单项回归：

```sh
node --test --test-name-pattern='fully denied storage' tests/chat-import-ui.test.cjs
```

结果：1 项通过，0 项失败。该回归使用测试 store 替身；它是补充证据，不能替代上面的真实 scoped-store 行为检查。

## 已运行测试的归属

在前一修复版本 `552bf68…` 上独立运行：

```sh
node --test --test-name-pattern='P1-|P2-' tests/chat-import-ui.test.cjs
```

当时结果：7 项通过，0 项失败，涵盖账号切换、最后 yield、receipt 后 close/freeze、前置体积限制、删除失败与成功路径。最终版本仅增量复验上述组合 SecurityError 边界；没有将前一版本的 7 项说成最终版本的全量重跑。

ZCode 报告的 224/224 不属于本次独立执行结果。真实桌面界面闭环由主任务执行，另见同目录 `desktop-ui-check.md` 和相关请求证据；本复核不代替该验收，也未独立复现界面布局、关闭动画或父面板交接。

## 结论限制

- 此处测试没有进行真实账户切换/注销服务器端完整链路、真实聊天上传、手机文件选择器或 WebView 实机验收。
- 审计检查了 ZIP 路径、体积、解压和取消边界相关实现及指定夹具，但不是穷尽式 ZIP/文本模糊测试。
- 账号隔离结论依赖宿主在可信 bootstrap 中绑定正确 owner scope、切换时推进 identityEpoch 并 reset。这里验证的是这些边界触发之后，导入模块不会把迟到结果写入新账户。
- 回执未知时保留原请求键用于重试；关闭/冻结后不继续 POST，已经在关闭前发出的请求不能靠前端取消保证服务端撤销。
- 原四个发现没有待修项；任何后续逻辑改动、接口语义变化或真实界面验收发现均需单独评估。
