# Wearing 原生客户端

2026-10-04。客户端与 Agent 核心分开运行，连接同一份个人记录。当前推进 Mac 技术验证；Windows 配置一并保存，真机验收仍待完成。腾讯云试验机继续暂停。

## 桌面第一增量

采用 Tauri 2 的系统 WebView、标准菜单、托盘、全局快捷键与单实例插件。源码位于 `clients/desktop/`；npm 和 Cargo 锁文件固定本次依赖。界面继续使用现有 Wearing 页面，不复制日历或聊天数据库，不包含 Python、Hermes、Cua Driver、ADB 或用户凭据。

- 主窗口提供今天、日历、清单、笔记与 Wearing 对话。
- 菜单栏/托盘提供「打开 Wearing」「记一下」「连接设置」「退出桌面端」。
- `Command + Shift + Space`（Mac）/ `Ctrl + Shift + Space`（Windows）唤起窗口并聚焦今天的书写区。前台菜单快捷键已实际通过；后台全局唤起仅确认注册，尚未通过。Windows 行为需实机核对。
- 关闭主窗口是收起；退出客户端只退出界面。已有服务、连接器和目标继续按原约定运行，暂停事项在 Wearing 内操作。
- 连接页先验证服务再切换；失败保留原连接。只接受本机 HTTP 或远端 HTTPS 根地址，不接收路径、内嵌账号、查询密钥。连接配置只保存 URL；系统 WebView 的登录 cookie 和网页草稿属于平台 WebView 数据，不能描述为客户端完全不存数据。

网页内容不取得客户端的文件系统、Shell 或原生设置命令权限。原生连接命令检查调用窗口和内置页来源；导航与原件窗口限制在当前服务来源。原生层只投递固定的快记/收起事件，不传入任意脚本或文件路径。首次麦克风、相机和系统日历仍遵循系统授权，应用不代为扩大权限。

本增量连接正在运行的本机服务 `http://127.0.0.1:8765/`。远端公开登录和认证重定向未在客户端验收；支持 HTTPS 地址格式不表示生产 SaaS 接入已经完成。若服务未启动，连接页提供重试；客户端暂不自动安装和启动后端。本机开发服务可显式使用 `wearing serve --engine-autostart` 恢复已安装配置的核心；默认不改手工外部引擎连接。

## 构建

```sh
cd clients/desktop
npm ci --ignore-scripts
npm run build -- --debug --bundles app
npm test
```

当前要求 Rust 1.90+、Node.js 和平台原生编译依赖；本机验证使用 Rust 1.96、Node.js 24 与 Xcode Command Line Tools。Mac 构建为 Apple Silicon 技术验证包，尚无正式签名、公证、自动更新和 Intel 验收。Windows 在 Windows 构建机运行：

```sh
npm run build -- --config src-tauri/tauri.windows.conf.json
```

Windows 还需官方要求的 C++ 构建工具和 WebView2。安装器配置已准备，但未构建或安装。官方依据：[平台依赖](https://v2.tauri.app/start/prerequisites/)、[菜单栏入口](https://v2.tauri.app/learn/system-tray/)、[快捷键](https://v2.tauri.app/plugin/global-shortcut/)、[单实例](https://v2.tauri.app/plugin/single-instance/)。

## 手机客户端增量

手机采用 React Native + Expo 开发构建，而不是给桌面网页只加一个外框。优先把「拍一下、说一句、写下来」跑通，继续调用现有 `/api/life` 和 `/api/life/assets`；云端整理仍是当前 capture 管线，不另建记录服务。

| 接入 | 采用已有能力 | 验收要点 |
| --- | --- | --- |
| 拍照/选图 | expo-image-picker / expo-camera 与系统选取器 | 只接收本次选择；取消不建记录；拍后可加语音说明 |
| 语音 | expo-audio 与系统麦克风 | 录音先落本机文件；停止/中断可恢复；退出录音页面不会继续偷录 |
| 离线队列 | expo-sqlite + expo-file-system | 原件先落地；相同 request_key 重试只产生一个 record_id；按身份分隔 |
| 登录 | 平台 Keychain/Keystore（expo-secure-store） | 不把访问凭据写入普通配置、URL 或日志；退出账号隔离本地内容 |
| 系统分享 | iOS Share Extension / Android 接收分享 | 图片/网页/文字先进入收件草稿；补一句用途后提交；不静默扩大读取范围 |
| 日历和通知 | EventKit / Expo Calendar、Notifications | 指定日历范围、撤销与版本冲突；自有记录保存和系统提醒启用分别显示 |

截至本次官方 SDK 表，Expo 55 的平台下限为 Android 7+、iOS 15.1+；56/57 为 Android 7+、iOS 16.4+。这意味着 Android 9 不因平台下限被排除，但小米 6X 的性能、MIUI 权限、安装与国内通知仍需真实验证。本轮锁定 Expo 57.0.26，不使用 canary，也不把官方平台下限当成真机通过。依据：[SDK 平台支持表](https://docs.expo.dev/versions/latest/)、[ImagePicker](https://docs.expo.dev/versions/latest/sdk/imagepicker/)、[Audio](https://docs.expo.dev/versions/latest/sdk/audio/)。

手机客户端基础与离线新建队列已经实现；同源码网页完成断网重开、同步和原件核对，Android 9 已通过 Expo Go 真机加载。正式安装包、系统分享和原生日历尚未交付，完整边界见 [手机客户端](mobile-client.md)。麦克风与拍照的真实权限验收、Mac/Windows 正式安装升级、公开云端认证、多端离线冲突依次推进；无需为本轮创建新云资源。
