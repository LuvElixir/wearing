> 2026-10-07：正式名称已确定为 **Pajio**。本目录为已确认角色与历史探索；当前品牌权威见 [Pajio](../../brand/pajio/README.md)。

# 睡衣小熊 · 角色探索

日期：2026-10-07。状态：用户已确认采用睡衣小熊品牌方向，第一版为角色基准；八套睡衣透明资产与衣橱已接入 App，新身份默认显示小熊。正式名称仍待定。当前规范见[品牌方向](../../../docs/plans/pajama-bear-brand-direction-2026-10-07.md)。

## 最新确认：第一版角色，有嘴

用户提供原始第一版并明确「还是这一版本最好，要嘴，然后多做一些睡衣，还有形态也是，名字还是得思考一下」。当前唯一角色基准为 `selected-character-base.png`（与第一版设计同方向）。保留原始头身比例、耳朵、眼距、绒毛、鼻子和小型刺绣嘴；温暖、可爱、轻微自然表情。

- **睡衣** `approved-base-wardrobe-07.png`：雾蓝条纹、奶油月牙、杏桃方格、燕麦针织、热可可、黄油云朵、鼠尾草格纹、玫瑰奶点。均保留嘴和原始体型。图中的姿态统一为轻招手。
- **形态** `approved-base-poses-08.png`：招手、坐着听、捧信封、坐在边缘、蜷睡、圆形头像。默认清醒形态用于交互；蜷睡只适合静态休息展示，不用于表示 Agent 仍在处理任务。
- 两组使用内置 imagegen 生成，对应完整提示词位于同名 `.prompt.txt`。八套睡衣另有独立透明生产图，位于 `clients/mobile/assets/bear/`，生成来源见 `app-cutouts-manifest.json`；App 已实现预览、保存、按身份恢复。形态板中的其余姿态仍是设计参考，未制作动画。
- 正式中英文名待定；命名研究仅存档，不自动应用候选名称。

以下为历史记录；本段最新要求优先于旧轮次的无嘴及体型建议。

## 历史探索：第六轮

`cuddle-study-06.png` 曾探索圆润大头、紧凑梨形身体、短手脚、无嘴表情；当前已由上面的用户选定基准取代。

本轮通过内置 imagegen 完成；提示词为 `cuddle-study-06.prompt.txt`。原图保留于 `/Users/archieliew/.codex/generated_images/01a0ee05-4561-73e3-8587-49c9ac376cad/exec-2c443ffa-b0ef-479a-bade-507b50933b95.png`。

第四、五轮仅存档，不再作为后续设计或实现依据。

## 历史探索：第四、五轮（已停用）

此轮曾据品牌研究线索探索体型，随后用户明确拒绝该方向；保留文件只为追溯。

- `shape-study-04.png`：三种体型对照。
- `long-limbed-study-05.png`：长四肢、扁枕形头部、松肩与自然垂落睡衣的组合方向。
- 资料核验、设计判断、限制及提示词索引见 [reference-research.md](reference-research.md)。
- 下方衣橱与此前的比例均为历史探索，不能视为用户已选定角色体型。

## 历史探索：第三轮衣橱

用户认可第二轮几款，并明确希望多做几套供用户自定义选择；所有款式保持温暖调性。脸、体型与绒毛固定，差异集中在服装版型、面料和小型刺绣。服装选择不改变助手能力或工作状态。

第三轮 `wardrobe-study-03.png` 的六套候选（从左到右、从上到下）：

| 编号 | 暂定款名 | 识别特征 |
| --- | --- | --- |
| 01 | 奶油月牙 | 奶油棉布、蜂蜜滚边、口袋月牙 |
| 02 | 蓝莓牛奶 | 暖雾蓝、奶油圆领、细格纹、小星星 |
| 03 | 杏桃方格 | 暖杏格纹、花瓣领、木色小纽扣 |
| 04 | 燕麦吐司 | 燕麦罗纹针织、圆领、吐司布贴 |
| 05 | 热可可 | 可可棕、奶油滚边、月牙刺绣 |
| 06 | 黄油云朵 | 浅黄纱布、云朵口袋、宽松袖口 |

建议默认从 01 或 02 中选择。产品入口为「我的 → 小熊衣橱」，点选即时预览，确认保存；聊天头像与个人页同步外观。此处是交互方案，当前尚未实现换装功能或拆分生产资产，图片仍为设计对照板。

原始图保留在 `/Users/archieliew/.codex/generated_images/01a0ee05-4561-73e3-8587-49c9ac376cad/exec-2b353c40-6c64-4777-8be9-4fbc786caf5d.png`。完整提示词见 `wardrobe-study-03.prompt.txt`。

## 历史探索：第一、二轮

用户喜欢睡衣小熊，以及 13DE MARZO 的服装和毛绒质感。角色应是原创玩偶，气质来自比例、绒毛与衣服细节。第二轮用户反馈明确要求：玩偶不带情绪，不用微笑，重新调整睡衣。

- 第一轮：`character-study-01.png`。奶油色小熊与雾蓝条纹睡衣，用户认为表情与睡衣仍需调整。
- 第二轮：`character-study-02.png`。统一无嘴、平静的玩偶脸，比较三种睡衣：01 奶油棉布与蓝滚边；02 雾蓝套装与奶油圆领；03 淡紫灰细格纹套装。
- 推荐继续细化 02 的轮廓与领口；最终选择尚待用户反馈。
- 命名候选 Pajio／派吉 尚未获得用户选定，未完成商标或域名筛查。

## 使用原则

角色出现在头像、欢迎和少量状态反馈中；界面文字与真实执行状态负责说明工作进展。保留豆包语音链路，不以角色表情模拟任务完成。无需持续摆动或衣服飘动。

## 参考资料

- [13DE MARZO 官方品牌故事](https://13demarzo.net/blogs/media/streetwear-fashion-trends-13demarzo)
- [Nighty Night Bear 睡眠主题服装](https://13demarzo.net/products/13de-marzo-nighty-night-bear-long-sleeve-polo-navy-blue)

参考限于服装材质、搭配与完成度；未沿用其标志或角色资产。

## 第二轮生成提示词

Reference image: `character-study-01.png`. Original output retained at `/Users/archieliew/.codex/generated_images/01a0ee05-4561-73e3-8587-49c9ac376cad/exec-6f9f1280-b550-498a-833f-eec4f9610137.png`.

Edit the attached original pajama teddy character concept into a second-round premium collectible plush fashion study. The user's central correction is an emotionally neutral, expressionless toy face: REMOVE ALL SMILING MOUTHS. Give the bear two small widely spaced dark bead eyes at an even horizontal level, a small cocoa oval embroidered nose, and NO VISIBLE MOUTH AT ALL. No eyebrows, blush, raised cheeks, tilted head, or acting expression. Its charm comes only from simple toy proportions and tactile craftsmanship. Calm, blank, unperformed, not sad or angry. Maintain an original oatmeal teddy bear identity, small rounded ears, subtly asymmetrical ear seam, plush head slightly oversized, compact pear body and short rounded limbs, refined dense short-pile fur. Avoid the smiling generic gift-shop teddy look of the input. Redesign the pajamas substantially. Create one clean 3-column landscape fashion lookbook on a continuous warm ivory studio background. Three FULL BODY front-facing bears of exactly the same proportions, face, and scale, all standing with relaxed arms down and zero expressive pose. Each wears a different thoughtfully tailored soft pajama outfit, and each gets a small fabric detail crop below. Option 01: buttercream washed cotton pajama set, oversized boxy drop-shoulder shirt, softly rounded small camp collar, restrained faded-blue narrow piping, two small milk-white buttons, generous low pocket, gently cropped wide trouser legs, subtle cotton wrinkles. Option 02: solid pale glacier-blue brushed cotton pajama set, softly rounded Peter Pan collar in warm ivory, generous sleeves and narrow turned ivory cuffs, three tiny tonal covered buttons, one very small ivory woven square label at the shirt hem, roomy softly gathered trousers. This is the most characterful and refined outfit, give careful attention to its silhouette. Option 03: misty lavender-grey fine yarn-dyed microcheck pajama set, collarless softly rounded neckline with a small ivory placket and two small buttons, softly puffed sleeves, matching soft trousers, beautifully subtle fabric texture. Outfits must clearly read as premium small-scale sleepwear, never business suits, medical scrubs, bathrobes, or fashion logos. Keep bare plush paws and tiny trouser folds. Remove envelope, greeting gestures, task symbols, and the old striped outfit entirely. Premium Japanese/European plush collectible editorial product photography, diffuse daylight, tactile fabrics and almost invisible grounded shadows, neutral natural color rendering, meticulous seams. Lots of breathing room, no panel dividers, no decorative swatches. A small understated serif title 'PAJAMA STUDY 02' at top, simple tiny numbers '01', '02', '03' beneath the corresponding bears; no other text, no brand name, no existing brand logos, no UI. The no-mouth neutral face must be immediately obvious in all three characters.
