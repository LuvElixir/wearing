# Android 手机接入验收

此文保留首轮基础控制的历史验收。后续中文输入与多设备改造见[新版验收](android-multiphone-2026-10-02.md)。

日期：2026-10-02。开发 Mac（arm64）通过 USB 连接小米 MI 6X，Android 9 / SDK 28。闲置 MacBook Air 与 Windows 本轮没有实机测试。

## 实际结果

手机由 MTP-only / ADB 不可见，经过用户开启并授权 USB 调试后变为 `device`。截图和 UI 元素读取先通过，但第一次点击被 MIUI 拒绝；系统日志明确记录 input event injection permission denied。用户再开启 USB 调试（安全设置）后，点击返回成功，元素标题从“开发者选项”变为“更多设置”。本次没有 Root、插 SIM 卡、安装额外 APK 或更改输入法。

由 Wearing 的真实模型 DeepSeek `deepseek-flash` 执行：启动系统设置、观察界面、滑动找到搜索栏、点击、输入 `Wearing123`、读取界面确认。运行耗时约 52 秒。独立工具随后再次读取到 `ClearableEditText` / `android:id/input` 的值为 `Wearing123`，并查看实际截图确认。

- task：`0cb6fe00b3ab4b99ab9758fa86889fec`
- run：`run_6e47a58be4814903a3250338c40ce65e`
- 状态保留 `completed_unverified`，没有冒充用户调用核对接口。
- 模型中途调用了旧驱动不支持的前台应用查询，结果被正确标记错误。模型随后使用元素读取完成测试；最终工具表已移除这项能力，以实测可用的应用列表替代。
- 截图：[实际手机结果](screenshots/wearing-android-search-20261002.png)。详细工具名、错误与事件序号见[结构化记录](android-phone-2026-10-02.json)。完整 SSE 仅留私有验收目录，文档不复制设置页其他内容。

## 中文输入与兼容性

在同一搜索框尝试“中文测试”，上游明确返回缺少 DeviceKit；代理将其规范化为错误，并用中文说明未输入，绝不当作完成。目前英文/数字已通过，中文未接通。

当前 [DeviceKit 官方仓库](https://github.com/mobile-next/devicekit-android)已迁移到 MobileCLI；当前文档列出 Android 10+ 和 dex 运行方式，不能用来证明旧驱动需要的 APK 适配 Android 9。没有为了掩盖兼容性问题而直接安装最新包。中文需另行验证兼容的输入桥接方案。

## 产品与边界验收

- Wearing 原生手机面板显示 MI 6X / Android 9，支持准备、绑定、重新检测、暂停和恢复。
- 浏览器点击暂停后，代理真实调用返回 `is_error=true` / “手机操作已暂停”。随后从页面恢复并重新连接引擎。
- 绑定固定设备。自动测试验证另一个设备、绑定变化、暂停和设备忙都会在调用上游之前拒绝。
- 57 项 pytest 通过，包括实际 MCP v2 进程、精确工具暴露、文件与手机共同发现、暂停与设备锁、错误规范化和记录不含输入文字。
- 本轮沿用官方 Mobile MCP 1.0.7 与 Google Platform Tools 37.0.1；锁定依赖，核验下载，禁用 npm lifecycle scripts 和 Mobile MCP telemetry。源代码未修改。
- 元数据 action receipts 有独立 action_id / resource_id，正常返回仍是 returned_unverified。尚未与 task_id 自动关联，不是完整审计链。
- 暂停不保证撤回已发出的操作，也不能锁住用户本人或其他软件；锁屏、拔线重连、长期稳定性、视觉模型、人工远程接管、Windows 和 iOS 待验收。

测试对话数据库独立，主对话保持 0 条，原草稿保留。测试服务退出；主 Wearing 与引擎保持运行。

最终界面：[手机连接面板](screenshots/wearing-phone-connected-20261002.png)。恢复后再核对：引擎运行、手机在线且 enabled、文件工具 6 项、手机工具 9 项。Node 语法和动画生命周期检查通过，wheel/sdist 构建成功，包内含手机连接器源码、lockfile 与许可证且不含私有数据目录。
