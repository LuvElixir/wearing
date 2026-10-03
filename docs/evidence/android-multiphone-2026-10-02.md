# 多手机资源与中文输入验收

日期：2026-10-02。Wearing 个人模式 v4。开发 Mac arm64 / 小米 MI 6X / Android 9（SDK 28）/ USB。

## 交付与实机结果

- 多部 Android 可以分别接入，旧绑定自动迁移而不覆盖其他设备。每台有自己的 resource_id、在线/授权状态、启用/暂停状态和字段填写验收时间。
- 模型先发现设备，随后每个动作明确指定 resource_id。离线或暂停时不替换目标设备。同一 OS 用户下的 Wearing 实例共享分设备执行锁，不同手机互不占锁。
- Mobile MCP 1.0.7 提供九项基础控制；新增 mobile_list_devices 和 mobile_set_text，总共十一项。文件空间仍为六项工具。
- UiAutomator2 3.7.0 在原生输入框进行单次全文替换，并核对写入前旧值与写入后全文。不会提交，不安装输入法 APK、不切换输入法、不需要 root 或 SIM。
- 真实 DeepSeek `deepseek-flash` 模型读取设备列表与设置搜索页，将“你好，Wearing”替换为“Wearing 帮我行动”，随后重新读取相同字段。独立于模型，再次调用界面读取并用 ADB 获取截图，确认完全一致。
- 模型 task：`aa5c58bc08a9414fa7e58a8a9d2a8443`；run：`run_fdf1229616c34a96b3c3ad35157cafb7`。业务状态保留 completed_unverified；测试人员的独立核对记在本文，没有代替用户点击确认。
- 浏览器点击这台手机的暂停按钮，真实 MCP 调用被拒绝，is_error=true。再从同一张卡片恢复，手机重新可用。

手机实际结果：[截图](screenshots/wearing-android-chinese-20261002.png)。界面：[连接面板](screenshots/wearing-multiphone-panel-20261002.png)。[结构化证据](android-multiphone-2026-10-02.json)。完整 SSE 保留在私有 QA 目录。

## 兼容范围

| 路线 | 当前状态 | 前提 / 尚未验证 |
| --- | --- | --- |
| 开发 Mac + 小米 6X / Android 9 | 真机已验证 | USB 调试与 MIUI 的安全调试授权；读取、点击、滑动、英文及中文原生字段填写 |
| 其他 Android 品牌/版本 | 通用 ADB 与 UiAutomator2 接口已接入 | 需要逐机验证厂商输入授权、锁屏、后台限制、WebView/自绘界面 |
| 同时连接多部 Android | 注册、路由、独立暂停/锁与离线拒绝已自动测试 | 用两个模拟资源通过真实 MCP 协议测试；第二台真机尚未接入，不等于多机实测通过 |
| Windows 主机 + Android | 安装与驱动路径按 Windows 处理 | 可能需要 OEM USB 驱动；Windows 主机没有实测 |
| 闲置 MacBook Air | 使用同一连接器设计 | 非当前开发机，硬件/系统与实际安装未测试 |
| iPhone | 尚未实现连接器 | 走 WDA/XCUITest 独立路线，需设备信任、签名/配置；iOS 16+ 开发者模式等要求按官方文档落实 |

产品目标是让用户已有设备尽可能接入，不承诺所有手机插线即可操控。依赖官方支持范围不等于 Wearing 实测范围。U2 原生填写暂不支持密码字段、缺少稳定标识的字段、WebView 或自绘输入控件；失败后先重新观察，不静默换输入方式重复写入。

## 验证与实现边界

- 63 项 pytest 通过，包括真实 Hermes + MCP v2 工具发现、两设备资源路由、锁隔离、暂停、离线、旧配置迁移、记录隐私，以及失去写入响应时单次执行/清理。
- Node 语法与现有动画生命周期检查通过。wheel/sdist 构建成功，包内含 U2 锁文件、哈希和 MIT 许可证；不含 .wearing 私有目录。
- 所有Python依赖固定版本和哈希。U2服务按操作短暂运行，结束时关闭自身启动的进程。依赖的单次 JSON-RPC 私有接口有单元测试，升级须重新验证。
- pause 只阻止后续动作，不撤回在途动作。设备锁不能阻止其他软件、用户本人或其他 OS 用户操作。动作记录未自动关联 task_id。断线重连、锁屏、长时间运行与远程接管仍需后续实测。
- 本次实际安装时发现 Hermes PM 将 uv 作为内部工具，不加入普通 PATH；改用其 uv_launcher 解析路径后，连接器安装成功。
- 一次完整测试中旧的 8 秒引擎启动等待超时；日志显示随后已就绪。验收等待上限调整为 30 秒，63 项重新全部通过。

测试使用独立 QA 数据库；主对话仍为 0 条，原草稿保留。主 Wearing 与执行引擎保持运行。

## 上游依据

- [UiAutomator2](https://github.com/openatx/uiautomator2)：复用成熟的 Android UI 服务与原生字段接口。
- [Mobile MCP](https://github.com/mobile-next/mobile-mcp)：基础跨设备操作；本轮固定 legacy ADB 路线。
- [Appium XCUITest 设备准备](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/device-setup/)：iPhone 的信任、开发者模式与 WDA 准备，不能把 Android 接入结果外推到 iOS。
