# Wearing 字标与头像：技能和工具调查

2026-10-03。用户要求暂停当前设计，寻找能提高标志、字体和 SVG 设计质量的技能或插件。本文记录能力核查，不表示任何候选已通过实际 Wearing 设计验收。

## 首选研究资料：kaankiziltug/logo-design-skill

来源：https://github.com/kaankiziltug/logo-design-skill
检索时 main commit：0ecf52e9a4b3ac92b714f7cc6e3148ab8c774134。
已阅读 SKILL、typography、svg-construction、critique；源文件保存在本目录。

适合补足：整词字体比较、光学字距、圆形超出基线/字高的补偿、曲线极值点和接点、负形、小尺寸版本、与成熟品牌并排审稿。仓库提供 1,400+ 标志参考和 SVG 审计/预览工具；参考标志仍属于各商标权利人。脚本未运行，未安装到全局技能目录。其检查分数只能衡量部分结构问题，不能代替审美判断。

对 Wearing 的直接启发：头像和字标分别设计；字标先比较完整单词的节奏，再选择少数字形定制；头像先看轮廓与表情是否让人喜欢，再处理 SVG 路径。对真实像素尺寸做光学校正，不能只确认代码或 XML 正确。

## 已安装插件：Adobe / adobe-fonts

已通过插件目录确认 Adobe installed=true。已阅读本地 adobe-fonts 技能：可以推荐、搜索真实字体，获取字族样式/元信息，生成字体预览；不负责设计排版，不保证所选字体适合 Wearing。后续可用来做专业字体候选的比较，避免直接手拼字母。

## 备选服务：Scenario Brand Kit + SVG/字体模型

技能：https://github.com/scenario-labs/skills/tree/main/skills/scenario-brand-kit
检索时仓库 main commit：c8a4bddf2b052864f2eaf98d7ce5aa044c72bf42。
MCP：https://mcp.scenario.com/docs
矢量化：https://docs.scenario.com/get-started/generation/vectorization-models/vectorization-models-scenario
字形 SVG：https://docs.scenario.com/get-started/generation/vectorization-models/vectorization-models-academia

官方文档列出 Scenario Vectorize（位图转可编辑 SVG）和 VecGlypher（文本/参考字形到 SVG）。需要 Scenario MCP 账号授权；当前会话没有已连接的 Scenario 工具，本轮插件目录也没有返回 Scenario 或 Recraft 可安装项。尚未接入、付费或实际运行，结果质量待实测。

## 对照检查

- atypica-ai/marketing-skills 的 logo-design：已读流程，覆盖品牌调研和 SVG，但专门字体/曲线/审稿资料的深度不及首选。
- neonwatty/logo-designer-skill 与 longcipher/svg-logo-skill：偏流程、并排预览和导出，不能单凭这些能力解决审美问题。
- 已有 Impeccable / Brandkit：前者偏界面，后者偏概念板，不替代字标与角色造型的专门训练。
- Figma：插件目录可找到，当前未安装；目录描述确认设计工作流、可编辑图层和协作，不足以声称有自动优质标志设计能力，因此本轮未推荐新增安装。
- 官方 curated skills 清单已查询，未找到专门 logo/SVG 制作技能；列出的设计能力集中在 Figma。

本轮只调研和阅读，未新增插件连接，也未执行第三方技能脚本。
