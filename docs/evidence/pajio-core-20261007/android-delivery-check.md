# Android 软件交付检查（2026-10-08）

## 当前最终构建状态

已经生成两个 ARM64 APK，产物保存在 `/Users/archieliew/Downloads/Pajio-test-20261008/`，没有把大包加入代码仓库。优先使用 `Pajio-0.2.0-arm64-standalone-test.apk`：68,112,866 bytes，包内 `assets/index.android.bundle` 与实际构建输出逐字节一致，包含 4113 模块，不依赖 Metro；联网助手仍需要可访问的后端。

| 产物 | SHA-256 | 使用边界 |
| --- | --- | --- |
| `Pajio-0.2.0-arm64-standalone-test.apk` | `1ca187b67c55dfdc10a9e83c7b4d8b97110ec2585d7f7f0876cd2edf47f7d4e3` | 内嵌 JS、关闭 debuggable；Release 变体但使用 Android Debug 测试签名 |
| `Pajio-0.2.0-arm64-debug-metro.apk` | `64f15165d27406410069565ffae1897888e09a5a8b804d1a37211750d3cbc253` | 94,980,487 bytes；没有 JS bundle，需要 Metro，仅开发调试 |

`README.md`、`SHA256SUMS.txt`、`build-verification.json`、签名报告与最终 Gradle 日志随包提供，下载目录内再次执行哈希核验两包均为 OK。包名为 `io.luckyloading.wearing.mobile`，应用名称 Pajio，版本 0.2.0 / versionCode1，minSdk24、target/compile36，ABI 仅 arm64-v8a。

完成的实际验证：

- 首次 `assembleDebug` 成功（17m10s）；独立 Release 变体首次被 `lintVitalRelease` 的网络配置检查拦下。定位到 config plugin 生成的三个 loopback `<domain>` 缺 `includeSubdomains`，在源插件显式添加 `false` 并重新生成候选 XML，没有关闭 lint 或扩大 HTTP。
- 修复后 `:app:assembleDebug :app:assembleRelease` 真正成功，31s / 940 tasks（59 executed、881 up-to-date）；`lintVitalRelease` 通过。
- 新增测试实际执行 Android config plugin 并解析 XML，验证精确 loopback 白名单、默认禁 HTTP、禁备份；与分享插件共 4 项通过。最终候选完整 `tsc --noEmit` 与 src ESLint 通过。
- 两包 APK Signature Scheme v2 校验通过，证书 `CN=Android Debug`。ZIP 的 16KB 对齐及全部 25 个原生 ELF 的 PT_LOAD 对齐检查通过；没有正式发布签名或商店提交。
- 独立包合并清单验证 `allowBackup=false`、无 debuggable 标记、`usesCleartextTraffic=false`；没有悬浮窗、广泛图库或外部存储权限；`POST_NOTIFICATIONS` 已实际进入合并清单。
- 独立包网络安全 XML 仅允许 localhost / 127.0.0.1 / ::1 的 HTTP，全部 `includeSubdomains=false`。局域网 HTTP 不能直接连；README 只说明明确选定的隔离 QA 可手动使用 adb reverse，本次构建没有配置转发。
- 本构建检查只读 `adb devices -l` 确认 MI 6X USB 状态为 device。主任务随后在该 API28 设备完成安装：首次 streamed install 返回 exit1 空原因，确认未安装后改用 `adb install --no-streaming -r`，Push Install 返回 `Success`。安装前无同包名旧应用，未卸载、未清数据。`dumpsys package` 回读 0.2.0/versionCode1/min24/target36，first/lastInstallTime=`2026-10-08 23:13:18`，flags 无 DEBUGGABLE。README 已加入该安装命令；启动/逐按钮/权限 UI 尚未验收。

用户已明确同意 Android SDK License Agreement 后，才继续接受 sdkmanager 的 `android-sdk-license` 并安装官方组件。工具链始终位于 `/tmp/pajio-android-toolchain-kcb_a3hp`，最终含 JDK17、Gradle9.3.1、platform36、build-tools35/36、NDK27.1.12297006、CMake3.30.5、platform-tools37.0.1。结束时隔离 `gradlew --stop` 返回 `No Gradle daemons are running`，未停止其他项目进程。

本轮源码改动仅增加 Android plugin 的三个显式属性和对应配置边界测试；iOS 原生工程、Web、桌面与运行中的 8765 未改。候选 `/tmp/pajio-android-review-XKwtST` 保留，最后任务恢复 UI 三文件按冻结 SHA-256 纳入。

## 早期软件检查（构建前历史）

候选目录：`/tmp/pajio-android-review-XKwtST`。由 `clients/mobile` 复制源码、APFS clone 本地 node_modules；排除源码的 ios/android/.expo/dist。生成操作只发生在这个临时候选，未生成或修改源码 Android 工程。未访问实体手机、8765、生产云、签名服务或付费构建。

- SDK57 Android JS export 成功，初次 4108 modules / Hermes bundle 8.5 MB；恢复修复后再次导出，日志 `android-export-final.log`、产物 `dist-android-review-final/`。
- `expo prebuild --platform android --no-install` 成功。
- `expo-modules-autolinking resolve --platform android --json` 成功，32 个 Expo 模块；Audio、Calendar、FileSystem、ImagePicker、Location、Notifications、SecureStore、Sharing、SQLite、Video 均有 Android project；候选保留 `android-autolinking.json`。
- Android 恢复、实际 Mobile handler、账户清理、分享、通知、原生日历同步共 73 项 TS 回归通过；分享 config plugin 3 项通过。全源码 `tsc --noEmit` 与相关文件 ESLint 通过。
- 首次检查 `/usr/libexec/java_home -V` 明确返回无法找到 Java Runtime，当时尚未生成 APK。后续已完成上方实际构建；预构建通过本身不等于 Kotlin 编译或真机运行已验收。

## 工具链准备与许可等待（历史）

2026-10-08，工具链目录 `/tmp/pajio-android-toolchain-kcb_a3hp`。仅使用官方 archive，未安装系统级软件、修改 shell 启动文件或复用其他项目 Gradle 缓存。此次未改 App/iOS 源码，也未操作真实设备。

- 官方 Adoptium API 返回 Temurin `17.0.20.1+1` macOS aarch64 JDK archive；已下载、解压并通过 SHA-256 校验：`196d13ba5f10414bef7f6a05a9b3f00edacb18ebacef2b99485db9e2ee18f0e8`。
- `JAVA_HOME=/tmp/pajio-android-toolchain-kcb_a3hp/jdk-17.0.20.1+1/Contents/Home`，`java -version` 成功。项目 wrapper 的 Gradle `9.3.1` 在该 JDK 启动成功，`GRADLE_USER_HOME` 为工具链下 `gradle-cache`；日志 `gradle-version.log`，清单 `toolchain-manifest.json`。这只证明工具能够启动，未编译 Android 工程。
- 当时没有设置中的 SDK 路径；`~/Library/Android/sdk` 及 Homebrew 常用 SDK 位置均不存在，已有 `.wearing/runtime/android` 只有 platform-tools/Expo Go，没有 `licenses`。当时没有找到可直接复用的已接受 SDK 许可。
- 官方下载页的 Mac ARM command-line tools `commandlinetools-mac_arm64-15859902_latest.zip` 在下载前要求本人勾选 Android SDK License Agreement，页面日期为 `2026-04-28`。此前按任务边界停在这一许可步骤；收到本人明确同意后才继续安装与构建。
- SDK 许可完成后所需平台依据当前已安装 RN Gradle catalog，而非泛化示例：`platforms;android-36`、`build-tools;36.0.0`、`ndk;27.1.12297006`；若实际构建要求 CMake，再按构建指明的版本安装。无需为 APK 编译下载模拟器系统镜像。
- 许可等待阶段尚未执行 `assembleDebug`；当前 APK 与哈希证据见顶部。候选 Gradle 配置的 debug 使用模板调试签名；release 也引用同一 debug 配置，不能据 variant 名称视为正式发布签名。默认 debug variant 跳过内嵌 JS/资源，需要 Metro，不能作为独立正式外测包。

后续已在同一隔离工具链和候选目录完成构建，没有在源码生成 Android 工程或借用正式签名。

## 本轮修复

Expo SDK57 文档要求 Android MainActivity 被系统回收后调用 `ImagePicker.getPendingResultAsync()` 取回结果。原实现只有等待 launch promise，没有该恢复入口。

新增 `picker-recovery.ts`：

1. 在打开系统选图前保存原始 `scope + draftId + UUID`，保存失败不打开选图。日志不保存令牌、EXIF、base64 或网络 URL。
2. 收到结果后先写本机 journal。冷启动时读取 SDK pending 结果，按照旧 intent 归属封存；没有 pre-launch intent 的系统残留不加入当前账户。
3. 仅原账户、原 tenant、原 identity、原 draftId 可以将结果加入草稿。切换账户不会把旧图片带给新账户，新账户仍可以开始自己的选图。
4. 媒体 UUID 固定，草稿与 journal 消费用 SQLite 同批提交，重复恢复不重复添加。最多保留 8 个未完成结果。
5. 私有副本使用与注销清理相同的队列与账户围栏。恢复时比对源与副本长度及 MD5；中断留下的半份文件只允许覆盖该 intent 私有 UUID 目的地。
6. 注销按 journal 条目的可信账户 scope 精确清除，保留其他账户条目；晚到回写不能复活已冻结账户数据。恢复只保存到原草稿，不发送、不自动上传。

SDK pending read 是消耗式且不提供 operation id。第二次进程死亡发生在 native 清除 pending 与 JS 持久化之间仍可能无法恢复；缓存被系统清理时也不能承诺拿回原件。这些情况不能标为保存成功。当前 journal 的已返回结果仅恢复到原 draftId；不自动搬到用户后来创建的另一份草稿。

## Android 平台核对

- 生成 manifest：Pajio 名称、`io.luckyloading.wearing.mobile` 稳定包标识、`pajio`/旧 `wearing` scheme、singleTask、predictive back；allowBackup=false。
- 网络安全：正式默认禁止 cleartext，仅 localhost/127.0.0.1/::1 例外。HTTPS 云账户可用；当前短期 LAN HTTP 开发配对在 Android 会被这层阻止，不能当作已验收链路。本轮不扩大 cleartext 范围。
- 分享：仅已声明 MIME 的 SEND/SEND_MULTIPLE；冷/热启动 Kotlin hook 将携带文本文件 EXTRA_STREAM 的 text/plain 交回 SDK 文件分支。接收实现使用受限 content:// 只读流，先复制私有文件再消费 intent，无 URL 解析/抓取。SDK57 FileSystem 原生实现支持 content URI 的 read-only FileHandle。
- 权限：照片使用系统选择器，不需要广泛图库读取权限；相机/麦克风/前台位置/日历按用户动作请求。主 manifest 阻止外部存储、广泛图片/视频读取和悬浮窗权限。
- 通知：Android channel 创建在权限请求与 token 获取前；撤权会停用 token，账户切换后的迟到 token 不注册。POST_NOTIFICATIONS 由原生 Notifications library manifest 提供，本轮实际 Gradle 合并 manifest 已核实存在；真实推送送达仍需单独验收。
- 返回：主页面硬件返回交系统后台行为，次页面通过 Expo Router 参数返回；Sheet 使用 Modal.onRequestClose，不依赖 iOS 手势。尚无 Android 设备 UI 验收，不宣称键盘/手势实测通过。
- 日历：Android 手动系统日历入口及显式选择来源后的同步有实现；Apple 提醒事项明确 iOS-only。云 Agent 的 NativeActionSession/Panel 目前也明确只对 iOS 开启，Android 不应宣传同等原生执行能力。
- React Native 已安装版本的 Gradle version catalog：minSdk24、compile/target36、build tools36.0.0、NDK27.1.12297006。兼容性下界只是配置事实，不能取代 Android9 或其他 ROM 真机测试。

## 对外测试还缺的真实条件

1. 已有本地生成的调试签名独立 APK，MI 6X/API28 安装成功；仍需跑启动、分享唤起、系统拒权/撤权、Activity 回收、通知点击与键盘/返回真机流程。正式发布仍需明确签名所有权与版本/分发配置。
2. 当前源码没有 EAS projectId / Android Firebase google-services 配置；远程推送需要匹配项目、FCM 与后端 provider 配置，再验证真机回执。不能把 UI 可点击或合成 provider 回执视为真实通知送达。
3. `expo install --check` 检出5项 patch 建议：expo57.0.26→57.0.27、image-manipulator57.0.20→57.0.21、linking57.0.11→57.0.12、router57.0.24→57.0.25、sqlite57.0.3→57.0.4。没有擅自升级正在 iOS 验收的共享依赖；发布冻结前应统一版本并重做双端构建。
4. Apple Developer 未开通影响 iOS 的签名/分发，不阻止本轮 Android APK 构建；不能把 Android 测试 APK 等同于 iOS 已获分发资格。首轮人数仍未定，两平台均需纳入验收，iPhone 为主。

## 核实来源

- [Expo57 ImagePicker：getPendingResultAsync](https://docs.expo.dev/versions/v57.0.0/sdk/imagepicker/)
- [Expo57 Notifications：Android channel、projectId、开发安装包](https://docs.expo.dev/versions/v57.0.0/sdk/notifications/)
- [Expo57 Sharing：接收分享配置](https://docs.expo.dev/versions/v57.0.0/sdk/sharing/)
- [React Native 0.86：JDK17 环境要求](https://reactnative.dev/docs/0.86/set-up-your-environment)
- [Adoptium 官方 Temurin 下载与 API](https://adoptium.net/temurin/releases/)
- [Android 命令行工具下载与许可](https://developer.android.com/studio#command-line-tools-only)
- [Android sdkmanager 安装与许可操作](https://developer.android.com/tools/sdkmanager)
- [Android Network Security Configuration：精确域匹配](https://developer.android.com/privacy-and-security/security-config#domain)
- FileSystem 版本页本轮抓取失败；恢复 copy options/hash 及 content URI 原生实现以安装的 `expo-file-system@57.0.7` 类型声明、Android 实现为准，未使用其他 SDK 版本示例。
