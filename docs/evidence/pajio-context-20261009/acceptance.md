# Pajio 上下文入口开发与验收

2026-10-09。本轮范围：App 选定聊天导入、共享后端、真机人工接管的权限基础；Web / Desktop 由 ZCode 只读 App 后独立实现。工作区原有变更全部保留；没有提交、推送、部署或重启生产 8765。

## 已交付代码

- App 从文件选择器或分享队列接收一份 ZIP / TXT；先本机解析、展示作者和消息，再明确确认提交。原 ZIP 与图片、语音等附件不上传。文件格式以 `clients/mobile/docs/chat-import.md` 为准，不代表所有微信版本兼容。
- 导入 journal 保留稳定请求编号，未知提交结果先查回执；批次列表、消息详情、来源编号和移除操作接通真实后端。退出账户清除本机正文；注销账户清除本人各身份草稿及 pending 键，持久 fence 拒绝迟到写回。
- 后端按可信账户及身份隔离规范化来源，提供批次、回执、检索、详情和导出；保留无正文删除回执，防止旧请求恢复已删除正文。没有自动生成画像、写入长期记忆或执行聊天中的指令。
- 删除移除该批来源正文和检索索引。此前生成的回答、另存记忆、历史会话及已下载文件不会自动清除。共享租户成员注销仍受现有归属登记完整性门槛限制。
- 真机接管的持久所有权、代次、互斥和断连暂停接入本机 phone proxy、远程 Connector 和 RelayStore。实时媒体、人工输入、端点加密与宿主进程隔离未实现，生产能力默认关闭。详见 `device-handoff-check.md`。

## 自动化证据

| 范围 | 结果 | 证据 |
|---|---|---|
| App 完整测试 | 720 / 720 | `app-tests-720.log` |
| 原生分享插件 | 3 / 3 | `app-share-plugin-tests.log` |
| TypeScript / src ESLint | exit 0 | `app-checks.json` |
| 本人账户清理，合成 SQLite | 1 / 1 | `app-account-cleanup-review.md` |
| 相关后端集成回归 | 199 / 199 | `backend-tests.log` |
| 设备接管相关回归 | 127 passed / 1 deselected | `device-handoff-check.md` |
| life 工具注册修复后范围回归 | 67 passed | [engine-contract-check.md](engine-contract-check.md) / [scoped-67-pytest.log](engine-contract-logs/scoped-67-pytest.log) |
| 最终注册合同与真实 life 子进程 | 2 passed | [final-2-pytest.log](engine-contract-logs/final-2-pytest.log) |
| 初始广泛引擎检查 | 31 passed / **1 failed**，保留首次 phone MCP 连接失败；后续已修复缺失依赖边界 | [初始完整日志](engine-contract-logs/initial-31-pass-1-fail-pytest.log) / [phone 子进程日志](engine-contract-logs/initial-phone-connection-failed-engine.log) |
| phone 启动修复与最终范围回归 | **31 passed**，真实 phone / life 子进程、跨进程互斥、无 site-packages 启动 | [修复记录](engine-contract-check.md) / [当场采集日志](engine-contract-logs/phone-startup-fixed-pytest.log) |
| ZCode Web / Desktop 前端回归 | **225 / 225**，保留 200 项原基线 | [ZCode 交付记录](zcode-delivery.md) |

以上为合成资料与测试适配器；不能据此宣称真实微信、真实社交账号、远程画面或私密密码输入已经通过。

## 安装构建

Android 独立测试包：`/Users/archieliew/Downloads/Pajio-context-test-20261009/Pajio-0.2.0-arm64-context-standalone-test.apk`。

- SHA256 `c129de66d265756140eca635f3d5ac7266639a1cf933eca3abb77829d0ec7263`。
- Pajio 0.2.0，arm64，API 24+，Release 构建使用开发测试证书；嵌入 Hermes bundle，无需 Metro，仍需连接 Pajio 后端。
- 源码一致性、APK v2 签名、ZIP 与 ELF 16 KiB 对齐检查通过；未覆盖真机安装与功能矩阵。保留原有安装包。

iOS 隔离候选已完成 `Release iphonesimulator arm64` 构建、签名验证，并安装至 iPhone Air 模拟器 `FC25D76C-DF85-4CB5-A862-DB33E302BA07`。主程序、内置 bundle 和分享扩展的 SHA256 见 [ios-build-check.json](ios-build-check.json)，源码输入清单见 [ios-source-manifest.json](ios-source-manifest.json)。原生 Files 选择与分享两条 UI 路径的结果见 [native-ui-check.md](native-ui-check.md)。这是模拟器安装验收；Apple Developer 会员尚未开通，仍没有可对外分发的 iPhone 安装包。

## 本轮原生交互验收环境

隔离合成服务 `http://127.0.0.1:8892/`，身份 `qa`，临时库 `/private/tmp/pajio-context-qa-sfhqjfjj/qa.sqlite3`。`qa-server.py` 禁用模型和真实设备执行；测试文件仅三条明确标注为合成的消息。请求审计只记方法、路径、身份和状态，不记正文。

根任务已通过 CUA 在 iPhone Air 模拟器实测：Files 原生选择合成 ZIP → 本机预览 → 移除预览 → 重选并确认本人作者 → 明确提交 → 详情与来源编号 → 刷新 → 两步移除。另完成 Files 分享 → Pajio Share Extension → 保存在手机 → App 分享收件箱 → 选定聊天预览 → 取消后收件箱为空。第二条仅预览取消，没有 POST。输入均为合成资料，**不是微信 App 的真实分享验收**。详见 [native-ui-check.md](native-ui-check.md)、[导入读回](native-import-detail.json)、[删除检查](native-delete-check.json)。

[native-flow-requests.json](native-flow-requests.json) 是共享 8892 服务的早期审计快照：其中 3 次 POST 只有 1 次属于原生确认路径，不能合并成 3 次原生验收。后续 root 在独立桌面壳真实点击完成文件选择、预览、确认、重开读回、来源详情、两步删除与关闭，新增 1 个自建合成批次已清理；详见 [desktop-ui-check.md](desktop-ui-check.md) 与 [桌面删除检查](desktop-delete-check.json)。

ZCode 按 `docs/plans/pajio-chat-import-zcode-handoff-2026-10-09.md` 只读 App 后实现 Web / Desktop；其浏览器点击链与源码交付见 [zcode-delivery.md](zcode-delivery.md)。[独立真实模块复核](web-review-check.md) 发现并推动修复了异步切账户串草稿、关闭/冻结后仍提交、超大文件读取过早、存储删除失败误报、入口与关闭接线问题；最后一次同时拒绝 get/remove 的存储边界也已复验通过。桌面和浏览器结果分别记录，没有以浏览器通过替代桌面通过。

## 仍需完成的产品链路

1. iPhone / Android 微信当前版本的真实分享入口、载荷和异常样本兼容验收。
2. 用户控制 App 到独占 Android 真机的实际视频、触控、中文输入、私密登录和安全交还；含宿主隔离及合成秘密泄漏测试。
3. 小红书、B站、抖音等各平台本人登录后按明确范围读取的实际适配与回执；不能以登录成功替代数据读取验收。
4. 基于来源生成可修正的上下文候选，再在引导中返回实际有用的内容。目前仅完成来源层，不宣称已自动建立可靠用户画像。
