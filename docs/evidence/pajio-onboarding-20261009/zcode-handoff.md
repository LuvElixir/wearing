# Pajio 首次认识流程 — Web / Desktop 交接

2026-10-09。原生 App 已完成实现、自动化验证及 iPhone Air 模拟器浅/深色点击验收；现在由 ZCode 负责 Web / Desktop 对齐。

## 先读这些

1. `docs/plans/pajio-onboarding-2026-10-09.md`：产品判断、研究来源、流程与未验证的假设。
2. `docs/evidence/pajio-core-20261007/onboarding-contract.md`：冻结的真实 API、状态、枚举、作用域、CAS、请求回执和上下文语义。
3. 只读 `clients/mobile/src/OnboardingPanel.tsx`、`OnboardingConnections.tsx`、`onboarding-model.ts`、`onboarding-client.ts`、`useOnboarding.ts` 及其测试，参考 `Mobile.tsx`、`PersonalHub.tsx` 的入口。
4. 本目录的 `confirm-day.png`、`confirm-night.png`、`expression-day-final.png` 和 `acceptance.md`。最终 iOS 与 Android 源码均包含表达样例修正。

## 本轮具体交付

实现六步点选式流程：见个面 → 日常角色 → 常用应用 → 兴趣与表达 → 可选资料连接 → 核对并确认。没有必填输入框；每一项可留空，不要求用户说出目标。沿用 Pajio 品牌、现有睡衣熊与日夜主题，桌面按合适阅读宽度排版，不重做品牌或导航。

- 新空账户只在正常登录完成且无优先恢复任务时按服务端 `recommend_onboarding` 推荐；老账户不强弹。设置添加「初始偏好」入口。
- 可返回、稍后继续、跳过、恢复草稿。草稿不进入模型上下文。已完成账户重开编辑只存本地，最终确认成功前已确认偏好仍有效。
- 选择微信、抖音等应用是用户自述，不能显示已经授权、导入历史或已经了解用户。来源步骤仅连接真实现有能力。
- Web 不模拟原生 EventKit 权限。日历可说明在手机 App 选择同步；飞书沿用已有配置完整时的用户 OAuth。未配置时如实说明，首次流程不出现 App Secret 表单、不做假连接按钮。
- 来源授权属于独立流程；未授权、拒绝、空数据均可继续。返回恢复原步骤与选择，刷新真实状态。
- 最后一页逐项核对/修改，展示真实来源状态。保存成功进入「今天」。无授权也可完成；不自动启动模型、生成简报、打开通知或创建定时任务。
- 所有新持久状态经 WearingStore，按账户、身份和会话隔离。切换/退出/删除冻结时旧响应不可更新新界面。
- `request_key` + 精确请求正文持久化，不确定结果重试原请求。409 保留本机输入，允许使用最新或以本机选择重新核对；不盲写。旧成功回执可能早于现状，必须重读当前 GET 后再更新界面。skip 后重放废弃 draft 返回409。
- 原生 completed → draft/skipped 禁止。清空已确认偏好应显式保存 completed + 全空/null，不伪装成跳过新手。

## 工作边界

只修改 `src/wearing/web/`、必要的 `clients/desktop/`、对应 Web 测试及本轮交付文档。App 与 Python 后端只读。有后端问题先反馈 root；不要修改协议或加入依赖。

保留当前全部脏工作。只在合成 QA `http://127.0.0.1:8891` 验收，identity 为 qa，路由现已加载；`GET /api/onboarding` 可用。现有合成 profile 是已完成 rev3，适合已有偏好编辑测试；可在同一合成 QA 中明确编辑它，不能重置整库。若需要新用户自动弹出的环境，请通过单元/集成测试或向 root 申请隔离 fixture，不要清空当前数据。QA 重启由 root 执行。

生产 8765 不动，不改真实账号，不真实授权、不调用模型/推送，不部署、不 Git push。第三方接口存在不等于当前授权成功。

保持既有 Web 约束：`html:not(.mobile-host)` CSS 门控；CSP 禁止模板内联 style/onclick；生命周期 epoch/reset；收据与草稿走 WearingStore。

## 验收与回报

运行 `node --test tests/*-ui.test.cjs tests/web-core-closure.test.cjs tests/web-import-goal.test.cjs` 并补充有意义的新测试。覆盖新旧账户、跳过、草稿恢复、confirmed取消编辑、重复请求/未知结果/409/晚回执、账户与身份切换、授权状态与空来源。

在真实浏览器 QA 页面点击：设置入口、选择、返回、关闭恢复、保存和 API 读回；浅深色、长页/小屏、键盘焦点。浏览器已有用户不能被引导截断。桌面构建与运行验收按当前既有流程执行，确认使用 QA 而非8765；必要时将 QA 启动方法写明后再启动。不要照抄历史交接里的全局 kill 命令。

把源码改动、命令及结果、截图、实际未验项追加到本目录 `zcode-delivery.md`，并更新既有交付矩阵。回复明确“已实现/已运行验证/尚未验证”；派发、构建和页面可见分别记录，不宣称市场验证或真实外部授权成功。
