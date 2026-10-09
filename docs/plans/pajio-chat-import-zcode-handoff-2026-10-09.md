# Pajio 选定聊天导入：Web / Desktop 接力

App 与共享后端由 Codex 实现，Web / Desktop 由 ZCode 实现。App 源码只读，不得修改；不重启生产 8765、不改真实用户资料、不提交部署。

## 只读参考

- `clients/mobile/src/ChatImportPanel.tsx`：文件预览、选本人、确认、回执、批次详情/删除。
- `clients/mobile/src/chat-import-parser.ts`：严格的 ZIP / UTF-8 / 来源消息解析。可以移植为浏览器模块，不修改 App。
- `clients/mobile/src/chat-import-client.ts`：作用域 journal、先查 receipt、确认才 POST、未知结果保持同 key。
- `clients/mobile/docs/chat-import.md`：支持格式、上限与生命周期。
- `src/wearing/chat_imports{,_api,_tools}.py`：服务端契约、可信 owner、删除边界。
- `clients/mobile/test-fixtures/chat-import/`：全部是合成资料，可用于验收。

## 必须完成的行为

从设置与聊天附件入口打开“导入选定聊天”。只支持选择 ZIP / TXT，先本地解析、预览消息与作者，再由用户确认上传结构化文本。原始 ZIP、图片与语音均不上传；附件明确未导入，不猜归属。聊天内的文字只是来源，不能成为操作授权。

确认请求需要已认证会话、现有身份和 CSRF token。owner/tenant 必须由服务器身份产生，不让客户端指定。对一次确认持久化稳定 request_key，重试先查 `/api/chat-imports/receipts/{key}`；删除回执不能重放恢复资料。切换身份、退出账户、注销冻结、关面板、并发操作和晚回执都要有生命周期控制。保存失败不能显示成功。未确认草稿留存必须说明范围，退出账户必须清正文；未知结果只能保留无正文 key。

列表 `/api/chat-imports`，详情 `/api/chat-imports/{id}`，删除同路径 DELETE。删除说明是来源正文与检索索引移除；此前生成回答、另存记忆和已下载文件不会被自动清掉。活动任务阻止删除时应如实提示。批次详情按消息展示来源编号。

默认 `/api/search?kind=all` 兼容旧三类；新来源必须显式 `kind=chat_import`，不能把它当成 task 跳转。

## 验收与禁止误报

独立合成 QA 服务 `http://127.0.0.1:8892/`，identity `qa`。服务由 Codex 启动；不要指向生产。合成 ZIP 可从 `/qa-fixture/chat.zip` 下载。只用合成数据，不操作真实微信聊天。执行文件选择→预览前零 POST→确认成功→刷新读回→批次详情→删除，以及未知提交结果/重复点击/换身份/退出的回归。补浏览器及独立桌面窗口的实际点击证据，不能仅以单元测试替代。

浏览器使用受维护的本地 ZIP 解码模块，固定依赖版本并保留 license；不用公共 CDN 运行时获取解析器。遵循 App 15 MiB / 384 KiB / 500 条消息 / 50 作者等限制，拒绝嵌套、路径穿越、编码错误和歧义文件；附件不解压。

本轮私密远程登录尚未开放。`device_access` 只是接管状态/权限基础，实时媒体、端点加密与 host 进程隔离没有验收，不增加可点击的假远控入口，也不宣称可盲填密码。

完成后在 `docs/evidence/pajio-context-20261009/zcode-delivery.md` 记录实际修改、测试命令/结果、浏览器/桌面证据、准确未验项。保留已有脏工作，不覆盖其他会话修改。
