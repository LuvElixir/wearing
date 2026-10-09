---
name: Wearing
description: 属于你的个人 Agent，以连续对话与卷袖准备动手的角色陪你把事情向前推进。
colors:
  page: "#fafafa"
  surface: "#fff"
  ink: "#272c35"
  muted: "#666d78"
  blue: "#4562dc"
  blue-deep: "#344cc3"
  blue-light: "#edf1ff"
  line: "#e5e7ed"
  danger: "#a33039"
  life-field-label: "#515b76"
  rail: "#f3f4f8"
  section-line: "#ebedf2"
  focus-border: "#91a2e3"
  symbol-fold: "#97A9F7"
typography:
  display:
    fontFamily: 'WearingGreeting, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "52px"
    fontWeight: 500
    lineHeight: 1.42
    letterSpacing: "-1.4px"
  headline:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.4px"
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.7
  conversation:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.95
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.7
  metadata:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.7
  code:
    fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace'
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.8
  life-heading:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "clamp(28px, 2.5vw, 34px)"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "-0.035em"
  life-section:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.7
  life-body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "14px"
  life-capture:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "16px"
    lineHeight: 1.8
  life-label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "13px"
    lineHeight: 1.7
  capture-detail:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "13px"
    lineHeight: 1.8
  mobile-record-title:
    fontSize: "16px"
    fontWeight: 500
    lineHeight: "25px"
  mobile-record-meta:
    fontSize: "12px"
    lineHeight: "20px"
  mobile-record-excerpt:
    fontSize: "14px"
    lineHeight: "23px"
rounded:
  control: "14px"
  companion-button: "16px"
  panel: "28px"
  panel-mobile: "24px"
  composer: "28px"
  composer-mobile: "25px"
  circle: "50%"
  life-control: "12px"
  life-editor: "24px"
  life-capture: "28px"
  life-section-mobile: "22px"
  record-target: "8px"
spacing:
  gap-tight: "8px"
  gap: "12px"
  inset-sm: "14px"
  inset: "18px"
  section-sm: "20px"
  inset-wide: "24px"
  section: "30px"
  life-row-inset: "10px"
components:
  confirmation-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "24px"
    padding: "24px"
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "9px 14px"
  button-primary-hover:
    backgroundColor: "{colors.blue-deep}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "9px 14px"
  button-text:
    textColor: "{colors.blue}"
    typography: "{typography.label}"
    padding: "3px 0"
  send-button:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.circle}"
    width: "42px"
    height: "42px"
  quiet-navigation:
    textColor: "{colors.muted}"
    padding: "8px 0"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "11px 12px"
  composer:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel-mobile}"
    padding: "12px 13px 12px 23px"
  user-message:
    backgroundColor: "{colors.blue-light}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "24px 24px 8px 24px"
    padding: "13px 19px"
  approval:
    textColor: "{colors.ink}"
    padding: "18px 0"
  keep-row:
    textColor: "{colors.ink}"
    padding: "18px 0"
  suggestion:
    textColor: "{colors.muted}"
    padding: "5px 0"
  life-button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.surface}"
    typography: "{typography.life-body}"
    rounded: "{rounded.companion-button}"
    padding: "10px 20px"
  life-button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.life-body}"
    rounded: "{rounded.control}"
    padding: "10px 20px"
  life-navigation:
    textColor: "{colors.muted}"
    typography: "{typography.life-body}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
  life-navigation-active:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.blue-deep}"
  life-capture:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.life-capture}"
    rounded: "{rounded.life-capture}"
    padding: "23px 24px 16px"
  life-kind:
    textColor: "{colors.muted}"
    typography: "{typography.life-label}"
    rounded: "{rounded.life-control}"
    padding: "8px 15px"
  life-kind-active:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
  life-editor:
    backgroundColor: "#f1f3f9"
    textColor: "{colors.ink}"
    rounded: "{rounded.life-editor}"
    padding: "24px"
  life-field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.life-body}"
    rounded: "{rounded.life-control}"
    padding: "10px 12px"
  life-row:
    textColor: "{colors.ink}"
    typography: "{typography.life-body}"
    padding: "10px 0"
  capture-tool:
    textColor: "{colors.muted}"
    typography: "{typography.life-label}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  capture-tool-active:
    backgroundColor: "{colors.blue-light}"
    textColor: "{colors.blue-deep}"
  capture-organize:
    textColor: "{colors.muted}"
    typography: "{typography.life-label}"
  capture-file:
    textColor: "{colors.ink}"
    padding: "8px 0"
  capture-state:
    textColor: "{colors.blue-deep}"
    typography: "{typography.capture-detail}"
  capture-state-error:
    textColor: "{colors.danger}"
  capture-originals:
    textColor: "{colors.ink}"
    typography: "{typography.capture-detail}"
  capture-original-link:
    textColor: "{colors.blue-deep}"
    typography: "{typography.capture-detail}"
  mobile-capture:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel-mobile}"
    padding: "20px"
  mobile-record-row:
    textColor: "{colors.ink}"
    typography: "{typography.mobile-record-title}"
    rounded: "{rounded.record-target}"
    padding: "8px 0"
  mobile-navigation-active:
    backgroundColor: "{colors.blue-light}"
    textColor: "{colors.blue}"
    rounded: "{rounded.companion-button}"
  capture-more:
    textColor: "{colors.muted}"
    rounded: "{rounded.control}"
    width: "44px"
    height: "44px"
  life-section-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel-mobile}"
    padding: "12px 23px 18px"
---

## 2026-10-07 App 设计更新（优先于下文旧版）

用户明确以所提供 Today 真机截图为本次 App 视觉和交互依据。App 切换到蓝天至暖杏的连续背景、半透明白色卡片、深色文字、轻量线性图标。主色阶 #ACCEEB / #DFE8F1 / #F4E7D9 / #FFE0BB，正文 #252C30，辅助 #66747D，行动蓝 #008CC8。原卷袖角色退出 App 的头像、底部导航与页面主视觉；产品名称暂留 Wearing，新品牌名尚未选择。

主入口：聊天 / 今天 / 任务 / 记忆 / 我的。聊天保留一处左上方紧凑进展入口；搜索、设置在右侧。删除每条回复后的核对结果、记成目标；保留确实需要用户决定的执行确认。任务状态必须对应真实任务，记忆更新状态必须有真实回执，不从文字推测。聊天页面不支持捏合或双击整体缩放，系统辅助文字设置独立保留。

原生外层与 App 专用 WebView 正文共用透明背景。助手白色气泡，用户灰蓝气泡；正文17pt，气泡24pt圆角，输入固定58pt，底栏31pt圆角。五个入口选中用低对比度底色和深色图标；触摸目标至少44pt。动效只用于切换、展开/收起与状态变化，不增加角色动作。

今天展示已同步日程、任务回执及可进入的结果；图文简报从对话发起，来源和生成结果不伪造。记忆读取同一身份的 Agent 记忆和真实文件夹。会员卡形状展示当前实际连接/版本，不虚构订阅；本机权限、云端授权、远程设备各自展示真实状态。设计从 App 开始，网页和桌面待 App 验收后由 ZCode 只读 App 源码再同步。

# Design System: Wearing

## Overview

**Creative North Star: "属于你的行动者"**

Wearing 的亲切感来自完整的 3D 钴蓝卷袖角色与自然中文。奶油色的圆角方头、两只椭圆眼睛、带布料质感的外套和浅色袖口，落在安静的近白空间里。挽起袖子的姿态表达“我来帮你做”，与界面里的“这件事，我来。”一致。

这份系统记录当前个人 Agent 界面的源码实现。连续对话是主要阅读与行动空间；角色负责建立熟悉感，界面负责让文字、真实状态和下一步清楚可见。辅助设置与以前留下的事情在需要时展开，保持日常交谈的舒适密度。

生活记录的随手输入延续这个世界。原话、图片和录音进入同一个书写区域，保存与后台整理分别显示真实文字；原件、识别内容和整理建议在当前记录中按需展开。新增组件沿用现有品牌资产与阅读材料。

手机记录延续同一品牌和原件语义：钴蓝表达可操作的入口，近白空间承接原话，平台控件承担触摸输入。记录、待同步和继续对话保持可辨的来处；具体手机构图与原生差异记录在独立 surface 文档中。

2026-10-05 Comfort 是同一视觉世界的日常体验精修。用户选定的折带 W 负责应用识别，已确立的完整 3D 卷袖角色负责问候、陪伴与反馈；两者与原有描边字标分别使用。每个当前操作状态保持一个清楚的主要下一步，可选输入通过加号展开。用户随后确认界面内只保留 3D IP：以 `character-poster.png` 和既有动作视频为角色依据，非聊天入口继续使用同源生成的 `companion-portrait.png`（512px 透明 PNG）。对话头像采用单独构图的 `chat-portrait.png`（256px 静态 PNG），以正面轻歪头和蓝色衣领表达倾听；下方陪伴区继续使用完整角色的动作视频。

结果产物延续同一视觉世界，以清楚的判断、可操作的条件和可核对的依据组织内容。钴蓝标记当前操作与关键变化，原生中文字体承接数字和说明；每份结果按问题选择表达形式，信息密度与交互状态共同服务理解。

**Key Characteristics:**
- 完整 3D 卷袖角色、应用折带 W 与 Wearing 字标各司其职。
- 近白空间、白色输入区域、浅钴蓝消息与清楚的墨灰文字。
- 中文问候具有独立展示字体，日常对话使用平台原生中文字体。
- 文字、留白和细分隔线建立层级，角色材质保留自然体积。

当前覆盖关系：`comfort.css` 在原有样式之后加载，下文标为 Comfort 的规则优先于文末历史增量中的布局、工具行、尺寸与动效描述；未改动的身份、记录、对话与原件语义继续适用。提取依据与局部适配见 [Comfort 设计记录](docs/design-comfort.md)。

依据：`PRODUCT.md`、`src/wearing/web/index.html`、`style.css`、`app.js` 与独立角色图 `character-poster.png`。当前首屏构图见 `.impeccable/surfaces/personal-conversation.md`。本文是源码提取的设计记录，不代表整套 UI 已获用户视觉批准；最终媒体质量与浏览器验收另行记录。

## Colors

近白与偏冷中性灰承托单一钴蓝操作色，浅蓝用于对话中的轻量色面；色值以前置元数据为准。

### Primary

- **行动钴蓝**（`blue`）：发送、主要按钮、链接、可点击文字的悬停与实际连接圆点。
- **深钴蓝**（`blue-deep`）：主要按钮与发送按钮的悬停反馈。
- **浅钴蓝**（`blue-light`）：用户消息的底色，帮助区分对话两方。

### Neutral

- **近白**（`page`）：整页、输入区底部承托层和辅助面板。
- **书写白**（`surface`）：输入框、次要按钮与轻量浮动操作。
- **正文墨灰**（`ink`）：主要文字与字标主体。
- **说明灰**（`muted`）：辅助说明、时间与安静入口。
- **分隔灰**（`line`）：章节、记录与需要决定的步骤之间的细线。

**问题红**（`danger`）是错误说明的语义色，不作为第二种装饰强调色。连接与结果状态始终有中文文字，圆点和颜色只是辅助。

随手输入没有新增调色板：图片与语音入口默认说明灰，悬停和录音中使用浅钴蓝底、深钴蓝字；保存与整理阶段以深钴蓝文字说明，上传或整理失败沿用问题红。折叠原件继续使用正文墨灰和分隔灰。

Comfort 复用的冷灰材料分别是 `rail`（网页与原生宽屏导航背景）、`section-line`（今天分区与原生记录容器边线）、`focus-border`（书写区、目标输入与桌面连接字段的聚焦边框）。`symbol-fold` 只服务折带 W 的背面折片，不作为第二种界面动作色。其他局部中性色留在组件样例。

### Named Rules

**The Action Cobalt Rule.** 钴蓝集中承载动作、交互反馈与用户消息的关联；状态颜色必须跟随真实探测或记录。

结果基础 CSS 与人工样板的说明文字均采用 `muted`，在样板浅色操作面上的正常文字对比度约为 4.63:1。正常文字至少满足 4.5:1，错误同时使用文字和字段状态说明。样板的浅色面、分隔线与错误色是局部材料，不新增全局色板。

## Typography

**Display Font:** 自托管 Noto Sans SC 问候子集以 `WearingGreeting` 注册；自托管 Manrope 字标子集以 `WearingWordmark` 注册。文件位于 `src/wearing/web/fonts/`，使用 `font-display: swap`。

**Body Font:** 前置元数据中的系统无衬线栈，按平台回退至中文 UI 字体。

**Label/Mono Font:** 标签沿用正文栈；命令、连接准备说明使用等宽栈。

**Character:** 问候较大、疏朗而自然，字标紧凑。日常对话不依靠展示字体的装饰性，保持熟悉的中文阅读节奏。

### Hierarchy

- **Display:** `display` 用于角色旁的问候。宽屏至少 1500px 时为 56px；不超过 850px 时为 43px；不超过 600px 时为 30px、行高 1.5、字距 -0.7px。
- **Wordmark:** `wordmark.svg` 使用 Fredoka 基础字形的矢量轮廓，g 尾端留钴蓝段；桌面宽 132px，手机端宽 112px。
- **Headline:** `headline` 是辅助面板标题；手机端缩至 21px。
- **Body / Conversation:** `body` 是常规正文，实际回复使用 `conversation` 的舒展行高。手机端消息正文为 14px；输入文字保持 16px。
- **Label / Metadata:** `label` 用于按钮、字段与解释；`metadata` 用于时间和低频次要操作。主要阅读内容不降入元信息层级。
- **Code:** `code` 保留换行，并允许长地址或命令折行。
- **Capture Detail:** `capture-detail` 用于整理阶段、原话、识别内容与原件折叠区；文件名和媒体入口沿用生活辅助层级，上传提示与文件说明保留 12px。手机媒体入口为 14px，快记输入继续保持 16px。

### Comfort reading hierarchy

生活页面沿用已建立的平台中文阅读字体，`life-heading` 是跨今天、日历、清单、笔记重复使用的页面层级，手机覆盖为 27px；它属于日常界面标题，不引入新的品牌展示字体。章节标题使用 `life-section`，编辑区标题保留既有 18px。原生手机的页面标题是 30 / 41、记录标题与元信息使用前置 `mobile-record-*`；网页与原生平台保持各自的清楚阅读密度。Comfort 的欢迎问候仍使用 `WearingGreeting`：宽屏为 44px、手机为 32px；原有问候子集和描边字标保持独立。字标宽屏 126px、网页手机 113px、原生 120px 是当前容器适配值。

### Named Rules

**The Greeting and Reading Rule.** 展示字体负责品牌与问候，原生中文字体负责持续阅读；现有子集仅覆盖当前用途，新增展示文案须核查字形覆盖。

结果中的标题、说明和原生字段沿用系统中文字体。比较数字与表格采用等宽数字特性（`tabular-nums`），单位与统计口径贴近数值；关键结论保持正文以上的视觉层级。人工样板的突出金额与标题尺寸属于当前构图，不扩充全局字级。

## Layout

### Current Comfort shell

网页在至少 1000px 时使用 220px 左侧栏；五个生活目的地在侧栏中纵向排列，辅助入口位于同一栏下方。641–999px 保留上方紧凑导航；不超过 640px 时，五项主导航固定在底部，并为安全区和书写区留出位置。这明确替代旧的手机横向滚动主导航描述。生活内容容器最大 1120px；今天的日程和待办在宽屏并列，最近笔记在下方，手机单列。

原生手机保留四项底部导航（安排包含清单），宽度达到 840 逻辑单位后改为 190 单位侧栏，内容最大 980 单位。网页断点与原生布局单位分开记录。当前精确留白、编辑栏和输入尺寸见 [Comfort 设计记录](docs/design-comfort.md)。

快记默认笔记。文字、已添加的原件和一个「记下」主动作保持可见；图片、录音和类型选择收在加号后。此规则明确替代此前常驻媒体工具行与类型分段的布局。录音过程中保留可见的结束入口，加号和类型选择不得把它收起。

### Incumbent conversation and record structure

空间围绕连续对话展开。顶部是小字标与文件、记录、连接三个安静入口；主内容最大宽度 1200px。当前欢迎状态中，完整角色与问候并列；开始交谈后，同一区域换成最大宽度 740px 的连续消息，完整角色移到输入框上方的陪伴区。角色容器保持同一个；两个视频缓冲交替解码，共用静帧和布局。用户消息靠右，回复靠左并带简化角色标志；消息容许长文本换行。

输入区域始终贴近当前对话，使用粘性底部位置，桌面宽度为 `min(780px, calc(100% - 64px))`。它保留页面色承托，消息滚动经过时维持清楚的书写区域。辅助面板从右侧打开，宽度为 `min(480px, 100%)`，由原生对话框管理焦点与遮罩。

响应式分界为宽屏 1500px、紧凑布局 850px 和手机 600px。紧凑布局收缩角色与左右留白；手机将角色放在问候上方，文字居中、问候取消硬换行。手机输入区左右各留 18px，消息区左右各留 20px；辅助面板占满可用宽度。顶部“记着的”入口隐藏文字，保留书签 SVG 与可访问名称。

重复间距采用前置元数据中的节奏：控件与图标较紧凑，消息、章节与主要区域逐层放宽。欢迎页的角色尺寸、双栏比例和问候摆位属于当前 surface；新增页面应继承阅读密度与品牌关系，不机械复制首屏。

随手输入在既有快记区域内增加原件行、安静的图片／语音工具行和可选整理勾选项，保留原来的记录类型、记下动作与下方日程／清单。原件详情接在生活编辑区之后。媒体工具行允许换行，沿用生活工具的 700px 分界：手机把上传提示放在独立一行，原件保持在内容宽度内。具体控件与媒体尺寸见 [随手输入设计记录](docs/design-capture-input.md)。

手机客户端的适配分界为 840 个布局单位：窄屏使用底部四项导航，宽屏改为左侧 190 单位导航；正文保留 24 单位内边距，宽屏内容容器最大 980 单位。这里只约束 `clients/mobile`，不替代网页已有断点。RN 尺寸为平台逻辑单位，网页预览映射为 CSS px。完整表单、状态和证据边界见 [手机设计记录](docs/design-mobile-client.md)。

### Result artifact reading order

**The Decision First Rule.** 先让用户看清本次要判断的结论与关键变化，再把可调条件和反馈放在相邻位置；依据与明细按需展开，窄屏按判断、操作、核对的顺序重新排布。

宿主将结果放在独立画布中，沿用既有手机分界：窄屏全屏展示，标题与操作组在同一行，标题可换行，下载、上一版与关闭保持可达。内容负责结论和操作，宿主负责名称、版本与依据入口。预算样板的双栏比例、620px 内容断点和具体金额范围只记录在 [结果 surface](.impeccable/surfaces/result-artifacts.md)，不成为其他产物的通用模板。

## Elevation & Depth

Comfort 在书写面、选中导航与模态浮层使用低强度柔和投影，分区和记录行仍由色面、细线与留白分层。近白页面、白色书写区、浅蓝消息、细边框和半透明对话框遮罩构成界面层级。角色图像自身的柔和投影与布料明暗属于 IP 的真实材质，必须保留其体积感。图像和视频按原比例完整显示，最终媒体背景与页面近白底色一致。

键盘焦点采用可见外描边（3px，偏移 4px）。输入组合通过边框改变反馈焦点；命令背景、次要按钮悬停色等局部材料值保留在组件样例中，不扩充为装饰色板。

媒体输入、原件行和折叠详情没有新增投影；细分隔线和现有编辑区色面继续建立层级。媒体按钮继承普通控件过渡，原件 summary、复选框和链接继承生活区域的可见键盘焦点（3px，偏移 3px）；减少动态效果规则继续生效。

Comfort 的书写区在静止和聚焦时使用不同轻投影，侧面板使用更深的环境阴影；具体投影保留在 sidecar，避免把它们当成独立品牌色。按钮按下轻缩至 0.98，普通反馈 140ms；页面和展开内容进入 240ms，原生对话框退出 160ms，网页使用 `cubic-bezier(.22,1,.36,1)`。新动作取消旧动画，减少动态效果时跳过位移并移除背景模糊；原生页面使用相同进入时长和平台 cubic-out。

### Named Rules

**The Quiet Interface, Tactile Character Rule.** 界面靠色面、边框与留白分层，角色靠布料、光影与轮廓建立存在感；两者保持各自的材料逻辑。

**The Focused Motion Rule.** 结果动效只解释交互反馈或数据变化，文字与数值直接呈现当前状态；减少动态效果时关闭过渡，结论仍可独立阅读。

当前结果入口的背景与边框反馈、样板比较柱的 transform 均使用 180ms ease。比较柱由同一固定尺度更新，数值不从零滚动。结果画布的环境阴影只表达模态层级；这些用途不改变角色已有的陪伴动作规则。

## Shapes

Comfort 的书写面使用 `life-capture`，网页手机与原生书写面复用 `panel-mobile`；今天分区、编辑区和日历外容器共享柔和大圆角，手机分区复用 `life-section-mobile`。保存动作与桌面连接字段复用 `companion-button`，加号及媒体按钮复用 `control`；记录点击区域使用 `record-target`。这些来自重复组件关系，局部底部面板的不对称顶角与头像尺寸留在 surface 记录。

折带 W 是用户已选择的应用图形：连贯钴蓝布带、浅蓝背面折片与上翻袖口。五个纯色路径构成独立 SVG；应用图标使用该资产，问候和会话统一使用已确立的 3D 角色及同源肖像。应用掩模、单色版与小尺寸要求见 `design/icons/folded-w/README.md`，不把标志拆成普通界面图标。

连接字段与常规按钮沿用轻圆角 `control`。发送、关闭和动效控制采用圆形；当前发送按钮为 42px，动效控制最终有效尺寸为 40px。对话输入区在 Comfort 中统一使用 `panel-mobile` 圆角。用户消息以一个较小的尾角表达说话方向，具体圆角属于消息组件。

角色保持完整轮廓与方圆头部，不裁切成品牌板局部。图标使用圆端、圆转角的细线 SVG；默认线宽 1.7，按按钮用途缩放，不使用文字字符替代图标。

媒体工具在 Comfort 中复用 `control`，图片缩略图和展开原图保留 `life-control` 的柔和圆角。工具图标和折叠箭头均为圆端 SVG；折叠入口使用可见的右向箭头，展开后向下，不用文字字符代替。

## Components

### Buttons

动作直接、语气自然，重要性通过色面区分。

- **Primary:** 钴蓝底、白字，最小高度 44px；悬停使用深钴蓝。
- **Secondary:** 白底、细灰边框、正文墨灰；悬停浅中性底。
- **Text:** 钴蓝文字，悬停下划线；用于继续消息、连接或只读检测。
- **Send:** 圆形钴蓝按钮与向上箭头 SVG，具有“发送消息”可访问名称。
- **States:** 请求期间相关按钮禁用、透明度降至 0.5、鼠标呈等待状态；异常由对应文字反馈。键盘操作保留可见焦点。

### Cards / Containers

对话以消息与开放文本组织。用户话语采用浅蓝气泡；助手回复以简化标志与宽松正文呈现。需要决定的步骤使用上下细线、原始操作说明和本次允许／拒绝按钮。以前留下的事情采用分隔行，保留标题、日期和真实状态文字；点击后在同一辅助面板查看。

持续目标有新反馈时，在对话上方以轻圆角、细边框和小头像提示；「一起记着的」显示真实未读数。抽屉内的反馈沿用浅钴蓝材料，按标题、阶段状态、结果和下一步组织，入口回到原目标。没有新反馈时整体隐藏，不占空白版面。查看或标为已读不表示目标达成，原报告和当前目标状态各自保留。反馈不弹出打断对话，也不改变输入框的内容或焦点。

### Inputs / Fields

连接字段是白底、细边框、轻圆角。对话输入由多行文字与发送按钮组成；整体边框在聚焦时变化，保留 0.2s ease 过渡。Enter 发送、Shift + Enter 换行，中文输入法组字时不触发发送。建议入口只把句子填入输入框并聚焦，由用户继续表达。

离线消息显示“已保存在本机”并提供连接入口；连接后草稿可继续送出。消息返回不等同于已核对的外部结果，核对记录由真实动作写入。上述状态必须使用可见文字，不由角色表情或动画暗示完成。

### Navigation

主入口遵循上文 Current Comfort shell：宽屏侧栏、手机底部、平板顶部。辅助入口沿用原有材料与状态语义：Wearing 字标回到对话，“一起记着的”打开旧记录，连接状态打开设置。辅助按钮默认说明灰，悬停钴蓝。连接圆点只有实际可达时才使用钴蓝。设置中的设备报告显示探测时间，并说明操作能力仍需验证；尚在开发中的能力保持明确说明。

连接面板先呈现“在这台电脑开始”，安装与启动状态按本地引擎实际结果变化。模型设置沿用官方向导；远程地址与密钥收进“连接另一台电脑或已有的 Hermes”。整个流程沿用现有文字、按钮、分隔线和原生 details，不在主对话增加管理卡片。角色视频使用修正后的 5 秒稳定循环和匹配首帧封面。

### Capture Focus and Disclosure

「记下」是当前快记表面的唯一实心主动作。加号提供图片、语音和记录类型，展开状态通过 `aria-expanded` 或原生 accessibility state 表达；原件和保存状态沿用已有组件。网页类型标签随 `aria-pressed` 的真实选择同步，包含恢复草稿后的变化；原生标签直接从表单类型读取。类型选择后收起可选项，录音时例外保持展开。placeholder 使用 `muted`，不另造更浅的提示色。

**The One Next Action Rule.** 每个当前操作状态突出一个主要下一步，同时让高频的切换、返回和纠错直接可达。单焦点不等于只有一个按钮，次级功能也不能一律藏进多层菜单；正在进行的录音必须保留可见的结束操作。

### Capture Originals and Background Work

先留住输入，再按用户选择整理当前记录。新组件是既有生活工具的增量，源码依据为 `src/wearing/web/capture.css`、`capture.js` 和 `index.html`，继承 `life.css` 与 `style.css`。

- **Media tools:** 图片、说一句和录音文件为轻量文字按钮，最小高度 44px。录音时按钮变为浅蓝并显示「说完了」，邻近状态文字显示时长和结束方法；权限或浏览器能力不足时说明可添加已有录音。
- **Upload:** 选择或粘贴媒体后立即上传，原件行分别显示「正在保存原件…」「原件已保存」或实际错误。失败可重试，待提交附件可移除；保存记录前等待原件上传完成，失败项仍保留可操作入口。
- **Optional organization:** 有附件时显示「记下后，请 Wearing 帮我整理」原生复选框，默认勾选；取消后仍可保存原话与原件。保存记录与后台整理是两个阶段，后台工作不要求用户留在输入处等待。
- **Background states:** 排队、读取图片／录音、整理中、已整理、只保存、失败、中断和编辑冲突均有可见文字。失败或中断保留原件并显示「再整理一次」；用户已编辑时保留修改，整理结果放进独立建议折叠项。
- **Originals disclosure:** 原生 `details`／`summary` 承载「原话与原件」和冲突时的「看看 Wearing 的整理」。summary 最小高度 44px，前置可见 SVG 箭头随开合转向；保留原生点击、键盘与焦点语义。同一记录后台刷新保留已展开状态。
- **Source reading:** 原话与识别文字保留换行和长词折行；展开原图按原比例完整显示，文件名可打开原件，录音使用浏览器原生播放控件。缩略图可裁成方形，仅用于附件列表，不改变原件。

**The Raw Record Rule.** 保存状态、后台整理状态和用户手动修改分别可见；原话与原件始终可回看，编辑冲突的整理建议单独展开，不覆盖用户修改。

详细状态和响应式值见 [随手输入设计记录](docs/design-capture-input.md)。2026-10-04 finish reviewer 最终 disposition 为 `ship`；原件折叠入口已补齐可见方向箭头。截图位于 `docs/evidence/images/capture-input-2026-10-04/`，以 `desktop-capture.png`、`mobile-capture.png` 及四张 `*-originals-*-fixed.png` 为本次状态记录。原件全页复拍中的滚动位置、粘性叠层和焦点痕迹不作为布局或默认状态规则；本记录没有新增浏览器或真机验收。

### Mobile Capture and Record Continuity

手机使用同源 3D 角色肖像、既有 SVG 描边字标和钴蓝主题；原生 Paper 按钮、展开后的类型分段、开关、勾选与日期时间选择器承担触摸操作。白色快记区域用细边框、既有柔和圆角与留白承接文字及本机原件，不新增装饰投影。`mobile-record-*` 仅记录移动端重复使用的阅读尺度，不改动网页对话层级。

同一记录的标题、原话与原件和「接着和 Wearing 聊」入口相邻。原生客户端在 WebView 中打开原有对话，网页预览显示带当前记录标题的对话入口；身份和记录上下文由同一链接生成器带入。本机待同步、服务端原件保存和后台整理使用不同的状态文字。更新失败保留当前编辑并说明「修改尚未确认」；空清单保留说明和创建入口。

**The Local State Rule.** 本机留存、正在同步、服务端保存和后台整理分别用真实文字说明；失败保留内容与下一步入口，当前记录继续对话时保留其标题与上下文。

手机原生相机、麦克风、本机存储和分发包的验收属于工程证据，不由组件外观推导；当前边界及截图见 [手机设计记录](docs/design-mobile-client.md)。

### Scheduled Intentions

「到时我来」复用既有记录行、细分隔线、原生圆角字段与钴蓝保存按钮。安排名称先出现，约定时间、当前状态与下次行动时间紧随其后；这些内容沿用系统中文阅读层级，不使用品牌问候字体。创建和修改使用同一份自由指令表单，各有一个实心保存动作；最近行动收在原生折叠区里。具体位置、表单断点和局部材料见 [到时我来设计记录](docs/design-schedules.md)。

**The Agreed Time Rule.** 安排名称、约定时间和真实状态相邻呈现；后续安排与已经开始的本轮分别说明，回应和已核对的结果保持区分。

结果回到现有对话，暂停入口明确写为「暂停后续」，反馈说明已开始的本轮可在对话中停止。服务运行要求由本机或私人服务的实际部署状态决定；记录变化通过同一表单的明确选项建立；系统推送与外部事件源不由这些视觉状态暗示。此次是既有世界的窄幅延伸，沿用已确认的配色、角色与控件体系。

### Result Artifacts

结果入口沿用白色容器、细分隔线、系统字体和钴蓝反馈，整张原生按钮可用键盘打开。自然标题、两行内的摘要、媒介与版本先提供可判断的线索。展开后保留下载、旧版和关闭，依据、假设与限制在原生折叠区查看；加载中、打开较慢与打开失败各有实际文字反馈。

**The Coherent Data Rule.** 同一份状态与计算结果驱动结论、图形、可访问文字和明细；单位、时间、口径与来源随结果保留，缺失或无效输入不伪装成有效数值。

**The Common Scale Rule.** 比较图从共同的基准和尺度出发，调整条件时保持尺度稳定；数值标签与文字等价信息始终可读，颜色仅辅助突出当前变化。

**The Native State Rule.** 使用带标签的原生输入、按钮与折叠控件，保留编辑焦点和可见键盘焦点；有效、空值和越界状态在操作附近反馈，恢复入口回到明确的初始依据，试算与真实执行分别说明。

人工样板以数字输入与 range 共同驱动计算，按最小货币单位运算；空输入和无效值显示待填写，结果和明细同步退出有效状态，文字状态另由礼貌播报提供。原生控件与恢复行为是可复用原则，预算项目、具体数值和控件组合属于样板。

提取依据为 [人工合成数据样板](design/artifacts/weekly-budget.html)、[按需设计指引](src/wearing/artifact_design.py) 与 [结果宿主样式](src/wearing/web/artifacts.css)。样板由人工打磨，只提供质量参照；指引提供媒介原则、基础 CSS 与审查用例，返回指引或保存成功均不代表自动视觉验收。关系图的媒介建议仍需逐份实现与观察，解释视频目前只有规划指引，制作与视频发布尚未接通。

### Character Presence

完整 IP 基于独立生成的角色，品牌依据为已选钴蓝卷袖方向。当前 `src/wearing/web/character-poster.png` 从最终角色视频的首帧导出，保持静帧与播放画面连续。对话头像、会话提示和手机问候使用同一 3D 母版派生的角色肖像；应用图标使用用户新选的折带 W。角色的光照、衣料与奶油色面部保持同源，首屏和陪伴区域保留完整角色及既有视频。早期平面头像文件仅归档供历史追溯，不再作为当前界面素材或未来界面的设计依据。肖像母版位于 `design/character/3d-20261005/companion-portrait-master.png`，依据 `character-poster.png` 忠实生成；当前网页、原生手机和桌面连接页分别使用 `src/wearing/web/companion-portrait.png`、`clients/mobile/assets/companion-portrait.png` 与 `clients/desktop/frontend/companion-portrait.png`。三份为同一 512px 透明 PNG；原有动作文件保持不变。早期运行时平面头像归档于 `.wearing/qa/comfort-20261004/retired-2d/`，历史设计文件继续保留。字标使用独立的 `wordmark.svg` 路径。角色的圆角方头、双椭圆眼睛、钴蓝布料与浅色袖口保持一致。

动效语义由真实上下文决定：待命、点按招手、倾听、思考、挽袖动手、等待接手。`character.json` 声明六段 720p 无声短动作，均经过逐帧材质校色并收回自然姿态；当前状态原生连续循环，加载好首帧才切换视频，普通状态变更等待当前动作完成，人工接管立即结束工作动作。循环与状态切换不插入静帧或等待间隔，点按不会叠加请求。首页、陪伴区均无播放／暂停控件，无原生视频控件。系统减少动态效果显示静帧，隐藏页面或离屏暂停，媒体失败保留静帧。动画只表达陪伴和当前处理状态，不代表业务成功。

## Do's and Don'ts

### Do:

- **Do** 保留完整 3D 角色、应用折带 W 和字标之间的清楚分工；角色肖像从已确立的 3D 素材派生，完整角色保持原比例。
- **Do** 让挽袖姿态与准备帮忙的中文表达保持一致。
- **Do** 使用文字交代连接、保存、执行与核对状态，并以真实数据驱动变化。
- **Do** 保留输入区焦点、键盘可达性、系统减少动态效果与静帧回退。
- **Do** 让持续阅读保持舒适行高，手机优先保证对话和输入可用。
- **Do** 分别说明原件上传、记录保存和后台整理，保留原件回看、失败重试与用户修改。
- **Do** 让原件和建议折叠入口保留可见方向箭头、原生 summary 语义和键盘焦点。

- **Do** 在手机区分本机留存、同步与整理状态，保留失败时的输入、重试入口和记录上下文。

- **Do** 让加号承接可选输入，每个当前操作状态保留一个实心主要下一步，并在录音时保留结束入口。
- **Do** 根据真实选中类型更新快记说明，恢复草稿后仍与表单状态一致。

- **Do** 让结果结论、图形、可访问文字和明细来自同一份状态，保留来源、口径与合成数据标记。
- **Do** 让输入附近出现有效、空值与错误反馈，并保留恢复、键盘操作和减少动态效果。

### Don't:

- **Don't** 混用应用图标与陪伴角色的职责；界面内角色保持同一套 3D 材质与造型。
- **Don't** 裁切品牌板作为独立角色成品，或用简化头像替代完整角色的情感入口。
- **Don't** 用角色动作、完成色或模型回复冒充真实设备能力与业务验收。
- **Don't** 把本次问候字形子集、首屏构图尺寸或媒体处理瑕疵当作所有页面的规则。
- **Don't** 把整理完成当成原件或识别内容已经准确核对，也不要把截图的滚动、粘性叠层或焦点痕迹推广为默认样式。

- **Don't** 将人工预算样板的业务内容、双栏构图或一次性尺寸推广为所有结果的模板。
- **Don't** 将指引返回、文件保存或模型生成成功当作实际呈现、内容正确性或视频制作的验证。

以下日期段落保留历史实现与验收；涉及导航、快记展开、图标、尺寸和动效时，以前述 2026-10-05 Comfort 规则和当前源码为准。

### 2026-10-02 模型与文件接入

保留连续个人对话及钴蓝挽袖 IP。连接抽屉新增常用模型服务、模型 ID、密码式 API Key 输入和保存反馈；已有密钥只显示保存状态。高级 CLI 配置收在折叠项内。右上角新增安静的「文件」入口，文件抽屉显示磁盘实际产物、大小与下载链接；无需先创建工作项目。空目录、安装中、失败和可用状态分别说明。此次在实际桌面浏览器中完成查看、保存现有模型与下载验收；未新增移动端真机或 Windows 验收。

### 2026-10-03 自然的角色状态

完整角色在欢迎区为 440px，在聊天输入区为 96px，手机为 78px。点按触发真正的局部肢体动作，键盘同样可达；减少动态效果时将焦点交给输入框。角色位置和外框不做弹跳、旋转或缩放，也不附带虚构对白。普通控件反馈 150ms，抽屉进入 280ms，统一使用 `cubic-bezier(.16,1,.3,1)`。

真实状态分为待命、输入中、正在送出、处理中、等待确认、连接中断、人工接管。送出时选挽袖动作，执行中选思考，输入中选倾听，等待确认或人工接管选等待；点按招手播放一次后返回当前状态。已有回应与已核对继续分开，未增加完成庆祝。

常规按钮与字段统一 14px 圆角，主输入 28px／手机 25px，浮层 28px／手机 24px。导航轻触底色 `#f0f2f7`，柔蓝按钮 hover `#e0e7ff`，输入轻投影 `rgb(47 64 119 / .06)`。陪伴主文字 14px／手机 13px，说明 11px。

制作与验证记录：`design/motion/wearing-companion/states-20261003/`、`docs/evidence/character-states-2026-10-03.md`。这是可实际使用的实现，仍由用户评价审美效果。


2026-10-03 循环修订：v4 对六段生成源视频逐帧匹配脸部与蓝色布料的色调，消除生成器首尾的曝光变化；统一 #fafafa 背景并声明 BT.709 编码。只在末四帧将已校色画面收回首帧，封面从成品视频导出。品牌标志重画为七个纯色矢量形状，采用紧凑 viewBox；文件、书签、箭头和关闭图标统一圆角笔画。相关证据见 docs/evidence/character-loop-v4-2026-10-03.md。

2026-10-03 标志比例 v5：用户要求优先考虑图形美感。头部采用更短、更宽的扁圆轮廓，缩短眼睛，放柔衣领外缘；头像与 favicon 使用同一 SVG。完整角色视频沿用既有素材。


2026-10-03 标志设计 v6：当前试用折叠 W 符号。三段圆润的蓝色笔画形成连贯轮廓，奶油色小表情嵌入内侧折面，浅蓝色折边提供材质暗示。标志在头像、会话提示与 favicon 中共用；完整动态角色保持独立表现。纯色矢量源位于 design/vi/wearing-mark-redesign-20261003/wearing-fold.svg。


## 2026-10-03 身份交互增量

保持卷袖角色、SVG 字标、PNG 头像和现有视频不变。字标旁的圆润身份按钮显示当前名字，点击打开与现有侧栏一致的身份面板。身份条目包含名字、用途、当前标记和编辑入口，底部展示真实能力状态。创建表单只收名字、使用范围、用途；不要求先填写电话或支付资料。

切换立即清空旧消息显示，再读取当前身份记录；进行中的任务保留原归属，其他身份有任务时显示可跳转提示。未发送草稿按身份保留，模态框遵循原生焦点和 Escape 行为。小屏将身份按钮放在字标下方，保留文件及连接入口的点击区域。当前已在 852px 浏览器验证创建、切换、草稿及旧记录保留；手机浏览器真机尚未验收。

## 2026-10-03 持续目标输入与对话衔接

右侧目标表单沿用白色书写面、近白侧栏、钴蓝操作和柔和聚焦。主目标输入使用 28px 圆角、18px 内边距、15px 正文和 1.8 行高；约定及补充输入使用 14px 圆角，手机宽度保持 16px 输入文字。焦点复用主输入既有的 #91a2e3 边框与 #93a4eb 可见轮廓，不新增品牌颜色。字段标签、段间距和按钮组明确分层，写目标时收起列表，标题滚动时保持可见并遮住下方字段。

目标可进入主对话的「聊聊」或「补充」模式。柔蓝上下文条显示选中的目标及本次发送的语义，可随时回到日常聊天；发送补充后回到讨论模式。讨论不改约定；已保存的新情况、排队等待及未连接分别用文字解释。聊天转目标保留原话，由用户编辑确认。

## 2026-10-04 生活工具增量

生活记录与 Wearing 共处一个界面：日历、清单、笔记采用原有近白、书写白、钴蓝与系统字体。此前字标、卷袖 IP、对话、身份和持续目标规范继续适用；新增的 `life-*` tokens 只约束生活工具，不改变品牌问候字体或主对话字号。源码依据为 `src/wearing/web/index.html`、`life.css`、`life.js` 及其继承的 `style.css`；详细组件与响应式规则见 [生活工具设计记录](docs/design-life-tools.md)。

### Colors

选中的页面和记录类型使用浅钴蓝底与深钴蓝文字；保存动作沿用行动钴蓝。字段标签新增可复用的蓝灰 `life-field-label`，只用于生活工具表单。编辑区的浅蓝材料属于 `life-editor` 组件；日历 Monarch 主题映射既有钴蓝、中性色与真实选中状态，局部按压色不扩充为品牌色板。

### Typography

生活页面标题使用 `life-heading`；章节和编辑区标题使用 `life-section`。记录行、导航、保存按钮与编辑字段以 `life-body` 为基础；快记输入保持 `life-capture`，类型选择、笔记摘要和日历辅助操作使用 `life-label`。手机页面标题为 27px，章节标题为 17px，副说明与导航为 13px；这些是本 surface 的响应式值。记录标题用中等字重，时间与帮助保持现有标签层级，长标题和摘要允许折行。

**The Everyday Reading Rule.** 生活记录沿用原生中文阅读字体；页面标题、记录正文、时间和保存状态保持清楚层级，展示问候字体继续用于既有品牌问候。

### Layout

生活工具导航提供「今天、日历、清单、笔记、和 Wearing 聊」五个短入口，以浅蓝选中态和 `aria-current` 标识当前位置。内容容器最大宽度为 1140px，桌面左右内边距为 40px；今天的日程与待办平分两栏，最近笔记在下方。快记先接住文字，再选择笔记、待办或日程，不要求先整理分类。

编辑区在桌面与记录并列，保持可见并允许继续浏览；紧凑布局缩小编辑栏，在手机上改为内容上方的普通流布局。手机的今天页改为单栏；该轮横向滚动导航已由 2026-10-05 Comfort 底部导航替代，书写与操作区域保留可达尺寸。日历手机默认「一周安排」；日期与事件分层、标题及时间折行，以保留完整内容。准确断点及粘性偏移属于该 surface，见详细记录。

### Elevation & Depth

生活记录使用开放行与细分隔线，快记使用白底细边框，编辑区使用浅蓝色面；这些组件没有新增投影。快记聚焦时边框转为钴蓝，生活工具键盘焦点采用可见外描边（3px，偏移 3px）。普通按钮与快记反馈继承已有缓动和减少动态效果规则，不给记录增加装饰运动。

### Shapes

保存按钮和主导航复用 `control`；类型按钮、日历视图按钮与编辑字段使用 `life-control`，编辑区使用 `life-editor`，快记使用 `life-capture`。勾选目标是圆角方形，并有独立点击区域；已完成项同时使用勾号和划线文字。今日头像的裁切圆角、日历单元尺寸与第三方局部色值保留为组件实现值，不推广为新的品牌形状或全局尺度。

### Components

**The Same Record Rule.** 记录可以直接编辑，也可以带着标题与记录上下文回到既有对话；当前记录入口、保存反馈和重新打开入口保持可见，不另建一套 Agent 身份或对话材料。

记录行以标题、时间或清单归属组织，整行标题可打开编辑；笔记保留多行摘要。保存、移除、恢复与版本冲突使用文字反馈，恢复和撤销保留轻量入口。编辑中的最新版本与用户输入分别显示，错误沿用问题红语义。日历的月、周与一周安排属于同一组件，选中视图使用浅蓝色面；系统提醒尚未接入的状态继续明确说明。

### Do's and Don'ts

- **Do** 保留既有品牌资产与对话材料，让生活工具使用同一套钴蓝、系统字体和自然中文。
- **Do** 在手机显示完整日期、时间与记录标题，允许事件内容折行，并保留可见键盘焦点。
- **Do** 用实际保存、恢复和冲突状态的文字反馈支持直接编辑与回到对话。
- **Don't** 将今日头像圆角、第三方日历局部值或当前首屏摆位升级为所有页面的规则。

此次桌面与手机截图已由 finish reviewer 复核；手机日历裁切修复后最终 disposition 为 `ship`。截图证据位于 `docs/evidence/images/life-tools-2026-10-04/`，其中 `mobile-calendar-fixed.png` 为修复后的日历记录。本设计文档仅记录当前实现与已完成的截图复核。

2026-10-04 原生桌面增量：标准系统窗口与菜单承载既有 Wearing 页面，内置连接入口复用现有钴蓝、近白、SVG 字标、PNG 头像、14px 控件圆角与平台中文阅读字体；连接进度和失败继续以实际结果的中文文字说明。菜单快记与网页使用同一份生活记录，收起或退出客户端不表示后台事项暂停。窗口尺寸、连接页层级和恢复状态见 [原生桌面设计记录](docs/design-native-desktop.md)，组件的局部值保留在该记录与 `.impeccable/design.json` 中。本次 finish reviewer 最终 disposition 为 `ship`，页脚裁切已修复；证据仅覆盖 Mac 本地技术预览，前台菜单加速键已通过，后台全局按键仅确认注册成功，Windows／手机原生 App 未在此次验收。

### 公开研究来源（2026-10-05）

对话回应下方的 `.research-receipts` 默认折叠，不增加主按钮。已读取网页排在搜索摘要之前，同 URL 合并；查询过程为次级展开。正文使用既有字体、蓝色链接、弱分隔线与 `--control-radius`。标题与 URL 在窄屏换行，来源时间仅表示工具观察时间。3D 角色、品牌图标、导航与对话主焦点保持既有设计。

### 对话回复头像 · 2026-10-06

当前对话使用单独生成的静态头肩肖像 `chat-portrait.png?v=1`：奶油色圆角头、椭圆眼睛和蓝色衣领，正面轻歪头，与下方完整卷袖角色区分。桌面 44px / 窄屏 36px，圆形裁切与 `--blue-light` 底色，不增加外部玻璃边框、点击动作或循环播放器。头像同时用于回复、等待、确认提示和对话开场。陪伴区与其他入口的原有角色不变。生成提示词、母版与验证记录在 [聊天肖像设计记录](design/character/chat-portrait-20261006/README.md)。


## 2026-10-06 交互结果视图

Operate 模式，扩展现有对话。正文后显示一个可点击结果卡片：自然标题、最多两行摘要、媒介和版本；钴蓝只用于打开入口与悬停状态。16px 卡片圆角、现有色板与系统字体；不生成假的缩略图。

展开使用独立的宽画布，桌面最大 1100px，手机全屏；顶部保留标题、版本、下载、上一版与关闭，底部折叠“查看依据与假设”。交互页面在沙盒 iframe 中加载，聊天轮询不重建它；关闭或切换身份销毁。减少动态遵循系统设置。主要实现为 `web/artifacts.js` 与 `web/artifacts.css`。实际看板内容由 Agent 生成，每份结果另行检查，框架不将模型生成成功视为设计验收。

本地真实模型与浏览器验收见 `docs/evidence/result-delivery-2026-10-06.md`。


### 结果控件的共享基础 · 2026-10-06

结果页面使用三层结构：视觉与交互规范 → 可复用控件 → 按当前问题生成的布局、内容、数据与计算代码。基础样式保证同一产品的手感，页面结构由需求决定，不把预算样板变成固定业务流程。

`src/wearing/artifact_controls.py` 提供可内联的 `CONTROL_CSS`、`CONTROL_JS` 与最小 HTML 用法；`artifact_design_guide` v3 返回这些基础。当前覆盖组合数字输入、范围滑杆、关闭与折叠，其余控件仍按视觉规则具体实现。脚本只同步本页面的滑轨进度，不包含金额规则、远程调用或业务动作。

- **One Focus Surface.** `.wr-field` 整组字段承接一个圆润的焦点边界；内部输入不再叠加矩形框，错误、禁用仍有明确状态。字段保留原生输入、标签和读屏语义。
- **Native Range, Shared Skin.** `.wr-range` 在原生 range 上统一轨道、滑块、悬停、按压与键盘焦点。视觉轨道仅 4px，实际操作面 44px；4px 是细轨道的局部几何，不新增全局圆角。滑块的移动即时跟随原生值；代码赋值和恢复后用 `WearingUI.syncRange` 同步同一数据。
- 聚焦反馈 160ms，滑块按压反馈 140ms；减少动态时禁用过渡与缩放。规则统一到控件源码，具体页面只定义范围、步进、标签、单位和结果逻辑。

本轮窄范围复核覆盖鼠标聚焦、原生滑轨点击、Home/End、输入小数、恢复后的轨道同步和 390px 窄屏。Chrome 系内置浏览器已验证；Firefox 样式分支提供但未实机验收。


### 关闭、展开与 App 优先 · 2026-10-06

共享 CSS 位于 `web/result-controls.css`，宿主引用它，创作指引将同一内容内联提供给模型。`.wr-close` 保留 44px 点击范围，内部视觉面 30px，图标 18px；悬停使用中性色，按压仅收缩视觉面。初始焦点落到结果标题；Tab 到关闭时才出现局部焦点环。关闭操作不采用主行动按钮的蓝色选中效果。

`.wr-disclosure` 使用原生 details/summary；16px 线条箭头随展开转 90 度，180ms 状态过渡，减少动态时直接切换。滑轨的 4px 局部圆角服务于 4px 细轨道，不属于容器圆角层级；设计检查对此值的提示属于已文档化的几何例外，不抑制规则。

App 为后续主要体验入口。窄屏先定信息与操作，再扩展桌面；对话、结果、拍摄与录音的整个操作过程需要真机验收。原生宿主负责身份、导航、安全区、键盘与返回，生成的结果只负责当前问题的内容。第一阶段以输入、打开结果、返回继续聊为验收主线，详见 App 体验推进顺序。

### 连续对话与目标关联 · 2026-10-06

App 的普通标签切换保留同一身份的对话页面，让草稿、滚动位置和展开的结果保持连续；隐藏页面停止轮询与陪伴动画，回到前台再恢复。身份或连接切换清除旧实例。此为当前源码行为；原生生命周期、软键盘与系统回收后的恢复须分开验收，不以资源导出宣称已通过。

记录变化安排沿用原有表单和原生选择框，在变化范围之后说明“接着推进哪件事”，相邻解释原目标的状态和剩余轮次。关联成功但目标尚未启动时，反馈直接说明等待目标启动，不制造已经执行的印象。


### 「现在」与回看 · 2026-10-06

这次导航更新替代上文五项一级导航和宽屏侧栏。现在是唯一主场，静态细环与中心点是它的识别符号；身份和「回看」在顶栏，回看内按日历、Todo、笔记呈现三个稳定入口。文件、目标与定时任务、连接设置属于次级工具。查看和直接改记录保持可达，不依赖模型回合。命名说明用途，不把设备清单错误改称 Todo。

沿用钴蓝、近白、原 3D 卷袖角色；角色在空闲画面居中，主邀请在其下方；对话后仍沿用真实状态驱动的陪伴行为。网页桌面保留文字输入，App 底部默认原生语音按钮，旁边是文字切换。打开 App 不自动录音；录音结束先保存原件，识别后进入同一对话草稿，可修正再发送；后台与最长时长停止并保留录音。

回看一次打开最近查看的记录类型，初次为日历；其页内保留日历、Todo、笔记的轻量切换条，返回主场保留输入草稿。回看不再先弹出目的地菜单；文件、目标和设置改由「更多」进入。按钮命中区至少 44px，选中项用白色底与深色字区分；保留现有键盘焦点与减少动态规则。记录之间切换不再让整个页面淡入一次。原生客户端采用同一层级，详情返回所属记录视图。

设计检查提出的文字尺寸与身份按钮圆角已回到现有尺度：文字采用 17/22/28px，身份按钮使用 control 变量。没有新增全局忽略。1280px 与 390px 实际网页检查通过；旧侧栏占位、手机输入框底部空位与身份绝对定位残留已清理。原生键盘、VoiceOver/TalkBack、系统回收、录音背景切换尚未真机验证，因此不能称为完整 App 体验验收。


### 回看职责收束 · 2026-10-06

Todo 与笔记用于 review Agent 整理的内容。空态仅说明当前没有记录和内容来源，不放「和 Wearing 说一句」或手动新建按钮；完成、修改和纠正已有记录仍可直接操作，返回「现在」仍在固定位置。日历本轮保留现有手动补充入口。

### 2026-10-06 确认与决定回执

确认卡片保留 Wearing 的白色书写面、钴蓝主动作和细边框；24px 圆角，桌面 24px / 窄屏 18px 内边距。标题用既有 22px / 窄屏 17px 字号，具体动作 15px，影响说明 13px，状态 12px。一个显著的确认按钮，拒绝为安静的次级操作；手机命中高度 46px。没有额外入场弹跳或持续动画，轻按缩放 .975，减少动态效果时取消变形。

所有卡片原文按文本转义，不能插入模型 HTML。送出时整组动作禁用；确认成功变为一条可展开的回执，“已确认”与业务完成区分。失效和送达不明不重新开放确认，保留重新查看与结束本轮的恢复入口。现有电脑关键动作、设备权限、异常核对与目标核对表单共享卡片外观，继续各自的执行校验。

完成检查：桌面和 390px 浏览器实点确认/拒绝，两段真实模型原运行继续；无横向溢出；失效/重复/断网与辅助检查失败隔离回归通过。初次静态检查发现的颜色/字号/圆角漂移已收敛到既有设计，最终检查零发现。原生 App 真机未在此轮验收。证据见 [确认卡片验收](docs/evidence/confirmation-cards-2026-10-06.md)。


### 确认卡减法 · 2026-10-06

正常确认只保留短标题、具体内容与必要影响；一个强调的动作按钮和次要“不执行”。不再叠加“需要你决定”标签、嵌套影响区、装饰图标或常驻说明。费用、对象、权限范围始终直接可见；提交和异常提示按需出现。完成决定后收成一行可展开回执。移动按钮至少 46px，保留键盘焦点与减少动画偏好。共用组件位于 web/confirmations.js/css；本轮桌面/390px 网页已验收，App 真机另行验证。

2026-10-06 iPhone 客户端增量：延续 Wearing 的钴蓝、近白和真实 3D 角色，记录语音主入口、次级回看、原生栈、轻按与弹层规则，见 [iPhone 体验设计记录](docs/design-ios-experience.md)。当前为本机示例交互预览，iPhone 真机与 TestFlight 另行验收；预览外框和业务示例不属于全局设计规则。

### iPhone 常驻输入与五入口 · 2026-10-06 最新对齐

本轮更新 `/experience` 的导航规则：底部并列「现在、日历、任务、记忆、Wearing」，安静的图标与标签承接回看；同一输入栏位于导航上方，在各页保留草稿。现在使用圆环内的中心点表达当下；记忆使用简洁脑部轮廓；日历图标显示设备当地日期，跨午夜和回到前台更新。已有消息时回到当前对话。日历内回看日历和笔记；任务内查看待办、持续目标与定时安排。用户可见的 Todo 统一改为「任务」，内部数据类型保持原值。

输入栏固定 58pt，语音与文字共用同一位置；文字框固定 44pt，多行内容内部滚动。提示绝对定位在输入栏上方，退出时淡出，包含「已取消」在内均不改变底栏高度。默认矩形蓝框由整体圆角细边界替代，键盘导航仍有可见焦点。主导航选中态是低饱和浅底，不增加粗边。

输入模式、图标、页面内容、分段内容、提示与弹层采用可中断的轻过渡；进出成组处理，避免逐行播放。减少动态遵循系统偏好。菜单补充统一线性图标，只保留非主导航入口。延续近白、钴蓝与现有 3D 角色，不改 IP。

完成复核：390px 和 320px 布局；多行输入恒高；跨页保留草稿；对话往返；菜单显示与关闭。网页版预览通过本轮检查；真实录音、iPhone 软键盘和触感不在此验收范围。记录见 [底栏验收](docs/evidence/ios-quiet-dock-2026-10-06.md)。


### 返回后的进展 · 2026-10-06

实际服务和原生客户端共用身份隔离的进展快照：等你处理、正在推进、已有结果。首页只放一条安静的摘要，点开后看具体事项；有新结果与待处理事项同时存在时，两者都可被发现。结果在成功打开对应内容后才记已读，已读不代表批准或核对完成。连接失败保留上次内容与时间，活动状态来自上次记录；读取时间不得包装成引擎在线证明。窗口进出沿用既有过渡与减少动态偏好，键盘焦点保留细线反馈。

审视与缺口见 [产品标准审视](docs/plans/product-standard-review-2026-10-06.md)，本轮证据见 [返回进展验收](docs/evidence/activity-return-2026-10-06.md)。新 App 体验预览仍为示例，原生真实进展代码接入与 iPhone 真机验收分别记录。

### 聊天、完整月历与可靠交接 · 2026-10-07 最新对齐

表达主入口命名回到「聊天」，图标为对话气泡，替代 10 月 6 日「现在」及中心圆环的定义。底部仍为聊天、日历、任务、记忆、Wearing。日历图标显示当天，内容提供完整月历、前后月、今天和所选日的安排，月份与选中变化使用轻过渡；笔记保留在日历页内回看。内部 now/conversation 路由保持兼容。

用户随后否定本次衣服飘动的动画，当前 App 首页、Wearing 页与欢迎页使用定稿 3D 静态角色，不为角色添加漂浮或呼吸动作。输入邀请短句仍只演示一次，页面和操作反馈继续使用轻量过渡。合适的角色动作需单独评审，不以“必须动起来”为验收目标。

进展区增加独立「已排队」，不将等待算作正在执行或等用户决定。已撤回的消息保留历史、明确没有开始执行，不制造一份新结果通知。交接状态来自实际服务持久回执，预览示例不充当执行证明。细节见 [本轮验收](docs/evidence/chat-calendar-handoff-2026-10-07.md)。

### Pajio Web 与桌面 · 2026-10-07

正式名称定为 **Pajio**（数字品牌文件见 [design/brand/pajio](../design/brand/pajio/README.md)，App 记录见 [clients/mobile/DESIGN.md](../clients/mobile/DESIGN.md)）。常规网页与桌面端由本轮 ZCode 交付对齐：中性浅灰日间／石墨夜间语义配色（数值来源 `clients/mobile/src/appearance.ts`），取消旧天空-暖杏渐变、重玻璃外框与会员形卡片；正文为平静实色分层，账户信息全部真实。

- **主导文件**：网页主题 `src/wearing/web/pajio.css` 与外观/衣橱 `src/wearing/web/pajio.js`，视图渲染 `src/wearing/web/views.js`，入口 `src/wearing/web/index.html`；桌面壳 `clients/desktop/`（Tauri）。全部 Web 新规则以 `html:not(.mobile-host)` 门控，App 宿主（`mobile-host.css`/`mobile-host.js`、原生桥、WearingHost、ackSeq/ackVoiceId、身份与草稿边界）不受影响。
- **日夜**：浅色/深色/跟随系统三态，首帧内联脚本按 `appearance:v1` 偏好设定 `<html data-app-theme>`；跟随系统默认。该属性名与 App 桥一致，但网页分支自行写入，宿主内本模块整体惰化。
- **品牌**：字标与单颗四角星使用品牌包轮廓 SVG，favicon 换单星；默认睡衣小熊（雾蓝条纹）与八套衣橱资产来自 `clients/mobile/assets/bear/`。衣橱按 `wardrobe:v2:web:{identity}` 显式保存，预览不落盘，身份间隔离；旧 v1 只读迁移与 App 行业一致。
- **信息架构**：五入口聊天/今天/任务/记忆/我的；「今天」为真实任务/返回结果/需介入视图（读取时间、零状态、简报仅为草稿入口）；任务页接入 `/api/activity` 的 `limit/cursor` 分页，409 保留当前内容并提示刷新，总量与已载入数分开；非聊天页提供 48px「交代一件事/继续草稿」紧凑入口，回到聊天续用同一草稿。
- **兼容边界**：协议头、`wearing` 存储键、CLI 名称、API 与 `io.luckyloading.wearing.desktop` 安装标识保留；桌面壳 productName、窗口标题、菜单、托盘、连接页与图标为 Pajio，连接页随系统日夜。本轮证据见 [Pajio ZCode 交付](docs/pajio-zcode-delivery-2026-10-07.md)。
