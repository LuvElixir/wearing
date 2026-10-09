"""On-demand, medium-specific design guidance for the result authoring harness.

These are composition principles and a reusable visual foundation, not task
workflows. Returning a guide never marks a result as visually reviewed.
"""
from copy import deepcopy

from .artifacts import ArtifactError
from .artifact_controls import CONTROL_CSS, CONTROL_JS, CONTROL_EXAMPLES

BASE_CSS = """:root {
  color-scheme: light;
  --paper: #ffffff; --ink: #272c35; --muted: #666d78;
  --accent: #4562dc; --accent-deep: #344cc3; --wash: #eff1fa;
  --line: #e6e7eb; --focus: #91a2e3; --error: #ba4354;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font: 15px/1.65 var(--font); }
button, input, select, textarea { font: inherit; }
button, summary, select { cursor: pointer; }
button, input:not([type=checkbox]):not([type=radio]), select { min-height: 44px; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 4px; }
.num { font-variant-numeric: tabular-nums; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; }
}
"""

COMMON = [
    "App 端优先：先设计窄屏的结论、主要操作与反馈，再扩展到桌面；关键判断不依赖 hover，触控不少于 44px。顶部导航、全局关闭与安全区由宿主负责，内容页不再复制一套；只有页面内自有弹层才需要自己的关闭按钮。",
    "先确定用户看完能做的一个判断，再选择构图。首屏给结论、关键变化和必要上下文；一个主要交互焦点，其余信息逐层展开。",
    "沿用 Pajio 的近白、墨灰与钴蓝；数字对齐、中文原生字体、克制的边线和圆角。用字号、间距、位置组织层级，不把每段话包装成同样的卡片。",
    "标题通常 22–27px，正文 15–17px，说明 12–13px；只给最重要的数字 40–52px。小字不承担关键结论，正常文字对比度至少 4.5:1。",
    "同一数据源驱动结论、图形和明细。说明时间、单位、统计口径和样本覆盖；未知是未知，不能用零补缺失。合成演示数据要清楚标示。",
    "交互在操作位置附近给出实际反馈；输入与结果尽量同屏。默认值有依据，提供恢复入口，空值、负数、超范围、无结果都有明确状态。保留编辑焦点，不强制改写未输入完整的值。",
    "使用原生语义控件和可见标签，键盘可操作、焦点可见、触控目标至少 44px。图形有文字等价信息；不能只靠颜色、悬停、声音或动画传达结论。",
    "动画用于解释变化和空间关系，通常 150–250ms；避免数字从零跳动、闪白、无尽装饰动画。支持 reduced-motion，视频有暂停与静态替代。",
    "窄屏重新组织阅读顺序，关键判断和主要控制优先，图表标签不裁切；不要把桌面页面整体缩小。证据与细节可展开，避免内容与宿主标题反复重复。",
]

MEDIA = {
    "dashboard": {
        "purpose": "让用户发现变化、核对数据并作出判断。",
        "composition": [
            "用一条与问题相关的结论引导一个主要图表；先决定比较、趋势还是构成，再选择图形。不要默认堆 KPI 卡片、环形图或随机曲线。",
            "柱状图从零起算，比较使用一致尺度；调整参数时保持尺度稳定，确需换尺度要清楚显示。单位、时间区间和分母可见。",
            "标签直接靠近数据；只给选中项或关键差异强调色。真实明细可查看，筛选同时更新图形、统计和当前口径。",
        ],
        "review_cases": ["核对合计、百分比分母、图形长度与同版本明细", "筛选无数据、单条数据与极值", "窄屏轴标签、触控与键盘"],
    },
    "diagram": {
        "purpose": "让用户看清边界、关系、先后和因果假设。",
        "composition": [
            "先选择关系结构：流程沿单一方向，层级按包含，系统按边界，因果图明确方向。布局必须传达真实关系，不把段落放进框里就叫图解。",
            "减少交叉连线；箭头端点明确落在节点，动词标注连线含义。已知、推测与未接通关系用线型加文字区分。",
            "重要路径先可见，细节按节点展开。SVG 使用 viewBox、title/desc 与可阅读标签；大图提供整体视图、缩放/复位及线性文字结构。",
        ],
        "review_cases": ["逐条核对节点、箭头方向、连线含义和系统边界", "长标签不重叠、不悬空", "手机能读完整路径，键盘可展开节点"],
    },
    "interactive": {
        "purpose": "让用户通过改变条件理解结果，并比较可行的选择。",
        "composition": [
            "把最有价值的可调变量与反馈放在一起，先给一个有解释的默认状态。输入、范围、单位和变化后果都清楚。",
            "由同一个状态与计算函数驱动所有数字、图形与明细；重算要真实，恢复要可用。空输入不等于零，不能把无效参数显示成成功结果。",
            "探索与执行分开。预览不连接真实账号或下单接口；没有可用执行通道时不放‘确认付款’等假按钮。离开会丢失试算状态时清楚说明。",
        ],
        "review_cases": ["默认值、改变后、恢复、空值、无效值、上下界", "金额按最小货币单位计算，跨模块结果一致", "Tab、方向键和触摸操作；反馈在视野内"],
    },
    "explainer_video": {
        "purpose": "用时间与连续变化解释静态图解难以表达的过程。",
        "composition": [
            "先写观众最终要懂的结论，再规划建立问题、解释变化、展示后果的镜头。镜头之间保留同一对象与空间关系，不能只是连续播放文字幻灯片。",
            "旁白、字幕、图形必须讲同一件事；每个镜头只推动一个理解点，为阅读留时间。避免用炫技转场掩盖因果跳跃。",
            "先做低成本分镜或静帧确认信息结构，再用实际可用的生成/合成工具；成片必须检查画面、字幕、音频、起止衔接及手机可读性。",
            "附静态摘要、证据与可定位的章节；可暂停、回看、静音。播放失败有真实替代，不能自动有声播放。",
        ],
        "review_cases": ["逐镜头核对事实、字幕、音画同步和对象连续性", "实际播放开头、中间、结尾，检查裁切、黑帧、白闪", "小屏字幕、静音理解、暂停与摘要"],
    },
}


def design_guide(presentation: str) -> dict:
    if presentation not in MEDIA:
        raise ArtifactError("请选择 dashboard、diagram、interactive 或 explainer_video。", 422)
    video = presentation == "explainer_video"
    return {
        "version": 3,
        "presentation": presentation,
        "delivery": "planning_only" if video else "self_contained_html",
        "capability_note": (
            "当前 artifact_publish 不支持视频。以下仅用于规划；有实际可用视频工具时才能制作，并另行验证成片。"
            if video else
            "HTML/CSS/JS/数据全部内联，1 MB 内 UTF-8。预览不支持联网、CDN、外部字体、iframe、主应用 API 或真实业务动作。"
        ),
        "principles": COMMON.copy(),
        **deepcopy(MEDIA[presentation]),
        "starter_css": None if video else BASE_CSS + CONTROL_CSS,
        "starter_js": None if video else CONTROL_JS,
        "controls": None if video else dict(CONTROL_EXAMPLES),
        "style_contract": None if video else [
            "统一的是视觉与控件交互规则；每次根据实际问题编写布局、数据结构、计算与内容，不固定业务流程。",
            "需要数字输入、滑轨、关闭或折叠时优先复用 wr-field / wr-range / wr-close / wr-disclosure 与提供的内联 CSS/JS，保持单层整体焦点和统一轨道/滑块状态。不要在内部输入框再叠加一圈焦点边框。",
            "将 starter_js 放在控件之后；业务代码直接赋值或重置 range.value 后调用 WearingUI.syncRange(input)，原生 input 事件会自动同步轨道。范围、标签、单位、aria-valuetext、验证与计算由本次页面代码设置。",
            "HTML、CSS、JS 全部保存在产物内；复制需要的基础与控件片段，不加载外部 UI 库、不访问宿主。尚未提供的控件沿用视觉规范按需实现。关闭属于退出动作，悬停保持中性色，键盘焦点只围绕小尺寸视觉面；折叠使用线条箭头随状态转向，保留原生 details 语义。",
        ],
        "authoring_review": [
            "制作前明确：用户要判断什么、首屏看什么、可操作什么、证据在哪；按本次问题自由构图，不套固定业务流程。",
            "制作后读回文件，复算代表性输入；若本轮工具能实际呈现，则检查桌面与窄屏、关键操作及错误状态，发现问题后修正。",
            "只有实际观察才能报告呈现/交互已验证。没有渲染工具时说明未目视验收；发布成功仅证明文件已保存。",
        ],
        "verification": "guidance_only_not_a_quality_verdict",
    }
