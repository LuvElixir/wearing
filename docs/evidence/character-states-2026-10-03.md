> Historical v3 verification. The user subsequently identified a white flash: corner brightness and endpoint matching did not detect the darker foreground during playback. V4 correction and current results: [character-loop-v4-2026-10-03.md](character-loop-v4-2026-10-03.md). The quiet gaps described below have been removed.

# Wearing — 角色状态与电脑真机验收

## 角色交互

用户否定了轻拍晃图和对白气泡，并明确要求首页、陪伴区都没有播放按钮。现已替换为真正的角色肢体视频：待命、招手、倾听、思考、挽袖动手、等待接手。点按招手只播放一次后回到当前状态，重复点击不叠加。普通状态更换等待当前动作结束，人工接管立即终止工作动作。没有虚构的回应或成功庆祝。

六段新生成视频均为 720×720、24 fps、5 秒、无声，单段约 0.26–0.40 MB。两个首版因角色长嘴被淘汰，原始文件保留但不交付网页。共 8 次生成，按已查询报价估算 377.20 积分；账户余额和实际结算未独立核验。原图直接复用，未生新图或 2K 素材。

首尾统一至同一个静帧，背景统一至 #fafafa；编码后的角落亮度在每个视频的全部 120 帧均为 249，首尾平均绝对像素差 0.59–0.61/255。切换时先等下一段首帧解码，静帧一直可回退。输入等待期间不重复下载整套视频。系统减少动态效果、隐藏页面、离屏、加载失败均有处理。

制作记录：[完整生成与采用清单](../../design/motion/wearing-companion/states-20261003/PROGRESS.md)，[六状态视频预览](../../design/motion/wearing-companion/states-20261003/output/states-overview-720.mp4)。

真实浏览器：8765 保留原 4 条对话；8766 为隔离初始页。首页和对话区均无播放按钮，video.controls=false；点按确实加载 attention.mp4，readyState=4、currentTime 前进，并结束回到待命静帧。输入触发倾听文案。390px 初始页 scrollWidth=innerWidth，无横向溢出。未向主对话提交测试消息。

## 电脑接入

用户手动添加并开启 CuaDriver 屏幕录制后，实际探测 accessibility=true、screen_recording=true、ready=true。已接入当前本机，Wearing 执行引擎报告 computer.active=true。Hermes 固定提交和 Driver 0.21.0 保持不变。

实际调用 Hermes 的 computer_use，在独立原生 WearingProbe 窗口读取结构、输入中文、点击“核对测试文字”，然后截图人工核对真实结果。输入有 AX value_readback；按钮本身只报告 effect=unverifiable，截图内的“已核对”文字才是实际结果证据。测试框原有“你好”得以保留，新增文字附在后面。文本框的 AXPress 不支持，未将这次失败称为成功；后续直接背景 AX 输入和按钮 AXPress 可用。

隔离测试未加载模型凭据，som 截图已落盘；自动视觉模型分析因未配置提供商而失败，此项不代表电脑截图失败，也不代表已经验收任意视觉模型。当前产品仍优先 AX 读取；Windows 和更复杂真实应用尚未真机验收。

通过正式页面点击“我来接管”，在主 Wearing profile 下实际验证 capture 和 type 都返回 human_has_control；随后经页面交回 Wearing，holder 恢复 agent。沿用 standard/manual，不改其他 profile 的权限。

截图：[独立窗口核对结果](presence-2026-10-03/computer-proof.png)、[初始页](presence-2026-10-03/welcome.jpg)、[手机宽度](presence-2026-10-03/welcome-mobile.jpg)。

## 工程验证

- Python 74 项通过。
- 媒体状态测试通过：首帧交换、动作结束后状态更换、点击去重、人工接管、隐藏/离屏/减少动态效果、旧加载回调竞争、错误回退、静止间隔、无播放器控件。
- JavaScript 语法检查通过，wheel/sdist 可构建。
- 主对话完整 JSON 排序哈希仍为 `467a1178ce762122b26dd8d94f406273bbe95f25bc85195bdf471b186add3982`，与本轮前一致。
- 本机设备冒烟测试已通过，不等同于端到端模型执行任意业务的验收；没有执行外部交易、发送消息或改动模型密钥。
