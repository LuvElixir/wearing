# Android 私密输入与连续视频实测

日期：2026-10-10（北京时间）。对象为独立 redroid 14 云手机，仅使用生成的合成文字，无真实用户账号或密码。

## 发现与修复

对 uiautomator2 3.7.0 内置 APK（SHA-256 `6f85594700ad96de89d012b3767049c2c6988510b68b31b439dd2a6dd93a30c9`）进行实际测试：中文成功输入，logcat 未命中，但 `dumpsys activity broadcasts` 两处留下 `extras: Bundle[{text=<Base64 合成标记>}]`。因此包名限定和宿主 stdin 不能令广播成为私密通道。该路径已移除；普通 `adb input text` 的设备子进程 argv 风险亦通过禁用该文本兜底解决。

最终自建 IME 使用双向内核 UID 检查和短期 nonce 的本地 socket，宿主以 `adb shell -T` 二进制 stdin 调用固定 APK 内客户端。源码在 `native/private-input`，没有广播接收器、provider、clipboard、联网权限或内容日志。文字不进入 shell 脚本或进程 argv。安装 APK SHA-256：`80960fcaa86936abdf20de79660ea63cbc10f024b3f43b3a6ee53e92c1037c27`；源摘要见 [build-manifest.json](build-manifest.json)。专用 APK 已在执行 VM 保存为 `/opt/pajio-native/pajio-private-input.apk`。

## 实测结果

[input-acceptance.json](input-acceptance.json) 记录：

- 原生滑动实际改变设置页面；原生点击打开系统搜索。
- 中英文、emoji、`%` 混合文字完整出现在目标输入框。
- 当前 logcat、广播历史、input_method dump 和 ps 中，合成标记明文及 Base64 均为 0 命中。
- 错误 nonce、错误服务端 UID、非 root/shell Android UID 的调用均未写入文字。
- 关闭后恢复原 LatinIME，专用 IME 进程不在运行，nonce 的自有可变缓冲清零；没有 IME TCP 转发。
- 宿主在启用 IME 前及每次 SocketClient 调用前，读取已安装 `base.apk` 的 SHA-256 并与代码中的固定摘要核对；执行 VM 实测摘要一致。单元测试覆盖首次连接及会话内同名 APK 替换，均在传输正文或运行客户端前拒绝。相关媒体、访问控制、API 与中继共 87 项测试通过。

[video-acceptance.json](video-acceptance.json) 记录官方固定 scrcpy 5.0.1 的连续 H264：720×1280，第一张解码帧 372 ms；5.012 秒内 85 张独立解码帧，78 种不同画面，测得 16.96 fps。配置上限为 24 fps，不把上限当作实测帧率。关闭后宿主进程结束、解码线程退出、最新帧引用清空、自有 ADB forward 移除；独立后续检查确认没有 scrcpy server 临时 jar、server 进程或 SocketClient 残留。

## 公网媒体与归还复测

首次公网失败的真实原因是初始化脚本重复设置宿主 Android 数据目录为 0700，导致 shell 无法遍历 `/data`，scrcpy 推送失败。设备 `/data` 恢复标准 0771，宿主外层目录仍受保护；初始化脚本由部署任务修复。

随后复现静止画面 3.24 秒后触发过期保护。官方 scrcpy 的[帧率说明](https://github.com/Genymobile/scrcpy/blob/v5.0.1/doc/video.md#frame-rate)明确帧率随画面变化。现在超过 0.75 秒无编码帧会实际读取设备截屏，标识 `capture_mode: adb-static-refresh`；旧帧时间不修改。30.06 秒静止验收，43 次独立捕获/解码，32 次真实截屏刷新，最大帧龄 0.71 秒，结束后两个图像缓存均清空。

还修复了归还时捕获线程与可信 clear 请求的竞争：`awaiting_scope` 保持隔离，成功清理才交还 Agent；清理失败仍暂停。相关测试增加首次/会话内 APK 替换、真实静态刷新和清理竞争覆盖，总计 92 项通过。

[public-media-acceptance.json](public-media-acceptance.json)记录已认证公网信令、双端只保留 TURN relay 候选的实际接收：720×1280，30 秒 643 帧、21.3 传输 fps；静止独立捕获 1.55 fps，明确不将传输 fps 当作新捕获率。显式归还到 `agent_ready`，旧 offer 返回 409，其他租户三项接口均返回 404。此次首帧 12.146 秒包括恢复上轮失败会话及等待 ACK，不是纯媒体建立时延。公网复测没有保存截图或发送输入。

这证明原生输入链路与测试客户端的公网媒体闭环；App WebView 实际交互、长时间使用和移动网络性能仍需主任务验收。真实密码输入框的显示行为由目标 App 决定，本测试不证明所有应用都不保存内容，也不证明操作系统所有内存副本已擦除。

## 输入法结束后的再次接管

原生 App 测试暴露后台退出后再次接管失败。真实设备定向复现：合成文字送达，测试主动结束 IME 服务，再执行原清理函数；原函数报告失败，但原 LatinIME 已恢复且专用进程不存在。原因是把释放 socket ACK 缺失永久等同于清理失败。30 秒租约过期本身会重新核对 nonce，不是本次已证实的原因。

修复后只有 APK 摘要、IME 恢复读回、force-stop 与进程退出四项后置证据都成立才判定清理成功。失败保留待清理上下文；已关闭会话仅能重试清理，不会恢复连接或重放文字。5 项新增测试覆盖 ACK 缺失、IME 不一致、进程残留、无法确认进程列表及清理重试，相关总计 97 项通过。

[reconnect-acceptance.json](reconnect-acceptance.json)记录同一宿主进程中的实际公网闭环：SCTP 合成输入收到 ACK，以按键清除，闲置 31 秒后测试主动结束 IME 服务，关闭连接与会话，状态为 `paused`；明确再次请求接管获得 74 帧，最后归还 `agent_ready`。首次会话收到 782 帧，整个测试未保存画面或输入正文。完成后宿主会话列表为空，LatinIME 已恢复，专用输入法进程不存在，ADB 转发为空。该测试使用 aiortc 客户端，App 原生后台/前台复验仍由主任务进行。

宿主部署只更新私密媒体源文件和专用 APK，未改配对/租户记录。原模块预像保存在执行 VM `/opt/pajio-native/backups/private-input-before-20261010/`。正常结束没有正在捕获的视频或持续执行的测试输入。

## 原生 App、模型工具、重启和状态备份

原生 App 验收由 App 任务在 iOS 27 Release 模拟器完成，连接真实公网服务和 Android 云手机：输入合成文字、按 iOS Home 切到后台后停画面并保持暂停、前台不自动接管、明确重新接管恢复画面、退出目标输入页后两项确认并收到设备交还 ACK。证据保存在私有验收目录的 `mobile-android-final-{text,paused,reconnected,returned}.png`。这是原生模拟器验收，尚不能替代物理 iPhone 的耗电、键盘和移动网络体验验收。

[release-acceptance.json](release-acceptance.json)记录真实模型 `deepseek-flash` 通过设备工具读取在线状态并调用 `mobile_list_apps`。Hermes 会话记录具有真实工具调用，独立租户中继数据库记录 `phone.mobile_list_apps` 为 `completed`、`isError: false`，包含 `com.android.settings`；没有打开 App、输入或改设置。产品任务状态保持 `completed_unverified`，这与我们对具体工具链路的独立验收是两个层次。

随后从明确暂停状态重启云手机 VM：22.04 秒后 SSH 恢复，持久化标记保留、设备仍暂停且 Agent 操作被拒绝，媒体、ADB 和 Docker 均恢复运行。新接管会话经设备确认后可明确交还。VM 1112 已开启自动启动，顺序 5、启动等待 20 秒、关闭等待 60 秒，并读回核对。此重启测试验证的是控制协议；公网视频恢复另行复查。

状态备份停止连接器、媒体及 Android 容器以形成一致副本，再逐项恢复；服务启动和 Android `boot_completed` 均复核。备份包含 2,227 个成员，压缩后 11,692,293 字节，在 Mac 上流式 AES-GCM 加密，不落地明文；完整解密校验和腾讯云广州独立云主机上的密文摘要校验均通过后，删除执行 VM 的临时明文归档。前置检查执行 VM、Mac 和异机容量，恢复失败会报告固定组件名。此处完成的是备份完整性及原服务恢复验收，尚未从该归档重建全新 VM。

备份后的公网复查通过：双端仅使用 TURN relay 候选，首帧 4.515 秒（含接管与信令），30 秒收到 516 帧，传输 17.19 fps、静止画面独立捕获 1.01 fps，720×1280。成功明确归还 `agent_ready`，旧 offer 为 409，另一租户三项访问接口均为 404。本轮没有保存画面或输入内容。
