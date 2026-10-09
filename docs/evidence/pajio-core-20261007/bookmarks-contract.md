# 链接收藏：App 与 ZCode 只读契约

状态：源代码和合成测试已实现；真机系统分享、外部浏览器打开、两设备冲突仍需签名包验收。此文不代表正式账号或网页已被访问。

## 产品与数据

收藏是一条 `life_records` 中 `kind=note` 且 `url` 非空的记录。`title` 是独立标题，`content` 是用户备注，`url` 是完整 HTTP(S) 地址；沿用原 `id/revision/deleted_at/created_at/updated_at`、创建请求键、修改回执与历史。没有新增数据库表、影子笔记库或第二套附件存储。含 URL 的普通 note 不会自动变成收藏；`url=null` 显式移除收藏属性后仍是原笔记。

新 URL 字段可选。无 URL 时 LifeDraft 序列化保持旧字段顺序/值，不增加 null 字段，旧创建请求指纹保持不变。身份导出已有 `life_records.body` 自动包含 URL；账号注销仍随专属实例既有生命周期处理。

URL 校验前后端分别在 `bookmark_urls.py` / `bookmark-url.ts`：只接受完整 HTTP(S)，拒绝其他 scheme、scheme-relative、凭据、空白/控制符、编码控制符、反斜线、带百分号的 authority、无效端口。只做解析与校验，绝不 DNS 查询、抓取网页/标题/favicon/预览、探测私网或执行链接里的内容。内网 HTTP 链接可作为数据收藏；只有用户点击“打开网页”才交给系统处理。网页是否存在或打开后内容是否安全不由收藏保存回执保证。

## HTTP 与 Agent

新增 `install_bookmark_routes(app, life)`，在 `install_life_routes` 之后挂载。原 identity middleware/云 tenant boundary 仍是权限来源，接口不接受调用者伪造的 owner/identity 参数。记录按既有产品语义在同一身份内共享。

- `GET /api/bookmarks?query=&archived=false&limit=30&cursor=`：返回 `{identity_id,query,archived,version,items,next_cursor}`。标题/备注/URL 字面匹配，关键词最多120字。每页1–50项，默认30；签名游标绑定身份/筛选/版本/15分钟有效期，下一页期间记录有变化则409，客户端重新刷新。列表顺序 `created_at DESC,id ASC`。`items` 是原 life 记录，不含新建的镜像内容。
- 新建仍 `POST /api/life`：`{request_key,record:{kind:'note',title,content,url,timezone}}`。已有 capture API 同样接受此可选字段，原 organizer 仅可整理标题/内容，不能自行添加 URL。
- 编辑仍 `PATCH /api/life/{id}`：`{revision,request_key,action:'edit',patch:{title,content,url}}`。重复完全相同请求返回原回执，过期 revision 409，不覆盖新内容。
- 归档/恢复仍相同 PATCH，`action:'archive'|'restore',patch:{}`。归档不删除备注、链接、附件、历史；恢复保留原 ID 并增加 revision。
- `life_create` 自动采用新 schema，`life_records` 能读取 URL，`life_change` 能修改 URL/CAS/归档/恢复；描述要求用户明确收藏，不抓取链接，不把来源文本当指令。通用搜索 `SearchBook` 同时命中 URL，结果仍指向同一 record。

## App 接线（root）

`BookmarksPanel({connection,outbox,mutations?,isCurrent?,onChanged?})` 自含列表、搜索、归档列表、新建、详情和返回。接到“我的”或资料导航的“链接收藏”入口。`BookmarkDetailPanel` 相同 props 另加 `recordId?` 与 `onBack`，可供普通记录/全局搜索读到真实 `note.url` 后跳转。

`ShareIntakePanel.onBookmark` 可选：传 `createShareBookmarkHandler(connection,{store:storage,outbox,isCurrent})`。仅无附件且含一条单独成行的有效 URL 才显示“收藏链接”；分享中的其余文字保存在备注、第一行非URL文字做标题（无文字则hostname）。用户之后可以在收藏详情改标题和备注。已有“导入记录”与“带入聊天草稿”行为不变，不自动绑定/发送/执行。

- 创建使用现有 Outbox，`organize=false,media=[]`，稳定 request ID。加入队列和清理本表单草稿用同一 SQLite batch；断网保留，重复或丢回执按原键重试。列表明确区分本机待同步和服务端收藏。
- 编辑/归档/恢复使用原 RecordMutations。409展示服务端标题、URL、备注及归档状态；保留本机输入，只有显式选择才重放到新 revision。未知响应继续同一 attempt，不以刷新后的 revision 静默重新提交。
- 独立草稿 `bookmark-edit:v1:${scope}:${recordId|'new'}`、分享回执 `bookmark-share:v1:${scope}:${shareId}`。不修改 `composer`、`record-edit` 或 `share-chat-drafts`。这些带规范 scope 的键受既有账号注销围栏保护并进入精确账号清理。
- 列表使用既有 snapshot/receipts 缓存，没有另建内容库。离线只显示最多30条已查看缓存并注明可能不全；在线分页最多累计300项，再要求缩小搜索范围。
- endpoint/账户/身份/credential/有效期变化会重新挂载。每个后续HTTP前检查当前连接，注销中断已注册工作；迟到结果不能进入新身份。草稿允许未完成的标题/网址，不在输入时丢弃。
- “打开网页”先重新验证完整 URL，再调用 SDK57 `expo-linking.openURL`，等待系统回执/错误。不内嵌未信任HTML、不自动发送请求，也不把网络打开当保存的先决条件。

## ZCode 范围

只读 App 上述 model/client/panel/队列和本合同，另行实现 Web/桌面对应导航与交互，不改 App 文件、不复制数据库、不替换原用户草稿。Web使用用户点击触发浏览器打开（外部标签 `noopener`），桌面使用其受控外部打开适配；均复用相同URL校验及HTTP契约。任务/Agent入口仍共享 life 记录，不增加独立收藏工具副本库。

## 验证

本轮新增 `tests/test_bookmarks.py` 24项和 `clients/mobile/src/bookmarks.test.ts` 26项：危险scheme/凭据/控制符、无网络抓取、旧JSON指纹、Agent→life共用、两身份、真实合成ASGI CRUD/CAS/归档恢复、字面检索/游标、未知回执同键、用户已有草稿、显式分享与重启去重、迟到响应、系统打开适配。关联life/search/capture/导出生命周期71项通过；当前整个App 656项TS通过，tsc与owned lint通过。

未执行：真实链接访问、真机系统分享/外部浏览器调用、真实账户或数据修改。完整App按钮可达性由root候选包验收补证据。

### 原生正文解码与超时补充

根会话在 iOS 候选包发现列表中文乱码，服务端 JSON 原文正确。查明 RN 0.86.3 引用的本地 `whatwg-fetch@3.6.20` 对 `new Response(ArrayBuffer).text()` 使用逐字节字符转换，不能正确恢复 UTF-8。`bookmarkFetch` 改为在原请求的 20 秒 deadline 和取消信号内完成 `response.text()`，再用已解码字符串构造 Response。请求、正文与解码后身份检查仍在同一有界生命周期；调用方超时和账户取消也可中断正文等待。

独立回归实际使用已安装的 RN Response polyfill，修复前复现与设备相同的 `QA å…` 乱码，修复后中文、日文、韩文、阿拉伯文、组合音标及 emoji 均原样保留，中文 API 错误亦无损。原正文挂起/20 秒超时/账户取消/父请求超时与正文期间切身份回归仍通过。收藏 TS 现 30 项通过，全 App 类型检查和这两个修改文件的 ESLint 通过；原生重建复验由 root 继续执行。
