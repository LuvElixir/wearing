---
name: Pajio App
description: 当前 App 采用睡衣小熊作为默认助手形象，以近中性日夜外观和真实能力组织体验；名称与数字品牌文件已确认。
colors:
  day-canvas: "#F6F7F9"
  day-surface: "#FFFFFF"
  day-raised: "#FFFFFF"
  day-soft: "#ECEEF2"
  day-ink: "#202228"
  day-muted: "#565C68"
  day-faint: "#626975"
  day-action: "#24262B"
  day-actionPressed: "#383C44"
  day-onAction: "#FFFFFF"
  day-accent: "#3156C8"
  day-accentSoft: "#EDF1FF"
  day-accentInk: "#2545A5"
  day-onAccent: "#FFFFFF"
  day-line: "#DDE1E7"
  day-outline: "#737B89"
  day-danger: "#B42338"
  day-dangerSoft: "#FDEEF0"
  day-success: "#176449"
  day-successSoft: "#E8F3ED"
  day-attention: "#6546A2"
  day-attentionSoft: "#F2EDFB"
  day-scrim: "rgba(20,22,26,.32)"
  day-dock: "#F6F7F9"
  day-portrait: "#ECEEF2"
  night-canvas: "#14161A"
  night-surface: "#1C1F25"
  night-raised: "#262A32"
  night-soft: "#282D36"
  night-ink: "#F0F2F5"
  night-muted: "#B8BEC9"
  night-faint: "#A4ACB9"
  night-action: "#E4E8EF"
  night-actionPressed: "#CDD4DF"
  night-onAction: "#181B20"
  night-accent: "#A3B7FF"
  night-accentSoft: "#263253"
  night-accentInk: "#D1DBFF"
  night-onAccent: "#14214B"
  night-line: "#353B46"
  night-outline: "#7A8596"
  night-danger: "#FFA7B3"
  night-dangerSoft: "#41252D"
  night-success: "#8FD6B0"
  night-successSoft: "#213B2E"
  night-attention: "#C8B1F2"
  night-attentionSoft: "#32273F"
  night-scrim: "rgba(0,0,0,.60)"
  night-dock: "#14161A"
  night-portrait: "#282D36"
typography:
  display:
    fontFamily: "system-ui"
    fontSize: "34px"
    fontWeight: 500
    lineHeight: "44px"
    letterSpacing: "-0.7px"
  greeting:
    fontFamily: "system-ui"
    fontSize: "25px"
    fontWeight: 600
    lineHeight: "35px"
  card-title:
    fontFamily: "system-ui"
    fontSize: "19px"
    fontWeight: 500
    lineHeight: "28px"
  reading:
    fontFamily: "system-ui"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: "28px"
  summary:
    fontFamily: "system-ui"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: "24px"
  detail:
    fontFamily: "system-ui"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: "19px"
  navigation:
    fontFamily: "system-ui"
    fontSize: "11px"
    fontWeight: 500
    lineHeight: "16px"
rounded:
  small: "12px"
  control: "16px"
  card: "24px"
  today-card: "16px"
  profile-card: "20px"
  section: "18px"
  sheet: "32px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
  section: "40px"
components:
  button-primary-day:
    backgroundColor: "{colors.day-action}"
    textColor: "{colors.day-onAction}"
    rounded: "{rounded.control}"
  button-primary-night:
    backgroundColor: "{colors.night-action}"
    textColor: "{colors.night-onAction}"
    rounded: "{rounded.control}"
---

# Design System: Pajio App

## Overview

**Creative North Star: "放心交代，回来能用"**

当前 App 实现记录，2026-10-07。正式名称为 **Pajio**，中文与英文界面统一使用；默认助手为已确认的睡衣小熊。语音交代、明确接收、执行进展与结果构成产品核心。近中性日夜色面、单四角星、账户与能力前置和个性化二级入口已写入当前源码。数字品牌资产已完成，市场验证尚未完成。[本轮交付证据](../../docs/evidence/pajio-delivery-2026-10-07.md)记录当前检查边界；[Pro 研究](../../docs/review/brand-reset-20261007/pro-review.txt)与[独立审视](../../docs/review/brand-reset-20261007/independent-review.md)是设计输入，不代替真实用户证据。

作用域是 `clients/mobile` 与 `src/wearing/web/mobile-host.css` 的 App 宿主样式。常规网页与桌面由 ZCode 负责；旧根设计保留，不应覆盖 App。当前运行界面名称为 Pajio；底层 wearing 包名、协议、存储键与安装标识保留兼容。

当前品牌方向为[睡衣小熊](../../docs/plans/pajama-bear-brand-direction-2026-10-07.md)。八套资产已接入；无有效保存选择时默认雾蓝条纹小熊，已有 v1 穿搭和有效 v2 明确形象选择继续保留。外观二级页按睡衣小熊／简洁标记排列，切换不改变能力。正式名称为 Pajio；技术安装标识继续兼容，数字品牌文件见 [Pajio 品牌包](../../design/brand/pajio/README.md)。主张为「你先休息，这件事我来」，日常交互为「你说，我来做」。

**Key Characteristics:**
- 中性浅灰／石墨色面承接持续阅读，主操作与小面积钴蓝强调各有语义。
- 账户、能力与数据控制优先，可选外观进入二级页。
- 睡衣小熊承担角色识别，单个实心四角星用于紧凑辅助触点；功能图标保持独立语义。
- 主题、形象和真实执行状态分别保存与反馈。

## Colors

真实来源为 `src/appearance.ts`。使用语义 palette，通过 `app-theme.tsx` 提供给组件，`useThemedStyles` 随外观变化。frontmatter 的 day/night 是同一语义的两个值。

`AppBackdrop` 使用纯 canvas 色面，`AppDock` 使用同色 dock，无底部光晕或外层圆角。内容主要使用 surface、raised 和 soft；文字使用 ink/muted，主 Paper 按钮使用 action/onAction，钴蓝 accent 用于链接、选中和少量强调。当前底色为中性浅灰／石墨，success、danger 与 attention 分别声明成功、错误和需介入语义，并须配合真实文字状态。源码保留 glow 兼容字段，其值与 canvas 相同；当前背景不渲染该装饰层。

首次默认 system，保留已保存的 day/night 明确选择；系统为 light 时显示浅色，其他值回退深色。外观选项为「浅色／深色／跟随系统」，保存成功后才更新当前选择，读取和保存失败有真实反馈。聊天通过受控主题桥接切换，不重新加载 WebView 或清空草稿。手动模式下 iOS 日期选择器同步 themeVariant。

`actionPressed`、`outline`、`attention`／`attentionSoft` 已进入 palette 定义；本次读取时，部分待处理标记仍使用 ink 或 accentInk，Paper outline 仍映射 line。这些语义 token 的存在不等于所有控件已经接入；不得把全页状态映射与边界辨识验收写成完成。

正常文字采用至少 4.5:1 的设计底线。Pro 报告的指定组合计算属于其独立 token 包；本记录不把报告中的检查成绩转记为 App 测试结论。透明层、图片、焦点和全部屏幕需另行核对，配色不能据此宣称全面辅助功能合规、观看舒适或改善睡眠。

## Typography

采用系统字体。frontmatter 中 px 对应原生逻辑尺寸，非物理像素。聊天正文 17pt，长文约 16pt，关键操作不得只依赖小字。保留系统文字大小支持，长标题换行，全文进入阅读视图。原生 fontScale 已通过受控脚本传给保留的聊天 WebView，宿主正文、气泡、状态和搜索使用同一缩放变量；输入栏允许内容随字号增长。浏览器宿主 200% 文本缩放已检查无横向溢出，这不是实体 iPhone 的系统大字号验收。全页字级、触达和所有原件类型仍需按 [研究决策矩阵](../../docs/review/brand-reset-20261007/research-decisions.md)继续核对。

## Layout

当前五入口保持聊天、今天、任务、记忆、我的。「我的」使用 UserRound 账户图标，与用户是否显示小熊无关。设置／我的先显示账户摘要，再依次呈现能力与连接、数据与身份、偏好设置；「外观与个性化」进入二级页，衣橱再下一层。账户摘要当前最小高度为 128pt，采用单层实色容器，不沿用旧会员卡装饰。

聊天保留完整语音输入；今天、任务、记忆等阅读页面采用 48pt 起的「交代一件事／继续草稿」紧凑入口，点按回到聊天。设置、我的、本机能力、连接和采集页隐藏共用聊天输入，采集页保留其独立记录表单。导航继续保留，同一连接／身份的 WebView 与草稿控制器留存。App 壳和聊天禁用整页捏合，正文正常滚动，原件阅读器可独立缩放。

共享触达至少 44pt，tab 最小 44×52pt；卡片间距 16–24pt，主内容单列。记忆文件夹可两列，阅读回单列。

## Elevation & Depth

用 surface/raised 层次、边界和间距建立前后关系。App 背景与底栏为稳定实色，账户摘要与设置分组以细边界分层；主阅读层不依赖重模糊。材料效果不能降低文字清晰度；可选图片在日夜模式下的边缘与背景仍须实际观察。Mobile 的整页入场平移已经移除，普通页面内容直接切换；局部控件、tab 选中和浮层仍沿用各自真实反馈及减少动态效果，不能宣称全部动效已统一为 Pro 的目标时长。

## Shapes

圆角采用 small/control/card/sheet 等现有尺度。当前账户摘要、设置分组和外观面板使用 18pt；记忆介绍／摘要与形象选择面板使用 20pt。底栏本身没有胶囊外框，选中 tab 保留 16pt 色面。今天的卡片与分组已经收敛为 16pt；衣橱和其他局部大圆角仍有保留，不能把本轮收敛说成所有容器均已改造。功能图标保持同组线宽和可访问名称。

`BrandStar` 是 24×24 viewBox 内约 16×20 的纵长单路径、单中心、四尖端实心标记，使用当前 ink 单色。它用于应用图标、日夜启动页、账户签名、简洁模式进展入口及形象预览；小熊模式进展入口显示当前穿搭头像，导航与技能仍使用各自功能图标。装饰星自身不增加辅助焦点。

`BrandWordmark` 使用 Pajio 的 Nunito 760 字重轮廓字标，标准写法不带句号。字标以 SVG 路径随包提供，通过当前 ink 适应日夜，无网络字体依赖；OFL 授权随资产保留。应用图标、Android 自适应图标与 72pt 日夜启动页来自同一品牌母版。名称、权限说明和新 `pajio://` scheme 已配置，旧 `wearing://`、安装标识与数据键保留兼容；Android 原生目录的名称、双 scheme、五级密度图标与日夜启动资源已从隔离的 Expo 候选同步；`expo-system-ui` 支持 Android 跟随系统。保留原安装标识与本机网络安全配置，详见[原生同步证据](../../docs/evidence/pajio-20261007/native-brand-sync.json)。iOS 原生候选由 CNG 在临时目录生成，未手工建立项目内 ios；独立安装包与启动页仍须设备验收。

## Components

`AppBackdrop` / `AppDock` / `BottomNavigation` 构成原生壳；`Conversation` 保留同一个聊天 WebView；`VoiceComposer` 使用真实录音链路，松手后可编辑并主动发送。`TodayPanel`、`ActivityReview`、`PersonalHub` 均使用当前身份真实数据，缺失或失败不可填成演示数据。今天已按待处理、最近返回、推进、排队和历史组织，counts 提供总体数量。活动服务提供 revision、cursor 和分页计数；任务与归档提供加载更多，跨页快照不一致或过期返回 409 时保留已读内容并要求刷新，不把不同修订拼接成完整列表。今天、进展与任务页已通过 `useActivitySnapshot` 共用同一身份与凭据作用域的内存首页快照，并复用请求与轮询；后台或无订阅者时停轮询，旧请求不会写回新作用域。归档分页保留固定修订，避免混入新的首页。该缓存不持久保存凭据，也不等于执行器心跳、后台执行或离开期间变化摘要。活动投影将结果返回、已核对、失败、停止、结案与未知分别表示；读取时间不冒充执行端最近观察。

网络状态已接入原生网络观察；发送同时检查真实离线状态、发送中状态和当前页面 ready 回执。网络类型尚未知时不伪报离线，未就绪仍不能发送。读取、转写或发送失败分别反馈，不把本机保存当作服务已接收。

记忆详情逐条提供「纠正这条」，带入真实选中条目及所在分区，用户编辑后发送。较长条目明确标注节选；此操作不直接改记忆，记忆来源、更新时间和删除／停用仍需要独立数据合同。

`AppearancePanel` 位于外观二级页，提供浅色／深色／跟随系统的原生可访问单选行。`CompanionPreferencePanel` 保存简洁标记／小熊；简洁模式隐藏衣橱入口，保留已选穿搭。`WardrobePanel` 继续使用八个 `PajamaBear` 资产，预览后由「穿这套并显示小熊」明确保存，不把预览当作已保存。

形象状态按服务与身份隔离，存储为 `wardrobe:v2`。没有 v2 时只读已有 v1，若存在有效明确穿搭则保持小熊与原款式；启动不重写旧记录，后续用户选择才写 v2。保存失败保留当前已生效形象并显示重试；切换到简洁标记不删除穿搭。图片无待机循环，现有按压、进入与真实状态反馈遵循减少动态效果。

**The Truthful Status Rule.** 设置中的能力目录不等于已授权；账户摘要显示实际身份、连接与模型状态，不伪造会员或额度；结果返回不等于外部业务已核验。语义契约优先于装饰。

**The Companion Identity Rule.** 睡衣小熊是默认助手形象，保留简洁模式和既有明确偏好；默认选择、持久化与保存失败分别处理，外观切换不暗示能力变化。

## Do's and Don'ts

- 正常、加载、失败、空、离线和部分完成均有明确表达。
- 保持减少动态效果、系统字号和安全区域；日期组件与正文都随主题变化。
- 去重进展信息，提供具体下一步，技术日志不占聊天主区域。
- 不用人物表情、循环动画或假百分比代表实际任务进度。
- 不把构建、截图或合成测试作为真机跨夜执行、品牌偏好或市场需求的证明。

当前验证入口为 [Pajio 交付证据](../../docs/evidence/pajio-delivery-2026-10-07.md)，最终测试计数、TypeScript、源码 ESLint 与 iOS bundle 导出状态以该证据文件为准，避免把共享活动缓存新增前的一轮成绩当作最终版本。浏览器宿主大字号检查只证明被测页面布局，不证明实体 iPhone、跨夜运行或市场验证。既有 [局部检查](../../docs/evidence/brand-ux-audit-2026-10-07.md)须核对采集版本。`/experience` 已同步 Pajio、睡衣小熊与生产浅色 token，但仍是标注示例的交互预览，不是真机或真实委托验收。后续工程和用户研究继续按 [决策矩阵](../../docs/review/brand-reset-20261007/research-decisions.md)追踪。
