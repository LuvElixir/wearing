"use strict";
/* Pajio 远程设备接管（Web/桌面）：真实 Linux/Android 画面、控制与中文输入。
   对齐 App NativeRemoteDevicePanel / remote-device-model / remote-viewer-document / remote-text-input
   与后端 /api/devices/access/* 状态机：
   - request → 等设备 ACK → transport/offer → 视频 ready → 用户显式开始操作 → 双确认 return → 等设备 ACK。
   - 未知状态、断网、过期、页面隐藏/关闭、换身份/退出立即停止输入与视频；不自动恢复 Agent、不自动重发输入。
   - 会话隔离：每个 viewer 持本地 session 对象（pc/channel/几何/回执全部局部捕获），
     代数 generation 全局单调（open 不归零），任何异步续体先校验 会话对象/代数/资源/身份快照。
   - API 冻结身份：所有请求发出前同步核对捕获的 identityId+identityEpoch，旧异步绝不借新身份发送。
   - 输入按 ready 能力整体预检（Linux 文本 32 码点/4096 字节，Android 4096/4096）；超长保留未发草稿
     （仅当前内存/DOM，绝不持久化/剪贴板/日志/截图），不截断、不分段、不回显私密文本。 */
(() => {
  if (document.documentElement.classList.contains("mobile-host")) return;
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  /* ---------- 模型（对齐 remote-device-model.ts / remote-text-input.ts） ---------- */
  const deviceIdentifier = v => typeof v === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(v);
  const integer = v => Number.isSafeInteger(v) && v >= 0;
  const invalid = () => {const e = new Error("设备接管信息不完整，请重新检查连接。"); e.status = 422; return e;};
  const STATES = ["agent_ready", "handoff_pending", "human_private", "return_pending", "paused"];
  function parseAccess(value, resource) {
    if (!deviceIdentifier(resource) || !value || typeof value !== "object" || typeof value.supported !== "boolean") throw invalid();
    if (!value.supported) return {resource_id: resource, supported: false, state: "unavailable", control_generation: 0, session_id: null, epoch: 0, gateway_epoch: null, device_confirmed: false, expires_at: null};
    if (value.resource_id !== resource || !STATES.includes(String(value.state)) || !integer(value.control_generation) || !integer(value.epoch)
      || value.session_id !== null && !deviceIdentifier(value.session_id) || value.gateway_epoch !== null && !integer(value.gateway_epoch)
      || typeof value.device_confirmed !== "boolean"
      || value.expires_at !== null && (typeof value.expires_at !== "number" || !Number.isFinite(value.expires_at) || value.expires_at <= 0)) throw invalid();
    if (["human_private", "handoff_pending", "return_pending"].includes(String(value.state)) && (!value.session_id || !value.epoch || !value.expires_at)) throw invalid();
    return {resource_id: resource, supported: true, state: value.state, control_generation: value.control_generation, session_id: value.session_id || null,
      epoch: value.epoch, gateway_epoch: value.gateway_epoch ?? null, device_confirmed: !!value.device_confirmed, expires_at: value.expires_at || null};
  }
  const canStream = (access, now = Date.now()) => access.supported && access.state === "human_private" && access.device_confirmed && !!access.session_id && access.epoch > 0
    && access.gateway_epoch !== null && access.expires_at !== null && access.expires_at * 1000 > now;
  const statusCopy = access => !access ? "正在检查设备" : ({unavailable: "远程接管尚未开放", agent_ready: "尚未接管", handoff_pending: "等待设备确认接管",
    human_private: "由你接管", return_pending: "等待设备确认交还", paused: "设备保持暂停"})[access.state];
  function iceServers(value) {
    if (!Array.isArray(value) || value.length > 8) throw invalid();
    return value.map(item => {
      if (!item || typeof item !== "object" || !Array.isArray(item.urls) || !item.urls.length || item.urls.length > 8
        || !item.urls.every(u => typeof u === "string" && /^(stun|stuns|turn|turns):[^\s<>]{1,500}$/.test(u))
        || item.username !== undefined && (typeof item.username !== "string" || item.username.length > 512)
        || item.credential !== undefined && (typeof item.credential !== "string" || item.credential.length > 1024)) throw invalid();
      return {urls: item.urls, ...(typeof item.username === "string" ? {username: item.username} : {}), ...(typeof item.credential === "string" ? {credential: item.credential} : {})};
    });
  }
  /** 拒绝黑边与零尺寸/无效帧——不点击别处。 */
  function pointInFrame(x, y, boxWidth, boxHeight, frameWidth, frameHeight) {
    if (![x, y, boxWidth, boxHeight, frameWidth, frameHeight].every(Number.isFinite) || [boxWidth, boxHeight, frameWidth, frameHeight].some(v => v <= 0)) return null;
    const scale = Math.min(boxWidth / frameWidth, boxHeight / frameHeight), width = frameWidth * scale, height = frameHeight * scale;
    const left = (boxWidth - width) / 2, top = (boxHeight - height) / 2;
    if (x < left || x >= left + width || y < top || y >= top + height) return null;
    return {x: Math.floor((x - left) / scale), y: Math.floor((y - top) / scale)};
  }
  const textLimits = (capabilities, kind) => {
    const caps = capabilities && typeof capabilities === "object" ? capabilities : {};
    const limit = (v, fallback) => typeof v === "number" && Number.isSafeInteger(v) && v > 0 ? Math.min(v, 4096) : fallback;
    return {chars: limit(caps.text_max_chars, kind === "android" ? 4096 : 32), bytes: limit(caps.text_max_bytes, 4096)};
  };
  /** 只返回元数据。绝不规范化、截断、分段、排队或持久化私密文本。 */
  function textIssue(text, capabilities, kind) {
    if (capabilities?.text !== "unicode") return "text_unavailable";
    const points = Array.from(text), limits = textLimits(capabilities, kind);
    if (points.some(p => {const v = p.codePointAt(0); return v >= 0xd800 && v <= 0xdfff;})) return "text_invalid";
    if (capabilities.text_disallow_controls === true && /[\u0000-\u001f\u007f]/.test(text)) return "text_invalid";
    if (points.length > limits.chars) return "text_too_long";
    if (new TextEncoder().encode(text).length > limits.bytes) return "text_too_large";
    return null;
  }
  const textNotice = (code, capabilities, kind) => code === "text_too_long" ? `这台设备一次最多输入 ${textLimits(capabilities, kind).chars} 个字符，请缩短后再试。`
    : code === "text_too_large" ? "文字超过这台设备的输入大小限制，请缩短后再试。"
    : code === "text_invalid" ? "文字含不支持的字符或换行，请修改后再试。"
    : code === "text_unavailable" ? "此设备的私密输入尚未就绪，暂时不能发送文字。"
    : null;
  const pauseCopy = {background: "你已离开接管页面，输入与画面已停止。设备保持暂停。", stale_video: "画面暂时没有更新，已停止操作。请重新连接后查看设备。",
    input_unconfirmed: "设备没有确认刚才的操作，已停止发送。请重新连接后检查实际结果。", geometry_changed: "设备画面尺寸改变，已停止操作。请重新连接。",
    expired: "本次接管已到期。设备保持暂停，可重新接管。", closed: "已结束画面连接。设备保持暂停。",
    // 媒体/协议层停止原因（区分能力不支持/播放被拒/ICE 超时/服务协商失败/通道异常/会话变更）。
    webrtc_unavailable: "这台环境的浏览器不支持实时画面（WebRTC 不可用），无法接管。可换 Chrome 或 Safari 后重试。",
    playback_failed: "画面被系统拒绝播放（可能缺少自动播放许可）。请点一下页面后重新连接。",
    negotiation_failed: "与设备的画面协商没有完成。请重新连接；若持续失败，请检查网络或稍后再试。",
    invalid_frame: "设备发来的画面数据不完整，已停止。请重新连接。",
    invalid_channel: "控制通道收到了无法识别的数据，已停止。请重新连接。",
    session_changed: "设备侧会话已变化，本次连接已结束。请重新查看设备状态。",
    slow_connection: "连接响应太慢，已停止操作。请在网络更稳的环境重试。"};
  const noticeCopy = {ascii_only: "这台云手机当前只支持英文、数字和常用符号输入，不支持中文或 %。", frame_not_ready: "正在等待新画面，本次操作未发送。"};
  const sameSession = (a, b) => a.session_id === b.session_id && a.epoch === b.epoch;
  const messageOf = error => error instanceof Error ? error.message : "这次连接没有完成，请重新检查设备。";
  // 诊断码白名单：仅 DOMException.name 严格枚举与数字 HTTP 状态；message/SDP/ICE/URL/body 一律丢弃。
  const DOM_NAMES = new Set(["NotSupportedError", "NotAllowedError", "AbortError", "NetworkError", "OperationError", "InvalidStateError", "SecurityError", "OverconstrainedError", "TimeoutError"]);
  function diagnosticOf(error) {
    const parts = [];
    if (error && typeof error === "object") {
      if (typeof error.name === "string" && DOM_NAMES.has(error.name)) parts.push(error.name);
      if (Number.isInteger(error.status) && error.status >= 400 && error.status <= 599) parts.push("HTTP " + error.status);
    }
    return parts.length ? ` · ${parts.join(" · ")}` : "";
  }
  const deletionBlocked = () => window.WearingDeletion?.workAllowed?.() === false;

  /* ---------- 面板状态 ---------- */
  const ui = {open: false, resource: "", name: "", kind: "computer", access: null, viewer: null, busy: false, live: false, controlling: false,
    isReturning: false, error: "", notice: "", rtt: null, capabilities: {}, keyboard: false, confirmReturn: false, safeScreen: false, scopeConfirmed: false,
    textDraft: null};
  let epoch = -1, identityId = "", readRevision = 0, desired = false, returning = false, opening = false, mutating = false, polling = false;
  let deadline = 0, alive = false, foreground = true, pollTimer = 0;
  let closingKeys = new Set();
  // 代数全局单调：open 不归零，旧异步续体靠不回退的代数失配。
  let attempt = 0;
  const active = () => alive && state.identityEpoch === epoch && state.identityId === identityId;
  /** 身份快照冻结：任何请求发出前同步核对，旧异步绝不借新身份发送。 */
  const identityFrozen = () => state.identityEpoch === epoch && state.identityId === identityId;
  function gatedApi(path, options) {
    if (!identityFrozen()) {const e = new Error("账户或页面已切换，请重新打开设备。"); e.status = 409; return Promise.reject(e);}
    return api(path, options);
  }

  /* ---------- 视频会话：全部状态局部捕获在 session 对象 ---------- */
  function makeSession(viewerAccess, transport, generation) {
    return {access: viewerAccess, transport, generation, resource: ui.resource, identityEpoch: epoch, identityId,
      pc: null, channel: null, stopped: false, frozen: false, ready: false, shown: false,
      geometry: null, geometryAt: 0, lastVideoAt: 0, seq: 0, gesture: null, latestMove: 0,
      heartbeat: 0, watch: 0, stats: 0, pendingAcks: new Map(), capabilities: {}};
  }
  const currentSession = () => ui.viewer && ui.viewer.session && !ui.viewer.session.stopped ? ui.viewer.session : null;
  const sessionValid = session => session === currentSession() && session.generation === attempt && session.identityEpoch === state.identityEpoch && session.identityId === state.identityId;
  function channelSendRaw(session, value) {
    if (session.stopped || !session.channel || session.channel.readyState !== "open") return false;
    if (session.channel.bufferedAmount > 8192) {viewerStop(session, "slow_connection"); return false;}
    const text = JSON.stringify(value);
    if (new TextEncoder().encode(text).length > 20480) return false;
    try {session.channel.send(text); return true;} catch {viewerStop(session, "connection_lost"); return false;}
  }
  function canInput() {
    if (deletionBlocked()) return false; // 账户注销/冻结期间禁止一切远程输入
    const session = currentSession(); if (!session) return false;
    const video = $("rd-video");
    return ui.controlling && !session.stopped && !session.frozen && session.ready && session.shown && session.channel && session.channel.readyState === "open" && session.geometry
      && Date.now() - session.geometryAt < 1800 && Date.now() - session.lastVideoAt < 2500 && video && video.videoWidth === session.geometry.width && video.videoHeight === session.geometry.height;
  }
  function sendInput(action, values) {
    const session = currentSession(); if (!session) return;
    if (!canInput()) {setNotice("frame_not_ready", true); return;}
    const n = ++session.seq;
    if (channelSendRaw(session, {type: "input", session_id: session.access.session_id, epoch: session.access.epoch, gateway_epoch: session.access.gateway_epoch,
      seq: n, frame_id: session.geometry.frame_id, action, ...values})) session.pendingAcks.set(n, Date.now());
  }
  function viewerStop(session, reason, stage = "", diagnostic = "") {
    if (!session || session.stopped) return;
    session.stopped = true; session.frozen = true; session.gesture = null;
    if (reason !== "closed" && stage) session.stopDiagnostic = {reason, stage: `[${stage}${diagnostic}]`};
    clearInterval(session.heartbeat); clearInterval(session.watch); clearInterval(session.stats); session.pendingAcks.clear();
    try {session.channel && session.channel.close();} catch {}
    try {session.pc && session.pc.close();} catch {}
    const video = $("rd-video");
    if (video) {try {video.pause(); video.srcObject = null;} catch {}}
    // 任何曾建立的会话停止都要走面板编排（含协商中失败），不能只在 live 时。
    if (ui.viewer && ui.viewer.session === session && !returning) stop(reason);
  }
  function frameTick(session) {
    if (session.stopped || !sessionValid(session)) return;
    const video = $("rd-video");
    session.lastVideoAt = Date.now();
    if (session.ready && session.geometry && video && video.videoWidth === session.geometry.width && video.videoHeight === session.geometry.height) {
      if (!session.shown) {session.shown = true; onLive();}
    } else session.shown = false;
    paintCover();
    if (video && video.requestVideoFrameCallback) video.requestVideoFrameCallback(() => frameTick(session));
  }
  function locate(session, event) {
    if (!session.geometry) return null;
    const video = $("rd-video"), box = video.getBoundingClientRect();
    return pointInFrame(event.clientX - box.left, event.clientY - box.top, box.width, box.height, session.geometry.width, session.geometry.height);
  }
  async function startViewer(viewer) {
    const session = viewer.session;
    if (typeof RTCPeerConnection === "undefined") {viewerStop(session, "webrtc_unavailable", "webrtc_setup", ""); return;}
    let stage = "webrtc_setup";
    try {
    session.pc = new RTCPeerConnection({iceServers: session.transport.ice_servers, bundlePolicy: "max-bundle"});
    session.pc.addTransceiver("video", {direction: "recvonly"});
    session.pc.ontrack = event => {
      if (!sessionValid(session)) return;
      const video = $("rd-video");
      video.srcObject = event.streams[0] || new MediaStream([event.track]);
      video.play().catch(cause => viewerStop(session, "playback_failed", "play", diagnosticOf(cause)));
    };
    const video = $("rd-video");
    video.addEventListener("loadeddata", () => {if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(() => frameTick(session)); else frameTick(session);}, {once: true});
    video.addEventListener("timeupdate", () => {if (!video.requestVideoFrameCallback) frameTick(session);});
    session.pc.onconnectionstatechange = () => {if (["failed", "disconnected", "closed"].includes(session.pc.connectionState)) viewerStop(session, "connection_lost");};
    session.channel = session.pc.createDataChannel("pajio-control", {ordered: true});
    session.channel.onclose = () => viewerStop(session, "connection_lost");
    session.channel.onerror = () => viewerStop(session, "connection_lost");
    session.channel.onopen = () => {
      if (!sessionValid(session)) return;
      channelSendRaw(session, {type: "heartbeat", session_id: session.access.session_id, epoch: session.access.epoch, gateway_epoch: session.access.gateway_epoch});
      session.heartbeat = setInterval(() => {if (sessionValid(session)) channelSendRaw(session, {type: "heartbeat", session_id: session.access.session_id, epoch: session.access.epoch, gateway_epoch: session.access.gateway_epoch});}, 5000);
    };
    session.channel.onmessage = event => {
      if (session.stopped || !sessionValid(session) || typeof event.data !== "string" || event.data.length > 20480) return;
      let m; try {m = JSON.parse(event.data);} catch {viewerStop(session, "invalid_channel"); return;}
      const scope = {session_id: session.access.session_id, epoch: session.access.epoch, gateway_epoch: session.access.gateway_epoch};
      if (m.type === "ready") {
        if (m.session_id !== scope.session_id || m.epoch !== scope.epoch || m.gateway_epoch !== scope.gateway_epoch) {viewerStop(session, "session_changed"); return;}
        session.ready = true; session.capabilities = m.capabilities || {}; ui.capabilities = session.capabilities;
      } else if (m.type === "frame") {
        if (m.gateway_epoch !== scope.gateway_epoch || typeof m.frame_id !== "string" || m.frame_id.length > 128
          || !Number.isInteger(m.width) || !Number.isInteger(m.height) || m.width < 1 || m.height < 1 || m.width > 8192 || m.height > 8192) {viewerStop(session, "invalid_frame"); return;}
        if (m.geometry_revision !== undefined && (!Number.isSafeInteger(m.geometry_revision) || m.geometry_revision < 0)) {viewerStop(session, "invalid_frame"); return;}
        if (session.geometry && (session.geometry.width !== m.width || session.geometry.height !== m.height || session.geometry.geometry_revision !== m.geometry_revision)) {viewerStop(session, "geometry_changed"); return;}
        session.geometry = m; session.geometryAt = Date.now();
      } else if (m.type === "input_ack") session.pendingAcks.delete(m.seq);
      else if (m.type === "error") {if (m.seq) session.pendingAcks.delete(m.seq); setNotice(typeof m.code === "string" ? m.code : "input_rejected", true); if (!m.seq) viewerStop(session, "session_changed");}
    };
    session.watch = setInterval(() => {
      if (session.stopped || !sessionValid(session)) return;
      if (Date.now() > session.access.expires_at * 1000) {viewerStop(session, "expired"); return;}
      if (session.shown && (Date.now() - session.geometryAt > 2500 || Date.now() - session.lastVideoAt > 3000)) {viewerStop(session, "stale_video"); return;}
      for (const at of session.pendingAcks.values()) if (Date.now() - at > 2500) {viewerStop(session, "input_unconfirmed"); return;}
    }, 300);
    session.stats = setInterval(async () => {
      try {
        if (session.stopped || !sessionValid(session) || !session.pc) return;
        const values = await session.pc.getStats(); let rtt = null;
        values.forEach(v => {if (v.type === "candidate-pair" && v.state === "succeeded" && v.nominated && typeof v.currentRoundTripTime === "number") rtt = Math.round(v.currentRoundTripTime * 1000);});
        if (rtt !== null && active()) {ui.rtt = rtt; paintHeader();}
      } catch {}
    }, 3000);
      stage = "offer";
      const offer = await session.pc.createOffer();
      if (!sessionValid(session)) return;
      await session.pc.setLocalDescription(offer);
      if (!sessionValid(session)) return;
      stage = "ice";
      await new Promise((resolve, reject) => {
        if (session.pc.iceGatheringState === "complete") {resolve(); return;}
        const timer = setTimeout(() => reject(Object.assign(new Error(), {name: "TimeoutError"})), 12000);
        session.pc.addEventListener("icegatheringstatechange", () => {if (session.pc.iceGatheringState === "complete") {clearTimeout(timer); resolve();}});
      });
      if (!sessionValid(session)) return;
      ui.notice = "正在与设备协商画面…"; paint();
      stage = "server_answer";
      const answer = await gatedApi(path(session.access.resource_id, "/offer"), {method: "POST", body: JSON.stringify({session_id: session.access.session_id, epoch: session.access.epoch, type: "offer", sdp: session.pc.localDescription.sdp})});
      if (!sessionValid(session)) return;
      if (answer?.type !== "answer" || typeof answer.sdp !== "string" || !answer.sdp.startsWith("v=0") || answer.sdp.length > 65536 || answer.gateway_epoch !== session.access.gateway_epoch) {viewerStop(session, "session_changed", "server_answer", ""); return;}
      stage = "apply_answer";
      await session.pc.setRemoteDescription({type: "answer", sdp: answer.sdp});
    } catch (cause) {
      if (!session.stopped && sessionValid(session)) viewerStop(session, "negotiation_failed", stage, diagnosticOf(cause));
    } finally {stage = "";}
  }

  /* ---------- API ---------- */
  const path = (resource, suffix = "") => `/api/devices/access/${encodeURIComponent(resource)}${suffix}`;
  async function getStatus(resource) {return parseAccess(await gatedApi(path(resource)), resource);}
  async function postClose(access) {
    return parseAccess(await gatedApi(path(access.resource_id, "/close"), {method: "POST", body: JSON.stringify({session_id: access.session_id, epoch: access.epoch})}), access.resource_id);
  }
  async function postBegin(access, requestId) {
    return parseAccess(await gatedApi(path(access.resource_id, "/request"), {method: "POST", body: JSON.stringify({expected_generation: access.control_generation, request_id: requestId})}), access.resource_id);
  }
  async function postTransport(access) {
    const value = await gatedApi(path(access.resource_id, "/transport"));
    if (!value || value.kind !== "webrtc" || value.session_id !== access.session_id || value.epoch !== access.epoch || value.gateway_epoch !== access.gateway_epoch) throw invalid();
    return {kind: "webrtc", session_id: access.session_id, epoch: access.epoch, gateway_epoch: access.gateway_epoch, ice_servers: iceServers(value.ice_servers)};
  }
  async function postGiveBack(access) {
    return parseAccess(await gatedApi(path(access.resource_id, "/return"), {method: "POST", body: JSON.stringify({session_id: access.session_id, epoch: access.epoch, safe_screen_confirmed: true, scope_confirmed: true})}), access.resource_id);
  }

  /* ---------- 会话编排 ---------- */
  function update(next) {ui.access = next; if (active()) paintHeader();}
  function clearViewer() {
    // 先摘除 viewer 再停会话：避免 viewerStop 的面板级编排重入 stop() 抬升代数。
    const viewer = ui.viewer; ui.viewer = null; opening = false;
    if (viewer?.session) viewerStop(viewer.session, "closed");
    ui.live = false; ui.controlling = false; ui.isReturning = false; ui.keyboard = false; ui.rtt = null;
    ui.capabilities = {}; ui.confirmReturn = false; ui.safeScreen = false; ui.scopeConfirmed = false; ui.textDraft = null;
  }
  function stop(reason, close = true) {
    const previous = ui.access, generation = ++attempt;
    // 诊断可见性：媒体层停止原因必须有用户能懂的固定文案；阶段+白名单诊断码附在文案后。
    const diag = ui.viewer?.session?.stopDiagnostic;
    const reasonCopy = pauseCopy[reason] ? pauseCopy[reason] + (diag && diag.reason === reason ? `　${diag.stage}` : "") : "";
    readRevision++; desired = false; returning = false; deadline = 0;
    clearViewer();
    ui.busy = false;
    if (active()) ui.notice = reasonCopy || (previous?.session_id && previous.state !== "agent_ready" ? "画面和输入已停止，正在确认设备暂停。" : "画面连接已结束。");
    paint();
    if (close && previous?.session_id && previous.state !== "agent_ready" && identityFrozen()) {
      const key = `${previous.session_id}:${previous.epoch}`;
      if (!closingKeys.has(key)) {
        closingKeys.add(key);
        postClose(previous).then(next => {
          if (identityFrozen() && generation === attempt) {update(next); ui.notice = reasonCopy || pauseCopy[reason] || "设备已保持暂停。重新连接后可继续。"; paint();}
        }).catch(() => {
          if (identityFrozen() && generation === attempt) {ui.notice = "画面和输入已停止。"; ui.error = "暂停回执尚未收到，请刷新设备状态；不会自动重新发送操作。"; paint();}
        }).finally(() => closingKeys.delete(key));
      }
    }
  }
  async function attach(next) {
    if (!desired || !canStream(next) || opening || ui.viewer || !foreground || !active()) return;
    const generation = attempt; opening = true;
    try {
      const transport = await postTransport(next);
      if (!active() || !foreground || generation !== attempt || !desired) return;
      const session = makeSession(next, transport, generation);
      ui.viewer = {access: next, transport, attempt: generation, session};
      await startViewer(ui.viewer);
    } catch (cause) {
      if (active() && generation === attempt) {
        stop("connection_lost");
        // 绝不回显原始 message：固定文案＋白名单诊断（DOMException.name / HTTP 状态）。
        ui.error = "连接设备没有完成。" + diagnosticOf(cause);
        paint();
      }
    } finally {if (generation === attempt) opening = false;}
  }
  async function refresh() {
    if (!active() || !foreground || polling || mutating) return;
    polling = true; const revision = ++readRevision;
    // 读取绑定打开时的资源快照：迟到的 A 读结果不得写进 B 面板。
    const resource = ui.resource;
    try {
      const next = await getStatus(resource);
      if (!active() || !foreground || revision !== readRevision || ui.resource !== resource) return;
      if (next.supported && next.resource_id !== resource) return; // 回执资源不匹配即丢弃
      const previous = ui.access;
      if ((desired || returning) && previous?.session_id && !sameSession(previous, next)) {stop("session_changed"); update(next); return;}
      update(next);
      if (returning) {
        if (next.state === "agent_ready" && next.device_confirmed && previous && sameSession(previous, next) && next.gateway_epoch !== null && next.gateway_epoch > (ui.viewer?.access.gateway_epoch ?? -1)) {
          returning = false; desired = false; deadline = 0; attempt++;
          clearViewer(); ui.busy = false; ui.notice = "设备已确认交还，Pajio 可以继续操作。"; paint();
        } else if (next.state === "paused") stop("session_changed");
        return;
      }
      if (!desired) return;
      if (!["handoff_pending", "human_private"].includes(next.state)) {stop("session_changed"); return;}
      if (ui.viewer && (!canStream(next) || next.gateway_epoch !== ui.viewer.access.gateway_epoch)) {stop("expired"); return;}
      if (canStream(next)) void attach(next);
    } catch (cause) {
      if (active() && revision === readRevision) {
        if (desired || returning) stop("connection_lost");
        ui.error = messageOf(cause); paint();
      }
    } finally {polling = false;}
  }
  async function begin() {
    if (mutating || !foreground || !deviceIdentifier(ui.resource) || deletionBlocked() || !active()) return;
    mutating = true; const generation = ++attempt; readRevision++;
    desired = false; returning = false; clearViewer();
    ui.busy = true; ui.error = ""; ui.notice = "正在请求设备暂停 Pajio 的操作…"; paint();
    try {
      let previous = await getStatus(ui.resource);
      if (!active() || !foreground || generation !== attempt) return;
      if (!previous.supported) {update(previous); ui.notice = "此设备尚未开放远程接管。"; ui.busy = false; paint(); return;}
      if (previous.session_id && !["agent_ready", "paused"].includes(previous.state)) {
        previous = await postClose(previous);
        if (!active() || !foreground || generation !== attempt) return;
      }
      const requestId = window.WearingIds.uuid().replaceAll("-", "");
      if (!/^[a-f0-9]{32}$/.test(requestId)) throw invalid();
      const next = await postBegin(previous, requestId);
      if (!active() || !foreground || generation !== attempt) {if (next.session_id && identityFrozen()) void postClose(next).catch(() => {}); return;}
      update(next); desired = true; deadline = Date.now() + 35000;
      ui.notice = "等待设备确认，确认后才会连接画面。"; paint();
      if (canStream(next)) void attach(next);
    } catch (cause) {if (active() && generation === attempt) {stop("connection_lost"); ui.error = messageOf(cause); paint();}}
    finally {mutating = false;}
  }
  async function giveBack() {
    const previous = ui.access;
    if (!previous || !canStream(previous) || !ui.safeScreen || !ui.scopeConfirmed || mutating || !active()) return;
    const generation = attempt; mutating = true; returning = true; desired = false; readRevision++;
    const session = ui.viewer?.session;
    if (session) {session.frozen = true; session.gesture = null;}
    ui.live = false; ui.controlling = false; ui.isReturning = true; ui.keyboard = false; ui.textDraft = null; ui.confirmReturn = false; ui.busy = true;
    deadline = Date.now() + 30000; ui.notice = "等待设备确认交还…"; paint();
    try {
      const next = await postGiveBack(previous);
      if (active() && generation === attempt) update(next);
    } catch (cause) {if (active() && generation === attempt) {stop("connection_lost"); ui.error = messageOf(cause); paint();}}
    finally {mutating = false;}
  }
  function onLive() {
    deadline = 0; ui.live = true; ui.busy = false;
    ui.notice = "画面已连接。点「开始操作」后，可直接触控设备。";
    paint();
  }
  function setNotice(code, isError) {
    if (!active()) return;
    const text = textNotice(code, ui.capabilities, ui.kind) || noticeCopy[code] || "设备拒绝了这次操作，操作不会自动重试。请检查画面后再操作。";
    if (isError) ui.error = text; else ui.notice = text;
    paintPreservingDraft();
  }

  /* ---------- 渲染（重绘保留文本草稿与焦点） ---------- */
  function paintPreservingDraft() {
    const field = $("rd-text");
    const draft = field ? field.value : ui.textDraft;
    const hadFocus = field && document.activeElement === field;
    const selection = field ? {start: field.selectionStart, end: field.selectionEnd} : null;
    if (draft !== null && draft !== undefined) ui.textDraft = String(draft);
    paint();
    const next = $("rd-text");
    if (next) {
      if (ui.textDraft !== null) next.value = ui.textDraft;
      if (hadFocus) {next.focus(); try {next.setSelectionRange(selection?.start ?? next.value.length, selection?.end ?? next.value.length);} catch {}}
    }
  }
  function paintHeader() {
    if (!ui.open) return;
    $("rd-title").textContent = ui.name || (ui.kind === "android" ? "云手机" : "云电脑");
    const connected = ui.live && !!ui.viewer && !ui.isReturning;
    $("rd-status").textContent = connected ? (ui.controlling ? "你正在操作 · Pajio 已暂停" : "查看画面 · Pajio 已暂停") : statusCopy(ui.access);
    $("rd-rtt").textContent = ui.rtt !== null && connected ? `${ui.rtt} ms` : "";
  }
  function paintCover() {
    const cover = $("rd-cover"); if (!cover) return;
    cover.hidden = ui.live && !!ui.viewer && !ui.isReturning;
  }
  function paint() {
    if (!ui.open) return;
    paintHeader(); paintCover();
    const caps = ui.capabilities;
    const connected = ui.live && !!ui.viewer && !ui.isReturning;
    const keys = ui.kind === "android"
      ? [["Back", "返回"], ["Home", "主页"], ["Recents", "最近任务"]]
      : [["Tab", "Tab"], ["Escape", "Esc"], ["ArrowUp", "↑"], ["ArrowDown", "↓"], ["ArrowLeft", "←"], ["ArrowRight", "→"]];
    $("rd-body").innerHTML = `
      ${ui.error ? `<p class="rd-error" role="alert">${esc(ui.error)}</p>` : ""}
      ${ui.notice ? `<p class="rd-caption">${esc(ui.notice)}</p>` : ""}
      ${connected ? `
        <div class="rd-row">
          <button class="primary" type="button" data-rd-control>${ui.controlling ? "停止操作" : "开始操作"}</button>
          <button class="secondary" type="button" data-rd-keyboard ${!ui.controlling || caps.keyboard !== true || caps.text !== "unicode" ? "disabled" : ""}>键盘</button>
          <button class="text-button" type="button" data-rd-return>交还 Pajio</button>
        </div>
        ${ui.controlling ? `<div class="rd-keys">${keys.map(([key, label]) => `<button type="button" class="rd-key" data-rd-key="${key}">${label}</button>`).join("")}</div>` : ""}
        ${ui.controlling && caps.text !== "unicode" ? `<p class="rd-caption">此设备的私密输入尚未就绪，暂时不能发送文字。</p>` : ""}
        ${ui.keyboard && ui.controlling && caps.text === "unicode" ? `
          <p class="rd-caption">每次最多 ${textLimits(caps, ui.kind).chars} 个字符。发送到远程当前输入框，发送后立即清空；不会在本机保存。</p>
          <div class="rd-row">
            <input id="rd-text" type="password" autocomplete="new-password" autocapitalize="off" spellcheck="false" aria-label="发送到远程输入框的文字" placeholder="输入要发送的文字">
            <button class="primary" type="button" data-rd-send>输入</button>
          </div>
          <div class="rd-keys">
            <button type="button" class="rd-key" data-rd-key="Backspace">删除</button>
            <button type="button" class="rd-key" data-rd-key="Enter">回车</button>
          </div>` : ""}
        ${ui.confirmReturn ? `<div class="rd-confirm">
          <p class="rd-strong">确认交还</p>
          <p class="rd-caption">设备确认后，Pajio 会恢复读取与操作。</p>
          <label class="rd-check"><input type="checkbox" data-rd-safe ${ui.safeScreen ? "checked" : ""}>已离开密码、验证码等私密页面</label>
          <label class="rd-check"><input type="checkbox" data-rd-scope ${ui.scopeConfirmed ? "checked" : ""}>允许 Pajio 继续操作这台设备</label>
          <div class="rd-row">
            <button class="primary" type="button" data-rd-return-confirm ${ui.safeScreen && ui.scopeConfirmed ? "" : "disabled"}>确认交还</button>
            <button class="text-button" type="button" data-rd-return-cancel>继续接管</button>
          </div>
        </div>` : ""}
        <button class="text-button" type="button" data-rd-stop>结束连接，保持暂停</button>`
      : `<button class="primary" type="button" data-rd-begin ${ui.busy ? "disabled" : ""}>${ui.busy ? (ui.isReturning ? "结束画面并检查状态" : "正在请求设备…") : ui.access?.state === "paused" ? "重新接管" : "接管设备"}</button>
        <button class="text-button" type="button" data-rd-stop>取消连接，保持暂停</button>
        <button class="text-button" type="button" data-rd-refresh>刷新设备状态</button>`}`;
  }

  /* ---------- 事件 ---------- */
  const panel = document.getElementById("remote-device-panel");
  function bindVideoEvents(video) {
    video.addEventListener("pointerdown", event => {
      const session = currentSession(); if (!session) return;
      event.preventDefault(); if (!canInput()) return;
      if (session.gesture) {viewerStop(session, "gesture_interrupted"); return;}
      const p = locate(session, event); if (!p) return;
      try {video.setPointerCapture(event.pointerId);} catch {}
      session.gesture = {id: event.pointerId, start: p, last: p, at: Date.now(), width: session.geometry.width, height: session.geometry.height, button: event.button === 2 ? 2 : 0};
      if (session.capabilities.pointer === true) sendInput("pointer", {phase: "down", x: p.x, y: p.y, button: session.gesture.button});
    });
    video.addEventListener("pointermove", event => {
      const session = currentSession(); if (!session || session.gesture?.id !== event.pointerId) return;
      event.preventDefault();
      const p = locate(session, event);
      if (!p || !canInput() || session.geometry.width !== session.gesture.width || session.geometry.height !== session.gesture.height) {viewerStop(session, "geometry_changed"); return;}
      session.gesture.last = p;
      if (session.capabilities.pointer === true && Date.now() - session.latestMove >= 30) {session.latestMove = Date.now(); sendInput("pointer", {phase: "move", x: p.x, y: p.y, button: session.gesture.button});}
    });
    video.addEventListener("pointerup", event => {
      const session = currentSession(); if (!session || session.gesture?.id !== event.pointerId) return;
      event.preventDefault(); const g = session.gesture; session.gesture = null;
      if (!canInput() || session.geometry.width !== g.width || session.geometry.height !== g.height) {viewerStop(session, "geometry_changed"); return;}
      const p = locate(session, event) || g.last;
      if (session.capabilities.pointer === true) {sendInput("pointer", {phase: "up", x: p.x, y: p.y, button: g.button}); return;}
      // 无 pointer 能力时的触摸 fallback 必须严格按 touch 白名单；keyboard 不构成触摸。
      if (session.capabilities.touch !== true) return;
      const distance = Math.hypot(p.x - g.start.x, p.y - g.start.y);
      // 后端 parse_input 只接受 50..1000ms：按协议截取合法时长，不先拒绝再重放。
      const duration = Math.max(50, Math.min(1000, Date.now() - g.at));
      if (distance < 12 && duration < 500) sendInput("tap", p);
      else sendInput("swipe", {x: g.start.x, y: g.start.y, to_x: p.x, to_y: p.y, duration_ms: duration});
    });
    video.addEventListener("pointercancel", () => {const session = currentSession(); if (session?.gesture) viewerStop(session, "gesture_interrupted");});
    video.addEventListener("contextmenu", event => event.preventDefault());
    video.addEventListener("wheel", event => {
      const session = currentSession(); if (!session) return;
      event.preventDefault();
      if (session.capabilities.scroll === true) sendInput("scroll", {delta_x: Math.max(-1000, Math.min(1000, Math.round(event.deltaX))), delta_y: Math.max(-1000, Math.min(1000, Math.round(event.deltaY)))});
    }, {passive: false});
  }
  panel.addEventListener("input", event => {
    if (event.target?.id === "rd-text") ui.textDraft = event.target.value; // 仅内存镜像，绝不持久化
  });
  panel.addEventListener("click", event => {
    if (event.target.closest("[data-rd-close]") || event.target.closest("[data-rd-close-btn]")) {stop("closed"); closePanel("remote-device-panel"); ui.open = false; return;}
    if (event.target.closest("[data-rd-begin]")) {begin(); return;}
    if (event.target.closest("[data-rd-refresh]")) {ui.error = ""; paint(); void refresh(); return;}
    if (event.target.closest("[data-rd-stop]")) {stop("closed"); return;}
    const control = event.target.closest("[data-rd-control]");
    if (control) {
      const session = currentSession();
      if (session?.gesture) {viewerStop(session, "gesture_interrupted"); return;}
      ui.controlling = !ui.controlling;
      if (!ui.controlling) {ui.keyboard = false; ui.textDraft = null; const field = $("rd-text"); if (field) field.value = "";}
      ui.notice = ui.controlling ? "你可以直接触控设备。结束后明确交还，Pajio 才会继续。" : "当前只查看画面。点「开始操作」后，可直接触控设备。";
      ui.error = "";
      paint(); return;
    }
    if (event.target.closest("[data-rd-keyboard]")) {ui.keyboard = !ui.keyboard; paint(); const field = $("rd-text"); if (field && ui.keyboard) field.focus(); return;}
    if (event.target.closest("[data-rd-return]")) {ui.confirmReturn = true; ui.safeScreen = false; ui.scopeConfirmed = false; paint(); return;}
    if (event.target.closest("[data-rd-return-cancel]")) {ui.confirmReturn = false; paint(); return;}
    const safe = event.target.closest("[data-rd-safe]"); if (safe) {ui.safeScreen = safe.checked; paint(); return;}
    const scope = event.target.closest("[data-rd-scope]"); if (scope) {ui.scopeConfirmed = scope.checked; paint(); return;}
    if (event.target.closest("[data-rd-return-confirm]")) {giveBack(); return;}
    const key = event.target.closest("[data-rd-key]");
    if (key) {
      // 快捷键需要键盘能力：所有设备一律显式 keyboard===true（缺字段/字符串均不算）。
      if (currentSession()?.capabilities?.keyboard === true) {
        sendInput("key", {key: key.dataset.rdKey, phase: "down"}); sendInput("key", {key: key.dataset.rdKey, phase: "up"});
      }
      return;
    }
    if (event.target.closest("[data-rd-send]")) {
      const field = $("rd-text");
      if (!field || !canInput() || ui.capabilities.keyboard !== true || !field.value) return;
      const issue = textIssue(field.value, ui.capabilities, ui.kind);
      if (issue) {ui.error = textNotice(issue, ui.capabilities, ui.kind) || ""; paintPreservingDraft(); return;} // 超长保留草稿，不截断不分段
      const draft = field.value;
      field.value = ""; ui.textDraft = null; ui.error = "";
      sendInput("text", {text: draft});
      paint(); return;
    }
  });
  panel.addEventListener("submit", event => {
    event.preventDefault();
    const field = $("rd-text");
    if (field && field.value) panel.querySelector("[data-rd-send]")?.dispatchEvent(new MouseEvent("click", {bubbles: true}));
  });
  panel.addEventListener("close", () => {if (ui.open) {stop("closed"); ui.open = false;}});

  /* ---------- 打开/生命周期 ---------- */
  function open(resource, name, kind) {
    if (!deviceIdentifier(resource)) return;
    stop("closed", false);
    ui.open = true; ui.resource = resource; ui.name = String(name || "").slice(0, 100); ui.kind = kind === "android" ? "android" : "computer";
    ui.access = null; ui.viewer = null; ui.busy = false; ui.live = false; ui.controlling = false; ui.isReturning = false;
    ui.error = ""; ui.notice = ""; ui.rtt = null; ui.capabilities = {}; ui.keyboard = false; ui.confirmReturn = false; ui.safeScreen = false; ui.scopeConfirmed = false; ui.textDraft = null;
    // attempt 不归零（全局单调），只重置本面板的编排标志。
    epoch = state.identityEpoch; identityId = state.identityId;
    readRevision++; // 单调递增：旧面板的在途读取全部失效
    desired = false; returning = false; opening = false; mutating = false; polling = false;
    deadline = 0; alive = true; foreground = !document.hidden; closingKeys = new Set();
    openPanel("remote-device-panel");
    paint();
    const video = $("rd-video");
    if (video && !video.dataset.bound) {video.dataset.bound = "1"; bindVideoEvents(video);}
    setTimeout(() => {void refresh();}, 0);
    clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      if (!ui.open || !foreground || !active()) return;
      if (deadline && Date.now() > deadline) {stop("connection_lost"); ui.error = "设备尚未确认这次连接，请重新检查后再试。"; paint();}
      else void refresh();
    }, 1500);
  }
  function close() {stop("closed"); ui.open = false; closePanel("remote-device-panel");}
  function reset() {
    alive = false; ui.open = false; attempt++; readRevision++;
    clearInterval(pollTimer);
    if (ui.viewer?.session) viewerStop(ui.viewer.session, "closed");
    else clearViewer();
    ui.viewer = null; ui.access = null; ui.busy = false; ui.live = false; ui.controlling = false; ui.error = ""; ui.notice = ""; ui.textDraft = null;
    const field = $("rd-text"); if (field) field.value = ""; // 身份切换清空私密草稿 DOM 残留
    try {$("remote-device-panel").close();} catch {}
  }
  document.addEventListener("visibilitychange", () => {
    foreground = !document.hidden;
    if (!foreground && ui.open) stop("background");
    else if (foreground && ui.open) void refresh();
  });
  window.addEventListener("pagehide", () => {if (ui.open) stop("background");});
  window.addEventListener("offline", () => {if (ui.open) stop("connection_lost");});
  // 桌面壳窗口隐藏（既有事件）→ 立即停止画面与输入。
  document.addEventListener("wearing:window-hidden", () => {if (ui.open) stop("background");});
  // 注销冻结：作废会话围栏并停止接管。
  window.WearingDeletion?.registerWorkGate?.({stop() {attempt++; if (ui.open) stop("closed");}});
  document.addEventListener("click", event => {
    const entry = event.target.closest("[data-rd-open]");
    if (!entry) return;
    const settings = $("settings-panel"); if (settings?.open) closePanel("settings-panel");
    open(entry.dataset.rdResource, entry.dataset.rdName, entry.dataset.rdKind);
  });

  window.WearingRemoteDevice = {open, close, reset,
    _test: {ui, parseAccess, canStream, pointInFrame, textIssue, textLimits, textNotice, iceServers, statusCopy,
      begin, stop, refresh, giveBack, attach, setNotice, viewerStop, startViewer, makeSession, sendInput, canInput, channelSendRaw, paint, paintPreservingDraft, diagnosticOf,
      getState: () => ({desired, returning, mutating, polling, opening, attempt, deadline, foreground, alive, epoch, identityId}),
      currentSession, sessionValid}};
})();
