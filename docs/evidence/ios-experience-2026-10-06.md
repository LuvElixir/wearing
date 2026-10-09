# iPhone 交互预览验收 · 2026-10-06

## 交付范围

当前阶段是可操作的 Expo/React Native 设计预览，不是签名 App 或 TestFlight。入口：http://127.0.0.1:8793/experience 。原有主客户端与 8765/8789 业务服务保持原状。

所有内容均为明确标注的示例，仅保存在 DemoProvider 本次会话内；刷新会恢复初始值。不调用麦克风、模型、付款、联系人或真实日历接口，不发送反馈。用户目标机为 iPhone Air；iOS 版本待核对。会员注册名义仍待用户决定，未付款、未提交 Apple 身份资料或接受会员协议。

## 已验证

- `npm run typecheck` 通过。
- 直接运行安装的 ESLint，覆盖 `src/experience`、`src/app/experience`、静态预览脚本，通过。标准 `expo lint` 在此机受全局 npx ESM 配置影响，未用该失败入口掩盖源码检查。
- 既有移动客户端 19 个核心测试通过。
- Expo web 与 iOS 资源导出通过；iOS 导出是 bundle/资产，**不是 IPA**。
- 静态服务器仅监听 127.0.0.1。handler 的 SPA、资产404、API404、路径越界、编码、Host、方法、HEAD 共10项检查通过。没有API代理。
- 在真实浏览器 420×900 与 1180×920 布局下查看；宽屏的手机框为430px。
- 现在→回看→Todo 勾选、笔记编辑保存与返回通过；回看是审核入口，没有新建笔记或Todo聊天导流按钮。
- 语音示例开始、结束、编辑、关闭后重新打开仍有文字、带入主草稿、发送进入对话通过。最新消息在实际布局后滚到可见位置。
- 记忆纠正保存、目标暂停/恢复、方案切换及预算变化通过。
- 确认周末时间后，10月10日出现示例事件，详情标题和时间与所选事件一致。
- 断网示例保留文字，发送按钮不可用；未表现为真实发送成功。
- 最终构建切换文字后焦点进入输入框；日历/Todo/笔记分段命中区实际44px。
- 可点击控件默认button语义，tab/checkbox保留专用角色；真机VoiceOver未验收。

## 设计复查

独立 Impeccable reviewer 首轮 `disposition: fix`：嵌套方案卡误示多入口；早拍导致语音/结果状态不完整；桌面flex覆盖失败拉宽；可点击控件语义不全。

修正：首屏改单张事项卡和无底色的方向摘要；结果进入不低于0.92不透明度并重拍稳定状态；手机框显式flex约束，桌面Sheet对齐框；TactilePressable默认button并允许覆盖。独立复验三项均resolved，最终 `disposition: ship`，范围仅限交互预览。

截图：
- [桌面全貌](images/ios-experience-20261006/desktop-final.png)
- [现在](images/ios-experience-20261006/now-final-420.png)
- [语音](images/ios-experience-20261006/voice-final-420.png)
- [结果](images/ios-experience-20261006/result-final-420.png)
- [对话](images/ios-experience-20261006/conversation-final-420.png)
- [离线](images/ios-experience-20261006/offline-final-420.png)

## 后续验收

iPhone真实录音/中断、键盘避让、触觉、边缘返回、Dynamic Type、VoiceOver及系统回收恢复尚未验收。生产登录、可达HTTPS服务、推送和真实Apple日历也不因示例可点而视为接通。账号归属确认与会员激活后再开始签名、设备安装和TestFlight路径。

体验设计规则见 [iPhone设计记录](../design-ios-experience.md)，分阶段交付见 [内测计划](../plans/ios-personal-alpha-2026-10-06.md)。
