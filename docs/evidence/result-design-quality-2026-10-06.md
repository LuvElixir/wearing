# 结果设计质量验收 · 2026-10-06

## 本轮范围

人工打磨预算演示；将按媒介的设计指引接入 Wearing 的既有 MCP 工具集。未重做品牌或角色，未调用付费模型生成新演示、未制作视频、未启动云 VM。

## 交付与真实性

- 设计源：`design/artifacts/weekly-budget.html`；使用合成数据，不读取私人账单。
- 独立演示服务：`http://127.0.0.1:8789/#conversation-main`。最新产物 `art_50c1d563d74449e1a21ec0ace326680c`（版本 5），保留全部旧版本。
- 本轮为人工设计修订，不是一次新模型自动生成效果；真实模型 v1 的链路证据留在上一轮记录。
- 下载内容与设计源逐字节一致，SHA-256 与不可变快照 metadata 一致。
- `artifact_design_guide` 按 dashboard、diagram、interactive、explainer_video 返回设计原则、基础样式和各自的审查用例；引擎精确工具集校验已纳入。
- 视频返回 `planning_only`，当前 HTML 发布契约不扩展为视频；指引返回 `guidance_only_not_a_quality_verdict`，不自动修改产物验证状态。
- 本机 8765 主服务已重新加载至 profile v17，runtime 为 `idle`；原有 4 条对话完整一致。引擎下次启动应用受管身份指引。

## 实际浏览器检查

通过 CUA 在真实隔离 iframe 操作，1280×800 桌面与 390×844 窄屏截图；窄屏 `scrollWidth == clientWidth == 390`。无浏览器控制台错误。

| 操作 | 实际结果 |
| --- | --- |
| 默认餐饮 350 | 合计 550、少花 70、减少 11.3% |
| 改为 280 | 合计 480、少花 140、减少 22.6% |
| 清空 | 显示等待有效金额，不用零代替缺失 |
| 1001、-1 或 1.001 | 提示有效范围/精度，结果不可用 |
| 恢复原计划 420 | 合计 620、差额 0 |
| 280.25 后滑杆 ArrowRight | 280.26、合计 480.26、差额 139.74 |
| 下限 0 | 合计 200、少花 420 |
| 上限 1000 | 合计 1200、多花 580；明细一致 |
| 展开明细 | 餐饮/交通/订阅与合计、合成数据说明均可见 |

两条柱使用固定 0–1,200 元相同尺度。过渡改用 transform，减少动态效果时禁用（源码检查，未单独切系统偏好验证）。手机顶部操作保持单行。未宣称真机或所有浏览器验收。

截图：`.wearing/qa/result-delivery-20261006/design-desktop-final.png` 与 `design-mobile-final.png`。

## 设计复核

Impeccable 独立 reviewer 最初 `fix`：次要说明文字在浅色底上的对比度为 4.42:1。修订为既有 `#666d78` 对 `#eff1fa`，4.631:1；复看同视口截图后返回：

| 项目 | 最终结论 |
| --- | --- |
| 次要文字对比度 | Resolved |
| 本次修改带来的回归 | 未发现 |
| 未解决项 | Clear |
| disposition | ship |

源文件 detector 的宽度动画警告改为 transform；移动数字字号使用局部 40px、桌面 52px，不把局部演示尺寸加入全球品牌约束。没有修改 detector 忽略项或放宽校验。

## 自动检查

- `pytest tests/test_artifacts.py tests/test_engine_integration.py tests/test_profile.py -q`：27 passed。包含实际引擎工具发现、受管迁移、新指引按媒介分支/非法类型/不产生记录，以及已有产物快照与访问边界。
- `node --test tests/artifact-ui.test.cjs tests/face-ui.test.cjs tests/research-ui.test.cjs`：7 passed。
- `git diff --check`：通过。

限制：本轮没有新增自动截图评审服务。后续模型生成是否稳定达到该完成度，需要按真实任务继续验证；本轮样板通过设计复核不代表所有未来输出已合格。

## 后续控件修订：共享样式 v2

用户指出双层焦点框和默认滑轨粗糙。新增 `artifact_controls.py`，通过设计指引 v2 返回可内联 CSS、JS 与最小用法；当前统一数字字段整组焦点、滑轨皮肤及状态。具体页面保留自主布局和计算。预算示例直接复用相同控件源码，发布版本 6（`art_eeb22290d4cf4e78953b9ea52f9a4998`），下载字节与设计源一致。

本轮实际检查：鼠标聚焦不再出现内部矩形；输入 280.25 对应轨道比例 0.28025；End 为 1、Home 为 0、恢复原计划为 0.42；窄屏点击滑轨中心为 0.5，390px 无横向溢出。截图 `controls-desktop-focus.png`、`controls-mobile-focus.png`、`controls-detail.png` 保存在同一 QA 目录。未操作系统减少动态设置或 Firefox 真机，相关样式只经源码检查。

14 个 artifact 测试通过，`git diff --check` 通过。设计 detector 仅提示既有局部金额 40px 和轨道 4px 圆角的 advisory；未修改忽略配置。此为窄范围自主修订，不沿用上轮独立 reviewer 的 ship 作为新版审美证明。
