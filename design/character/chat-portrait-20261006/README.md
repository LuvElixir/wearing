# Wearing 聊天肖像

2026-10-06。用户要求聊天头像独立设计，与下方站立角色区分，静态或动态由设计判断。这一版使用静态头像：正面轻歪头、完整头部和蓝色衣领，延续原 3D IP。界面中呈现为 44px / 手机 36px 的圆形肖像。

## 素材

- 生成方式：内置 imagegen，以 `design/character/3d-20261005/companion-portrait-master.png` 为角色参考。
- 母版：`portrait-master.png`；运行时：`src/wearing/web/chat-portrait.png`，256×256 PNG，使用 sips 机械缩小，未改变构图或颜色。
- 源输出：`/Users/archieliew/.codex/generated_images/01a0ee05-4561-73e3-8587-49c9ac376cad/exec-d088edbe-0022-4588-9f8b-1324b283835f.png`。
- `face.js` 仅生成静态标记；移除回复专属视频解码器及其重绘钩子。下面的全身角色继续使用原播放器和六种动作。
- 本次仅接入同源网页（包含加载此网页的客户端），没有替换手机原生 App 或桌面独立打包资源。

## 验证

`node --test tests/face-ui.test.cjs tests/research-ui.test.cjs` 6 项通过；face.js / app.js 语法检查通过。原动态头像测试随静态实现更新为不依赖媒体 API 的渲染检查。

实际 IAB 的 855px 与 390px 宽度下，4 张回复肖像均加载成功，尺寸分别为 44px / 36px，无横向溢出，回复 video 数量为 0；全身角色素材保持 `character-poster.png?v=4`。最终恢复普通浏览窗口，在 1280×720 再确认 44px 头像及无溢出，页面错误日志为空。截图：`.wearing/qa/chat-portrait-20261006/desktop.jpg`（1280px）与 `mobile.jpg`（390px）。

## 生成提示词

Use case: identity-preserve. Create one production chat AVATAR portrait of the established Wearing 3D character shown in the reference. This is a newly posed standalone bust portrait for 44px chat messages, not a crop of its existing standing or sleeve-rolling pose. Preserve the recognizable warm ivory softly rounded rectangular head, two dark simple oval eyes, no mouth, and cobalt blue coat collar with pale blue lining. Preserve smooth micro-suede/soft clay-like tactile surface at small scale, NOT shaggy fur, NOT human skin. Art-direct it as a beautiful miniature character portrait: direct eye contact at camera eye level, a gentle curious 8-degree head tilt, relaxed friendly face, a shorter generously rounded head with less empty forehead and eyes approximately at the vertical midpoint, subtle asymmetry giving personality. The head is slightly three-dimensional, not an outlined illustration. Do NOT add nose, ears, eyebrows, mouth, hair, accessories, arms or hands. Only the full head, short neck, small shoulders and elegantly simplified blue collar at the bottom; no buttons or sleeve gesture. Composition MUST remain spacious: head occupies only 60-64 percent of the square canvas width, complete silhouette, plenty of clearance above and beside it, collar/shoulders occupy the lower quarter, small centered bust with good balance and enough room for circular clipping. The charm comes from eye contact and the curious pose, not giant baby eyes. Soft chocolate-black oval eyes with very subtle catchlight. Clean restrained pale periwinkle/off-white studio background (#EDF1FF family), soft diffuse studio illumination from upper left, delicate ambient shadow, premium contemporary 3D icon craft, calm and intimate. Background fills entire square with no frame or ring. This is a flat exported portrait asset, NOT a physical medallion, window, glass disc, badge, toy product on a pedestal or full character scene. No glass/reflections/rim, no text, no logo, no UI, no additional objects. Keep its original character identity while making the newly composed headshot aesthetically distinct from the standing companion.
