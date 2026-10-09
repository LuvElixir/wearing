# Pajio — Web / Desktop implementation handoff

2026-10-07. 用户明确批准名称 **Pajio** 和原版睡衣小熊，并授权 App 由 Codex 完成后，网页与桌面交给 ZCode 按 App 实现对齐。本文件替代旧 Today 风格交接中的视觉要求。

第一轮交付后的独立验收尚有待修项：`docs/evidence/pajio-20261007/web-review-followups.md`。长对话导航可达性、字标实际尺寸/填充、委托文案及桌面候选包签名验证通过后，才可关闭本交接。

## Current source of truth

- `clients/mobile/DESIGN.md`、`src/appearance.ts`（相对 mobile）、`app-theme.tsx`：中性浅灰日间 / 石墨夜间，默认跟随系统，用户明确选择持久保存。
- `design/brand/pajio/README.md`、`manifest.json`、wordmark/symbol/signature SVG、app-icon PNG：正式 Pajio 数字品牌。
- `clients/mobile/src/BrandStar.tsx`、`BrandWordmark.tsx`：一个实心四角星，Pajio 字标已转轮廓；功能图标仍各自表达用途。
- `clients/mobile/src/PersonalHub.tsx`、`TodayPanel.tsx`、`AgentTaskList.tsx`、`PersonalPanels.tsx`、`Mobile.tsx`、`VoiceComposer.tsx`：已经完成的 App 信息架构和实际交互。只读这些文件。
- `clients/mobile/assets/bear/*.png` 与 `wardrobe.ts`：八套已选原版睡衣小熊，无有效明确偏好时默认雾蓝条纹；保留有效的简洁模式或穿搭选择。
- `docs/evidence/pajio-delivery-2026-10-07.md`：App 验证记录。源码、模拟器、物理 iPhone 证据分开。

## Implement in your scope

1. 全部 Web / Desktop 用户可见 Wearing 改为 Pajio，包括 title、无障碍名、空态、连接提示、账户摘要和新助手称呼。旧历史消息、不可变产物原件不重写。保留协议、cookie/storage/IPC、包标识和 API 兼容。
2. Web 实现浅色/深色/跟随系统，使用 App 语义配色。取消旧 Today 蓝杏渐变、重玻璃外框和假会员卡；正文背景平静，账户信息真实。
3. 使用提供的 Pajio 字标和单星，默认睡衣小熊；我的→外观与个性化→八套衣橱，预览后显式保存，按连接和身份隔离。无新定价/虚构权限，不重造角色图。
4. 五入口聊天/今天/任务/记忆/我的，大屏以桌面阅读宽度组织；窄屏不挤压正文。聊天只保留一个总进展入口，真实任务/记忆事件低干扰，搜索/设置可达。移除泛化逐条核对/记成目标。
5. 对齐非聊天页紧凑输入入口；草稿与上下文保留。今天基于真实已接任务/返回结果/需介入，不能伪造自动简报。任务使用现有新分页接口 `limit/cursor`，409 保留当前内容并明确刷新；总体数量与当前载入数量分开。
6. Desktop 原生 Tauri 外壳也必须更新：productName、窗口标题、连接页、图标、构建 App 名称；保留 `io.luckyloading.wearing.desktop` 和现有数据路径兼容。核对 `clients/desktop/src-tauri/tauri.conf.json`、frontend 和 Rust 用户可见字符串。完成实际编译和本地候选包，勿以浏览器适配替代桌面交付。
7. 更新根 DESIGN.md 及 Web/Desktop 交付记录，明确主导文件及兼容边界。

## Boundary and shared working tree

只改 Web 常规分支、Desktop 和其测试/交付文档。`clients/mobile/**`、`src/wearing/web/mobile-host.css`、`mobile-host.js`、原生 bridge、后端和语音/数据库/认证只读。index/app/life 等共享文件须增量修改，保留 `html.mobile-host`、WearingHost、ackSeq/ackVoiceId、身份/草稿/确认安全边界。常规 Web CSS 用 `html:not(.mobile-host)` 门控。不要 git reset/clean，当前有大量他人脏改。不要 push/部署/服务重启/删历史数据。

## Verify before saying done

- JS/UI tests, desktop cargo check/test and actual native build (report any concrete local signing/build blocker).
- Web 日夜五入口、八套换装选择与保存、身份切换、窄屏/大屏、搜索、分页；截图和实际结果。
- App-host 回归：受控字体倍率、原生输入导航仍由 App 持有、不受 Web 新主题影响、重复进展不回归。
- No fake users/tasks, no business sends. Read-only UI verification and reversible appearance changes only; restore QA preference if pre-existing.
- Write `docs/pajio-zcode-delivery-2026-10-07.md` with exact files, commands, results, screenshots, native package path and remaining limitations. Dispatch is not completion.
