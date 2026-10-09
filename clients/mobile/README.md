# Wearing mobile

React Native + Expo 57 的手机客户端开发基础。沿用 Wearing 的角色、字标及同一 `/api/life`、`/api/captures` 记录，不另建数据后台。

已在小米 6X Android 9 的 Expo Go 57.0.9 中运行，验证拍照、录音、离线重启与恢复同步；也可运行同源码网页预览；Android/iOS 的 JS/Hermes 运行资源已导出，尚未交付 APK/IPA。完整验收与限制见 [手机客户端](../../docs/mobile-client.md)。

```sh
cd clients/mobile
npm ci --ignore-scripts
npm run typecheck
npm test
npm run export:web -- --max-workers 2
npm run preview
```

默认预览 http://127.0.0.1:8787/ 只代理本机 http://127.0.0.1:8765/。需要先启动 Wearing 服务。预览服务只监听回环地址，不能作为公网入口。

```sh
npm run export:android -- --max-workers 2
npm run export:ios -- --max-workers 2
```

上述命令是运行资源导出，不生成安装包。原生开发构建分别运行 `npm run android`、`npm run ios`，需要 Android SDK/JDK 或完整 Xcode。Android 配置由 `app.json` 和 `plugins/local-preview.cjs` 生成；不手改生成的 `android/`。USB 本地调试可用 `adb reverse tcp:8765 tcp:8765`，仅作用于已授权设备；远端入口必须为 HTTPS。不要把网页预览地址作为手机服务地址。

相机和麦克风权限按操作请求。原件存入 App 私有目录，草稿/待同步/快照使用 SQLite；网页验收使用 IndexedDB。离线新建可用，已有记录的修改、完成和对话需要连接服务。同步只在前台进行。

发布前仍需真机权限、身份切换和恢复验收、公开身份认证、系统分享、提醒/日历、签名与依赖审计。当前 npm audit 有 24 条依赖告警，不能直接作为正式发行包发布。

## 已接上的测试手机

当前使用官方 Expo Go 开发宿主，电脑保留 Metro 8081 与本地 Wearing 8765。手机可从 Expo Go 最近项目打开 Wearing。USB 断开后无法访问本机服务，已记下的内容会留在本机，重新接通后在前台同步。

```sh
node node_modules/expo/bin/cli start --localhost --port 8081 --go --max-workers 2
adb reverse tcp:8081 tcp:8081
adb reverse tcp:8765 tcp:8765
adb shell am start -a android.intent.action.VIEW -d exp://127.0.0.1:8081
```

小米当前 WebView 74 的内嵌对话尚未通过，请暂在电脑 8765 网页聊天；手机随手输入与共享记录已验收。

正式安装包、HTTPS 账号登录及手机脱离开发电脑后的使用流程仍需下一轮交付。测试宿主来源：[Expo Go 57.0.9](https://github.com/expo/expo-go-releases/releases/tag/Expo-Go-57.0.9)。

## iPhone 同 Wi-Fi 真实语音开发验收

`/experience` 是隔离的交互示例。真实录音请使用 Expo Go 打开短期配对链接，连接后进入 App 首页 `/`。按住录音、上滑取消、松开转为可编辑文字、点发送进入原有对话；失败可继续识别本机录音。无需开发者会员，但不等于 TestFlight 交付。

在仓库根目录启动已经配置的后端与开发桥；将示例 IP 换为 Mac 当前 Wi-Fi 的私人 IPv4。配对文件必须使用新的文件名。

```sh
.venv/bin/wearing serve --port 8765 --data-dir .wearing --engine-autostart
.venv/bin/python -m wearing.dev_mobile --listen 192.168.1.25 --port 8795 --upstream http://127.0.0.1:8765 --identity daily --pairing-file .wearing/mobile-dev/new-session.json
```

在 `clients/mobile` 启动 Metro 并本地生成配对二维码。二维码含临时凭据，不应分享或提交 Git。

**iOS Expo Go 57 要求电脑 CLI 与手机登录同一免费 Expo 账号。** 先运行 `./node_modules/.bin/expo login --browser`，再在手机 Expo Go 登录相同账号；仅 Metro 健康不表示真机能打开。已登录后可在手机点 Try again，无需重开后端。依据：[Expo 官方登录排障](https://docs.expo.dev/troubleshooting/expo-go-sign-in-required/)。二维码脚本会先检查电脑登录状态。

```sh
REACT_NATIVE_PACKAGER_HOSTNAME=192.168.1.25 ./node_modules/.bin/expo start --go --lan --port 8081
node scripts/iphone-pairing-qr.cjs ../../.wearing/mobile-dev/new-session.json ../../.wearing/mobile-dev/iphone.pbm exp://192.168.1.25:8081
```

PBM 是可转换为 PNG 的本地二维码图像，未调用外部二维码服务。手机用相机扫描后，Expo Go 显示地址、身份与到期时间，用户点连接后才保存配对。首次麦克风权限打断长按时，允许后再按住一次。

开发桥四小时到期，所有路径均需凭据，只允许指定身份。HTTP 不提供链路加密，仅用于此次可信 Wi-Fi；普通连接和生产版仍要求 HTTPS。Mac 必须保持运行，手机离开该 Wi-Fi 后不能继续访问此开发服务。真机结论及独立服务端证据见 [iPhone 语音验收](../../docs/evidence/iphone-voice-2026-10-07.md)。

2026-10-07 新增 iOS 开发配对的边录边传：运行时探测 Expo AudioStream，单路 PCM 采音同时保存私有 WAV 与发送实时小块；实际采样率校验后转换为 16 kHz 单声道 int16。松手返回整句可编辑文字，无实时字幕。取消区暂停发送，移回顺序续传；取消/后台关闭会话，失败保留原件，由用户显式重试文件路径。旧运行时、Android、网页和普通云连接保留 M4A/浏览器文件识别。供应商 Key 始终留在 Wearing 后端。

[豆包接入与测量](../../docs/evidence/voice-cloud-asr-2026-10-07.md) 区分了代码、完整服务链路与真实手机验收。iOS export 只验证 JS/Hermes 资源；本机停止后 150 ms drain 也不是原生尾包保证。

排障先读 Metro 与 Wearing 服务日志。本轮已经从真机收到脱敏阶段诊断，但具体 Expo Go 版本是否将每类日志回传需要分别核对；服务端日志可见识别耗时和安全错误码。此能力不等于屏幕共享或发布版崩溃监控，不能承诺自动看到所有手机报错。
