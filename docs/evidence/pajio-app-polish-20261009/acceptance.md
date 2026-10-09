# Pajio App 体验优化验收 · 2026-10-09

本轮只修改 `clients/mobile` 的交互连续性和动效。不改 Web、桌面实现，不发布生产服务，不接入尚未验收的 WorkBuddy 候选视频。保留工作区原有未提交改动。

## 已完成

| 体验 | 实现结果 |
| --- | --- |
| 聊天输入 | 切页时收起键盘；返回后保留文字模式和草稿，不自动抢焦点。身份切换清除待执行的焦点请求。发送增加当前页面及最新发送状态检查。 |
| 录音反馈 | 只有真正进入录音状态才显示录音强调色，准备阶段不会提前表现为已开始录音。 |
| 阅读位置 | 今天、任务各分栏、记忆首页和我的首页按连接身份保留本次使用中的滚动位置。用户触摸优先于迟到的恢复；iOS 上下回弹值按有效范围保存，避免返回后延迟跳动。 |
| 任务刷新 | 后台读取不反复打断刷新按钮；用户操作可排在正在进行的读取之后，连续点击合并，不自动重试结果未知的写入。刷新保留已有结果和展开状态。 |
| 小熊换衣 | 八套睡衣统一为 150ms 合帘、230ms 开帘的短过渡；连续点选以最后一套为准，图片、名称及保存状态保持一致。只挂载当前与待展示的大图。失败可重试；未保存离开保留原穿搭。 |
| 降低干扰 | 去掉小熊每 23 秒重复播放招呼的循环；每次挂载只完整播放一次，退后台暂停。修复减少动态效果设置异步读取覆盖新偏好的竞争。 |

换衣仍是对齐后的图片配合原生遮挡过渡，不是三维骨骼或真实布料模拟。小熊离开后重新挂载仍可再次招呼，不宣称全 App 会话只播放一次。

## 实际原生验收

环境：iPhone Air / iOS 27.0 模拟器，Release 原生构建；仅连接本机 8892 隔离 QA 服务、合成身份 `qa`。没有调用真实模型、ASR、外部连接器或远程物理设备。

- 输入 `QADRAFTKEEP-DONOTSEND` → 今天 → 聊天：草稿保留、焦点不自动恢复。没有发送；结束后清空了本次合成草稿。模拟器启用硬件键盘，本次没有验证物理 iPhone 的软键盘遮挡。
- 换衣连续点奶油月牙、杏桃方格：最终图片与名称、保存按钮一致；未保存离开后仍为雾蓝条纹。
- 保存奶油月牙，退出重进并切深色外观：已保存穿搭与深色页面显示正常。
- 任务滚动到底 → 记忆 → 任务：返回截图保持相同历史记录位置。
- 任务详情展开原话 → 刷新：显示“进展已更新”，原话和返回结果仍可见，展开状态保留。

### 原生检查中发现并修复的问题

第一轮实际操作发现 iOS 底部回弹的超界 offset 被保存，切回任务页需等 1500ms 才夹取恢复。已限制保存范围并容忍 1pt 布局舍入差，新增行为测试，重新构建安装后复测通过。

- `tasks-position-before.png`、`tasks-position-restored.png`：第一次发现问题的证据，后者记录修复前的顶部跳转。
- `tasks-fixed-before.png`、`tasks-fixed-return.png`：最终版本切页前后位置一致。
- `task-detail-refreshed.png`：刷新后仍展开原话。
- `chat-draft-return.png`：返回聊天后草稿仍在。
- `wardrobe-dark.png`：深色衣橱与保存状态。

## 自动检查与构建

- 740 / 740 测试通过：`tests-final.log`。
- TypeScript 检查通过：`typecheck-final.log`。
- 源码 ESLint 通过：`node node_modules/eslint/bin/eslint.js src App.tsx index.ts`，见 `lint-source-final.log`。
- 原有 `npm run lint` 的 Expo 包装命令被本机全局 `npx` 的 CommonJS/ESM 配置错误阻断，未修改全局工具链；直接执行了对应源码范围的 ESLint。
- `lint-direct.log` 是曾误纳入已生成 dist 的全目录检查失败日志，不作为源码 lint 结果。
- iOS 模拟器 Release 构建成功并安装：`xcodebuild-final.log`。
- Android JS/资源导出通过：`android-export-final.log`。本轮没有重新构建 APK，也没有 Android 真机体验结论。
- 本轮 15 份改动源码与最终原生构建候选的 SHA-256 一致：`build-manifest.json`。

## 可供 ZCode 只读参考

核心文件为 `IntentComposer.tsx`、`Mobile.tsx`、`tab-scroll-memory.ts`、`AgentTaskList.tsx`、`TaskDetailPanel.tsx`、`task-request-queue.ts`、`WardrobeStage.tsx`、`WardrobePanel.tsx`、`wardrobe-transition.ts`、`LivingPajamaBear.tsx`。Web/桌面迁移应保留平台原生输入与滚动逻辑，不复制模拟器专用配置或 QA 身份。
