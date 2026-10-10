# App Linux 远控停止：诊断、修复与验收记录

日期：2026-10-10（Asia/Shanghai）。范围：Pajio Acceptance iPhone Air 模拟器中的实际 App、acceptance-a 的 Linux 测试电脑。初始诊断阶段没有修改源码、发送输入、抓取画面、读取输入内容或输出 SDP。随后经 Root 授权的最小修复、隔离 Xvfb 试验、部署及真实客户端复验按时间分别记录如下。

## 已观察到的现象

Root 操作员报告：App 成功显示 Linux 的合成 Firefox 测试页面，连接显示 21 ms；点击“开始操作”后，稍后尝试点击 Save note，随后看到“画面暂时没有更新，已停止操作”。该次点击是否执行、Saved 计数是否改变，没有获得证据，不能记作操作通过。

独立只读检查在 12:05:59（UTC 04:05:59）读到当前会话 `human_private`、`device_confirmed=true`、epoch 16、gateway_epoch 31；媒体服务 `ready=true`，会话 `closed=false`、`cleared=false`、`cleanup_attempts=0`、`cleanup_code=null`。这是检查时的新会话状态，不能用于推断前一会话关闭原因。

## 三处源码结论

1. `clients/mobile/src/remote-viewer-document.ts`：`frameShown` 由 `requestVideoFrameCallback` 更新视频呈现时间；不支持该 API 时使用 `timeupdate`（55–61、115–116 行）。数据通道 `frame` 消息单独更新 geometry 时间（126–130 行）。watch 每 300 ms 检查：画面已展示后，geometry 超过 2500 ms 未更新，**或**视频呈现回调超过 3000 ms 未更新，两者都触发同一个 `stale_video`（134–139 行）。没有“用户多久未输入就停止”的条件。输入门槛更早生效：geometry 必须新于 1800 ms，视频必须新于 2500 ms（41 行）。
2. `clients/mobile/src/NativeRemoteDevicePanel.tsx`：`stale_video` 映射到操作员看到的固定文案（20–26 行）。收到停止事件后清空 viewer 并请求设备暂停，因此停后无法从组件状态恢复两种帧龄。21 ms 来源于候选连接的 RTT，代码没有以该数字证明视频连续更新。
3. `src/wearing/private_media.py`：每次捕获都会发送新的 geometry 元数据（276–291 行），视频轨按 source.max_fps 调度，未实现“画面静止就停发”的逻辑。媒体 `/v1/status` 仅暴露 ready、closed、cleared 和清理结果（543–546 行），不保存前一次关闭的分支、帧龄、解码统计。现有安全状态足以确认连接及清理情况，不足以解释该次 stale。

源码行号为此诊断读取时的位置；后续改动应以函数名定位。

## 可确认与尚未确认

可确认：该文案属于帧新鲜度保护。用户几十秒没有输入，本身不应使连接停止。显示 RTT 不能代替视频持续性证据。

尚未确认：究竟是数据通道 geometry 停更、视频解码/呈现回调停更、客户端调度/可见性变化，还是服务端捕获/网络暂时停顿。当前两个分支合并且没有保留脱敏诊断，无法客观归因；这些是后续排查方向，不是已证实故障。

## 具体验证方向

- 在模拟器和远控画面持续前台可见时，重连后立即“开始操作 → Save note”，比较动作前后 Saved 计数，记录真实 UI 与设备回执；不重发结果未知的旧动作。
- 在同一会话中停止输入但保持前台可见，观察 10–15 秒，验证静止画面不会错误触发空闲停止。另行测试退出页面/切后台是否按设计停止，两个场景分别记录。
- 如果再次复现，再做最小本地诊断：停止分支、geometry_age_ms、video_age_ms、video.paused/readyState、PC 连接状态、累计 framesDecoded/bytesReceived。仅保留数字和固定枚举，排除画面、输入、SDP、令牌及原始异常文本。
- 不通过放宽超时、伪造最新帧时间或自动重放输入掩盖故障。首先辨别数据帧与呈现帧停滞，再决定修复位置。

Root 在随后流程中已明确交还 Linux 设备并观察到 agent_ready；这不追认上述未确认点击。


## 后续定位：Linux 输入阻塞（12:24 现场复现后）

后续 App 和桌面客户端均出现相同行为：Linux 画面稳定，开始操作后点击合成页面 Save note，随后停止；同客户端 Android Home 输入可以完成。这将排查范围收敛到 Linux 共享输入链路。

12:24 现场只读采样记录到媒体服务的 `xdotool mousemove --sync` 子进程存活 3,970 ms，77 次采样处于睡眠状态（`hrtimer_nanosleep` / `do_poll.constprop.0`）；随后进入按键清理。采样只保留固定命令种类、是否 sync、时长和进程状态，没有坐标或输入文本。`X11Source` 的原生命令超时为 4 秒，而 `PrivateSession.native` 在输入与抓帧间共享串行锁；移动等待会阻塞后续抓帧，先触发客户端 2.5/3 秒帧保护。

服务器安装 xdotool 3.20160805.1。该版本的 [mousemove 实现](https://raw.githubusercontent.com/jordansissel/xdotool/v3.20160805.1/cmd_mousemove.c) 在 sync 模式下等待指针离开旧坐标；[等待函数](https://raw.githubusercontent.com/jordansissel/xdotool/v3.20160805.1/xdo.c) 最多轮询 500 次、每次间隔 30 ms。同坐标按下/抬起、重复点击及滑动中四舍五入后的重复坐标，都可能没有位置变化。这里需要的是 X11 请求有序，而不是等待发生新的位移。

独立测试最初未加 `-noreset`，最后一个 X 客户端退出导致虚拟服务器重置光标，测试产生假阴性。纠正为独立 `Xvfb -noreset -nolisten tcp` 后，同坐标 sync 命令在 4,001 ms 超时；移除 sync 的同坐标移动与按下/抬起 3 ms 返回。独立显示不是生产 `:10`，没有借 SSH 输入生产设备。

候选仅移除 `private_media_sources.py` 中 pointer、tap、swipe 起点及 swipe 中间点的四处 `mousemove --sync`。Plain mousemove 的 XWarpPointer 会 flush；pointer 的移动进程退出并关闭 X 连接后才启动按键进程，tap/起始 swipe 的移动和按键则在同一连接顺序提交。保留原来的设备权限、串行锁、4 秒进程超时、帧新鲜度门槛及未知结果不重放规则。

验证结果：新增六项回归，连同原媒体测试共 49 项通过。候选仅在独立进程内存加载，真实 X11 事件观察到七对顺序正确的按下/抬起；pointer 2–4 ms、重复 tap 114–115 ms、含同坐标/四舍五入重复步的 swipe 160–169 ms，每次输入后抓帧成功。

此处仅记录候选验证，尚未部署，也不等同于生产 App/桌面点击通过。文件散列、现场采样和独立试验记录见同目录 `linux-input-stall-proof.json`；部署后仍需真实客户端复验。


## 精确部署完成（12:32）

Root 审核后授权 B Linux → A Linux。两台都确认没有活动 human 会话，核对 root 所有权、单文件旧散列、测试租户及设备绑定；持有本机原生操作锁，保存持久 intent 与精确备份，然后原子替换这一文件。只重启 `pajio-private-media.service`。每台重启后连续三次验证 PID 稳定、active/running、媒体 ready、无残留会话、源码散列一致，且 native 状态与 epoch 未变。

- B：PID 35278 → 49713，保持 `agent_ready`，native epoch 10；备份 `/var/backups/pajio-linux-input/linux-b-20261010T043206`。
- A：PID 27424 → 50554，保持 `paused`，native epoch 36；备份 `/var/backups/pajio-linux-input/linux-a-20261010T043235`。
- 激活源码 SHA-256：`68224908ba6aee571facf46c6bb6eb48b98e86e1312ac5e1123cabfcc4ee7f8c`。

未修改 Android、Core、connector、权限、租约或客户端门槛。`linux-input-stall-proof.json` 的 `deployed=false` 是先前候选验证时的状态快照；现在的部署回执见 `linux-input-deployment.json`。真实 App/桌面重测由 root 随后进行，以上服务部署证明不代替客户端验收。


## App 修复后真实界面复验（12:34–12:37）

Root 使用 **Pajio Acceptance iPhone Air 模拟器中的实际 App** 重新接管 A Linux；这不是物理 iPhone 验收。

- 同一位置两次点击 Save note，合成页面 Saved 计数从 3 → 4 → 5；画面持续 live 到 12:36，没有重现这次同坐标输入导致的 stale。
- App 键盘面板发送合成文本 `好梦42🌙`，远程截图清晰显示 `好梦42`，本地输入已清空。表情字形很小，本记录不声称其精确字形已经视觉核验。
- 点击页面空白处后使用远程方向键 ↓，观察到页面滚动。原生 CUA wheel 没有产生可确认效果，**不把原生滚动手势记作通过**。
- 12:37 操作员完成交还的两项确认并开始等待 ACK；此段只记录发起交还，最终 ACK 与设备可用状态需后续独立收尾检查。

截图 `app-linux-fixed-save.jpg` 为合成测试页面。桌面客户端修复后重测和最终 API/native 收尾验证在本段记录时尚未完成。

App 交还补充：Root 随后实际完成两项复选 → 确认，并看到“设备已确认交还，Pajio 可以继续操作。”截图见 `app-linux-return-confirmed.jpg`。该观察证明 App 收到了交还确认；最终 A/B API/native 状态仍将在桌面复验后统一检查。


## 桌面修复后真实界面复验（12:42–12:44）

Root 使用当前 app55 / remote6 的实际桌面客户端，对已部署修复的 A Linux 复验。该段不宣称尚待部署的 v56 已经过验收。

- 同一位置两次点击 Save note，Saved 从 5 → 6 → 7，画面持续 live。
- 键盘面板发送合成文本 `桌面验收42`，远程 input 显示对应文字，本机输入随后清空。
- 真实远程滚动到 Section 2 / 3，区别于 App 段仅方向键滚动的结果。
- 截图 `desktop-linux-fixed-save.jpg` 为合成测试页面。
- 本段结束时 Root 点击“结束连接，保持暂停”，UI 显示设备保持暂停。该行为没有把设备交还 Agent；从设备列表明确交还与最终 API/native 状态检查，等待 v56 入口修复部署后另行记录。


## 桌面暂停入口修复后复验（v58）

Root 在部署 v58 后重连实际 QA 客户端，从“我的 → 设备”进入。暂停的 Linux 显示“查看并交还”，点击后远程面板仍显示“设备保持暂停”，没有未经确认自动恢复会话。随后 Root 明确选择重新接管；本段记录时看画面与双确认交还仍在进行中，最终只读状态检查尚未执行。该入口修复与本记录的 Linux `--sync` 媒体修复分别交付。


## 最终交还与独立收尾检查

Root 在桌面 v58 看画面后完成双确认交还，实际 UI 显示“设备已确认交还，Pajio 可以继续操作。”截图见 `desktop-linux-return-confirmed.jpg`。Root 随后停止远程输入，授权执行一次最终只读检查。

本次独立读取四台设备的公共 access / inventory、原生 SQLite（`mode=ro` 与 `query_only`）、媒体服务状态、systemd 状态与源码散列；没有抓取画面、发送输入、重新接管或更改状态。四台全部通过：公共与 native 均为 `agent_ready`、设备确认交还、在线且无暂停/待控制/待审查标记，媒体 ready 且没有未清理会话，服务 active / running。

| 设备 | 原生观测时间（UTC） | 公共 / 原生状态 | Native epoch | 媒体 PID |
| --- | --- | --- | --- | --- |
| a-linux | 2026-10-10T05:01:16.926344+00:00 | agent_ready / agent_ready | 42 | 50554 |
| b-linux | 2026-10-10T05:01:18.614268+00:00 | agent_ready / agent_ready | 10 | 49713 |
| a-android | 2026-10-10T05:01:20.103725+00:00 | agent_ready / agent_ready | 36 | 366 |
| b-android | 2026-10-10T05:01:21.566754+00:00 | agent_ready / agent_ready | 14 | 3343 |

A/B Linux 激活文件仍为 SHA-256 `68224908ba6aee571facf46c6bb6eb48b98e86e1312ac5e1123cabfcc4ee7f8c`，root:root / 0644；Android 仅核验现有文件和状态，未部署此 Linux 修复。脱敏完整快照见 `linux-input-final-state.json`，SHA-256 `510351eab191c55ff2140aab302e14f5261225f3f2742717b1437be4de5d6188`。

该快照证明此时的交还与可用状态，不代表长时间稳定性、物理 iPhone 验收或 App 原生滚动手势通过。没有创建定时监控。
