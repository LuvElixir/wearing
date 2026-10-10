# ZCode Web/Desktop 交付 — 真实设备远程接管（2026-10-10）

分工：ZCode 实现 Web/桌面；App/共享后端/设备/真实 A/B 验收归 Codex/root（只读参考，未改动）。不部署、不 commit/push、不改 Codex memory、不操作真实设备。基线 `4e7dad7`，并行脏工作全部保留。

## 已实现

### Web 远程接管模块（`src/wearing/web/remote-device.js` v4，window.WearingRemoteDevice）

- **状态机对齐 App**（NativeRemoteDevicePanel/remote-device-model/remote-viewer-document/remote-text-input 逐项移植）：request（带 request_id＋expected_generation）→ 等设备 ACK → transport（ice_servers 严格校验）→ offer/answer（gateway_epoch 绑定）→ 首帧 ready+frame（几何/CRC 语义）→ **用户显式「开始操作」** → 双确认交还（safe_screen＋scope）→ 等设备 ACK（agent_ready＋device_confirmed＋gateway_epoch 前进）。
- **WebRTC**：页面与服务同源，页面内 RTCPeerConnection＋`pajio-control` DataChannel（recvonly video、5s 心跳、bufferedAmount>8192 停、20 KiB 帧上限）；协商失败/连接断开/通道关闭 → viewerStop。
- **会话隔离（第一轮代码审查#3 落实）**：每个 viewer 一个本地 session 对象（pc/channel/几何/回执全部局部捕获）；模块级 `attempt` 全局单调（open 不归零）；每个异步续体校验 会话对象/代数/资源/身份快照；**API 身份冻结**（gatedApi 发出前同步核对 identityId+identityEpoch，旧异步绝不借新身份发送——A/B 读取竞态同款修复）。
- **输入**：pointer/tap/swipe/scroll/key/text 按 ready 能力白名单——**Android touch fallback 仅在 `touch===true`（keyboard 不构成触摸）、快捷键需要 keyboard 能力**；几何映射拒绝黑边；滑动时长按后端协议 50..1000ms **截取合法值**（不拒绝后重放）；输入 ACK 未确认 2.5s → 停止发送（input_unconfirmed）。
- **中文/私密输入**：password 型输入框（不回显、autocomplete=new-password）；超长/非法**保留未发草稿**（仅内存/DOM 镜像 ui.textDraft，绝不持久化/剪贴板/日志/截图），不截断不分段；重绘保留草稿与焦点；发送成功即清空；**身份切换 reset 清空 DOM 残留**。
- **停止边界**：页面隐藏（visibilitychange）/桌面 `wearing:window-hidden`/pagehide/offline/换身份/注销冻结立即停止输入与视频；不自动恢复 Agent、不自动重发输入；close 每会话仅一次、失败如实（「暂停回执尚未收到」不自动重试）。
- **入口**：云设备列表「远程接管」按钮按**显式输入方法白名单**（电脑 `computer.input`；云手机 phone.* 输入方法集合，与 App device-management.ts 同集；**files.\* 与只读观察不算**）。
- 布局：桌面大屏（1100px 面板、视频 letterbox 等比、控制区滚动、竖屏云手机 min-height 420px）；状态常显（你正在操作 · Pajio 已暂停 / 查看画面 · Pajio 已暂停 / 等待设备确认…）；RTT 显示。

### 桌面公开登录路径（Rust，`clients/desktop/src-tauri/src/endpoint.rs` + `main.rs`）

root 实测：`https://pajio.luckyloading.com/api/bootstrap` 未登录 401（正常），而 verify 要求 200 → 公开服务连不上；且 main.on_navigation 仅 service_origin 会拦掉 `https://id.pajio.luckyloading.com/realms/pajio/...` 的 OIDC 跳转。实现：

- **verify 探测**：`verify_probe(url, official_entry)`——仅严格匹配的正式服务（https＋host 精确 `pajio.luckyloading.com`＋默认端口＋无 userinfo）允许 **401=未登录引导**；200 仍需合法 bootstrap；302/重定向一律不跟随；自定义地址维持原严格 200 探测。TLS 校验始终启用（reqwest 默认证书链验证，未放宽）。
- **导航边界**：主窗口允许 bundled_origin ｜ 已连服务 origin ｜ **官方 IdP 登录**（仅当当前连接为正式服务时：`https://id.pajio.luckyloading.com` ＋ 固定 `/realms/pajio/` 前缀＋默认端口＋无 userinfo/fragment；允许 OIDC 所需查询串）。`login_navigation_allowed` 纯函数判定。**不放开任意 HTTPS/任意重定向；IdP/远程页无任何原生 IPC（native_caller 仅 bundled origin）。**
- **默认地址**：DEFAULT_SERVER 改为正式服务；本机使用仍完整支持（http+loopback 白名单不变，saved connection.json 优先）。连接页文案说明「首次连接正式服务会先打开官方登录页面，登录后自动回到 Pajio」。

## 独立复核修复记录（三批，全部行为复现→修复→回归）

1. **第一批（代码审查 5 项）**：①`data-rd-send` 局部 `const input` 遮蔽 `sendInput` 致合法文本 TypeError；②超长分支 paint 重建丢草稿——重绘保留草稿＋焦点（真 DOM innerHTML 重建语义测试）；③startViewer 全局 pc/channel/旧回调可作用新会话——本地 session 对象捕获＋单调代数＋身份冻结＋open 不归零代数；④重连中协商失败可卡 busy——viewerStop 对任何已建会话（非仅 live）都进入面板编排；⑤文本栏重绘焦点/草稿生命周期真 DOM 覆盖。
2. **第二批（验收边界）**：桌面 `wearing:window-hidden` 监听停止；`WearingDeletion.registerWorkGate({stop})`＋canInput 受注销冻结阻断；Android 输入能力按显式 phone.* 白名单（files.* 不算）；测试 setTimeout 改异常捕获型（吞异常即断言失败）。
3. **第三批（repro.test.cjs 4 场景）**：①A 设备迟到读取不得写进 B 面板（读取绑定资源快照＋readRevision 单调＋回执 resource_id 校验）；②Android touch/keyboard:false 时 tap fallback 与快捷键零发送；③慢滑 1200ms → 按协议截取 ≤1000ms（不拒绝重放）；④身份切换 reset 清空私密草稿 DOM 残留。

另修复（自测发现）：clearViewer→viewerStop→stop() 重入抬升代数导致第二次 begin 提前失效——先摘 viewer 再停会话。

## 已运行验证

- **Web 测试**：`node --test --test-timeout=15000 tests/*-ui.test.cjs tests/web-core-closure.test.cjs tests/web-import-goal.test.cjs` → **239/239**（remote-device-ui 13 项：模型/黑边/文本上限/全流程（含中文输入与坐标映射 640,360）/隐藏·离线·换身份停止＋无重放＋身份冻结 close 抑制/旧会话回调不影响新会话/协商失败释放 busy/超长草稿保留＋焦点＋成功清空/cleanup 失败单次/旋转停止/代数单调＋双击单请求/第三批 4 场景）。复核方复现脚本 4/4 通过（修复后实跑）。
- **Rust 测试**：`cargo test --locked -j 2` → **13 passed**（默认地址为正式/官方 origin 拒绝伪装域名·端口·userinfo/IdP 仅固定 realm 前缀＋拒绝错主机·端口·路径·userinfo·fragment/导航许可仅正式连接/401 引导仅正式入口·自定义严格·不跟随重定向/既有 loopback·symlink·响应上限全保留）。
- **QA 桌面包**：独立标识构建（identifier `io.luckyloading.pajio.desktop.remoteqa20261010`、数据目录预置正式服务地址）——构建结果见下节。

## 桌面包

- 构建（exit 0）：`CARGO_TARGET_DIR=/tmp/pajio-desktop-remote-qa-target npm run build -- --debug --bundles app --config`（productName "Pajio Remote QA"）→ `/tmp/pajio-desktop-remote-qa-target/debug/bundle/macos/Pajio Remote QA.app`。生产实例未动；构建并发受限（-j 2、与 App 构建不抢核）。**未启动**——真实公网 A/B 由 root 统一进行，避免同时操作。
- 连接行为：预置 connection.json＝正式服务 → 启动自动探测（401→进入登录页）；登录后 OIDC 跳转/回跳在主窗口允许范围内。

## 未验项（如实）

- **真实公网 A/B**（真实 Linux/Android 设备、TURN/DTLS/SRTP/SCTP 实流、设备确认时序、真实登录）——由 root 协调，本包冻结后进行。
- 8892 合成 QA 不含 `/api/devices/access/*` 私网路由（local_devices=True 返回 supported:false/409）——UI 对 unsupported 如实显示，未冒充。
- Tauri WKWebView 内 WebRTC 实流未验证（root A/B 覆盖）；浏览器路径已由 mock 合同＋模块测试覆盖。
- Android 慢滑同类问题在 App 侧由 Codex 修复（本侧仅 Web/桌面，未动 App）。

## 冻结点（终版，含第四批能力白名单收口）

第四批（冻结前补口）：pointer/scroll/keyboard/touch 事件 handler 与快捷键**一律 `capability === true`**（此前 pointer/scroll 为 truthy、computer keyboard 为 `!== false`——缺字段/字符串/1 均默认允许）。回归：五种非严格形态（全缺字段/undefined/字符串 "true"/"false"/1）下 pointer down·move·up·wheel·快捷键**零发送**；显式 true 恢复各路径。App 同类由 Codex 修（本侧未动）。

- Web：`remote-device.js` **v4**、`app.js` **v54**、`index.html`（面板＋脚本 v4）、`pajio.css` v21（rd-* 门控样式）。
- 桌面：`endpoint.rs`/`main.rs`/frontend 连接页文案（默认正式地址）；**Rust 无变——QA 包复用** `/tmp/pajio-desktop-remote-qa-target/debug/bundle/macos/Pajio Remote QA.app`（构建于 Rust 终版后，未重新打包）。
- 测试：**239/239**（web，新增零输入形态回归）＋13/13（rust）＋复核方 repro 4/4（v4 复跑通过）。
- 冻结 SHA-256（前 16 位，交付机实测）：
  - `src/wearing/web/remote-device.js` — `68da063781d9cf6a`
  - `src/wearing/web/app.js` — `8cc1b0943462e12e`
  - `src/wearing/web/index.html` — `d4c70219203d8ef3`
  - `clients/desktop/src-tauri/src/endpoint.rs` — `5af53dcb4d6ccc40`
  - `clients/desktop/src-tauri/src/main.rs` — `7342469affc2c2f6`


## 新冻结点（attempt 2 · P2 回归修复，2026-10-10；不改动上方 v4 冻结证据）

终复审 P2 回归：上一版把所有设备的 `data-cloud-control` 暂停/恢复按钮整体替换成了仅输入白名单设备可见的「远程接管」——observe-only、files-only、具备 `computer.input` 但无私密媒体路由的旧 connector 全部丢失暂停/恢复能力。

**修复（`app.js` v55 + `pajio.css` v22）**：恢复独立 `data-cloud-control` 暂停/恢复按钮，**所有设备渲染**（含只读/files-only/旧 connector）；远程接管按钮**并列保留**，仍按严格显式输入白名单（computer.input / phone.* 输入方法集，files.* 不算）。`control_pending` 时暂停/恢复按钮 disabled（markup 属性＋click 分支 `dataset.pending==="true"` 双保险，提示「设备正在确认上一次切换」）；暂停/恢复走原 `/api/devices/control`（expected_generation CAS、pendingDeviceControl 跟踪、用户确认时序不变——不绕过人类私密会话安全交还）。

**回归（`tests/remote-device-entry-ui.test.cjs` 5 项，实际 render 提取执行）**：observe-only/files-only/legacy-input/正常远控四类设备都有暂停/恢复入口且空闲态可用；接管按钮仅白名单设备出现（files-only/observe-only 无）；control_pending 在 markup 中禁用；click 分支含 pending 守卫与原 control 端点/generation/pending 跟踪（正反断言，非永真）。

**测试**：全套 **244/244**（+5 项入口回归）；Rust 无变复用 QA 包。

**冻结 SHA-256（前 16 位，attempt 2 实测）**：
- `src/wearing/web/app.js`（v55） — `0e65cd2a3ce653de`
- `src/wearing/web/index.html` — `ec2d9d707f17a6a5`
- `src/wearing/web/pajio.css`（v22） — `dd5c280cc115c405`
- `src/wearing/web/remote-device.js`（v4 未变） — `68da063781d9cf6a`
- Rust 无变（endpoint.rs `5af53dcb4d6ccc40` / main.rs `7342469affc2c2f6`）；QA 包复用。


## 新冻结点（attempt 3 · WK 阻断诊断修复，2026-10-10；attempt 2 证据未改动）

真实桌面验收发现：A 账号 Linux 接管→ACK→几秒后自动 stop paused，UI 只显示「设备已保持暂停。重新连接后可继续」，原因被吞（A host ready=true 且 sessions={}，失败在媒体 session 建立之前）。remote-device.js v4 的 catch 块不携带原因，pauseCopy 缺 webrtc_unavailable/playback_failed/negotiation_failed/invalid_frame/session_changed 等条目。

**修复（`remote-device.js` v5）**：

- **完整停止文案**：pauseCopy 补齐全部媒体/协议层原因——webrtc_unavailable（浏览器不支持实时画面）、playback_failed（播放被系统拒绝/自动播放许可）、negotiation_failed（画面协商未完成）、invalid_frame/invalid_channel（设备数据异常）、session_changed、slow_connection；每个都可与「到期/黑边/输入未确认」区分。
- **阶段标记**：startViewer 全程 stage 标记（webrtc_setup→offer→ice→server_answer→apply_answer），stop 时把 `[阶段+诊断]` 附在固定文案后，排查可见（如 `[server_answer · HTTP 409]`）。
- **严格诊断白名单 `diagnosticOf`**：仅接受 DOMException.name 严格枚举（NotSupportedError/NotAllowedError/AbortError/NetworkError/OperationError/InvalidStateError/SecurityError/OverconstrainedError/TimeoutError）与数字 HTTP 状态（400–599）；**任何其它字段（原始 message/SDP/ICE 详情/URL/响应 body）一律丢弃**。ICE 超时改抛 `{name:"TimeoutError"}` 以落入白名单。
- 安全门禁/期限/自动重试语义零变化（只加诊断透传，未动任何停止条件或重试策略）。

**回归**（remote-device-ui 新增「diagnosis」1 项，共 15 项）：九种错误形态白名单进出断言（含白名单外 name/非数字状态/范围外丢弃与 SECRET/sdp/evil 零泄漏）；offer HTTP 409 → 固定协商文案＋`[server_answer · HTTP 409]` 且不落入通用暂停文案；RTCPeerConnection 缺失 → webrtc_unavailable 专属文案。

**测试**：全套 **245/245**；复核方 repro 4/4（v5 复跑通过）；Rust 无变。

**冻结 SHA-256（前 16 位，attempt 3）**：
- `remote-device.js` v5 — `387aacd1d69953b0`；`index.html` — `2dfb67949d24e00b`；`app.js` v55 `0e65cd2a3ce653de`；`pajio.css` v22 `dd5c280cc115c405`
- 勘误：此节最初把 index.html 写成与 attempt 2 相同值——正确值即上方；以 attempt 4 为最终冻结。


## 最终冻结（attempt 4 · WebRTC setup 诊断补口，2026-10-10）

v5 独立复审阻断：RTCPeerConnection 构造 / addTransceiver / createDataChannel 三处异常发生在 startViewer 的 try 块之前，直接落入 attach 的 catch 以 `messageOf` 原样回显原始错误——丢失 webrtc_setup 阶段诊断且泄漏私密文本。

**修复（`remote-device.js` v6）**：上述三处纳入同一 try 块（webrtc_setup→offer→ice→server_answer→apply_answer 全阶段统一白名单 viewerStop）。ICE 超时改抛 `{name:"TimeoutError"}` 落白名单。门禁/期限/自动重试零变化。

勘误（attempt 4 实际验证范围）：本节初稿称「attach/begin/giveBack/refresh 四处 catch 的 messageOf 全部替换」——实际仅替换了 attach 的 catch（setup 复现脚本覆盖路径）；begin/refresh/giveBack 三处 catch 仍使用 `messageOf(cause)`（其输入为 API 层错误，错误信息来自 gatedApi 的 409/422 状态映射文本而非 WebRTC 原始异常）。WebRTC setup 层的原始 message 泄漏已修复并被 3 分支复现脚本验证。

**回归**：新增 1 项（reviewer 复现 3 分支：constructor NotSupportedError / transceiver InvalidStateError / channel SecurityError——均 raw_message_visible=false、fixed_stage_visible=true），并入自套共 16 项；reviewer 全量 16 项通过。全套 **246/246**。

**最终冻结 SHA-256（前 16 位，attempt 4 实测）**：
- `src/wearing/web/remote-device.js`（v6） — `9086adb692f09632`
- `src/wearing/web/app.js`（v55） — `0e65cd2a3ce653de`
- `src/wearing/web/index.html` — `cea1ce0bc89e871c`
- `src/wearing/web/pajio.css`（v22） — `dd5c280cc115c405`
- Rust 无变（QA 包复用）。root 已独立复核通过（3 setup 复现＋246/246）。

## attempt 5（index.html 字面量换行修复，2026-10-10）

真实桌面验收发现页面左上显示字面 `
`——index.html 两 script 标签间的换行是字面量 backslash-n（`</script>
<script`）而非真实换行字节。修复为真实换行。remote-device.js/app.js/pajio.css 无变。

另修正 attempt 4 节的验证范围描述（见上方勘误段）。

**index.html 新冻结 SHA-256（前 16 位）**：`053abe67abbfd242`


## attempt 6（私密暂停交还入口修复，2026-10-10）

真实桌面验收：A Linux 私密接管后 paused，设备列表「交回」按钮调 `/api/devices/control` 被 `human_session_requires_explicit_return` 拒绝。

**修复（`app.js` v56）**：新增 `resolveControlAction`（对齐 App deviceControlAction）——点击恢复前读 `/api/devices/access/{resource}`，冻结 identity/resource/generation 并核对异步续体后分派：

- `paused`/`human_private` → **进 `WearingRemoteDevice.open` 查看并明确交还，不发 `paused:false`**；
- `handoff_pending`/`return_pending` → 等待（禁用提示）；
- `agent_ready` 或 `supported:false`（只读/legacy）→ **普通恢复**（`/api/devices/control`）；不把所有设备强制远控；
- generation 不匹配 / identity 在途切换 / API 失败 → 提示检查设备状态。

列表按钮文案：私密 paused 的电脑显示「查看并交还」（control_pending 显示「等待确认」）；聊天 `computer-takeover` 入口同款处理。pending 禁用不变；不自动交还。

**回归**（remote-device-entry-ui 新增 2 项，共 7 项）：resolveControlAction 10 分支行为测试（private paused/human_private→return、handoff/return_pending→wait、agent_ready→resume、legacy supported:false→resume、generation 不匹配→check、未暂停→pause 无需读、pending→wait、**在途身份切换→check（受控 Promise 门控验证异步竞态）**、API 失败→check）；click handler 源码断言（return→远控面板、chat 入口同款、按钮文案）。

**测试**：全套 **248/248**。

**冻结 SHA-256（前 16 位，attempt 6 实测）**：
- `src/wearing/web/app.js`（v56） — `3cb4c42e3a67579f`
- `src/wearing/web/index.html` — `6ff699bc02e63cb4`
- `remote-device.js` v6 `9086adb692f09632` / `pajio.css` v22 `dd5c280cc115c405` — 未变


## attempt 7（v56→v57 阻断修复：paused 反转／supported 严格／冻结 kind，2026-10-10）

v56 root 复审发现 click handler 传 `resolveControlAction` 的 paused 参数写成 `dataset.paused!=="true"`（完全反转）；纯函数测试因参数方向一致而漏检。

**修复（`app.js` v57）**：

1. **paused 语义修正**：click handler 改传 `dataset.paused==="true"`；函数内 `if (!paused) return "pause"`（未暂停→直接暂停）、`paused===true` 才读 access。
2. **supported 严格布尔**：仅 `supported===false` 为 legacy/只读（→resume）；`supported` 缺值/字符串/数字/其它 → `check`（fail-closed）。`supported:true` 但 `control_generation` 缺失/非安全整数/不匹配 → `check`。
3. **kind/name 从冻结设备记录**：return 分支的 `kind`/`name` 改从 `state.remoteDevices.find(...)` 取（await 后不读可变 `button.dataset`）；返回前再次核对设备记录的 `control_generation` 未变。
4. **Android paused 文案统一**：「查看并交还」（与 aria-label 一致）；computer-takeover 重复三元简化。

**回归（8 项，共 318 行）**：纯函数 11 分支（paused 语义正反、private/human_private→return、legacy supported:false→resume、supported 六种非严格形态→check、generation 缺失/字符串→check、设备记录缺失→check、受控 Promise 门控身份竞态→check、受控 Promise 门控 generation 竞态→check、API 失败→check、agent_ready→resume）；**真实 handler 行为**（从 render 出的 dataset 驱动：未暂停→POST paused:true、私密 paused→零 /control POST＋打开远控面板（kind 从冻结记录取）、legacy paused→POST paused:false、pending→禁用零请求）；源码断言（paused 反转已移除、kind/name 来自 frozen 记录、文案统一无 kind 条件、aria 一致）。

**测试**：全套 **249/249**。

**冻结 SHA-256（前 16 位，attempt 7 实测）**：
- `src/wearing/web/app.js`（v57） — `76096fd72a6f4e6e`
- `src/wearing/web/index.html` — `bb61db82eedd2de8`
- `remote-device.js` v6 `9086adb692f09632` / `pajio.css` v22 `dd5c280cc115c405` — 未变
