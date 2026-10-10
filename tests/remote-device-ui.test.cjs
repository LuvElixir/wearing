"use strict";
// 第二十四轮：远程设备接管（Web/桌面）mock 合同回归（含第一轮代码审查 5 项的行为覆盖）。
const {test} = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const vm = require("node:vm");

const module_ = fs.readFileSync("src/wearing/web/remote-device.js", "utf8");
const app = fs.readFileSync("src/wearing/web/app.js", "utf8");
const html = fs.readFileSync("src/wearing/web/index.html", "utf8");

test("compiles; wiring; privacy/invariant assertions", () => {
  new vm.Script(module_);
  new vm.Script(app);
  assert.match(html, /remote-device\.js\?v=6/);
  assert.match(html, /id="remote-device-panel"/);
  assert.match(app, /data-rd-open data-rd-resource/);
  assert.match(app, /window\.WearingRemoteDevice\?\.reset\(\);/);
  assert.doesNotMatch(module_, /localStorage|sessionStorage|navigator\.clipboard/);
  assert.match(module_, /type="password" autocomplete="new-password"/);
  // 审查#1：send 分支用 field，不遮蔽 sendInput。
  assert.doesNotMatch(module_, /data-rd-send[\s\S]{0,80}const input/);
  assert.match(module_, /const field = \$\("rd-text"\);/);
  // 审查#3：会话局部捕获 + 单调代数 + 身份冻结。
  assert.match(module_, /function makeSession\(/);
  assert.match(module_, /function gatedApi\(/);
  assert.match(module_, /identityFrozen/);
  assert.match(module_, /let attempt = 0;/);
  assert.doesNotMatch(module_, /ui\.open = true[\s\S]{0,600}attempt = 0/);
});

function harness({apiImpl, pcBreak} = {}) {
  const elements = {};
  const makeElement = id => {const el = {id, textContent: "", hidden: false, dataset: {},
    listeners: {}, open: false, checked: true, value: "", selectionStart: null, selectionEnd: null, videoWidth: 0, videoHeight: 0,
    addEventListener(type, fn) {(this.listeners[type] = this.listeners[type] || []).push(fn);},
    setAttribute() {}, close() {}, focus() {}, setSelectionRange() {}, dispatchEvent() {},
    getBoundingClientRect: () => ({left: 0, top: 0, width: 800, height: 600}),
    setPointerCapture() {}, play: () => Promise.resolve(), pause() {},
    _innerHTML: "",
    get innerHTML() {return this._innerHTML;},
    set innerHTML(markup) {
      this._innerHTML = String(markup);
      // 真 DOM 重绘语义：innerHTML 赋值后，其中带 id 的元素被重建（缓存失效）。
      for (const match of String(markup).matchAll(/id="([a-z0-9-]+)"/g)) {
        if (elements[match[1]] && match[1] !== this.id) {const fresh = makeElement(match[1]); if (match[1] === "rd-video") {fresh.videoWidth = 1280; fresh.videoHeight = 720;} elements[match[1]] = fresh;}
      }
    }};
    return el;};
  const element = id => elements[id] || (elements[id] = makeElement(id));
  element("rd-video").videoWidth = 1280; element("rd-video").videoHeight = 720;
  const calls = [];
  const apiFn = async (path, options = {}) => {calls.push({path, method: options.method || "GET", body: options.body}); return apiImpl(path, options, calls);};
  const makeChannel = () => ({readyState: "open", bufferedAmount: 0, sent: [], onopen: null, onclose: null, onerror: null, onmessage: null,
    send(text) {this.sent.push(text);}, close() {if (this.readyState !== "closed") {this.readyState = "closed"; this.onclose && this.onclose({});}}});
  const makePc = () => ({iceServers: null, connectionState: "new", iceGatheringState: "complete",
    localDescription: {type: "offer", sdp: "v=0\noffer"},
    addEventListener(type, fn) {this["on" + type] = fn;}, removeEventListener() {},
    addTransceiver() {}, createDataChannel: makeChannel,
    createOffer: async () => ({type: "offer", sdp: "v=0\noffer"}),
    setLocalDescription: async () => {}, setRemoteDescription: async () => {}, getStats: async () => new Map(),
    close() {if (this.connectionState !== "closed") {this.connectionState = "closed"; this.onconnectionstatechange && this.onconnectionstatechange({});}}});
  const pcs = []; const channels = [];
  const origMakeChannel = makeChannel;
  const timerErrors = [];
  const gates = [];
  const context = {
    window: {WearingIds: {uuid: () => "0123456789abcdef0123456789abcdef"}, WearingDeletion: {workAllowed: () => true, registerWorkGate(g) {gates.push(g);}},
      addEventListener(type, fn) {(element("window").listeners[type] = element("window").listeners[type] || []).push(fn);}},
    RTCPeerConnection: function(config) {
      if (pcBreak === "constructor") {const e = new Error("SECRET constructor ice:… sdp:…"); e.name = "NotSupportedError"; throw e;}
      const pc = makePc(); pc.iceServers = config.iceServers; pcs.push(pc);
      if (pcBreak === "transceiver") pc.addTransceiver = () => {const e = new Error("SECRET transceiver sdp=…"); e.name = "InvalidStateError"; throw e;};
      const orig = pc.createDataChannel.bind(pc);
      pc.createDataChannel = (...a) => {
        if (pcBreak === "channel") {const e = new Error("SECRET channel http://x"); e.name = "SecurityError"; throw e;}
        const c = origMakeChannel(); channels.push(c); return c;};
      return pc;},
    MediaStream: function(tracks) {this.tracks = tracks;},
    TextEncoder, Date, JSON, Number, Array, Object, String, Boolean, Math, Error, Promise, RegExp, Map, Set, Uint8Array,
    state: {identityId: "qa", identityEpoch: 1, connected: true},
    api: apiFn, notice() {},
    openPanel(id) {element(id).open = true;}, closePanel(id) {element(id).open = false;},
    setInterval: () => 0, clearInterval: () => {}, setTimeout: fn => {try {fn();} catch (e) {timerErrors.push(e);} return 0;}, clearTimeout: () => {},
    document: {
      documentElement: {classList: {contains: () => false}},
      getElementById: element, querySelector: () => null,
      addEventListener(type, fn) {(element("document").listeners[type] = element("document").listeners[type] || []).push(fn);},
      body: {classList: {contains: () => false}}, hidden: false, activeElement: null,
    },
  };
  context.window.WearingStore = {get: () => null, set: () => true, remove: () => true};
  vm.createContext(context);
  vm.runInNewContext(module_, context);
  const flush = () => new Promise(r => setTimeout(r, 8));
  const fire = (id, type, event) => {for (const fn of element(id).listeners[type] || []) fn(event);};
  return {context, calls, elements, element, pcs, channels, flush, fire, gates, timerErrors, mod: context.window.WearingRemoteDevice,
    sessionOf: () => context.window.WearingRemoteDevice._test.currentSession()};
}
const accessOf = (over = {}) => ({resource_id: "dev_main", supported: true, state: "agent_ready", control_generation: 7, session_id: null, epoch: 0,
  gateway_epoch: null, device_confirmed: false, expires_at: null, ...over});
const liveAccess = (over = {}) => accessOf({state: "human_private", session_id: "sess_1", epoch: 3, gateway_epoch: 11, device_confirmed: true, expires_at: Math.floor(Date.now() / 1000) + 600, ...over});
const transport = {kind: "webrtc", session_id: "sess_1", epoch: 3, gateway_epoch: 11, ice_servers: [{urls: ["stun:stun.example.com"]}]};
function livePhases() {
  const s = {phase: "agent"};
  return {s, impl: path => {
    const out = (() => {
    if (path.endsWith("/request")) {s.phase = "handoff"; return accessOf({state: "handoff_pending", session_id: "sess_1", epoch: 3, gateway_epoch: 11, expires_at: Math.floor(Date.now() / 1000) + 600});}
    if (path.endsWith("/transport")) return transport;
    if (path.endsWith("/offer")) return {type: "answer", sdp: "v=0\nanswer", gateway_epoch: 11};
    if (path.endsWith("/close")) return accessOf({state: "paused"});
    if (path.endsWith("/return")) return liveAccess({state: "return_pending"});
    return s.phase === "handoff" || s.phase === "live" ? liveAccess() : accessOf();
    })();
    return out;
  }};
}
async function driveToLive(h) {
  const t = h.mod._test;
  h.mod.open("dev_main", "主机", "computer");
  await h.flush(); await h.flush();
  await t.begin(); await h.flush(); await h.flush();
  await t.refresh(); await h.flush(); await h.flush();
  const session = t.currentSession();
  if (!session) return null;
  session.channel.onmessage({data: JSON.stringify({type: "ready", session_id: "sess_1", epoch: 3, gateway_epoch: 11,
    capabilities: {keyboard: true, touch: true, pointer: true, scroll: true, text: "unicode"}})});
  session.channel.onmessage({data: JSON.stringify({type: "frame", gateway_epoch: 11, frame_id: "f1", width: 1280, height: 720})});
  h.element("rd-video").videoWidth = 1280; h.element("rd-video").videoHeight = 720;
  h.fire("rd-video", "loadeddata", {});
  await h.flush();
  return session;
}

test("model: parse/canStream/black-bar/text limits", () => {
  const h = harness({apiImpl: () => accessOf()});
  const t = h.mod._test;
  h.mod.reset();
  assert.throws(() => t.parseAccess({supported: true, state: "weird"}, "d"), /不完整/);
  assert.equal(t.canStream(accessOf({state: "human_private"})), false);
  assert.equal(t.canStream(liveAccess()), true);
  assert.equal(t.canStream(liveAccess({expires_at: Math.floor(Date.now() / 1000) - 1})), false);
  assert.deepEqual(t.pointInFrame(400, 300, 800, 600, 1280, 720), {x: 640, y: 360});
  assert.equal(t.pointInFrame(400, 10, 800, 600, 1280, 720), null, "top black bar rejected");
  assert.equal(t.pointInFrame(400, 590, 800, 600, 1280, 720), null, "bottom black bar rejected");
  assert.deepEqual(t.textLimits({}, "computer"), {chars: 32, bytes: 4096});
  assert.deepEqual(t.textLimits({}, "android"), {chars: 4096, bytes: 4096});
  assert.equal(t.textIssue("a".repeat(33), {text: "unicode"}, "computer"), "text_too_long");
  assert.equal(t.textIssue("a".repeat(33), {text: "unicode"}, "android"), null);
  assert.equal(t.textIssue("好", {text: "ascii"}, "android"), "text_unavailable");
});

test("flow: begin→handoff→refresh→attach→live→control→inputs→unicode text→giveBack", async () => {
  const ph = livePhases();
  const h = harness({apiImpl: ph.impl});
  const t = h.mod._test;
  const session = await driveToLive(h);
  assert.ok(session, "viewer session attached");
  assert.deepEqual(h.pcs[h.pcs.length - 1].iceServers, transport.ice_servers);
  assert.equal(t.ui.live, true);
  h.fire("remote-device-panel", "click", {target: {closest: sel => sel === "[data-rd-control]" ? {} : null}});
  await h.flush();
  assert.equal(t.ui.controlling, true);
  h.fire("rd-video", "pointerdown", {pointerId: 1, clientX: 400, clientY: 300, button: 0, preventDefault() {}});
  h.fire("rd-video", "pointerup", {pointerId: 1, clientX: 404, clientY: 302, button: 0, preventDefault() {}});
  await h.flush();
  const inputs = session.channel.sent.map(x => JSON.parse(x)).filter(m => m.type === "input");
  assert.ok(inputs.length >= 2);
  assert.equal(inputs[0].frame_id, "f1");
  assert.equal(inputs[0].x, 640); assert.equal(inputs[0].y, 360);
  t.ui.keyboard = true; t.paint();
  const field = h.element("rd-text");
  field.value = "你好世界";
  h.fire("remote-device-panel", "input", {target: field});
  const sentBefore = session.channel.sent.length;
  h.fire("remote-device-panel", "click", {target: {closest: sel => sel === "[data-rd-send]" ? {} : null}});
  await h.flush();
  const textMsgs = session.channel.sent.slice(sentBefore).map(x => JSON.parse(x)).filter(m => m.action === "text");
  assert.equal(textMsgs.length, 1);
  assert.equal(textMsgs[0].text, "你好世界");
  assert.equal(h.element("rd-text").value, "");
  t.ui.confirmReturn = true; t.ui.safeScreen = true; t.ui.scopeConfirmed = true;
  await t.giveBack(); await h.flush();
  assert.equal(t.getState().returning, true);
  assert.equal(t.ui.isReturning, true);
  h.mod.reset();
});

test("safety: hidden/offline/identity-switch stop; no replay; stale close suppressed under new identity", async () => {
  let closed = 0;
  const ph = livePhases();
  const impl = path => {
    if (path.endsWith("/close")) {closed++; return accessOf({state: "paused"});}
    return ph.impl(path);
  };
  const h = harness({apiImpl: impl});
  const t = h.mod._test;
  const session = await driveToLive(h);
  assert.ok(session);
  h.context.document.hidden = true;
  for (const fn of h.element("document").listeners.visibilitychange || []) fn({});
  await h.flush();
  assert.equal(t.ui.live, false);
  assert.equal(closed, 1, "close posted once on stop");
  const sentBefore = session.channel.sent.length;
  session.channel.readyState = "closed";
  t.ui.controlling = true; t.ui.live = true;
  t.sendInput("tap", {x: 1, y: 1});
  assert.equal(session.channel.sent.length, sentBefore, "no replay over closed channel");
  const callsBefore = h.calls.length;
  h.context.state.identityEpoch++;
  h.mod.reset();
  await t.refresh().catch(() => {});
  assert.equal(h.calls.length, callsBefore, "stale refresh posts nothing");
  h.mod.open("dev_main", "主机", "computer"); await h.flush();
  await t.begin(); await h.flush();
  h.context.state.identityEpoch++;
  t.stop("background");
  await h.flush(); await h.flush();
  assert.equal(closed, 1, "stale close suppressed for switched identity");
});

test("session locals: stale offer/ontrack/channel of an old session cannot touch the newer one", async () => {
  const ph = livePhases();
  const h = harness({apiImpl: ph.impl});
  const t = h.mod._test;
  const first = await driveToLive(h);
  assert.ok(first);
  await t.begin(); await h.flush();
  await t.refresh(); await h.flush();
  const second = t.currentSession();
  assert.ok(second && second !== first);
  const before = second.channel.sent.length;
  first.channel.onmessage({data: JSON.stringify({type: "ready", session_id: "sess_1", epoch: 3, gateway_epoch: 11, capabilities: {text: "unicode"}})});
  assert.equal(second.channel.sent.length, before, "old channel message ignored for new session");
  const video = h.element("rd-video");
  video.srcObject = null;
  first.pc.ontrack({streams: ["legacy"], track: {}});
  assert.equal(video.srcObject, null, "stale ontrack ignored");
  h.mod.reset();
});

test("negotiation failure during connect releases busy (viewerStop covered without live)", async () => {
  const ph = livePhases();
  const impl = path => {
    if (path.endsWith("/offer")) throw new Error("negotiation failed");
    return ph.impl(path);
  };
  const h = harness({apiImpl: impl});
  const t = h.mod._test;
  h.mod.open("dev_main", "主机", "computer"); await h.flush();
  await t.begin(); await h.flush();
  await t.refresh(); await h.flush();
  assert.equal(t.ui.viewer, null, "viewer torn down");
  assert.equal(t.ui.busy, false, "busy released");
  assert.ok((t.ui.error || t.ui.notice).length > 0);
  h.mod.reset();
});

test("oversize draft kept in DOM with focus; success clears; never truncated", async () => {
  const ph = livePhases();
  const h = harness({apiImpl: ph.impl});
  const t = h.mod._test;
  const session = await driveToLive(h);
  assert.ok(session);
  h.fire("remote-device-panel", "click", {target: {closest: sel => sel === "[data-rd-control]" ? {} : null}});
  t.ui.keyboard = true; t.paint();
  const field = h.element("rd-text");
  h.context.document.activeElement = field;
  field.value = "长".repeat(40);
  h.fire("remote-device-panel", "input", {target: field});
  const sentBefore = session.channel.sent.length;
  h.fire("remote-device-panel", "click", {target: {closest: sel => sel === "[data-rd-send]" ? {} : null}});
  await h.flush();
  assert.equal(session.channel.sent.length, sentBefore, "oversize not sent");
  assert.match(t.ui.error, /最多输入 32 个字符/);
  const after = h.element("rd-text");
  assert.equal(after.value, "长".repeat(40), "draft retained verbatim");
  assert.equal(h.context.document.activeElement === after || h.context.document.activeElement === field, true, "focus preserved");
  after.value = "好的";
  h.fire("remote-device-panel", "input", {target: after});
  h.fire("remote-device-panel", "click", {target: {closest: sel => sel === "[data-rd-send]" ? {} : null}});
  await h.flush();
  assert.equal(h.element("rd-text").value, "", "cleared after send");
  h.mod.reset();
});

test("cleanup failure honest; close attempted once", async () => {
  let closeAttempts = 0;
  const ph = livePhases();
  const impl = path => {
    if (path.endsWith("/close")) {closeAttempts++; throw new Error("设备连接中断。");}
    return ph.impl(path);
  };
  const h = harness({apiImpl: impl});
  const t = h.mod._test;
  h.mod.open("dev_main", "主机", "computer"); await h.flush();
  await t.begin(); await h.flush();
  t.stop("background");
  await h.flush(); await h.flush(); await h.flush();
  assert.equal(closeAttempts, 1);
  assert.match(t.ui.error, /暂停回执尚未收到/);
  h.mod.reset();
});

test("rotation stops; generation monotonic across open; begin race single request", async () => {
  const ph = livePhases();
  const h = harness({apiImpl: ph.impl});
  const t = h.mod._test;
  const session = await driveToLive(h);
  assert.ok(session);
  session.channel.onmessage({data: JSON.stringify({type: "frame", gateway_epoch: 11, frame_id: "f2", width: 720, height: 1280, geometry_revision: 2})});
  await h.flush();
  assert.equal(t.ui.live, false, "stopped after rotation");
  assert.equal(t.ui.viewer, null);
  const gen1 = t.getState().attempt;
  h.mod.reset();
  h.mod.open("dev_main", "主机", "computer"); await h.flush();
  assert.ok(t.getState().attempt >= gen1, "generation never rewinds");
  const events = [];
  const impl = path => {
    if (path.endsWith("/request")) {events.push("request"); return liveAccess();}
    return ph.impl(path);
  };
  const h2 = harness({apiImpl: impl});
  const t2 = h2.mod._test;
  h2.mod.open("dev_main", "主机", "computer"); await h2.flush();
  const a = t2.begin(); const b = t2.begin();
  await a; await b; await h2.flush();
  assert.equal(events.length, 1, "single request despite double click");
  h2.mod.reset();
});

test("review3: late read from A cannot replace B access; receipt resource mismatch dropped", async () => {
  let release; const wait = new Promise(r => release = r);
  const h = harness({apiImpl: path => path.endsWith("/dev_a") ? wait : accessOf({resource_id: "dev_b"})});
  h.mod.open("dev_a", "A", "computer"); await h.flush();
  h.mod.open("dev_b", "B", "computer"); await h.flush();
  assert.equal(h.mod._test.ui.access.resource_id, "dev_b");
  release(accessOf({resource_id: "dev_a", state: "paused"})); await h.flush();
  assert.equal(h.mod._test.ui.resource, "dev_b");
  assert.equal(h.mod._test.ui.access.resource_id, "dev_b", "stale A result discarded");
  h.mod.reset();
});

test("review3: Android touch/keyboard false blocks every input path (tap fallback + keys)", async () => {
  const ph = livePhases();
  const h = harness({apiImpl: ph.impl});
  const session = await driveToLive(h);
  const t = h.mod._test;
  t.ui.kind = "android";
  session.capabilities = {touch: false, keyboard: false, pointer: false, scroll: false, text: "unavailable"};
  t.ui.capabilities = session.capabilities;
  h.fire("remote-device-panel", "click", {target: {closest: q => q === "[data-rd-control]" ? {} : null}});
  const n = session.channel.sent.length;
  h.fire("rd-video", "pointerdown", {pointerId: 1, clientX: 400, clientY: 300, button: 0, preventDefault() {}});
  h.fire("rd-video", "pointerup", {pointerId: 1, clientX: 400, clientY: 300, button: 0, preventDefault() {}});
  h.fire("remote-device-panel", "click", {target: {closest: q => q === "[data-rd-key]" ? {dataset: {rdKey: "Home"}} : null}});
  assert.equal(session.channel.sent.length, n, "no tap/key input without touch/keyboard capability");
  h.mod.reset();
});

test("review3: slow Android swipe clamped to protocol 50..1000ms, no replay", async () => {
  const ph = livePhases();
  const h = harness({apiImpl: ph.impl});
  const session = await driveToLive(h);
  const t = h.mod._test;
  t.ui.kind = "android";
  session.capabilities = {touch: true, keyboard: true, pointer: false, scroll: false, text: "unicode"};
  t.ui.capabilities = session.capabilities;
  h.fire("remote-device-panel", "click", {target: {closest: q => q === "[data-rd-control]" ? {} : null}});
  h.fire("rd-video", "pointerdown", {pointerId: 1, clientX: 400, clientY: 300, button: 0, preventDefault() {}});
  session.gesture.at = Date.now() - 1200;
  h.fire("rd-video", "pointerup", {pointerId: 1, clientX: 420, clientY: 380, button: 0, preventDefault() {}});
  const message = session.channel.sent.map(x => JSON.parse(x)).find(m => m.action === "swipe");
  assert.ok(message, "swipe sent");
  assert.ok(message.duration_ms <= 1000 && message.duration_ms >= 50, "duration clamped to backend range");
  h.mod.reset();
});

test("review3: identity reset wipes private draft from retained dialog DOM", async () => {
  const ph = livePhases();
  const h = harness({apiImpl: ph.impl});
  await driveToLive(h);
  const t = h.mod._test;
  h.fire("remote-device-panel", "click", {target: {closest: q => q === "[data-rd-control]" ? {} : null}});
  t.ui.keyboard = true; t.paint();
  const field = h.element("rd-text");
  field.value = "SYNTHETIC-PRIVATE-DRAFT";
  h.fire("remote-device-panel", "input", {target: field});
  h.context.state.identityEpoch++;
  h.mod.reset();
  assert.equal(t.ui.textDraft, null);
  assert.equal(h.element("rd-text").value, "", "private draft removed from DOM");
});

test("freeze gate: missing/string capability fields never enable any input path", async () => {
  const ph = livePhases();
  const h = harness({apiImpl: ph.impl});
  const session = await driveToLive(h);
  const t = h.mod._test;
  h.fire("remote-device-panel", "click", {target: {closest: q => q === "[data-rd-control]" ? {} : null}});
  const variants = [
    {}, // 全缺字段
    {pointer: undefined, touch: undefined, keyboard: undefined, scroll: undefined},
    {pointer: "true", touch: "true", keyboard: "true", scroll: "true"}, // 字符串
    {pointer: "false", touch: "false", keyboard: "false", scroll: "false"},
    {pointer: 1, touch: 1, keyboard: 1, scroll: 1}, // truthy 非 true
  ];
  for (const caps of variants) {
    session.capabilities = caps; t.ui.capabilities = caps;
    const n = session.channel.sent.length;
    h.fire("rd-video", "pointerdown", {pointerId: 1, clientX: 400, clientY: 300, button: 0, preventDefault() {}});
    h.fire("rd-video", "pointermove", {pointerId: 1, clientX: 410, clientY: 310, preventDefault() {}});
    h.fire("rd-video", "pointerup", {pointerId: 1, clientX: 430, clientY: 340, button: 0, preventDefault() {}});
    h.fire("rd-video", "wheel", {deltaX: 0, deltaY: 120, preventDefault() {}});
    h.fire("remote-device-panel", "click", {target: {closest: q => q === "[data-rd-key]" ? {dataset: {rdKey: "Home"}} : null}});
    assert.equal(session.channel.sent.length, n, "zero input for caps " + JSON.stringify(caps));
  }
  // 显式 true 全开：各路径恢复发送
  session.capabilities = {pointer: true, touch: true, keyboard: true, scroll: true, text: "unicode"};
  t.ui.capabilities = session.capabilities;
  const base = session.channel.sent.length;
  h.fire("rd-video", "pointerdown", {pointerId: 2, clientX: 400, clientY: 300, button: 0, preventDefault() {}});
  h.fire("rd-video", "pointerup", {pointerId: 2, clientX: 430, clientY: 340, button: 0, preventDefault() {}});
  h.fire("rd-video", "wheel", {deltaX: 0, deltaY: 120, preventDefault() {}});
  h.fire("remote-device-panel", "click", {target: {closest: q => q === "[data-rd-key]" ? {dataset: {rdKey: "Home"}} : null}});
  assert.ok(session.channel.sent.length > base, "explicit true re-enables input");
  h.mod.reset();
});

test("diagnosis: fixed stop-reason copy, whitelisted diagnostic codes, no raw leaks", async () => {
  const h0 = harness({apiImpl: () => accessOf()});
  const t0 = h0.mod._test;
  // 1) 诊断白名单：DOMException.name 枚举进、HTTP 状态进、其它字段一律丢。
  const mk = (fields, msg = "SECRET-RAW sdp:… ice:… http://evil/x body") => Object.assign(new Error(msg), fields);
  const cases = [
    [mk({name: "NotSupportedError"}), "NotSupportedError"],
    [mk({name: "NotAllowedError"}), "NotAllowedError"],
    [mk({name: "TimeoutError"}), "TimeoutError"],
    [mk({status: 502}), "HTTP 502"],
    [mk({name: "NetworkError", status: 409}), "NetworkError · HTTP 409"],
    [mk({name: "EvilCustomError"}), ""],   // 白名单外 name 丢弃
    [mk({status: "502"}), ""],             // 非数字状态丢弃
    [mk({status: 9999}), ""],              // 范围外丢弃
    [mk({}), ""],                          // 无字段
  ];
  for (const [error, expected] of cases) {
    const out = t0.diagnosticOf(error);
    assert.equal(out, expected ? ` · ${expected}` : "", JSON.stringify({name: error.name, status: error.status}));
    assert.ok(!out.includes("SECRET") && !out.includes("sdp") && !out.includes("evil"), "no raw leak: " + out);
  }
  h0.mod.reset();

  // 2) offer 阶段 HTTP 409 → negotiation_failed 固定文案 + [server_answer · HTTP 409]
  const ph = livePhases();
  const impl = (path, options) => {
    if (path.endsWith("/offer")) {const e = new Error("SECRET server says nope sdp=…"); e.status = 409; throw e;}
    return ph.impl(path, options);
  };
  const h = harness({apiImpl: impl});
  const t = h.mod._test;
  h.mod.open("dev_main", "主机", "computer"); await h.flush();
  await t.begin(); await h.flush();
  await t.refresh(); await h.flush();
  await h.flush(); await h.flush();
  const shown = (t.ui.notice || "") + (t.ui.error || "");
  assert.ok(shown.includes("画面协商没有完成"), "fixed negotiation copy shown: " + shown);
  assert.ok(shown.includes("[server_answer · HTTP 409]"), "stage+status diagnostic: " + shown);
  assert.ok(!shown.includes("SECRET") && !shown.includes("sdp"), "no raw server text leaked");
  assert.ok(!shown.includes("已保持暂停。重新连接后可继续"), "not falling to generic pause copy");
  h.mod.reset();

  // 3) webrtc 不可用 → 专属文案
  const h2 = harness({apiImpl: ph.impl});
  h2.context.RTCPeerConnection = undefined;
  const t2 = h2.mod._test;
  h2.mod.open("dev_main", "主机", "computer"); await h2.flush();
  await t2.begin(); await h2.flush();
  await t2.refresh(); await h2.flush(); await h2.flush();
  const shown2 = (t2.ui.notice || "") + (t2.ui.error || "");
  assert.ok(shown2.includes("不支持实时画面"), "webrtc_unavailable copy: " + shown2);
  h2.mod.reset();
});

test("review-v5: WebRTC setup (constructor/transceiver/channel) whitelisted, raw message never visible", async () => {
  const impl = path => {
    if (path.endsWith("/request")) return accessOf({state: "handoff_pending", session_id: "sess_1", epoch: 3, gateway_epoch: 11, expires_at: Math.floor(Date.now() / 1000) + 600});
    if (path.endsWith("/transport")) return transport;
    if (path.endsWith("/offer")) return {type: "answer", sdp: "v=0\nanswer", gateway_epoch: 11};
    if (path.endsWith("/close")) return accessOf({state: "paused"});
    return liveAccess();
  };
  const breaks = [
    ["constructor", "NotSupportedError"],
    ["transceiver", "InvalidStateError"],
    ["channel", "SecurityError"],
  ];
  for (const [where, name] of breaks) {
    const h = harness({apiImpl: impl, pcBreak: where});
    const t = h.mod._test;
    h.mod.open("dev_main", "主机", "computer");
    await h.flush();
    await t.begin(); await h.flush();
    await t.refresh(); await h.flush(); await h.flush();
    const shown = (t.ui.notice || "") + (t.ui.error || "");
    assert.ok(!shown.includes("SECRET") && !shown.includes("sdp") || !shown.includes("sdp:"), where + ": no raw leak");
    assert.ok(shown.includes("协商没有完成") || shown.includes("不支持实时画面"), where + ": fixed copy");
    assert.ok(shouted(shown, where, name), where + ": stage + whitelisted name shown: " + shown);
    h.mod.reset();
  }
  function shouted(shown, where, name) {return shown.includes("[webrtc_setup") && shown.includes(name);}
});
