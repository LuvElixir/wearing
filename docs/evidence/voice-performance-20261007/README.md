# 语音修复验收

2026-10-07。实际 iPhone Air / iOS 27.0 **模拟器**，Expo Go，`/voice-lab` 开发专用路线。使用独立 wearing-voice-qa.db，语音状态为合成驱动；无麦克风、网络录音、用户资料读写。

- `native-processing.png`：200/200 原生 SQLite 并发检查通过，输入栏只有一处识别反馈，栏高 58 pt。
- `native-error.png`：同一 IntentComposer 的错误提示净化检查，无 Swift/SQLite 堆栈，栏高不变。
- `native-final.mp4`：原生三点动画及错误状态切换录屏，非识别速度或真实语音证明；未用此录屏推算帧率。
- `native-processing.mp4`：较早录屏，期间新增平台文件引发 Fast Refresh，不用于最终动画验收。出现开发运行时 ExpoAsset 缺失后已完整 Reload，最终页面和存储重新验收通过。
- `activated-api.json`：更新后的实际 LAN 入口，两份合成中文音频转写、原件摘要一致性。未发送 agent 消息或创建任务。

量化性能见 [报告](../../../perf/报告.md) 和 [配对数据](../../../perf/bench/voice-warm-20261007.json)。
