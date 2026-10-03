# Wearing 电脑接入与持续陪伴 · 2026-10-02

历史记录：后续的实际电脑验收与角色交互替换见 [2026-10-03 验证](character-states-2026-10-03.md)。下文记录当时状态，非当前交付状态。

本轮基于用户“在本机试验电脑接管、继续打磨 IP 和交互”的授权实施。现有手机、文件空间、模型凭据和连续对话继续保留。

## 电脑控制

选择已有 Hermes `computer_use`，底层为 Cua Driver，未另写点击或读屏驱动。当前 Hermes 固定提交 `367441274c48a03d12ee9f8d3d9ccd9bc1585392`，其 PM 锁定 Cua Driver `0.21.0`。本机通过 PM 安装并校验，驱动未打包进 Wearing 的 wheel。参考：[Hermes 官方说明](https://hermes-agent.nousresearch.com/docs/user-guide/features/computer-use)、[Cua 源码](https://github.com/trycua/cua)。

Wearing 新增安装、实际权限检查、显式接入、暂停与交回。接入后才把 `computer_use` 放入模型工具集；保留 standard/manual 权限，不开放 terminal、任意代码、消息平台或调度器。默认后续观察为 AX 文本，适合当前文本模型；截图仍属于需要视觉模型的独立能力。

暂停直接使用 Hermes 的跨进程控制 lease：不排队等待当前模型回合结束，后续观察和操作被拒绝，操作过程中发生接管时丢弃该次观察结果。已发出的输入无法保证撤回。该 lease 按 Wearing/Hermes profile 生效；这不是阻止其他软件或其他 profile 使用电脑的系统级隔离。

最终探测：Cua Driver 已安装；辅助功能已由用户开启并读回为 `true`，屏幕录制仍为 `false`，电脑尚未接入。已在系统设置中定位并选中实际运行目录里的 CuaDriver.app，停在添加前，等待用户点击打开并授权。Wearing 也新增了缺项提示与实际应用路径说明。真实读屏、点击、中文填写仍待系统权限后验收，不能把代码接入等同于真机成功。Windows 路由沿用上游跨平台实现，尚未真机验收。

准备了独立原生测试窗口（私有 QA 目录中的 `ComputerProbe.swift`／`WearingProbe`），仅用于后续输入→点击→读回实验，本轮未启动或操作该测试窗口。

## 交互

- 同一个完整蓝色卷袖角色从欢迎场景移到聊天输入区，单个 video 节点继续播放。
- 轻拍有一次短促布偶摆动与文字回应；工作、输入、等待确认、接管与离线由真实状态显示。
- 普通按钮、输入框、抽屉更圆润，提供按下和进入反馈。
- 手动暂停保存在本机；减少动态效果、隐藏页面、角色离屏和人工接管时暂停。视频失败时保留独立封面。
- 沿用已修复的 720p 无声循环；未新购或生成素材。

真实浏览器检查：欢迎→对话、角色轻拍、暂停、重载后偏好保留、设置抽屉、320px 与 390px 窄屏。两种窄屏 `scrollWidth == innerWidth`，对话状态仅有一个 video，已加载到 readyState 4。隔离预览数据在 8766，主对话 8765 未注入测试消息。

截图：[欢迎区](presence-2026-10-02/welcome.jpg)、[窄屏对话](presence-2026-10-02/conversation-mobile.jpg)、[主页面持续陪伴区](presence-2026-10-02/companion.jpg)。它们是实现预览，不代表用户最终审美验收。

## 验证

- Python：74 项通过，含真实固定版本 Hermes API 适配器合同检查。
- 原版 Hermes lease 验证：接管后 capture 与 type 均在驱动启动前被拒绝；错误 holder 无法交回，正确 holder 可交回。该项没有向真实屏幕发送输入。
- JavaScript：持续角色、手动暂停、系统偏好变化、离屏、人工接管及媒体失败回退通过；语法检查通过。
- 设计扫描已运行，报告的色阶、圆角及字号文档偏差已在 DESIGN.md 中补充本轮取值；扫描不是审美验收。
- wheel 与 sdist 构建通过。
- 主服务重启后引擎正常，原 4 条消息的完整 JSON SHA-256 与重启前一致。

私有检查记录在 `.wearing/qa-desktop-presence-20261002/`。本轮未修改 API key、提交外部内容或进行真实业务交易。
