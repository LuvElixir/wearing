# Wearing 中文语音服务选型

2026-10-07。决策：主选豆包 Seed-ASR 2.0，使用官方语音服务，不再使用 Whisper Small。

## 比较口径

优先考察中文口述、生活人名地名、日期金额、中英混说、口音、取消和松手响应。不同厂商自报的“准确率”不能直接横比；公开数据集也不等于本人的 iPhone 录音。目前没有相同 Wearing 语料上的各厂商对照实测，因此不声称豆包准确率第一。

| 服务 | 已核对的实时识别价格 | Wearing 适配判断 |
| --- | --- | --- |
| 豆包 Seed-ASR 2.0 | 1 元/小时，按量后付费 | 主选。提供一句话识别、双向流式、二遍修正、热词；中国大陆接入与中文生活场景匹配 |
| 阿里 Fun-ASR realtime / Qwen3-ASR flash realtime | 0.00033 元/秒，约 1.188 元/小时 | 备选。需用同一组用户自愿提供的语料比较实体错误率和松手延迟 |
| 阿里 Paraformer realtime v2 | 0.00024 元/秒，约 0.864 元/小时 | 单价更低，但不能仅凭价格判定综合体验更好 |
| 腾讯实时识别大模型 2.0 | 1 元/小时；混元 ASR 当前文档标注内测 | 可对照评估，但新模型访问资格与成熟度需要确认 |

以上按实时产品口径比较，不把录音文件离线接口价格混入。若每人每天说 10 分钟，30 天为 5 小时，豆包 ASR 约 5 元/月；这是单独 ASR 成本，不含 Agent、网络与服务器。

## 为什么选择这个接入方式

`bigmodel_nostream` 是一句话识别：输入可分包，返回句级结果，官方定位于输入法与 IM 转写；资源 `volc.seedasr.sauc.duration` 明确选择 2.0。当前先服务松手后保存的完整录音，输入为本机解码的 16 kHz 单声道 PCM。只接收完整终包作为草稿；`enable_ddc=false`，避免“语义顺滑”删去否定或自我纠正；开标点及数字规整。

**云端 WebSocket 协议不代表手机流式输入已经交付。** iPhone 当前仍录完整段 M4A 后上传。真正边录边传、临时文字、松手末尾音频封存和安全中继，按 [流式接入计划](../plans/voice-streaming-2026-10-07.md) 实现并单独真机验收。

控制台“录音文件识别2.0 已开通”不能推断所有资源已授权。本轮对极速资源 `volc.bigasr.auc_turbo` 的合成音频请求返回 403 / 45000030（requested resource not granted），所以没有把它作为已接通功能。最终保持主选的一句话识别资源，按服务实际授权与 API 成功回执验收。

## 验收尺度

1. 合成短句先验证鉴权、原件保留、协议终包、时延；合成音频不能证明自然口音准确率。
2. 用户提供或明确允许的自然录音，覆盖金额日期、人名地名、中英混说、噪音和“不是 X，是 Y”。不自动重传历史私人录音。
3. 同批样本比较中文 CER、关键实体错误数、松手到最终文字 p50/p95；供应商中间结果和最终结果分开统计。
4. 取消不能送给 Agent；重试复用成功转写；断网/超时保留原件；服务错误不能进入输入草稿。
5. 每个会话有界，无自动付费重试；API Key 只留服务端私有配置，不发 App、二维码或日志。

## 官方资料

- [豆包模型与模式](https://docs.volcengine.com/docs/DoubaoVoice/model-list?lang=zh)
- [豆包计费](https://docs.volcengine.com/docs/DoubaoVoice/Billinginstructions-21?lang=zh)
- [一句话识别协议](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-automatic-speech-recognition-websocket?lang=zh)
- [实时识别协议](https://docs.volcengine.com/docs/DoubaoVoice/bidirectional-streaming-automatic-speech-recognition-websocket?lang=zh)
- [录音极速接口与资源](https://docs.volcengine.com/docs/DoubaoVoice/LargemodelrecordingfileLiterecognitionAPI?lang=zh)
- [阿里模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)
- [腾讯实时识别计费](https://cloud.tencent.com/document/product/1093/35686)
- [腾讯混元 ASR 接入说明](https://cloud.tencent.com/document/product/1093/135476)
- [Qwen3-ASR 技术报告](https://arxiv.org/abs/2601.21337)（厂商评测，不能替代本产品同集实测）
