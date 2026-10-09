# ZCode Web/Desktop 交付 — 首次认识流程对齐（2026-10-09）

> **本文为当前终稿，取代此前版本的全部验收表述。** 早先版本（onboarding.js v1–v4 时期）曾写「QA 全流验收完成／188 通过」等结论——该状态已被独立复核推翻（见「独立复核与修复史」），请勿引用。当前有效结论以本文为准。

分工：ZCode 负责 Web/桌面（`src/wearing/web/`、`clients/desktop/`）；App 与 Python 后端只读未改。QA `http://127.0.0.1:8891/?identity=qa`（root 维护；本轮进程 PID 18337，`--resume-root` 保留既有合成数据；库规模为 root 完整统计记录：**83 表 429 行＋usage 2 表 1 行**（health 类可新增）——本人未独立核对，引用 root 记录）。生产 8765 零写入、未部署、未 Git push、未真实授权/模型/推送。

## 已实现（当前版本）

- **`src/wearing/web/onboarding.js` v7**（window.WearingOnboarding；v7＝从设置进入引导时关闭父设置面板，完成/退出不再叠加双模态）：六步点选（见个面 → 你的日常 → 常用应用 → 兴趣与表达 → 带上资料 → 确认偏好），枚举/上限/文案与 App onboarding-model.ts 一致（roles≤3、apps≤10、interests≤5、reply_detail/reply_tone 单选可空）。
  - **草稿/确认分离**：草稿（`onboarding-draft:v1:<identity>`，WearingStore）只留本机；completed 账户重开编辑翻页零 POST，最终「确认并进入」才提交 completed（CAS）。清空选择＝显式保存全空 completed，不伪装跳过。
  - **规范化**：新请求与草稿按枚举序 canonicalValues 持久；同意图按语义比较（revision/status/step＋规范化 values）；旧 pending 保留原 key/正文原样重试，回执比较两侧规范化——点击顺序不再造成回执指纹死循环。
  - **持久回执**：`onboarding-request:v1:<identity>`（`{identity,body}`）必须 `WearingStore.set` 持久成功（返回 true）后才 POST；失败如实提示「本机暂时没能保留这次保存，没有发出请求。」；未知结果重试完全相同请求；同 key 改意图拒绝。
  - **晚回执**：POST 后重读 GET，fresh 低于回执或同版不同 status/step/values →「最新偏好还没有核对」且保留 pending（与 App 一致）；fresh 更新则采用 fresh。
  - **409 双选择**：保留本机选择，重新核对 / 使用已保存的最新偏好；仅 fresh.revision>pending.revision 才废弃原请求；**先换快照为 fresh 再落草稿检查点**（刷新后不再二次冲突）。
  - **围栏与忙态（票据分离）**：`ui.generation` 仅作面板会话围栏（reset/注销冻结作废）；load/save/feishu 各持独立票据（loadTicket/saveTicket/feishuTicket）——只读来源查询与面板重读不得作废业务保存票据，杜绝「确认按钮永久禁用」；reset 清 busy/feishuBusy；旧请求晚归不写新会话。
  - **注销冻结**：`WearingDeletion.workAllowed()===false` 时 choose/go/retain/save/授权全拒（不写草稿/journal、不 POST，如实提示）；`registerWorkGate({stop})` 冻结时作废会话围栏并解锁；缓存清理见 account-deletion 条。
  - **来源真实状态**：日历如实「网页端不读取系统日历；请在手机 App 中连接」；飞书仅 apps 含 feishu 时出现，读真实 `/api/cloud-apps/feishu`；**撤销中优先于已连接**（connected+revocation_pending 不显示「已授权/连接已建立」，成功分支须 `!revocation_pending`）；授权结果手动「我已授权，检查结果」，**不声称自动回跳同步**；无开发者凭据表单、无假连接、不声称已读取。404 文案对齐 App「这台服务还未提供初始偏好设置，可以先进入产品。」。
  - **入口与面板交接**：设置「初始偏好」（进入引导时关闭父设置面板——完成进入「今天」、退出回到原页面，均无叠加模态）；`maybeOffer()` 在 `initialize()`（openFromLink＋activity_task 恢复之后）与 switchIdentity 末尾调用；`?view=`/`life_record`/`activity_task` 或非聊天视图不自动弹（深链恢复优先）；已有面板打开或读取失败不弹。
  - **返回链**「上一步/退出初始设置」；首步 draft 快照「先进去看看」（skip＝全空 skipped）；空步骤「这一项暂时不补充」；「稍后继续」保留草稿；completed 保存后的 close 事件不回写草稿。
- **`src/wearing/web/account-deletion.js` v7**：`clearAccountCaches` 业务键清理补 `onboarding-draft:v1`/`onboarding-request:v1`（原仅 chat/voice/native——独立复核确认的真实遗漏）；按账户 scope 前缀精确清理、他账保留。
- **`index.html`**：`#onboarding-panel` 中心模态＋设置入口＋脚本（onboarding.js?v=7、app.js?v=51、pajio.css?v=18）；**`app.js` v51**：maybeOffer 钩子移至入口恢复之后＋switchIdentity 末尾、switchIdentity 增加 `WearingOnboarding?.reset()`；`pajio.css` 全部 `html:not(.mobile-host)` 门控 ob-* 样式。

## 独立复核与修复史（按发生顺序）

1. 自查修复（v3/v4）：完成保存后 close 事件回写草稿；返回链缺「上一步」按钮。
2. 独立复核第一批（1+4+5 项，VM 复现，复核人只读未改）：A1 飞书撤销中优先、B1 pending 从 `{identity,body}.body` 读取、B2 set 返回值核实、B3 resolve 以 fresh revision 落检查点、B4 单选直接换选、C5 规范化指纹、C6 深链入口优先、C7 注销冻结门、C8 异步围栏、C9 晚回执守卫——v5 全部修复。
3. **v5 引入的新 P1（独立复核第二批）**：loadFeishu/save 共享 `++ui.generation`——选飞书→确认页自动来源查询作废保存票据→busy 永不清、确认按钮永久禁用；保存中关闭重开同样复现。**v6 以会话围栏＋独立票据修复**。同批确认 account-deletion.js 清理正则漏 onboarding 键——修复（v7 版 account-deletion）。
4. **幽灵面板（root 桌面 CUA 复核时定位表象、本人定位根因）**：`pajio.css` `.ob-panel{display:flex}` 覆盖 UA `dialog:not([open]){display:none}` → 未打开的对话框常显且关不掉（生产实例与隔离实例均复现）→ `.ob-panel[open]`（pajio.css v18）。
5. **面板交接（root 桌面实测确认保存后指出）**：从设置进入引导时设置对话框未关闭，完成后仍挡住「今天」→ onboarding.js v7：进入即关父面板；完成→今天、退出→原页面，无双模态。

## 已运行验证

**测试**：`node --test tests/*-ui.test.cjs tests/web-core-closure.test.cjs tests/web-import-goal.test.cjs` → **200/200**（onboarding-ui 24 项，含票据分离/晚回执/409/规范化/冻结/面板交接回归）。独立复现脚本 `/tmp/pajio-onboarding-web-independent-review.cjs`（真实加载 scoped-store/account-deletion、不联网不写产品文件）→ **14/14**。当前版本：onboarding.js **v7**、account-deletion.js **v7**、app.js **v51**、pajio.css **v18**。

**QA 8891 真实点击**（合成 profile，原始基线 roles=[employed,business]/apps=[wechat,feishu]/interests=[design,reading]/brief/warm；仅编辑该 profile，未清库）：

- 设置入口→面板开在确认页、摘要与基线逐字一致；老账户（completed）不自动弹。
- completed 编辑全程零 POST（fetch 间谍）；「稍后继续」→重开草稿恢复。
- **未知结果→整页刷新→重试**：一次性拦截 POST→确认→未知结果（pending journal 在场）→**整页 reload**→重开 pending 从 body 正确恢复（不崩溃）→「重试同一次保存」同 key 成功（rev→8，journal 清）。
- **409→保留本机→保存→刷新零冲突**：带外推进 revision→UI 按旧版确认→409 双选择（本机输入保留）→「保留本机选择，重新核对」→再确认成功→**reload 重开无冲突框/无草稿残留**。
- **单选直接换选**（简短结论→适量解释）与**点击序保存**（先 在校学习 后 在职工作→服务端枚举序 [employed,student] 落库）均通过。
- **票据分离（v6）**：apps 含飞书→确认页自动来源查询（飞书 · 尚未连接）→busy=false、确认按钮可用。
- 数据终态：**rev13 completed＝原始基线值**，journal 全清（其后 root 桌面验证保存 rev13→14，最后 v7 复验保存 rev14→15，值仍为基线）。
- **面板交接（v7）**：设置打开→「打开初始偏好」→父设置面板即关、单模态打开确认页；「稍后继续」退出后页面无任何叠加对话框；完成→「今天」由回归覆盖。
- 视觉：六张截图 `docs/qa-web-desktop-20261007/round22-onboarding-*.png`（浅/深/小屏/409/来源页/见面页）。

## 桌面隔离验收（独立 identifier 构建）

- 数据目录 `/tmp/pajio-desktop-qa-data-20261009`（首次启动前仅写 `connection.json`＝`{"url":"http://127.0.0.1:8891/"}`，无查询参数→启动 auto-connect(false)）；构建 `CARGO_TARGET_DIR=/tmp/pajio-desktop-qa-target-20261009`、`tauri build --debug --bundles app --config`（productName "Pajio QA"、identifier `io.luckyloading.pajio.desktop.onboardingqa20261009`、`app.appDirectoriesOverride` 指向该目录；single-instance 按 identifier 与生产实例隔离）。本节构建与后续重启针对独立 QA 实例，未修改生产连接配置。此前生产前端有只读观察，不能将整轮描述为从未接触该界面。
- 结果见文末「桌面结果」。

## 未验项（如实）

- B2 真实持久失败、C9 真实 fresh 落后、A1 真实撤销中状态：需故障注入/夹具（单测与独立脚本覆盖）。
- C6 深链真实入口、C7 真实注销冻结、C8 真实身份切换：QA 单一 completed 身份且无注销网关路由（单测与独立脚本覆盖三种入口形态/冻结/切换）。
- 新空账户自动弹出与 skip 的真实点击流：待 root 隔离 fixture。
- 完整 Tab 序列/读屏 radio 语义的逐项键盘遍历未做（程序化 focus 已验证可达）。
- 不宣称：用户实验指标、任何第三方授权成功、授权页自动回跳同步、浏览器验收等同桌面验收。

## 桌面结果（隔离 Pajio QA.app，2026-10-09）

- **构建**：`CARGO_TARGET_DIR=/tmp/pajio-desktop-qa-target-20261009 tauri build --debug --bundles app --config`（productName "Pajio QA"、identifier `io.luckyloading.pajio.desktop.onboardingqa20261009`、`app.appDirectoriesOverride=/tmp/pajio-desktop-qa-data-20261009`）→ 产物 `/tmp/pajio-desktop-qa-target-20261009/debug/bundle/macos/Pajio QA.app`（42.97 MiB）。构建 exit 0。single-instance 按 identifier 隔离，两实例并行；本次 QA 构建没有覆盖生产安装或连接配置。
- **连接**：数据目录预置 `connection.json={"url":"http://127.0.0.1:8891/"}`（无查询参数）→ 首次启动 auto-connect(false) → 主 webview 即 QA 页面（AX 确认「QA 验收（合成数据） · Pajio」、QA 身份、菜单名 Pajio QA）。
- **幽灵面板根因与修复**：首次启动即观察到「初始偏好」面板常显且主体空白、AX/键盘无法关闭——根因是 `pajio.css` 的 `.ob-panel{display:flex}` 覆盖了 UA 的 `dialog:not([open]){display:none}`（未打开的对话框被常显；此前在生产实例上看到的「打不开也关不掉的空面板」同一根因，并非用户或 maybeOffer 打开）。修复：`.ob-panel[open]{...}`（pajio.css v18）＋回归断言；隔离实例重启后幽灵面板消失。
- **已验证（桌面壳内）**：设置面板经 AXPress 真实打开（248 元素完整渲染，「初始偏好」区段在位）；「打开初始偏好」经 AXPress 打开面板且**完整渲染**（截图逐字核对：六步进度 6/6、摘要与 rev13 基线逐字一致、「日历与提醒事项 · 在手机 App 中连接」「飞书 · 尚未连接」如实状态、确认按钮在位）；面板可关闭并恢复页面。
- **桌面保存闭环（root 实证，2026-10-09）**：root 经 CUA 以 2360×1640 截图的**实际像素坐标 [1695,1307]**（不可除 2）点击「确认并进入 Pajio」，`GET /api/onboarding` 证实 **revision 13→14、completed、值与基线完全一致**。本人此前的合成点击（AX/坐标/键盘）在 WKWebView modal 态不可靠，该结论以 root 记录为准。
- **面板交接缺陷与修复**：root 同次复核指出完成保存后原设置对话框仍挡住「今天」（从设置进入引导未关父面板）——onboarding.js **v7** 修复（进入即关设置面板），回归＋浏览器真实验证通过（进入单模态/退出零叠加/完成进今天）。**root 已于本地 02:48 通过 CUA 独立复验 v7：确认后直接显示“今天”，无设置面板遮挡；GET 为 revision 15、completed、值保持基线。重开摘要后关闭也正常回到“今天”。** 见 [最终接口快照](desktop-saved-profile-final.json) 与 [root 验收记录](acceptance.md#web-与桌面独立复验)。
- 备注：生产实例前端来自同一共享工作树，其幽灵面板随 pajio.css v18 修复，用户 Cmd+R 重载即消失；本轮未再触碰生产实例。
