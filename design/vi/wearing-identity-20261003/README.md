# 当前状态：头像已改用生成稿

用户看过 SVG 重描后明确否定，指出生成角色草图好看而手绘 SVG 丑。本次已撤下手描头像：`src/wearing/web/avatar.png` 使用草图 B 的独立透明生成素材，保留脸颊、衣领、袖口的曲线和细节。字标继续使用 `wordmark.svg`。头像 PNG 为 1254 × 1254 RGBA、712784 字节，包含真实透明通道。`rejected-avatar-v2.svg` 仅归档；不再由运行界面引用。`identity-live.jpg` 为更新后的实际浏览器预览。

浏览器宽度覆盖接口未实际改变视口，真实应用禁止跨源 iframe；因此未把这些尝试记作移动端验证通过。桌面两页已更新，实际图片加载与接口文件字节另行核对。

---

以下是被后续反馈替代的探索记录，不能视作当前选定设计。

# Wearing 头像与字标：本地界面修订

2026-10-03。用户要求按新找到的技能和工具重做。当前界面采用 **B 的抬手肖像 + A 的圆润字标**，这是供用户继续评审的一次可逆 UI 修订，不表示品牌已经最终验收。尚未制作完整品牌套件。

- `wearing-avatar.svg`：短头、略微侧倾、抬起卷袖打招呼。13 个闭合填色路径，无描边依赖、渐变或位图。
- `wearing-wordmark.svg`：基于 Fredoka 530 的字形，HarfBuzz 排字、FontTools 转轮廓，调整整词间距，`g` 尾端用布尔路径加入钴蓝段。
- `type-study.png`：24 个开源字体的整词比较。
- `concepts-v1.png` / `concepts-v2.png`：两轮 SVG 实际渲染。第一轮头像轮廓过板，第二轮改为短头和手势；应用选择 B 头像、A 字标。
- `portrait-sketches.png`：辅助造型的生成草图。没有裁切成产品头像，也未嵌入 SVG。
- `before/`：修订前的四个界面文件。

## 技能与权限

已通过官方 skill-installer 安装 `kaankiziltug/logo-design-skill`，固定提交 `0ecf52e9a4b3ac92b714f7cc6e3148ab8c774134`。阅读 redesign、typography、svg-construction 并使用参考库与结构审计。Adobe Fonts 初始化返回 OAuth 未连接，因此本轮未使用 Adobe 字体，也未新增账号授权。选择 Google Fonts 官方仓库的 Fredoka；许可证见 `fonts/fredoka-OFL.txt`，运行时亦附带。

## 审计说明

`audit-final.json` 没有 FAIL：无活文本、位图、滤镜和遮罩。剩余提示是五种配色、手绘姿态的非标准角度和非对称边界，以及专业字体轮廓点数与小数 viewBox。保留这些构造，避免为了机器分数破坏角色姿态与字形。结构通过不代表审美得到用户确认。

页面只替换头像、favicon、字标和对应缓存版本；动画播放器、视频、对话与设备接口没有修改。主界面的 SVG 图片可直接缩放，不会发生字体晚加载后的字标跳动。

复现：`uv run --no-project --with fonttools --with uharfbuzz --with cairosvg --with skia-pathops python design/vi/wearing-identity-20261003/refine.py`。`install.py` 是本次有前置断言的迁移记录，不应重复执行。
