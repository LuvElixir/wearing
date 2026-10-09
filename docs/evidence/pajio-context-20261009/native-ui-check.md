# iOS 原生聊天导入交互验收

日期：2026-10-09。结果：**Release 模拟器安装、Files 文件选择完整导入/查看/移除，以及 Files 分享到 Pajio 后的本机预览/取消均已完成。** 这不是物理 iPhone、真实微信导出或对外分发验收。

## 证据来源与环境

UI 操作与逐步观察由根任务通过 CUA 完成；本文由子任务依据根任务的实际观察回报及以下保存的构建、请求和数据库证据整理，没有声称子任务独立重复了这些 UI 操作。CUA 观察证明原生界面与操作顺序；HTTP 审计和合成数据库读回补充证明提交时点、入库内容与删除结果，两类证据不互相替代。

- 安装目标：iPhone Air **Simulator**，UDID `FC25D76C-DF85-4CB5-A862-DB33E302BA07`。
- 产物：隔离候选 `Release iphonesimulator arm64`；构建成功、签名验证退出 0，包含 `main.jsbundle` 和 `expo-sharing-extension.appex`。路径与产物 SHA256 见 [ios-build-check.json](ios-build-check.json)，输入清单见 [ios-source-manifest.json](ios-source-manifest.json)。这是模拟器产物，`distribution_package=false`。
- 服务：隔离合成后端 `http://127.0.0.1:8892/`，身份 `qa`。`qa-server.py` 禁用模型和真实设备执行，不访问真实账号。
- 输入：[合成选定聊天.zip](fixtures/合成选定聊天.zip)，包含 3 条合成消息、2 名作者和 1 个附件条目。附件只在本机提示存在，内容不读取为模型上下文、不上传，也不猜测其属于哪条消息。

## 路径一：Files 原生选择 → 确认 → 查看 → 移除

| 步骤 | CUA 实际观察与补充证据 |
|---|---|
| 原生文件选择 | 在 App 打开系统 Files 选择器，选中合成 ZIP，回到本机预览，看到 3 条消息、2 名作者、1 个附件未导入。 |
| 预览取消 | 确认前移除本机预览，再重新选择文件。确认前保存的 [native-preview-audit.json](native-preview-audit.json) 中 `post_count=0`；没有把选文件或预览当成提交授权。 |
| 本人作者确认 | 重新预览后选择“测试用户”为本人，再点击确认。 |
| 提交 | 04:13:34 UTC 先查询稳定请求键回执得到 404，再 POST `/api/chat-imports` 得到 200。请求键为 `401448de-1dd6-476c-befb-ba28769659d9`，批次为 `chi_efd4f3169b654470a6ade6ee3f3da684`。 |
| 查看详情 | 打开批次，看到作者、来源时间、消息内容与 `message-1`、`message-2`、`message-3` 来源编号；随后刷新。服务端读回见 [native-import-detail.json](native-import-detail.json)：`self_author=测试用户`、3 条消息、各条 `attachments=[]`、`attachment_count=0`、`attachments_imported=false`。本地发现 1 个附件与服务器保存 0 个附件不矛盾，附件未纳入导入。 |
| 两步移除 | 在 App 发起移除并再次确认，04:14:56 UTC DELETE 返回 200。随后刷新列表。数据库检查 [native-delete-check.json](native-delete-check.json) 显示正文与摘要已清、`body_bytes=0`、`message_index_rows=0`；请求键回执仍为 `deleted`，用于阻止旧请求恢复正文。 |

这条原生确认路径产生 **1 次 POST**。此前生成的回答、另存记忆、历史会话及下载文件不属于来源批次移除范围，本次没有以删除来源证明它们一并清除。

## 路径二：Files 系统分享 → Share Extension → 分享收件箱 → 本机取消

根任务实际操作：在 Files 中分享合成 ZIP，选择 Pajio Share Extension，选择保存在手机；打开 App 的分享收件箱，对该条目选择“预览为微信选定聊天”，成功进入本地预览，随后移除本机预览，返回分享收件箱后为空。

该流程验证系统分享扩展、共享文件交接、App 收件箱路由与取消清理。操作来源是 **Files，不是微信 App**；“微信选定聊天”是 Pajio 的解析入口名称，不能据此说真实微信分享格式已通过。

[native-flow-requests.json](native-flow-requests.json) 在 04:17:02–04:21:17 UTC 记录 6 次 GET、零 POST。这与此流程只预览并取消一致，没有上传来源正文。

## 共享请求审计的归属边界

`native-flow-requests.json` 是共享 8892 合成服务的审计，当前快照共 38 条请求、3 次 POST，**不是 3 次原生导入**。根任务同时协调 ZCode 验收：04:13:34 的批次属于上述原生流程；04:15:51 和 04:16:39 的另外两次 POST 属于 ZCode 操作。客户端归属来自协调记录与具体批次/请求键，而不是审计中不存在的客户端标识。

04:17:00.614 UTC 仍有 ZCode 批次 DELETE，因此没有把整个“04:17 开始”笼统描述为只有 GET。上述分享流程审计窗口从 04:17:02 起算。Web / Desktop 的独立 UI 验收另记，不在这里归入原生成功数量。

## 后续仍需验证

- 真实 iPhone 和 Android 微信当前版本的分享入口、载荷与异常样本，以及物理设备的存储权限和后台恢复。
- Android 真机安装与相同交互矩阵；APK 构建成功不等于该矩阵通过。
- Apple Developer 分发签名与真实设备安装；目前没有可对外分发的 iPhone 安装包。
- 真机远程视频、触控、私密登录与安全交还保持未完成，见 [device-handoff-check.md](device-handoff-check.md)。

本轮另发现并修复 life 工具注册与引擎启动允许列表不一致，67 项范围回归、最终 2 项真实 life 子进程检查通过；初始广泛检查的 phone 分支仍有 1 项失败，诊断中。完整成功与失败证据均保留在 [engine-contract-check.md](engine-contract-check.md)，不由本次 iOS 界面验收覆盖或消除。
