# Wearing 已选视觉方向

日期：2026-09-30。用户选择第 1 个钴蓝外套、卷袖动作的角色方案，并要求独立标志更简洁。

- [完整角色依据](../wearing-round-01/01-cuff.png)
- [头部与折领的简化标志](mark-simple-v1.png)

简化标志由 ImageGen 依据已选概念板生成，透明背景 PNG。它是精修草稿，不是 SVG；仍需在正式制稿时统一轮廓、纯色、微小边缘和小尺寸辨识。完整角色不随小标志简化而删掉卷袖动作。

制作规范与待交付资产见[品牌工作区](../README.md)。名称和主视觉方向已定，开发按[落地总方案](../../../docs/implementation-blueprint.md)推进。

## 本轮生成提示词

Use case: logo-brand, targeted edit/derivation from selected visual identity. Attached is the user-approved Wearing brand direction. Derive ONE much simpler standalone brand symbol from this exact cream rounded-rectangular-headed character and cobalt blue folded overshirt. Output a single flat emblem on a truly transparent background, 1024x1024 canvas, centered with generous safe padding. Retain only a friendly softly squared cream head with two small charcoal oval eyes and a pair of very simple cobalt-blue folded collar shapes beneath it. The two folded collar shapes suggest a broad W. Preserve the approved character's recognizability and calm alert expression. Front-facing, compact bust silhouette, same proportions and palette as reference. Use at most four clean solid colors: ivory head, charcoal eyes, cobalt outer collar, pale blue inner collar. Crisp smooth vector-like geometry, very few curves, ideally only 5-7 filled shapes. Do not add hands, legs, body, motion rays, pockets, buttons, fabric grain, gradients, shading, shadows, outlines, circles, rounded-square app tile, text, labels, wordmark, or extra variants. This will be a tiny app/avatar brand mark, so readability at 24px is more important than illustrating action. The full character stays as already approved; only simplify the separate symbol.


## 2026-10-03 SVG 版本

`wearing-mark.svg` 是重新绘制的 SVG 标志，已同步到 `src/wearing/web/mark.svg`，用于头像、会话提示和 favicon。共七个纯色形状，无位图嵌入、滤镜或外部字体，保留奶油方头、双眼和 W 形蓝色衣领。已检查 24 / 32 / 64 / 128 px。原 PNG 保留作历史设计参考。完整动态角色仍使用 720p 视频。

### 比例修订 v5

按用户反馈，以图形本身的美感为准重新调整：头部改为宽 80、高 53 的扁圆轮廓；眼睛高度缩至 10.4，衣领外缘和肩线更柔和；使用更明亮的奶油色与钴蓝。24 / 32 / 48 / 80 px 与放大效果均已在浏览器检查。当前文件为 v5；v4 长头版本被替换。


## 当前标志：折叠 W

运行中的 `wearing-mark.svg` 使用折叠 W 与嵌入式表情，独立于完整角色的写实造型。设计源与生成概念板见 [本轮标志设计](../wearing-mark-redesign-20261003/README.md)。当前为设计提案和实现，尚未取得用户最终定稿确认。
