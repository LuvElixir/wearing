# 本地语音识别修复与基准 — 2026-10-07

## 已定位并修复

1. 原实现每次转写启动一个 Python 进程并载入 small/int8 模型。新实现复用一个只接受单请求的本地 JSON-lines 解码器；空闲 180 秒释放，服务退出时关闭。录音文件仍先落盘，身份检查仍先于转写，没有改变 HTTP 返回结构，也没有启用新的云端语音提供方或下载模型。
2. 持续进程复用同一文件锁，与原件整理/OCR/其他 HTTP worker 互斥。超时、取消、破损响应或进程故障会终止该解码器；下一请求创建新进程，避免把迟到的上一份结果错配给当前录音。模型前文条件仍为关闭，逐请求不带上一段文字。
3. 去掉错误的第二轮片段过滤。旧实现只保留 `avg_logprob > -1 AND no_speech_prob < .6` 的片段，但 upstream 已经过 VAD、重试和联合静音判断；这层过滤会丢掉 upstream 已接受的有效片段。现在直接连接 upstream 发出的片段；模型无语音结果仍为空，不补造文字。
4. 解码器测量本地解码、权重加载、识别耗时。worker 以标准 Python `wearing.capture_worker` INFO logger 写入白名单数值；不记录录音路径、身份或转写文字。部署若未配置这个 logger 的 INFO 输出，不应声称实际已收集日志。

## 原始资料

当前依赖为 faster-whisper 1.2.1。对应官方 [转写源码](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py) 的 `generate_segments` 在决定跳过无语音片段时明确保留 log probability 足够高的候选；`generate_with_fallback` 也会结合两个指标进行回退与静音判断。已同时对照本机安装源码；不是仅按阈值猜测。

本轮保留 `beam_size=5`、CPU/int8、4 线程、VAD、已有提示和语言自动识别。没有以降低搜索宽度换速度，也没有得到用户口音、专名或真实环境的 WER/CER 提升数据。

## 配对基准

机器为 Apple M5 MacBook Air，16 GB 内存。测试素材由 macOS `say` 的「Tingting (中文（中国大陆）)」生成，长度约 8 秒，不包含用户录音。

合成语句：明天下午三点提醒我拿快递，周末想找一个人少一点的地方走走，预算五百块。

复验（先准备好本机已授权的模型，不会自动下载）：

```sh
say -v 'Tingting (中文（中国大陆）)' -o /tmp/wearing-voice-bench/sample.aiff '明天下午三点提醒我拿快递，周末想找一个人少一点的地方走走，预算五百块。'
.venv/bin/python perf/bench/voice-warm.py --audio /tmp/wearing-voice-bench/sample.aiff --output perf/bench/voice-warm-20261007.json
```

[完整原始结果](../../perf/bench/voice-warm-20261007.json) 保存素材 SHA-256、模型清单 SHA-256、运行时版本、源码 SHA-256、每一组顺序/耗时/转写及汇总。

[旧冷进程基线](../../perf/bench/voice-cold-baseline.py) 冻结旧实现；[基准脚本](../../perf/bench/voice-warm.py) 独立测量新进程首请求，然后做十组 cold→warm / warm→cold 交替配对。每组顺序执行，无并发竞争。p95 使用 nearest-rank，因此十次采样下等于该组最大值。这个结果测量服务端本地转写，不包含 iPhone 录音停止、上传、SQLite、本机网络和界面展示时间，不能当作真机端到端延迟，也不能当作准确率评测。

最终源码的十组结果：

| 测量 | p50 | p95 |
| --- | ---: | ---: |
| 原冷进程 | 3.2213 秒 | 3.2799 秒 |
| 已热身的新解码器 | 2.6735 秒 | 2.7153 秒 |

p50 减少 17.0%。新解码器第一次请求仍需 3.0237 秒，不能把热进程结果用于首请求承诺。10/10 组转写逐字相同；合成文字中的数字被正常规整为阿拉伯数字。源码 hash 已与当前文件复核一致。

## 回归

`tests/test_voice_decoder_worker.py`、`tests/test_voice_input.py`、`tests/test_capture.py` 共 46 项通过，覆盖有效片段不丢弃、空语音不补字、复用、空闲回收、跨 worker 互斥、超时/取消后不串结果、协议异常恢复、原件保留、身份隔离及缓存幂等。

## 下一层语音输入设计

要进一步逼近即时口述体验，应让录音采集与网络上传/识别重叠，而不是等文件全部结束后才发起。火山官方提供两种可评估协议：[单向流式输入](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-automatic-speech-recognition-websocket?lang=zh) 适合语音输入法/IM，在句末输出完整结果；[双向实时识别](https://docs.volcengine.com/docs/DoubaoVoice/bidirectional-streaming-automatic-speech-recognition-websocket?lang=zh) 持续返回会修正的中间结果。它们的产品适用说明可以支持选型，但不能证明豆包或微信 App 内部采用了哪一种实现。

若引入云识别，需要独立评估中文专名、口音、噪音、网络异常、费用与音频传输同意；本轮没有启用。已确认 Expo 57 提供实时 PCM 接口，当前整段输入是 Wearing 应用的实现方式，并非 Expo Go 的框架限制。后续接入见 [流式语音计划](../plans/voice-streaming-2026-10-07.md)。
