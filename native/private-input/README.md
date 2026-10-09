# Pajio Private Input

专用 Android IME，用于人类接管期间的 Unicode 私密输入。现有 uiautomator2 的广播输入会在 Android 广播历史留下 Base64 文本，不能承担密码输入；本组件不使用广播、clipboard、内容文件或日志，也不申请 INTERNET 权限。

`PrivateInputMethod` 是唯一 Android 组件，由系统 `BIND_INPUT_METHOD` 权限保护。它监听 abstract Unix socket `pajio.privateinput.v1`。仅内核 peer UID 0/root 或 2000/shell 可以发请求；`SocketClient` 从实际包管理器得到的预期 UID 反向检查服务端，防止其他 App 抢占同名 socket。身份检查依据 [LocalSocket.getPeerCredentials](https://developer.android.com/reference/android/net/LocalSocket#getPeerCredentials())。文本通过 [InputConnection.commitText](https://developer.android.com/reference/android/view/inputmethod/InputConnection#commitText(java.lang.CharSequence,%20int)) 送到当前输入框。

模型与可运行任意命令的 Agent 必须在其他 VM；此安全边界不能抵御执行手机内的恶意 root、shell 或已被入侵的系统。普通第三方 App 没有上述 Unix UID，也不能用广播调用输入。输入已交给目标 App 后，目标 App 自身仍可能存储它。

## 构建与部署

只使用已授权安装的 Android SDK 36/build-tools 36.0.0 与 JDK 17，无 Gradle 或联网依赖：

```sh
python3 native/private-input/build.py \
  --sdk /path/to/android-sdk \
  --java-home /path/to/jdk17 \
  --output /private/build-output \
  --signing-directory /private/persistent-signing
```

签名目录首次生成 PKCS12 密钥及 0600 密码文件，后续构建复用；不得将该目录入库。产物为已验证 v2/v3 签名的 `pajio-private-input.apk` 和包含所有源文件摘要的 `manifest.json`。安装前核对该摘要，安装后通过 `pm path` 与设备文件摘要再核对。APK 更新必须保留签名密钥。部署端还应保存 APK 到 `/opt/pajio-native/pajio-private-input.apk`。

```sh
adb -s YOUR_FIXED_SERIAL install -r /private/build-output/pajio-private-input.apk
```

媒体宿主资源配置 `unicode_ime: true` 后，会先核对已安装 IME，再按需切换。原 IME 名称只保存于当前宿主会话，退出时恢复并 force-stop 专用 IME。若旧会话崩溃，默认 IME 已是专用 IME 而无法确定之前的输入法，拒绝输入，交给宿主恢复；不会猜测用户设置。`unicode_ime: false` 和低帧率截屏降级均显示 `text: unavailable`，没有不安全的文本兜底。

## 二进制协议

启用前及每次调用客户端前，宿主读取已安装 APK 的 SHA-256，与 `private_media_android.PRIVATE_IME_SHA256` 固定值核对。包名或 UID 相同但代码不同会拒绝输入。更新 APK 时须经过审查、签名与设备验收，再同步更新该固定值；不能仅配置新包名跳过验证。

宿主以固定参数启动 APK 内的 `SocketClient`：`adb shell -T env CLASSPATH=<installed APK> app_process / io.pajio.privateinput.SocketClient <expected UID>`。输入数据是二进制 stdin，不是 shell 脚本或 argv；stdout 只有一个状态字节。ADB `exec-out` 在此次实际环境不转发 stdin，因此不用于此路径。

请求为 `PIM1` 四字节、32 字节会话 nonce、1 字节 operation、4 字节大端 payload 长度、UTF-8 payload。operation 1 输入（0 长度仅探活），2 释放租约（必须为 0 长度）。最大 payload 16 KiB。服务端仅接受当前 nonce，30 秒无输入租约过期，新的合法宿主可以重新获取。宿主仍在每次输入前后校验产品 Gateway 的 scope/session/epoch；Android nonce 不能代替该授权。

响应 0 表示 InputConnection 接受、1 租约不匹配、2 没有当前输入框、3 无效输入或空探活、4 结果不确定、5 客户端无法确认端点或通信。只有不含文字的探活可重试；实际文字没有自动重试。接口的成功表示已送入输入连接，不替目标 App 提交表单。

两个 Java 端及 Python 宿主清理自有 byte buffer，IME 不学习输入、不同步剪贴板。Java 字符解码、Binder、操作系统及目标 App 可能产生副本，不能据此宣称所有内存完全清零。当前 Android 输入框也不会被擅自清空；用户退出敏感页面后才明确归还 Agent。

Android 可能已在关闭时销毁 IME 服务，因而租约释放请求没有 ACK。宿主仍须验证固定 APK 摘要，恢复并读回原默认 IME，成功 force-stop 专用包，再通过完整进程名列表确认专用进程不存在。全部后置条件成立才承认已清理；仅缺失 socket ACK 不能替代这些证据。任一后置条件失败保留待清理身份并保持暂停，后续明确连接只可重试清理，不重放输入。

## 实测

[云手机验收与摘要](../../docs/evidence/private-input-20261010/acceptance.md)记录真实 redroid 14 中英输入、日志残留、UID/nonce拒绝及清理。安装包的公开签名证书 SHA-256 为 `eef6a7bfb3499904f029b343fde8a2d9fb4328d2d9dbd0d3b5196a228b62a321`。测试均使用合成标记，无真实用户密码。
