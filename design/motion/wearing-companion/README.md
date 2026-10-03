# 当前交付：六种角色状态

2026-10-03：网页已使用 [states-20261003](states-20261003/PROGRESS.md) 的六段短动作，由状态驱动，不显示播放按钮。下面保留早期单循环制作历史。

# Wearing 挽袖动作

最终网页素材：`output/wearing-final-720.mp4`，720×720、5 秒、无声、可循环。实际网页使用 `src/wearing/web/character-cuff.mp4` 与同一视频首帧静态图。用户要求的主语义是“这件事，我来。”

`authors/presence.svml` 保存独立生图和袖口动作的提示词；`runs/presence.svrun` 使用已接受的挽袖角色图，仅请求动作。更改或运行该生成 Run 会产生新的付费请求。`runs/delivered.svrun` 直接复用本地最终影片，不重新生成。原始素材、未采用版本与 QA 记录保留在 assets、output、PROGRESS.md。

最终背景整理为免费本地 FFmpeg 合成：

```sh
ffmpeg -i output/wearing-cuff-720.mp4 -filter_complex_script neutral-background.filter -map '[v]' -an -c:v libx264 -preset medium -crf 20 -movflags +faststart output/wearing-final-720.mp4
```

`neutral-background.filter` 只对这段固定背景素材适用，不是通用人物分割器。首版视频擅自增加嘴部，未采用；一次人像抠图未识别非人角色，亦未采用。最后一版保留两眼无嘴的造型，只有轻微挽袖动作。帧表、首尾对比、元数据与浏览器检查范围见 output/QA.json。

## 循环修正 v2 · 2026-10-02

逐帧检查发现角色头部在生成片段首尾变亮，背景像素始终为 RGB 250。保留旧版 `output/wearing-loop-v1.mp4`，去除亮度异常帧，将稳定动作区间用 12 帧余弦权重叠化接合；结果为 120 帧 / 5 秒。封面同步取新片首帧，网页素材带 `v=2` 缓存版本。

```sh
ffmpeg -i output/wearing-loop-v1.mp4 -filter_complex_script seamless-loop.filter -map '[v]' -an -c:v libx264 -preset medium -crf 20 -movflags +faststart output/wearing-final-720.mp4
```

检查包含完整解码、接缝六帧目视检查和浏览器连续三次首尾切换。没有额外生成费用。
