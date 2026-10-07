---
name: Wearing App
description: 当前已实现的日夜外观候选；品牌与交互战略另见方案，不等于市场验证。
colors:
  day-canvas: "#F3ECE2"
  day-surface: "#FCF8F2"
  day-raised: "#FFFDF8"
  day-soft: "#EAE0D3"
  day-ink: "#3B312D"
  day-muted: "#6E6056"
  day-faint: "#6E6056"
  day-accent: "#8B5E40"
  day-accentSoft: "#E5D3BF"
  day-accentInk: "#4A3427"
  day-onAccent: "#FFFAF3"
  day-line: "#DCCEC0"
  day-danger: "#A83F40"
  day-dangerSoft: "#F6E3DE"
  day-success: "#436B53"
  day-successSoft: "#E0EADD"
  day-scrim: "rgba(39,30,28,.32)"
  day-dock: "#F9F2E8"
  day-portrait: "#E7D8C7"
  day-glow: "#E5CBAA"
  night-canvas: "#24232A"
  night-surface: "#302D34"
  night-raised: "#3B343B"
  night-soft: "#393139"
  night-ink: "#F0E4D5"
  night-muted: "#BCAEAA"
  night-faint: "#BCAEAA"
  night-accent: "#E4BC91"
  night-accentSoft: "#514035"
  night-accentInk: "#F0D1AF"
  night-onAccent: "#30251D"
  night-line: "#51444A"
  night-danger: "#F0AB9F"
  night-dangerSoft: "#503539"
  night-success: "#A4C7AF"
  night-successSoft: "#314339"
  night-scrim: "rgba(12,10,14,.62)"
  night-dock: "#2B282F"
  night-portrait: "#655248"
  night-glow: "#49372F"
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
    fontSize: "20px"
    fontWeight: 500
    lineHeight: "29px"
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
  today-card: "27px"
  profile-card: "28px"
  dock: "31px"
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
    backgroundColor: "{colors.day-accent}"
    textColor: "{colors.day-onAccent}"
    rounded: "{rounded.control}"
  button-primary-night:
    backgroundColor: "{colors.night-accent}"
    textColor: "{colors.night-onAccent}"
    rounded: "{rounded.control}"
---

# Design System: Wearing App

## Overview

当前实现记录，2026-10-07。语音交代、明确接收、执行进展与结果构成产品核心。暖中性色与完整日夜模式是已运行的视觉候选；品牌、信息主次和市场验证以[完整方案](../../docs/plans/product-brand-ux-strategy-2026-10-07.md)为下一轮决策依据。

作用域是 `clients/mobile` 与 `src/wearing/web/mobile-host.css` 的 App 宿主样式。常规网页与桌面由 ZCode 负责；旧根设计保留，不应覆盖 App。当前名称仍为 Wearing；新名称是研究候选，没有改包名、域名或对外品牌。

睡衣小熊八套资产、衣橱和头像已接入。最新方向将其定位为可选个性化；当前尚未实现角色隐藏开关。暂停额外资产扩张。不能将规划中的可选行为写成已交付。

## Colors

真实来源为 `src/appearance.ts`。使用语义 palette，通过 `app-theme.tsx` 提供给组件，`useThemedStyles` 随外观变化。frontmatter 的 day/night 是同一语义的两个值。

背景以 canvas 为主，底部弱暖色 glow；内容主要使用 surface、raised 和 soft，不再沿用 Today 天空到暖杏的全屏渐变。文字使用 ink/muted，主操作使用 accent/onAccent；成功与失败独立表达，并附文字。

开发版当前首次默认 night，可保存 day/night/system；用户选系统时响应系统颜色。下一版策略建议首次跟随系统，保留用户已有选择，此项尚未改默认值。聊天通过受控主题桥接切换，不重新加载 WebView 或清空草稿。手动模式下 iOS 日期选择器同步 themeVariant。

两套正文、次要文字与主要按钮组合已通过至少 4.5:1 的对比度测试。透明层、图片和全部屏幕的辅助功能检查仍待完成，不宣称全面合规或改善睡眠。

## Typography

采用系统字体。frontmatter 中 px 对应原生逻辑尺寸，非物理像素。聊天正文 17pt，长文约 16pt，关键操作不得只依赖小字。保留系统文字大小支持，长标题换行，全文进入阅读视图。

## Layout

当前五入口：聊天、今天、任务、记忆、我的；固定语音/文字输入与导航。App 壳和聊天禁用整页捏合，正文正常滚动，原件阅读器可独立缩放。外观、衣橱下沉及非聊天页输入收敛是下一阶段方案，未在当前版本实施。

共享触达至少 44pt，tab 最小 44×52pt；卡片间距 16–24pt，主内容单列。记忆文件夹可两列，阅读回单列。

## Elevation & Depth

用 surface/raised 层次、边界和间距建立前后关系。主阅读层不依赖重模糊；材料效果不能降低文字清晰度。日夜图片均检查白底刺眼和毛绒边缘。当前截图显示主题与衣橱占首屏过多，下一轮优先修改信息层级。

## Shapes

圆角采用 small/control/card/sheet 等现有尺度。只在容器和明确控制处使用大圆角，不为每段话增加卡片。图标保持同组线宽和可访问名称。

## Components

`AppBackdrop` / `AppDock` / `BottomNavigation` 构成原生壳；`Conversation` 保留同一个聊天 WebView；`VoiceComposer` 使用真实录音链路，松手后可编辑并主动发送。`TodayPanel`、`ActivityReview`、`PersonalHub` 均使用当前身份真实数据，缺失或失败不可填成演示数据。

`AppearancePanel` 显示晚安/日光/随系统，保存成功后生效；`WardrobePanel` 使用八个 `PajamaBear` 资产，按服务与身份隔离。图片无待机循环；动画只服务按压、进入与状态反馈。

设置中的能力目录不等于已授权；账户卡不伪造会员或额度；结果返回不等于外部业务已核验。语义契约优先于装饰。

## Do's and Don'ts

- 正常、加载、失败、空、离线和部分完成均有明确表达。
- 保持减少动态效果、系统字号和安全区域；日期组件与正文都随主题变化。
- 去重进展信息，提供具体下一步，技术日志不占聊天主区域。
- 不用人物表情、循环动画或假百分比代表实际任务进度。
- 不把构建、截图或合成测试作为真机跨夜执行、品牌偏好或市场需求的证明。

验证见 [本轮局部检查](../../docs/evidence/brand-ux-audit-2026-10-07.md)。原 `/experience` 与静态 token 仍含历史预览，不是当前真机或品牌最终验收依据。
