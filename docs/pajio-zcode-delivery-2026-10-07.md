# Pajio Web / Desktop 交付 · 2026-10-07

状态：ZCode 按 [Pajio 交接](pajio-zcode-handoff-2026-10-07.md) 完成的常规网页与原生桌面实施与验证记录。App 与后端只读；本文件不代表应用商店发布、签名公证或市场验证。

## 改动文件

### Web（`src/wearing/web/`）

| 文件 | 改动 |
| --- | --- |
| `pajio.css`（新增，替代已删除的 `today.css`） | 日/夜语义配色（数值对齐 `appearance.ts`：日 `#F6F7F9/#FFF/#202228/#3156C8`，夜 `#14161A/#1C1F25/#F0F2F5/#A3B7FF`），覆盖旧 CSS 变量使全部既有组件随之换肤；实色分层卡片、紧凑输入入口、今天/任务行、账户摘要与分组、外观/衣橱面板、搜索浮层、窄屏底部 Dock。**全部规则 `html:not(.mobile-host)` 门控**（新增测试逐规则断言）。 |
| `pajio.js`（新增） | 日夜三态（浅色/深色/跟随系统，`appearance:v1` 持久保存，随系统变化即时切换并同步 `theme-color`）；八套睡衣衣橱存储（`wardrobe:v2:web:{identity}` 显式保存、预览不落盘、v1 只读迁移、保存失败保留现妆）；品牌字标/单星/小熊 markup；App 宿主下整模块 return。 |
| `views.js`（重写） | 今天视图（真实活动分区：等你处理/最近返回/正在推进/已排队/历史 + 今日安排 + 读取时间 + 简报草稿入口，零状态如实呈现）；任务页「交给 Pajio 的事」分页区（`limit=20` 首页、`cursor` 加载更多、跨页去重纯函数 `appendActivityPage`、409 保留内容并转刷新、`已显示 X / Y 项`）；我的视图（实色账户摘要：字标+单星+身份+连接点+真实模型服务名；能力与连接/数据与身份/偏好分组）；外观与个性化二级页（日夜单选、陪伴形象、衣橱三级页：预览→「穿上X并显示小熊」显式保存）；记忆视图沿用。 |
| `index.html` | 标题/meta/主题引导内联脚本（宿主参数跳过）；字标轮廓 SVG、单星 favicon；聊天入口与进展入口挂小熊芯片 `[data-pajio-chip]`；欢迎页小熊（简洁模式显示单星）；`#compact-entry`；五入口 `data-life-view="today"` 成为真实视图；用户可见 Wearing→Pajio（CLI 命令与隐藏旧形象元素保留）。 |
| `life.js` | `today` 独立视图（不再别名 capture，补记表单保留在 capture）；渲染委托 `WearingViews.render`；紧凑入口（宿主隐藏、有草稿时显示「继续草稿 · 摘要」）；身份切换通知 `WearingViews.reset` 与 `WearingPajio.identityChanged`。 |
| `app.js` / `capture.js` / `activity.js` / `schedules.js` | 用户可见文案 Wearing→Pajio；标题 `身份名 · Pajio`；协议头、`wearing-` 存储键与代码标识不动。 |
| `bear/*.png`、`pajio-symbol.svg`、`pajio-wordmark.svg`（新增资产） | 来自 `clients/mobile/assets/bear/`（八套生产图）与 `design/brand/pajio/`。 |

### 桌面（`clients/desktop/`）

| 文件 | 改动 |
| --- | --- |
| `src-tauri/tauri.conf.json` | `productName: "Pajio"`；`identifier io.luckyloading.wearing.desktop` 保留。 |
| `src-tauri/src/main.rs` | 窗口标题「Pajio」「连接 Pajio」「Pajio · 原件」；菜单「打开 Pajio」/产品子菜单；托盘 tooltip「Pajio — 随时记一下」；panic 文案；移除强制 `Theme::Light`，窗口随系统日夜。 |
| `src-tauri/src/endpoint.rs` | 用户可见错误文案 Wearing→Pajio（测试夹具 `wearing.example` 保留）。 |
| `frontend/index.html` `connection.js` `connection.css` | 连接页 Pajio 品牌：轮廓字标、雾蓝条纹小熊、「连接 Pajio」；CSS 换日夜语义配色并 `prefers-color-scheme` 跟随系统。 |
| `src-tauri/icons/*` | `tauri icon` 从品牌包 `app-icon.png` 全量再生成；`tray.png` 换单星模板。 |
| `frontend/pajio-wordmark.svg`、`frontend/bear/mist-blue.png` | 品牌资产副本。 |
| `DESIGN.md`（根） | 追加「Pajio Web 与桌面」一节，指明主导文件与兼容边界。 |
| `README.md`（desktop） | 名称与说明更新为 Pajio。 |

测试：`tests/pajio-web-ui.test.cjs`（新增 9 项，替代 web-today-ui）。

## 实际命令与结果

- `node --test tests/*-ui.test.cjs`：**103 通过 / 0 失败**（94 基线 + 9 新增；含宿主门控逐规则、五入口顺序、分页合并去重纯函数、409 文案、无逐条核对/记成目标）。
- `uv run python -m pytest tests/test_api.py tests/test_dev_mobile.py tests/test_gateway.py tests/test_tenant_worker.py tests/test_life.py tests/test_activity.py`：**130 通过**，1 个既有失败（`test_profile_exposes_life_tools_preserving_model_config`，上午已确认源于并行修改的 `profile.py` mcp_servers 字段，非本轮引入，未代改）。
- `cargo check --manifest-path clients/desktop/src-tauri/Cargo.toml --locked`：通过。`cargo test`：**9 通过 / 0 失败**。
- `cd clients/desktop && CARGO_PROFILE_RELEASE_STRIP=none ./node_modules/.bin/tauri build`：**成功**。

### 桌面构建阻碍与绕过（具体、可复现）

`src-tauri/Cargo.toml` 的 `[profile.release] strip = true` 在本机（macOS 27 / rustc 1.96）使 release 产物中的 proc-macro dylib LINKEDIT 错位（dlopen 报 `mis-aligned LINKEDIT string pool`），所有派生宏 crates（serde_derive、thiserror_impl、phf_macros、darling_macro 等）编译失败；dev profile 不受影响。**绕过**：构建时 `CARGO_PROFILE_RELEASE_STRIP=none`。未改他人 Cargo.toml；建议后续维护者评估调整该 strip 设置或升级工具链。

### 原生构建产物（已实际编译）

`clients/desktop/src-tauri/target/release/bundle/macos/Pajio.app`（13.69 MiB，本地 ad-hoc 签名，未公证）。核验：`CFBundleName/CFBundleDisplayName = Pajio`，`CFBundleIdentifier = io.luckyloading.wearing.desktop`（保留），可执行文件名 `wearing-desktop`（保留），`icon.icns` 为品牌单星。二进制含「Pajio desktop could not start」等新文案。

**桌面真实运行**：按路径显式启动 `Pajio.app`，进程运行于新二进制路径；Computer Use 读到 App 名「Pajio」、窗口标题「Pajio」（1156×804，988 个可访问性元素 = 自动连接 127.0.0.1:8765 后网页已加载）。像素截图被本机屏幕录制权限（TCC）拒绝，`screencapture` 同因失败——这是本次唯一未取得的桌面视觉证据，窗口标题/元素树为程序化证据。验证后已退出该实例。

**运行环境说明**：本机 `~/.wearing/desktop/Wearing.app` 旧预览与 LaunchServices 注册发生冲突（按 bundle id 启动会拉起旧预览），验证期间旧预览进程被误停一次，**已重新启动恢复**（文件未动）；后续启动新包需按路径 `open .../bundle/macos/Pajio.app` 或先重新注册。另：`clients/mobile/src/Mobile.tsx` 在本轮进行中被主任务并行修改（18:57），本轮未触碰 `clients/mobile/**`。

## 浏览器实跑验证（本机 8765，Pajio/profile24，真实数据）

截图：`docs/qa-web-desktop-20261007/pajio-*.png`（夜间聊天/今天、日间聊天/我的/任务、外观日间、窄屏今天、宿主回归共 8 张 + 上一轮 Today 存档）。

- **日夜**：跟随系统默认（本机深色 → 夜间）；三态切换即生效并持久化（`appearance:v1`），刷新后保留；`theme-color` 同步；日夜画布/卡片/文字对比按语义色板。
- **五入口与今天**：导航顺序聊天/今天/任务/记忆/我的；今天视图真实分区（等你处理 1、最近返回 3、推进/排队 0 如实、历史 3、今日安排 0 日程/2 待办、读取时间戳）；简报入口仅准备草稿文本。
- **衣橱**：八套预览（预览不落盘）、「穿上奶油月牙并显示小熊」显式保存 → `wardrobe:v2:web:daily` 写入 `{version:2,outfit,companion}`，聊天入口/欢迎页小熊即时换装；刷新保留；另一身份为雾蓝默认且无键（隔离）；简洁标记面板可用。QA 后已清除写入的偏好、恢复 system。
- **任务分页**：任务页显示「已显示 9 / 9 项 · 读取于 HH:MM」与真实分组；接口链路实测 `limit=3` 首页 → cursor 下一页无重叠、篡改游标 422 拒绝；409 保留行为由后端 87 项分页测试与前端结构/纯函数测试覆盖（本地 9 条数据无法自然触发跨修订 409，未伪造任务）。
- **搜索/输入收敛**：页内搜索零请求；非聊天页紧凑入口「交代一件事/继续草稿」回到聊天续用同一草稿（capture 与宿主除外）。
- **窄屏**：390px 底部五入口 Dock（含小熊聊天入口），正文不挤压，输入坞上移无重叠。
- **App 宿主回归**（`?host=mobile&composer=native`）：`WearingPajio`/`WearingViews` 均未注册、body 透明、无渐变层、header/紧凑入口隐藏、受控 17px 字号、助手正文样式由宿主 CSS 掌控、进展横幅隐藏；`WearingHost.openReview` goals 面板与 draft 注入正常。

## 未完成与边界

- 桌面像素截图缺失（TCC 屏幕录制权限）；以窗口标题与可访问性树为证。
- Windows NSIS 包未在本机构建（无 Windows 环境）；`tauri.windows.conf.json` 保留。
- 跨修订 409 未在浏览器自然复现（数据量不足，不允许伪造任务），由后端测试 + 前端结构测试覆盖。
- 旧 `.wearing/desktop/Wearing.app` 预览与 LaunchServices 的 bundle id 冲突需用户择一清理；本轮未删除任何数据目录内容。
- 未做：外部 OAuth、会员计费、自动简报生成链路、公证签名、应用商店与商标事务。

## 复核收尾 · 2026-10-07（独立复核四项）

依据 [web-review-followups](evidence/pajio-20261007/web-review-followups.md)，全部修复并复验：

1. **长聊天导航与进展入口可达**：`pajio.css` 将网页顶栏改为 `position:sticky;top:0`（实色画布底、z-index 6），唯一进展入口 `#activity-return` 钉在 `calc(var(--pajio-header) + 8px)`（桌面 86px / 窄屏 104px 变量）；未新增第二块进展、未改宿主布局。实测 1280×720 自动滚底（scrollY 1434）：顶栏 top 0 高 87、五入口与搜索/设置在视口内、进展入口 top 94 在视口、输入坞在底；390×844（scrollY 1766）：顶栏 0、进展入口 112、底部 Dock 768 全部可达且无横向溢出。
2. **字标尺寸与填充**：通用 `svg{20×20;fill:none}` 规则会压垮属性尺寸——新增分级规则显式恢复：顶栏字标 72×31、账户卡 76×33、单星 18/22、欢迎星 44，全部 `fill:currentColor;stroke:none`。实测计算值 72×31、fill 日间 `rgb(32,34,40)`/夜间 `rgb(240,242,245)`、stroke none。
3. **交代式文案**：占位符「说一声，我来做…」、脚注与待机状态「说一声，我来做。/交代要做的事，有进展会回到这里。」、sr-only 标签「说一声，Pajio 来做」；历史消息未动。测试断言旧闲聊引导（想到哪儿/我在接着说/想做些什么）不再出现。
4. **桌面签名**：对 bundle 执行 `codesign --force --deep --sign -` 后 `codesign --verify --deep --strict` 通过（`valid on disk` + `satisfies its Designated Requirement`），`Signature=adhoc`、`Identifier=io.luckyloading.wearing.desktop`；签名后的包实际启动运行（App/窗口名 Pajio）后退出。注意：bundle 重建后需重新执行该签名命令（当前 Cargo.toml 的 release strip 设置仍需 `CARGO_PROFILE_RELEASE_STRIP=none` 构建绕过）。

新增回归：`tests/pajio-web-ui.test.cjs` 第 10 项「follow-ups」；全套 `node --test tests/*-ui.test.cjs` **104 通过 / 0 失败**。复验期间写入的日间偏好已恢复跟随系统；`tests/test_life.py` 按复核方修复后 19 项通过，本轮未触碰该测试与 profile 运行配置。新截图：`docs/qa-web-desktop-20261007/pajio-followups-long-chat-day.png`（390×844 长聊天日间：粘性顶栏 + 进展入口 + 底部 Dock 同屏）。

## 品牌资源同步 · 2026-10-07（P+熊图标与原创字标）

用户调整品牌资源后同步到 Web/Desktop（App 只读）：

1. **应用图标**：以 `design/brand/pajio/app-icon.png`（sha256 `9ea5a71b…`，与 `clients/mobile/assets/icon.png` 逐字节一致）为新 master，`tauri icon` 重新导出桌面全套（icon.icns/icon.ico/各尺寸 PNG/Windows Square 系列）；托盘保持单星模板（UI 单星不变）。favicon/launcher 改为 P+熊：网页 `<link rel=icon>` 指向 `/assets/pajio-icon.png`（品牌包 icon-32）。从 bundle icns 提取 128px 图标目检确认为「睡衣布料 P + 下方毛绒熊头」，非单星、非坐熊候选。
2. **原创字标**：`wordmark-custom-v2.svg`（5 条原创填充 path，viewBox `12 20 574 240`，比例 574/240）替换网页顶栏与「我的」账户卡内联 SVG、`pajio.js` `wordmarkMarkup`、桌面连接页字标（内联 currentColor，112×47）。CSS 尺寸按新比例：顶栏 72×30、账户卡 76×32（72px 宽按新母版可读）。黑白正式版（`wordmark-black/white.svg`，你方导出）确认存在于品牌目录；未采用 icon-studies 候选与旧素材。
3. **构建与签名**：重建 `Pajio.app`（16.29 MiB）→ `codesign --force --deep --sign -` → `codesign --verify --deep --strict` 通过（valid on disk + satisfies Designated Requirement）；`CFBundleName=Pajio`、`io.luckyloading.wearing.desktop` 与存储路径不变。构建仍需 `CARGO_PROFILE_RELEASE_STRIP=none`（见上节）。
4. **单实例验收（不停旧预览）**：旧预览（pid 2533）全程运行；按路径启动新 Pajio.app 后新进程经单实例转发立即退出，旧预览 pid 不变——同标识双包共存行为符合预期。
5. **复验**：实机计算值 72×30、5 path、viewBox 正确，日夜填充 `rgb(32,34,40)`/`rgb(240,242,245)`；favicon 指向新图标；测试新增第 11 项「brand assets」，全套 `node --test tests/*-ui.test.cjs` **105 通过 / 0 失败**。新截图：`pajio-wordmark-v2-day.png`（顶栏新字标特写）、bundle 图标提取件见本节描述。后端全组 131/131（[backend-profile-regression](evidence/pajio-20261007/backend-profile-regression.md)）与本轮改动无关，未触碰。

## 更正：P+熊图标被否决 · 2026-10-07

用户否决上一节的 P+熊应用图标，本节为最新状态，覆盖上一节的图标结论（该图标**未完成、不得标记为交付**）：

- **立即暂停**：图标替换与桌面图标重建全部停止；在新的定稿 master 送达前，不再从 `design/brand/pajio/app-icon*` 读取任何 P+熊候选执行 `tauri icon` 或构建。
- **已回退**：网页 favicon 恢复为单星 `/assets/pajio-symbol.svg`（实测指向正确）；本轮复制进生产目录的 `src/wearing/web/pajio-icon.png` 已删除。UI 内单星标记（starPath）本就未动。
- **桌面现状（待重做）**：`clients/desktop/src-tauri/icons/` 与现有 `Pajio.app` bundle 内 icns 仍是上一轮生成的被否决 P+熊版本（覆盖了此前的单星图标集；品牌目录中的旧 master 亦已被替换，本地无法回导出单星集）。该 bundle 视为**作废候选**，不得作为图标交付或分发；待用户提供新 master 后重新生成、重建、重签并复验。
- **保留有效**：custom-v2 原创五 path 字标同步（Web 顶栏 72×30 / 账户卡 76×32 / 桌面连接页 112×47、日夜填充）与此前已批准的四项修复（粘性导航与进展入口、字标尺寸填充、交代式文案、ad-hoc 签名流程）均不受否决影响，实测仍生效。
- **测试**：`pajio-web-ui.test.cjs` 品牌断言已改为「favicon 维持单星、禁止引用被否决图标文件」；全套 `node --test tests/*-ui.test.cjs` **105 通过 / 0 失败**。

## 真实截图收尾与实际改名运行 · 2026-10-07（本轮）

依用户真实截图问题与 App 最新源码（只读同步 `bear-registration.ts`、`wardrobe.ts`、`WardrobeStage.tsx`、`PersonalHub.tsx`、`PajamaBear.tsx`）：

1. **进展卡与导航小熊**：`pajio.js` 移植 App 的 `bearBounds`/`bearFrame` 实测 alpha 注册框（1254px 源图、portrait zoom 1.92 头肩裁切）。进展卡改为左侧 52px 圆形头肩熊紧邻两行文字（标题/摘要）+ 右侧箭头；顶导航聊天入口为 28px 头肩熊（不再把整熊压成 20px）。修复了 `activity.css` 的 `#activity-return>span{flex:1}` 把芯片拉宽到 397px 的问题（`flex:0 0 auto`）。实测截图：进展卡与窄屏均呈现可辨认熊头、左右留白正常。
2. **简洁标记移除**：外观页删除「陪伴形象」面板与 `setCompanion`；读取迁移把历史 symbol 存档按 bear 显示并保留 outfit（与 App `wardrobe.ts` 同语义），写回仍为 `{version:2,outfit,companion:'bear'}`；历史消息未动。
3. **八套衣橱**：模块加载即预载并 decode 八图（`bearReady` 门控换装）；衣橱舞台移植 WardrobeStage——八图常驻叠放，试衣帘（左右帘 + 三道折痕）闭合 180ms 提交、开启 300ms，快速连点只提交最新目标，`prefers-reduced-motion` 下直接切换、无帘；未给整熊图片加任何晃动动画（Hypit 真动作待用户交付）。实测：8 层 + 2 帘、连点 rose-dot→cocoa-moon 最终提交 cocoa-moon。
4. **实际改名运行**：旧预览进程确认路径为仓库数据目录 `/Users/archieliew/Documents/facet/.wearing/desktop/Wearing.app`（pid 2533）后仅退出该进程；其 WebUI 草稿随输入即时保存在该应用容器 localStorage，退出不清数据。启动新 `Pajio.app`（pid 15570）并**保持运行**（不再恢复旧 Wearing）。AX 实测 App 名/窗口标题均为 "Pajio"（1180×820，自动连接 8765 加载 Web）；菜单/托盘文案以二进制字符串（"Pajio"、"Pajio desktop could not start" 等 11 处）与源码为准——本机屏幕录制 TCC 仍拒绝像素截图。
5. **临时开发图标（非定稿）**：被否决的 P+熊图标未再使用。从旧预览 bundle 的 icns（石墨底 #202630 奶油单星，即首个 Pajio 图标）恢复 1024 母版，存为 `clients/desktop/dev-icon-TEMP-star-not-final.png`，仅用于本轮重建验证；正式图标待用户新 master 定稿后替换。`tauri icon` 重导出 → 重建（13.74 MiB）→ `codesign --force --deep --sign -` → `codesign --verify --deep --strict` 通过（valid on disk + satisfies Designated Requirement），`io.luckyloading.wearing.desktop` 与存储路径不变。
6. **验证与证据**：全套 UI 测试 **105/105**；截图新增 `pajio-bear-day-wide / pajio-bear-night-wide / pajio-bear-night-narrow / pajio-wardrobe-stage`（docs/qa-web-desktop-20261007/）。备注：IAB 内 `getComputedStyle` 对该 span 报 0×0/block 的测量怪象与渲染无关，实际布局以截图与 `#activity-return` 52px 芯片实测为准。

## Hypit 真实动作接入 · 2026-10-07（本轮）

用户审定的两段真实动作（`clients/mobile/assets/bear-motion/`，只读来源）已接入 Web/Desktop，语义对齐只读参考 `LivingPajamaBear.tsx`、`WardrobeFilm.tsx`、`WardrobeStage.tsx`：

1. **顶部进展熊 idle（仅雾蓝）**：素材复制到 `src/wearing/web/motion/`（idle 284KiB/5.04s、poster、双向换装各 ~2.8s）。`pajio.js` `mountLivingBear`：muted、playsinline、disablepictureinpicture、无 controls、loop 关；播一次后停在末帧安静停留，每 23 秒 `greet()` 一次；`document.hidden`/IntersectionObserver 离屏/`prefers-reduced-motion` 任一命中即暂停并回落 poster；视频 error 同样回落。其它七套睡衣与顶导航聊天入口保持各自静图（不穿错蓝色）。
2. **衣橱蓝↔奶油真实转身**：`views.js` `mountWardrobeStage` 新增 `filmPair` 分支——`mist-blue↔cream-moon` 双向播放对应 `blue-to-cream.mp4` / `cream-to-blue.mp4`（muted、内联、无控件），`ended` 后提交正确目标静图并清除影片层；`error` 立即提交目标静图；页面隐藏暂停/恢复继续；**其它组合仍走短试衣帘**。快速连点：新目标打断影片 → `clearFilm` 取消 → 回退试衣帘并只提交最新目标（实测 奶油→rose-dot 打断后最终 rose-dot）；离开页面由容器销毁兜底；全程**不自动保存穿搭**（实测 localStorage 全程无写入，仍需「穿上X并显示小熊」显式保存）。
3. **实捞验证**（127.0.0.1:8765，真实浏览器）：idle 视频 muted=✓、controls=无、playsinline=✓、duration 5.04s，手动驱动播放→seek 末尾 `ended=true, paused=true` 停留 5.04 末帧；换装影片双向实测播放中 `playing=true` 且结束后 `shown=cream-moon` / `mist-blue` 正确提交；连点回退正确。注：IAB 嵌入浏览器拦截了初始静音自动播放（回落 poster），手动播放生命周期完整——常规 Chrome/Safari 静音自动播放不受此限。减少动态路径为结构测试覆盖（`reducedMotion` 分支 + CSS `@media` 停用试衣帘）。
4. **桌面**：运行的 `Pajio.app`（pid 15570）窗口保持可见，已通过 Cmd+R 刷新其前端（窗口/App 名仍 "Pajio"）；图标维持临时开发单星（非定稿）。
5. **测试与证据**：`pajio-web-ui.test.cjs` 新增第 12 项（素材在位、静音内联无控件、23s、隐藏/离屏/减少动态、仅雾蓝、影片仅蓝奶油对、失败提交、连点取消、无自动保存）；全套 **106/106**。新截图 `pajio-wardrobe-film.png`（换装影片播放帧）。桌面连接页无需动效副本（主窗口加载服务端 Web 资源）。

## 桌面复核问题修正（CSP 真因）· 2026-10-07（本轮）

独立复核（[desktop-regression](evidence/pajio-20261007/bear-motion/desktop-regression.png)）确认：顶导航熊不显示、进展卡左半空白且文本居中、进展熊消失。**此前报告的「IAB 测量怪象」判断错误——span 0×0 是真实缺陷**，根因为服务端 CSP `style-src 'self'`（app.py:283，未改动）拦截标记中的 `style` 属性：bearMarkup / mountLivingBear / 衣橱 swatch / 衣橱入口按钮的内联样式全部失效。未放宽 CSP、未改后端。

**修复方式（CSP 允许的 CSSOM 路径）**：
- `bearMarkup` 不再输出任何 `style` 属性，只携带 `data-bear-outfit/size/portrait`；由 `hydrateBear` 在节点入文档后经 `el.style.*` 赋值容器尺寸与每套睡衣的注册框（MutationObserver 兜底覆盖所有注入点）。
- `mountLivingBear` 的 video/poster 取景框同样改为 CSSOM 赋值。
- 衣橱 swatch 颜色改 `data-swatch` + CSSOM；入口按钮样式归入 `.me-wardrobe-entry` 类。
- 资源版本 pajio.js v4 / views.js v9 / pajio.css v7（服务端对页面本就 `Cache-Control: no-store`，版本号双保险，未清任何用户数据）。

**同步 App 更新（只读）**：WardrobeFilm 的 220ms 末帧淡出——影片结束先淡出视频层（其下是首帧后即衬底的目标静图），淡出完成才提交；减少动态效果下 transition 关闭。修复了首轮实现中 finishing 标志阻止提交的真实缺陷。

**实捞复验（同一 CSP 下）**：导航熊 computed 26×26、进展芯片 52×52、living video/poster 取景 98.4px、卡片 880×92——此前 0×0 的位置现在全部有宽高/定位；衣橱入口 76、舞台 8×218、轨道 100、swatch 着色；蓝→奶油与回程影片播放→淡出（中段 opacity 0.25 实测）→提交正确静图；连点打断提交 rose-dot、无自动保存。截图 `pajio-csp-fixed-chat.png`、`pajio-csp-fixed-wardrobe.png`。测试新增 CSP 合规项（模板零内联样式、CSSOM 注水、观察器在位），全套 **107/107**。

**报告更正**：上一节「用户审定的两段真实动作」表述不准确，应为「本轮生成并审看的动作样片」；「常规 Chrome/Safari 静音自动播放不受此限」未实测，不作为保证——IAB 内自动播放被拦时回落 poster 是已验证行为，其余浏览器自动播放策略未验证。桌面 `Pajio.app`（pid 15570）保持运行，已 Cmd+R 刷新至 CSP 修复版前端。**待用户 CUA 复核桌面真实渲染。**

## 图标 C 定稿替换 · 2026-10-07（本轮）

用户选定图标 C（被窝里的睡衣小熊），`icon-selection.json` 已 selected、`icon-manifest.json` 含 SHA（`app-icon.png` sha256 前缀 `4afacec34b2dfaadfebf`，与磁盘实测一致；1024×1024 无透明）。仅 Web/Desktop：

- **替换**：`tauri icon` 以定稿 master 重导出桌面全套（icns/ico/各尺寸/Windows Square）；网页 favicon 换为品牌包 icon-32（`/assets/pajio-icon.png?v=2`）；临时开发图标 `dev-icon-TEMP-star-not-final.png` 已删除。字标 `wordmark-custom-v2.svg` 未动。
- **构建与签名**：重建 `Pajio.app`（16.74 MiB）→ ad-hoc 重签 → `codesign --verify --deep --strict` 通过（valid on disk + satisfies Designated Requirement）；`CFBundleName=Pajio`、`io.luckyloading.wearing.desktop` 保留。构建仍需 `CARGO_PROFILE_RELEASE_STRIP=none`。
- **进程切换**：旧 Pajio 预览（pid 15570）确认路径后仅退出该进程（其 WebUI 草稿随输入 180ms 防抖即时写入应用容器 localStorage，新实例同 bundle 复用同一存储，草稿不丢）；新包已启动并**保持运行**（pid 22555，App/窗口名 "Pajio"，1180×820，自动连接 8765）。
- **图标提取目检**：从新 bundle icns 提取 128px 成员确认是「被窝里的睡衣小熊」（非单星、非 P+熊）。
- **CSP 显示复核（实际截图，非结构测试）**：`pajio-icon-c-chat.png` 实拍——顶导航 26px 圆熊头可见、进展卡 52px 熊头紧邻两行文字 + 箭头且左侧无空白、字标正常、favicon 指向 `pajio-icon.png?v=2`；computed 复测 navBear=26 / progressBear=52 / video 在位。
- **测试**：品牌断言更新为「favicon 使用定稿 C 图标」，全套 **107/107**。

## WKWebView 进展熊空圈修正 · 2026-10-07（本轮）

Root CUA 实拍（pid 22555）确认：名称、导航熊、卡片布局正常，但 52px 进展位只剩空圆。两处真实缺陷：

1. **取景错位（像素问题）**：视频/海报素材按 App 视频构图制作，我却套用了静图 1254px 全身注册框（bearFrame portrait）裁切，熊被裁出可见圆。已改为 App `LivingPajamaBear` 的固定视频取景 `size*1.92 / left -size*.46 / top -size*.04`（视频与海报同框）。
2. **海报回退不可靠**：旧实现用 `poster.hidden = firstFrame/!firstFrame` 切换——WKWebView 拒绝自动播放或暂停路径下会同时露出空白。已改为 **poster 常驻底层**（永不隐藏）；视频默认透明，仅在真实渲染出画面后（`requestVideoFrameCallback` + `playing`/`timeupdate` 双保险）淡入 `is-live`；`pause`/`ended`/`error`/`visibilitychange` 隐藏/IO 离屏/减少动态任一发生即退出 `is-live`、暂停并露回海报——无焦点、自动播放被拒、暂停、首载四种状态圆里都有熊。`preload` 升为 auto 以便 WKWebView 预备首帧；注水器跳过 living span 避免覆盖视频取景。

**验证**：IAB 实测首载海报 loaded+可见（100px @ -24 偏移）、视频 opacity 0；手动播放后 `is-live` + opacity 1；暂停回落 0 露出海报。截图 `pajio-living-poster-base.png`。测试更新（living-video 标记、poster 常驻无 hidden、真帧显现、固定取景常量、preload auto），**107/107**。资源 pajio.js v5 / css v8。桌面按指示仅重启 Pajio 预览进程（22555→**24969**，运行中），服务未动；桌面 WKWebView 内的真实像素以 Root 下一次 CUA 复核为准。

## 核心能力按钮闭环（第一轮）· 2026-10-07

独立审计产出 [web-desktop-button-matrix](evidence/pajio-core-20261007/web-desktop-button-matrix.md)（逐按钮/处理器/真实接口/测试/状态）。发现并修复三个真实断链：**目标与定时面板此前在 Web 无任何主入口**（其按钮全在隐藏的 review-panel 内）、今天页无显式刷新、补记录在 Web 近乎不可达。三项均接真实处理器与接口（loadKeeps→/api/goals+/api/schedules、清缓存重读 /api/activity+/api/life、quickCapture 表单），新增副作用测试 `tests/web-core-closure.test.cjs`（4 项，断言 openPanel/loadKeeps/render/quickCapture 真实调用与失败反馈），全套 **111/111**。浏览器实测：刷新 apiCallsDelta=1、补记聚焦表单、面板打开且 4 条真实定时渲染、目标诚实空态；证据图 `pajio-core-tasks-entry.png`、`pajio-core-keeps-panel.png`。桌面已重启至同一前端（pid 28988），WKWebView 像素待 Root CUA 复核。

## 核心能力按钮闭环（第二轮 · App 合同对齐）· 2026-10-07

对照 App 已落地合同（RecordDetail/record-editor、TaskManagementPanel/ongoing-management、PersonalHub）只读核查：Web 已有 内容修改、日程时间编辑、草稿恢复、archive/restore、最近删除、capture retry、目标/定时全套控制与历史直达。**补齐唯一缺口：409 双选择**——并排最新版 +「保留我的输入」（仅换 revision）/「采用最新内容」（弃草稿载入），最新已删除诚实收起；顺带修复 dataset→属性命名导致的按钮选择器失配。新增副作用测试 3 项（web-core-closure 共 7 项），全套 **114/114**。真实 409 浏览器实测（先开编辑器→并发 PATCH→旧表单保存）全链路通过：错误→并排面板→保留我的输入→重存成功（服务端 rev3 我的标题生效）；证据图 `pajio-core-409-choice.png`。验证笔记已归档至最近移除。矩阵文档已更新第二轮对照表；App 原生的记忆内文件搜索/分享在 Web 如实记为未移植。桌面已重启（pid 31063），WKWebView 验证由 Root 补。

## 文件导入与目标幂等（外测推进第一列）· 2026-10-07

Web 实装两列真实能力（App 只读对齐）：**文件面板**——导入（`POST /api/workspace/import?name=&request_key=` raw bytes ≤20MB、身份+Token、失败重试沿用同一 key、回执核对 request_key/sha256/path/size）、文件名搜索（命中 X/Y 计数、200 截断如实）、每行「打开/下载/交给 Pajio」（草稿带真实路径不自动发送）、`capability` 缺失的兼容；**目标创建幂等**——表单 spec 指纹失败重试同 `request_key`（服务端重放回原目标，UI 反馈「未重复建」），成功重置。新增 `tests/web-import-goal.test.cjs` 5 项副作用测试（raw 字节、同 key 重试、回执拒绝、key 稳定/字符集/重置、body 携带），全套 **119/119**。

QA(8891) 实测：搜索「测试」命中 2/4、打开 200、交给 Pajio 草稿含路径。**两处 QA 脚本滞后已报告 Root**：① `qa-server.py` 未挂 `POST /api/workspace/import`（409 未启用）→ 导入端到端暂只能在真实后端单测层验证；② QA `NewGoal` 模型 `extra='forbid'` 无 `request_key` → 幂等创建在 QA 422（真实 `goals.py` 已支持，`test_goal_delegation` 覆盖）。补齐后我可立即完成两项端到端实机验收。QA 导入失败显示服务真实 detail、未假装成功；8765 本轮零写入（历史验证笔记保持归档可恢复）。矩阵已更新第三轮对照与阻碍节。

## 简报/技能/消息/记忆编辑接入（外测第二列）· 2026-10-07

QA 端到端补全：**导入**（201/回执核对/同 key 重放同路径/异内容 409/列表可见）与**目标幂等创建**（201/同 id 重放/异 spec 409；修复 `source_task_id:null` 触发 QA `extra=forbid`）全部通过。新接入（Web）：

- **持久简报**（`briefings.js`+`#brief-panel`，对齐 briefings-contract）：版本化列表八态映射、`request_key` 发出前持久化/未知结果同 key 取回/回执五项核对、前台 5 秒轮询后台停、成果与任务直达、来源快照；今天页不再预填聊天草稿。QA 实拍：面板打开、第 1 版「已排队」、创建进入「正在整理…」、来源快照显示（截图 `pajio-brief-panel.png`）。
- **技能**（我的→技能）：list/detail/启停/安装接真实 `/api/skills*`（revision 随请求）；**聊天工具**（设置）：`/api/messaging*` 配置验证/启停/断开（二次确认），**凭据仅表单内存、提交即清空、零持久化**；QA 未挂载两者均如实显示服务 409，不假装目录。
- **记忆直接编辑**：GET 暴露 `revision` 才启用编辑/删除/添加（App MemoryEditor 同款门控），PATCH 精确 `{target,action,revision,index,content}`，409 保留输入；QA 未暴露 revision 自动回退纠正草稿。
- 修复：views.js 新渲染函数误置于 `renderMe` 作用域导致整模块加载失败（浏览器暴露；已记录切片测试盲区）。测试增至 **122/122**（新增简报 journal/技能与消息真实路由与零凭据存储/记忆精确体与门控）。待 Root 挂载 QA 的 skills/messaging/memory(PATCH+revision) 后补三项实机验收。

## 飞书个人账号接入 + 设备面板对齐（外测第三列）· 2026-10-08

**飞书个人账号**（`cloud-apps.js` + 设置面板新段，与聊天机器人配置完全分开，对齐 `cloud_apps_api.py`/App `cloud-apps-model`）：配置（App ID `cli_` 门 + Secret + 文档/日历范围，**凭据仅表单内存、finally 清空、模块零持久化 API**）→ 显式「连接飞书（官方授权）」→ authorizing 态显示用户码/官方链接（仅 feishu.cn，同 App 校验门）/剩余时间并按服务 interval 自动轮询 → connected 态能力授权矩阵 + 检查 + 二次确认解除（含撤销提示）+ 云文档文件夹钻取/文档分页全文/日历/未来 7 天事件。QA 未挂 `/api/cloud-apps/*` → 面板如实显示服务 409 与重试按钮（截图 `pajio-cloud-honest-409.png`；另注：QA 身份非 daily 时 showSettings 走身份面板分支，属既有逻辑）。

**设备面板对齐核查**：Web 已覆盖 `device-management.ts` 全套真实动作（offer already_paired 禁选、pair request_id、permissions revision、control expected_generation、input-approvals、reviews），无新增缺口。

**记忆字段更正确认**：Web PATCH `/api/memory` 用 `target/action/revision/index/content`，与当前代码一致；新增断言确保无 `base_revision`/旧 entry 字段残留。测试增至 **124/124**（新增 cloud 行为测试 + 记忆字段防回归）。待 Root 挂 QA 的 cloud-apps/devices/skills/messaging/memory(PATCH+revision) 后补五组实机验收。

## 设置身份门修复 + 待核对决定 + 用量页 · 2026-10-08

- **修复实质缺口**：`showSettings` 不再把非 daily 身份重定向到身份面板——所有身份都可打开设置（skills/memory/cloud-apps/messaging/usage/decisions 全部可达）；身份管理保持独立入口。QA 实测 qa 身份直接打开设置面板（截图 `pajio-qa-identity-settings.png`）。
- **待核对的决定**（`decisions.js`，对齐 `confirmation_api.py`/App `pending-decisions.ts`）：列表 + 仅 `can_resume && needs_recheck` 的「重新核对并继续」；request_key 按 身份+卡片+revision 持久保存、同次重试不生成新键、成功清除；回执严格校验（`authorized:false`、task、五种 delivery），完成后刷新并回对话定位。QA 路由已挂（200，空态如实）。
- **用量页**：GET `/api/usage`，trial/not_enabled 如实、金额未知明示「未接入计费，不显示为 0 元」（无任何假 0 元）、剩余/并发/音频秒数与本身份累计。QA 未挂→如实 409。
- QA 扩展复验：cloud-apps 状态机渲染正常（未发起真实授权）、messaging 渲染正常。测试增至 **127/127**。

## QA 点击验收（合成凭据全 Mock）+ 决定键修正 + 记忆 v2 · 2026-10-08

QA 8891（PID 60648）使用清单合成凭据完成 UI 点击验收（未填真实凭据/未访问真实授权链接）：**飞书**授权→连接→文件→文档全文；**Telegram** 配置（token 提交即清空）→启用→停用→断开；**技能**安装与启停（真实文件复制）；**记忆 v2** 添加/离页草稿/409 输入保留/清空二次确认/set_enabled 门控（settings_revision CAS 随请求）；**待核对决定**合成卡片恢复成功且 request_key 成功后保留。证据图 `pajio-qa-feishu-flow.png`、`pajio-qa-identity-settings.png`。修正：决定键成功不清除（同键永久，防迟到重放双恢复）+ `execution_unknown` 状态（禁恢复）。全套测试 **127/127**。

## 数据导出 + 服务端文件分页 + 用量验收 + 决定键持久化 · 2026-10-08

QA 8891（PID 66072）真实路由 UI 点击验收：**带走我的数据**（新 `data-exports.js`——列表找回、localStorage 幂等键创建真实 ZIP：GET 200/zip/1.8MB、unzip 内容核对、同键二次创建无第三份、SHA256/有效期/遗漏明细、凭据零存储）；**文件面板迁移服务端分页搜索**（`/api/workspace/page` 服务端文件名搜索 + opaque cursor 续页 + scan_id 变化重读 + complete 才称完整，移除旧 200 项客户端 filter）；**用量页验收**（真实 not_enabled + 金额未知不显示 0 元）；**决定 request_key 迁 localStorage**（跨标签页同键、成功保留、纯 UUID）。证据图 `pajio-qa-export-files.png`。全套测试 **130/130**。

## P0 账号隔离 + 跨对象搜索 · 2026-10-08

**P0 修复**：`scoped-store.js` 统一个人持久存储——bootstrap 拿到可信 `storage_scope` 后才初始化（此前仅内存占位，bootstrap 失败零 localStorage 触碰）；cloud 按 `pajio:{scope}:` 前缀隔离（A/B 同 origin 同 identity 互不可见、重登同键稳定），无/伪 scope 仅内存且不读旧缓存不迁移；账号变化清内存+作废在途请求；local 沿用旧键兼容。改道范围：草稿、发送流水、语音回执、原生草稿流水、衣橱、简报 journal、决定/导出 request_key、记忆离页草稿。行为测试覆盖 A/B、重登、bootstrap 失败三场景。

**跨对象搜索**：搜索浮层「跨对象」分区接 `GET /api/search`（防抖/迟到丢弃/续页）与 `/api/search/messages/{id}` 消息深链，task/record/message typed 深链全部落位；QA 实测命中与记录深链通过。全套 **132/132**。

## scoped-store 复核修正 + 诊断面板 · 2026-10-08

按 Root 复核修正两点：memory 适配器完整 Storage 接口（实测无 scope 输入保留到本次页面、零 localStorage）；`bind` 仅 local 沿用旧键，其余一切形态（含 unknown/undefined/失败）一律内存。新增诊断面板（`diagnostics.js`：只读生成/五态摘要/JSON 预览/下载/重试，无假提交）接真实 `GET /api/diagnostics`，QA 实测通过。搜索真实检索复验通过。**132/132**。

## 复核修正（bind 原始值/诊断投影）+ 安静时段 · 2026-10-10

1. `bindScopedStorage` 改传**原始** deployment/scope（删除 `||"local"` 兜底），fail-closed 收敛在 store；新增真实 bootstrap→bind 集成测试（六形态）。
2. 诊断重写为**白名单投影**（移植 App `diagnosticsSnapshot`：枚举/上限/格式验证、永远新建对象），导出不含服务端原样 JSON；伪造字段测试证明 token/路径/错误文本/日志通道不进投影；切身份 AbortController 取消在途、Blob URL revoke。QA 实测投影渲染。
3. 安静时段面板（GET/POST preferences、revision CAS、相等拒绝、不宣称推送效果）；QA 未挂路由如实 409。`offline-record-edits.md` 不存在（已核对目录），现有记录编辑的 request_key 幂等与 409 恢复此前已实装。**135/135**。

## 草稿误报修复 + 安静时段文案 + 编辑幂等 · 2026-10-10

**真实缺陷定位修复**：QA 页持续显示「草稿暂时只能留在当前页面」的根因是 WearingStore 缺 Storage 接口（drafts 模块调 getItem 抛错被吞）。补齐接口后 QA 三步实证：输入无误报、切页回聊天草稿恢复、**整页重载草稿恢复**；cloud 无 scope 模拟下内存可用且零 localStorage 泄漏（fail-closed 不受影响）。安静时段文案对齐 awaiting_registration 语义（重新登录恢复/仍有效才发/不保证手机已显示）。记录编辑提交接 request_key 固定 attempt（同 revision+patch 同键重放，对齐 offline-record-edits 服务端合同；该合同明确本机离线队列属 App）。**136/136**。

## 安静时段 QA 实机收口 · 2026-10-10

QA 8891（PID 19872，46 表数据保留）对 Web 安静时段做完整真实 UI 验收（自有安装 ID，无真实推送）：默认关闭 22:00–08:00 → 开启 23:30–07:00 保存（反馈含重新登录/仍有效语义）→ **整页重载持久** → 服务端并发后旧 revision 提交 **409 且输入保留** → 重读最新 revision → 关闭成功。截图 `pajio-qa-quiet-hours.png`。全套 **136/136**。至此 quiet-hours 在 Web 端完整闭环。

## 技能移除 + 结果选项 + 品牌残留 · 2026-10-10

QA 8891（PID 23615）真实 UI 验收：**技能移除**完整流程（预览含操作编号→确认→QA 活动任务 **423 如实**，零文件移除、技能保留，成功路径由严格回执校验 + 后端测试覆盖）；**结果选项**原生区（两选项→instruction 预览→二次确认→提交成功→「已排队，尚未执行」诚实回显；request_key 经 WearingStore 按身份+结果+选择持久；iframe 无桥）；**可见 Wearing 残留清理**（face/海报/叫一下 → Pajio，内部兼容名保留）。新增行为测试 2 项，全套 **138/138**。

## 账户注销接入（可独立部分）· 2026-10-10

新 `account-deletion.js` + 设置「注销账户」段，对齐两份冻结合同与 App 面板（只读）：范围展示（严格 plan 校验/三类 action 文案/blockers）→ 独立重新验证（Web CSRF 空 body → authorize_url）→ **凭证先存**（request_key/plan_revision/receipt_token 经 WearingStore 按账户持久）→ 恰四字段固定 key 提交 → 非 202/失响应用保存凭证查询同一申请 → completed 仅 verified+data_erased=true；已登出可凭回执只读查询；受理后清理**仅当前身份标记**的业务缓存（其他账户与凭证保留）。合成行为测试覆盖 plan/status 校验、凭证往返、缓存围栏；QA 网关未挂路由，真实 UI 如实降级（未假联调、未请求真实注销）。**139/139**。

## 账户注销复核修正 · 2026-10-10

按 Root 六点复核逐项修正：围栏改为 origin+user_id（精确归属段匹配，同 identity 不同账户不串）；按钮真实 id + 真实事件绑定；POST 携带 x-wearing-csrf（对照 gateway.py）；plan 必需字段缺失整份拒绝；status 白名单对齐 operator 契约；submit 异常必查同一申请、not_submitted 恢复业务；业务冻结门接入主轮询/发送/life 轮询 + 工作门 + 重载恢复。5 项行为测试（真实事件/CSRF/掉响应/围栏/门），全套 **143/143**。

## 六项注销复审修复 + 三项新合同 · 2026-10-10

按 zcode-review-next.md 修复：CSRF 改 GET /auth/session（真实 gateway 协议）；缓存清理按 storage_scope 前缀精确匹配（local 不清）；saveFence 持久失败阻断提交；生产冻结门（generation/rememberComposer 拦截/启动前恢复/设置入口独立）；not_submitted 真实 plan 刷新；plan/status 契约校准。接入三项新合同并 QA 实拍：简报偏好（表单+幂等+来源状态）、工作区文本编辑（读取/保存/409 双版对比/恢复版本/423 如实）、健康历史与支持包（分页+导出严格回执+下载不声称已发）。**147/147**。

## 清单/日历视图/任务操作 · 2026-10-10

三项新合同接入并 QA 点击验收：**我的清单**（真实三路由 + board revision CAS + request_key 持久幂等 + 双分页 + 完成/归档复用既有 API，QA 两清单与事项打开验证）；**日历月/周/议程**（FullCalendar 月 + 原生周/议程列表、跨日去重与标签、30 天窗口、批 100 渲染，QA 三视图切换验证）；**任务停止/撤回**（真实队列回执门控 + 两击确认 + CSP 无内联处理器，QA 验证 active 任务显示停止、无排队不显示撤回）。全套 **150/150**。

## 第十八轮收口与下一会话交接 · 2026-10-10

第十八轮三项（清单/日历视图/任务停止撤回）已交付，但按用户指名**尚未完成**：calendar-series 完整 UI（重复日程/单次例外）、offline-record-lifecycle 归档恢复的 request_key 幂等、task-detail 同快照精确已读——QA 路由未挂载，本轮先完成交接。新增冻结合同 briefing-automation / record-reminders 同样待 QA 加载后接入。**完整交接、未做清单、验证命令已写入 [zcode-next-session.md](evidence/pajio-core-20261007/zcode-next-session.md)**——包含 SeriesCommand 精确闭集、AutomationSave/ReminderSave 字段、WearingStore/二次确认/409/幂等四套站内模式、QA 探活模板与桌面重启命令。技能移除与文件编辑的成功链验收等 root 停掉剩余合成任务后补做。当前 150/150 全绿。

## 第十九轮 · 五项合同完整交付 + 两项成功链补验 · 2026-10-08

接 zcode-next-session.md 交接清单，五项全部完成并 QA 8891 真实事件+浏览器 UI 验证：

1. **重复日程完整 UI**（新 `series.js`，~490 行）：单入口九动作闭集、系列列表/编辑器/实例面板（仅这一次 vs 整个系列）、例外保留与恢复原规则、移除/恢复、月视图紫色事件与周/议程区段合并展示（只读投影）。request_key 单槽账本（WearingStore 先持久后发、未知沿用、已知错误换新 key、开新操作前尽力结算旧账）；409 双选择与合同文案一致。API 预验证含：CAS 409、同 create key 重放返回原回执、update 遗漏例外拒绝。
2. **归档/恢复幂等**：PATCH 带 request_key + 两击确认范围文案；同 key 重放返回旧回执且不重复改变当前记录（服务端实证）。
3. **同快照精确已读**：openTask 在结果渲染后按 GET /api/tasks/{id} 的 activity_receipt 确认精确版本；cancelled 队列保持未读；服务端核对已读状态真实落库。
4. **每天自动简报**：偏好区面板完整字段 + 偏好版本绑定/提示 + 回执列表 + 幂等；开启需偏好版本匹配、关闭不要求（API 实证）。
5. **具体时间提醒**（新 `reminders.js`）：双 CAS + 持久幂等 + 如实回执文案；挂 life 编辑器与系列实例（occurrence target）；改期后服务端联动调整锚点在 UI 实证。

**补验成功链**：文件编辑真实保存（内容服务端持久化）；qa-summary 技能移除（预览→确认→列表变安装态）。

**视觉抽查发现并修复一个真 bug**：同视图重渲染时旧 FullCalendar 实例挂在被替换容器上导致月历空白（数据轮询更新即触发）——重建前销毁旧实例（life.js v20）。

全套 **161/161**（`node --test tests/*-ui.test.cjs tests/web-core-closure.test.cjs tests/web-import-goal.test.cjs`）。截图六张存 `docs/qa-web-desktop-20261007/round19-*.png`。资产版本：series/reminders v2、life v20、activity v4、briefings v4。桌面已重启加载新前端。

**遗留风险（如实）**：① 系列月视图事件对比度为既有主题样式（dayMaxEvents 折叠变暗），未改主题；② 系列 request_key 为单槽账本，极端并发下旧回执可能取不回（代码内 ponytail 注释，升级路径按键分槽）；③ 自动简报回执列表需服务端 tick 产生数据，QA 当前为空属预期；④ 提醒真机送达仍需外测（合同声明 Web 不声称手机已展示，已如实文案）。

## 第二十轮 · 两项新合同 Web 实现 + 系列多槽账本 · 2026-10-08

1. **链接收藏**（新 `bookmarks.js`）：完整面板（双列表/字面搜索/分页 409 重读/新建/编辑/归档恢复/显式打开 noopener）；URL 校验纯函数与 App 同规则逐条对齐（24 个用例）；全部写路径带 request_key 持久幂等，409 读最新保留输入，未知结果同 attempt key 重放（harness 实证 rev6 同 key 两次）。url 清空保存 → null 移除收藏属性仍保留笔记。
2. **对话引用范围**（新 `conversation-sources.js`，UI 先行——root 独立复核仍在修目标续轮上下文）：范围预览+两击确认+取消不发请求；闭集四字段+页面快照 revision+稳定 request_key 先持久；回执严格校验；未知结果开面板自动同请求取回；4xx 须重读重选；「排除后不提供恢复引用」「历史仍保留」如实文案。入口：记忆页区段。
3. **系列 request_key 多槽账本**（修已知可靠性问题，不再留注释）：按 action:series|new:occurrence 分槽互不覆盖；同意图沿用原编号；三入口各自恢复；旧单槽键一次性迁移。
4. 交接文档日期统一 2026-10-08，历史未完列表标注旧状态。

全套 **170/170**；冒烟：我的/记忆页入口渲染、三模块加载无错。**QA 点击验收已补做**（2026-10-08，root 重启 PID81367 后）：收藏全流程实证（列表/搜索/伪协议拒绝/新建默认标题=主机名/409 读最新保留输入/归档恢复 rev3→4/url=null 移除收藏属性仍保留 note/打开网页 noopener 实开新标签）；来源范围**只读**验收（两条合成来源、预览、取消零 POST）。修复并复验：成功提示被 refresh 开头清空的三处顺序 bug（bookmarks.js v3）。「来源范围2」的排除 POST 已于同日 root 授权后补验完成（两击→POST→revision 1→2→历史仍可查看双重核验；「来源范围1」由 App 完成）。桌面已重启。

## 第二十一轮 · 恢复请求用户展示与 saved 撤回（2026-10-08）

合同 `recovery-presentation-contract.md`（冻结）Web 侧接入，改动收敛在 `app.js`（v48）：

1. **恢复消息识别与文案**：`kind/message_kind=confirmation_recovery` 双通道；saved 草稿显示「重新核对」（代替「继续这句话」）+「不会直接执行原提案」说明 + `blocked_reason` 展示。
2. **能力字段门控**（只信任务回执）：`can_retry===false` 隐藏开始；saved 撤回仅 `can_cancel===true`（新操作，旧服务缺字段不开放）；queued 撤回仅 `can_cancel===false` 显式关闭（旧 queued 兼容）。
3. **显式重试**：start 两击确认；提交前 GET `/api/tasks/{id}` 重读 `can_retry`；POST start 用原任务；响应丢失仅提示重读不自动重试。
4. **固定失败文案**：`failure_code=execution_limit` 固定说明（与后端同文）；未知类型通用失败；全模块不再透传 `turn.error`。
5. **saved 撤回**：两击确认 → 同一 `cancel-message` 端点。

QA 8891 真实材料验收（fetch 间谍）：恢复草稿渲染（含真实 blocked_reason）/两击首击零任务请求/4 秒复位/`GET 回执→POST start` 序列/服务端安全门拒绝经 notice 如实呈现（无伪造成功、无自动重试、保持 draft）/saved 撤回闭环（stopped+按钮移除+「这条已撤回」+账本生成新 needs_recheck 子卡，root 的 App 材料完好）。截图 `round21-recovery-draft.png`。全套测试 **176/176**。

**遗留收口（2026-10-08 root 重启后）**：①成功 start 转 running 已由 App 用旧任务 705195… 同任务 retry→synthetic running→stop 验证（root 报告），Web 侧同端点同语义；②「来源范围2」排除验收已完成（root 授权）：前置核验无活动任务、本人合成恢复任务已停（未为验 saved 改任何已入场状态）；两击确认首击零 POST；POST exclude 闭集体；回执 revision 1→2、excluded、history_retained；**历史消息仍可查看（API+聊天 UI 双重核验）**；journal 确认后才写、成功即清（截图 round21-sources-excluded.png）；③execution_limit 固定文案已于同日补验完成：root 在隔离 QA 加入合成任务 7fcb4e28…（failed+execution_limit、error 不透传），Web 渲染固定说明+保留结果（截图 `round21-execution-limit.png`）；未发生真实模型超限。


## 补记 · 后续排期（2026-10-08）

用户新增密码管理器需求，root 设计文档 `docs/plans/pajio-private-credentials-2026-10-08.md`，**尚未实现**。Web/桌面在合同冻结与后端路由就绪前不做任何入口或假可用占位。


## 第二十二轮 · 首次认识流程 Web/桌面对齐（2026-10-09）

onboarding-contract（冻结）Web 侧：新 `onboarding.js` v4 + 设置入口 + maybeOffer/reset 钩子（app.js v49、pajio.css v17）。六步点选、草稿/确认分离、CAS+request_key 持久回执（先持久后发/同 key 同 body 重试/改意图拒绝）、晚回执重读采用更新、409 双选择+较新版本守卫、来源真实状态（日历说明在手机 App 连接、飞书真实状态无假按钮）、skip 全空不伪装。QA 合成 profile（rev3 completed）真实点击全流验证并还原原始值（终态 rev7）；测试 188/188（新增 onboarding-ui 12 项）；实测暴露并修复两个真缺陷（完成保存后 close 回写草稿、返回链缺按钮）。**未验项**：桌面壳连 QA 的点击流（运行实例为用户真实会话）、新空账户自动弹出与 skip 的真实点击（待 root 隔离 fixture）。详见 docs/evidence/pajio-onboarding-20261009/zcode-delivery.md。
