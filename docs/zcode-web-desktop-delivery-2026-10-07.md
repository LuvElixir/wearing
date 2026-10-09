# ZCode 网页 / 桌面迁移交付 · 2026-10-07

状态：本轮由 ZCode 完成，依据 [App 交接](app-today-zcode-handoff-2026-10-07.md) 与 [App DESIGN.md](../clients/mobile/DESIGN.md)。本文记录改动文件、运行入口、已完成与未完成范围、验证证据。不代表品牌定稿或全量真机验收。

## 运行入口

- 网页 / 桌面同源：本机 `wearing serve`（当前实例 `http://127.0.0.1:8765`，验证期间未重启、未部署）。
- 视图直达参数：`?view=capture`（今天）、`?view=tasks`、`?view=memory`、`?view=me`；`?host=mobile&composer=native` 为 App WebView 宿主分支。
- 截图证据：[docs/qa-web-desktop-20261007/](qa-web-desktop-20261007/)（聊天、今天、任务、记忆、我的、搜索、窄屏、App 宿主回归各一张）。

## 改动文件

| 文件 | 改动 |
| --- | --- |
| `src/wearing/web/today.css`（新增） | Web/桌面 Today 主题。天空至暖杏连续背景、透光卡片、克制选中态、五入口顶栏与窄屏底部 Dock、账户卡与能力格、搜索浮层。**每条规则均以 `html:not(.mobile-host)` 门控**，App WebView 不加载任何新观感。 |
| `src/wearing/web/views.js`（新增） | 「记忆」「我的」两个视图的渲染（真实接口驱动）、对话内搜索（纯页内查找，不发请求）、导航日期角标。App 宿主下整模块直接 return，不注册任何行为。 |
| `src/wearing/web/index.html` | 顶栏改为「Wearing 字标 + 身份胶囊 + 五入口导航 + 搜索/设置」；旧「回看 / 更多」按钮保留在 DOM（`web-hidden`）供共享 `now.js` 绑定 App 宿主跳转；主题色 meta；引用新资产并提升版本号。 |
| `src/wearing/web/life.js` | `today` 别名指向 `capture`（今天视图）；视图集合纳入 `memory` / `me` 并委托 `WearingViews.render`；`body[data-view]`；身份切换时通知视图重置跳过标记。 |
| `src/wearing/web/app.js` | `turnActions` 收敛：聊天回复不再逐条渲染「核对结果 / 记成目标」；真实执行控制（先停一下 / 重新查看）、澄清与回执表单、`note-saved` 回执全部保留；旧任务详情仍保留「核对结果」入口；`renderGoalUpdates` 同步任务入口徽标。 |
| `tests/web-today-ui.test.cjs`（新增） | 结构回归：资产加载顺序、五入口顺序、today.css 宿主门控（逐规则断言）、today 别名、views.js 宿主惰性与搜索零请求、聊天回复无逐条核对/记成目标、徽标同步。 |
| `docs/qa-web-desktop-20261007/*.png`（新增 8 张） | 实跑截图证据。 |

只读遵守：`clients/mobile/**`、`mobile-host.css`、`mobile-host.js`、`now.js`、后端 / 合同 / 认证 / 数据库 / 语音 / 录音 / 生产配置均未改动；未部署、未 push、未迁移、未重启服务。`app.js` / `life.js` / `index.html` 属并行工作树上他人已有改动的文件，本轮只做上述增量，未还原或覆盖他人内容。

## 已完成范围

1. **五入口导航（聊天 / 今天 / 任务 / 记忆 / 我的）**：桌面为顶栏胶囊，窄屏（≤600px）落到底部透光 Dock；选中态为低对比中性胶囊；「今天」入口图标显示本地当日日期；目标新进展以红点徽标呈现在「任务」入口。
2. **今天视图**：沿用 `capture` 视图的真实内容（今日日程、惦记的事、最近记下的 + 随手记表单），透光卡片材料，主标题改为「今天」。
3. **任务视图**：真实任务分组卡片化；目标与定时入口保留在原面板（导航徽标提醒）。
4. **记忆视图**：关于你 / 一起积累的经验（区分未开启、读取失败、空），标注「读取于」时间；资料文件只读预览（前 8 个 + 截断提示），入口进文件面板。
5. **我的视图**：会员形账户卡（渐变铺满圆角、独立背景层）显示真实身份名、个人空间 / 云端实例、连接点；能力格逐项真实状态（本地引擎、模型服务、这台电脑、手机、文件空间、记忆），每项来自真实接口，无虚构 Pro / 到期日 / 额度。衣橱入口仅预留 `data-wardrobe-slot` 结构，不渲染占位 UI。
6. **对话搜索**：页内查找用户气泡与助手正文，计数、上一处 / 下一处、完成，命中高亮；不发任何请求；会话重绘后自动重算。
7. **聊天净化**：每条助手回复下的「核对结果」「记成目标」移除；全局进展仅剩顶部一条轻量横幅（activity-return）；goal-updates 卡在 Web 隐藏（信息由徽标与任务面板承载）；旧卷袖角色头像退出新界面（presence/face 机制保留，仅 CSS 隐藏）。
8. **大屏适配**：内容列宽与卡片栅格（我的能力格 auto-fill），聊天气泡对齐 App 材料（白透光助手气泡、灰蓝用户气泡）。

## 验证证据

- **测试**：`node --test tests/*-ui.test.cjs` 101 通过（基线 94 + 本轮新增 7）。Python 相关面：`test_api` / `test_dev_mobile` / `test_gateway` / `test_tenant_worker` 共 74 通过。
- **既有失败（非本轮引入）**：`tests/test_life.py::test_profile_exposes_life_tools_preserving_model_config` 因并行工作树中 `profile.py` 给 `mcp_servers.wearing_life` 新增 `timeout` / `elicitation` 字段而失败；本轮未改任何 Python，按约不代为修复。
- **实跑**（本机 8765 实例，真实数据）：
  - 五视图桌面截图 + 窄屏 Dock 截图 + 搜索交互截图（命中 3 处、翻页 2/3→3/3、完成清除高亮）。
  - DOM 断言：聊天 6 轮回复 0 个逐条「核对结果 / 记成目标」；goal-updates 卡 CSS 隐藏；`wearing-face` 头像全部不可见；导航顺序正确。
  - **App 宿主回归**（`?host=mobile&composer=native`）：`mobile-host` / `native-composer-host` 类生效、body 透明、渐变层 `::before` 为 none、header/nav/composer 隐藏、助手气泡沿用宿主样式；`WearingHost.openReview` 桥接 files / goals 面板正常打开。
  - **身份隔离**（真实双身份实例）：记忆视图在切换后不再串数据；切回原身份内容恢复；另一身份按真实回执显示「执行引擎还未启动」；全程零未捕获异常。
- **本轮发现并修复的两个缺陷**（均由实跑暴露，已补进结构测试的关联行为）：
  1. 身份切换清空容器但不清 `data-view-key` 跳过标记，切回原身份时记忆视图卡在加载态 → `WearingViews.reset()`。
  2. `available=false` 的身份 `/api/memory` 无 `targets` 字段，直接取值抛异常 → 与聊天面板一致按真实回执呈现。

## 未完成与边界

- **自动图文简报**：未实现生成 / 定时 / 权益链路；「今天」不显示虚构简报。
- **云端 OAuth / 外部应用授权、会员计费**：能力目录只显示真实连接与运行状态，不折叠成假「已连接」。
- **桌面专属壳**（托盘、全局快捷键等）：本轮为同源网页在桌面浏览器的适配，未新增原生桌面壳。
- **品牌**：睡衣小熊候选图与新名称未进入实现；旧角色仅从新界面退出展示，模块与测试保留；衣橱仅结构预留。
- **深色外观、VoiceOver / 大字号全量走查、Windows 真机**：未验证。
- 窄屏 Dock 与输入坞的间距按 4px 重叠问题已修正（`composer-dock bottom:76px`），未做真机触摸测量。
