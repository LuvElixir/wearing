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
typography:
  display:
    fontFamily: 'WearingGreeting, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "52px"
    fontWeight: 500
    lineHeight: 1.42
    letterSpacing: "-1.4px"
  wordmark:
    asset: "/assets/wordmark.svg?v=1"
    construction: "Fredoka 530 outlined paths, optical word spacing, cobalt g terminal"
    width: "132px"
    mobileWidth: "112px"
    height: "auto"
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
rounded:
  control: "14px"
  companion-button: "16px"
  panel: "28px"
  panel-mobile: "24px"
  composer: "28px"
  composer-mobile: "25px"
  circle: "50%"
spacing:
  gap-tight: "8px"
  gap: "12px"
  inset-sm: "14px"
  inset: "18px"
  section-sm: "20px"
  inset-wide: "24px"
  section: "30px"
components:
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
    rounded: "28px"
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
---

# Design System: Wearing

## Overview

**Creative North Star: "属于你的行动者"**

Wearing 的亲切感来自完整的钴蓝卷袖角色与自然中文。奶油色的圆角方头、两只椭圆眼睛、带布料质感的外套和浅色袖口，落在安静的近白空间里。挽起袖子的姿态表达“我来帮你做”，与界面里的“这件事，我来。”一致。

这份系统记录当前个人 Agent 界面的源码实现。连续对话是主要阅读与行动空间；角色负责建立熟悉感，界面负责让文字、真实状态和下一步清楚可见。辅助设置与以前留下的事情在需要时展开，保持日常交谈的舒适密度。

**Key Characteristics:**
- 完整卷袖角色、简化标志与 Wearing 字标各司其职。
- 近白空间、白色输入区域、浅钴蓝消息与清楚的墨灰文字。
- 中文问候具有独立展示字体，日常对话使用平台原生中文字体。
- 文字、留白和细分隔线建立层级，角色材质保留自然体积。

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

### Named Rules

**The Action Cobalt Rule.** 钴蓝集中承载动作、交互反馈与用户消息的关联；状态颜色必须跟随真实探测或记录。

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

### Named Rules

**The Greeting and Reading Rule.** 展示字体负责品牌与问候，原生中文字体负责持续阅读；现有子集仅覆盖当前用途，新增展示文案须核查字形覆盖。

## Layout

空间围绕连续对话展开。顶部是小字标与文件、记录、连接三个安静入口；主内容最大宽度 1200px。当前欢迎状态中，完整角色与问候并列；开始交谈后，同一区域换成最大宽度 740px 的连续消息，完整角色移到输入框上方的陪伴区。角色容器保持同一个；两个视频缓冲交替解码，共用静帧和布局。用户消息靠右，回复靠左并带简化角色标志；消息容许长文本换行。

输入区域始终贴近当前对话，使用粘性底部位置，桌面宽度为 `min(780px, calc(100% - 64px))`。它保留页面色承托，消息滚动经过时维持清楚的书写区域。辅助面板从右侧打开，宽度为 `min(480px, 100%)`，由原生对话框管理焦点与遮罩。

响应式分界为宽屏 1500px、紧凑布局 850px 和手机 600px。紧凑布局收缩角色与左右留白；手机将角色放在问候上方，文字居中、问候取消硬换行。手机输入区左右各留 18px，消息区左右各留 20px；辅助面板占满可用宽度。顶部“记着的”入口隐藏文字，保留书签 SVG 与可访问名称。

重复间距采用前置元数据中的节奏：控件与图标较紧凑，消息、章节与主要区域逐层放宽。欢迎页的角色尺寸、双栏比例和问候摆位属于当前 surface；新增页面应继承阅读密度与品牌关系，不机械复制首屏。

## Elevation & Depth

仅在输入框聚焦和角色回应气泡使用轻微向下的柔和投影；其余界面主要由色面和细线分层。近白页面、白色书写区、浅蓝消息、细边框和半透明对话框遮罩构成界面层级。角色图像自身的柔和投影与布料明暗属于 IP 的真实材质，必须保留其体积感。图像和视频按原比例完整显示，最终媒体背景与页面近白底色一致。

键盘焦点采用可见外描边（3px，偏移 4px）。输入组合通过边框改变反馈焦点；命令背景、次要按钮悬停色等局部材料值保留在组件样例中，不扩充为装饰色板。

### Named Rules

**The Quiet Interface, Tactile Character Rule.** 界面靠色面、边框与留白分层，角色靠布料、光影与轮廓建立存在感；两者保持各自的材料逻辑。

## Shapes

连接字段与常规按钮沿用轻圆角 `control`。发送、关闭和动效控制采用圆形；当前发送按钮为 42px，动效控制最终有效尺寸为 40px。对话输入区使用更柔和的整体圆角，手机缩至 25px。用户消息以一个较小的尾角表达说话方向，具体圆角属于消息组件。

角色保持完整轮廓与方圆头部，不裁切成品牌板局部。图标使用圆端、圆转角的细线 SVG；默认线宽 1.7，按按钮用途缩放，不使用文字字符替代图标。

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

### Inputs / Fields

连接字段是白底、细边框、轻圆角。对话输入由多行文字与发送按钮组成；整体边框在聚焦时变化，保留 0.2s ease 过渡。Enter 发送、Shift + Enter 换行，中文输入法组字时不触发发送。建议入口只把句子填入输入框并聚焦，由用户继续表达。

离线消息显示“已保存在本机”并提供连接入口；连接后草稿可继续送出。消息返回不等同于已核对的外部结果，核对记录由真实动作写入。上述状态必须使用可见文字，不由角色表情或动画暗示完成。

### Navigation

主入口位于顶部：Wearing 字标回到对话，“一起记着的”打开旧记录，连接状态打开设置。辅助按钮默认说明灰，悬停钴蓝。连接圆点只有实际可达时才使用钴蓝。设置中的设备报告显示探测时间，并说明操作能力仍需验证；尚在开发中的能力保持明确说明。

连接面板先呈现“在这台电脑开始”，安装与启动状态按本地引擎实际结果变化。模型设置沿用官方向导；远程地址与密钥收进“连接另一台电脑或已有的 Hermes”。整个流程沿用现有文字、按钮、分隔线和原生 details，不在主对话增加管理卡片。角色视频使用修正后的 5 秒稳定循环和匹配首帧封面。

### Character Presence

完整 IP 基于独立生成的角色，品牌依据为已选钴蓝卷袖方向。当前 `src/wearing/web/character-poster.png` 从最终角色视频的首帧导出，保持静帧与播放画面连续。对话头像、会话提示与图标使用 `avatar.png`：从已认可的角色草图制作独立透明图片，保留造型与衣料的柔软细节；不再使用手描 SVG 头像。它不能替代首屏的完整角色。字标使用独立的 `wordmark.svg` 路径。角色的圆角方头、双椭圆眼睛、钴蓝布料与浅色袖口保持一致。

动效语义由真实上下文决定：待命、点按招手、倾听、思考、挽袖动手、等待接手。`character.json` 声明六段 720p 无声短动作，均经过逐帧材质校色并收回自然姿态；当前状态原生连续循环，加载好首帧才切换视频，普通状态变更等待当前动作完成，人工接管立即结束工作动作。循环与状态切换不插入静帧或等待间隔，点按不会叠加请求。首页、陪伴区均无播放／暂停控件，无原生视频控件。系统减少动态效果显示静帧，隐藏页面或离屏暂停，媒体失败保留静帧。动画只表达陪伴和当前处理状态，不代表业务成功。

## Do's and Don'ts

### Do:

- **Do** 保留完整角色、简化标志和字标之间的清楚分工，以及角色图像原比例。
- **Do** 让挽袖姿态与准备帮忙的中文表达保持一致。
- **Do** 使用文字交代连接、保存、执行与核对状态，并以真实数据驱动变化。
- **Do** 保留输入区焦点、键盘可达性、系统减少动态效果与静帧回退。
- **Do** 让持续阅读保持舒适行高，手机优先保证对话和输入可用。

### Don't:

- **Don't** 裁切品牌板作为独立角色成品，或用简化头像替代完整角色的情感入口。
- **Don't** 用角色动作、完成色或模型回复冒充真实设备能力与业务验收。
- **Don't** 把本次问候字形子集、首屏构图尺寸或媒体处理瑕疵当作所有页面的规则。

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
