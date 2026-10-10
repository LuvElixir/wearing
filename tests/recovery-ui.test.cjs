"use strict";
// 第二十一轮：recovery-presentation-contract 的 Web 侧检查。
// 覆盖：恢复消息按 kind/message_kind 显示「重新核对」；can_retry/can_cancel/blocked_reason
// 只信任务回执（旧服务缺字段沿用旧语义）；failure_code=execution_limit 固定文案、
// 不透传 raw error；saved 撤回走同一 cancel-message 端点；开始需两击确认且提交前重读。
const {test} = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const vm = require("node:vm");

const app = fs.readFileSync("src/wearing/web/app.js", "utf8");
const html = fs.readFileSync("src/wearing/web/index.html", "utf8");

test("app.js compiles (syntax gate; regex tests cannot catch parse errors)", () => {
  new vm.Script(app);
});

test("recovery detection and capability gates match the contract", () => {
  const markup = app.slice(app.indexOf("const failureText="), app.indexOf("async function loadConversation"));
  // 真实账本投影识别：message.kind 与 turn.message_kind 双通道，不用提示词猜测。
  assert.match(markup, /const isRecovery=message\.kind==="confirmation_recovery"\|\|turn\.message_kind==="confirmation_recovery"/);
  // 恢复请求用「重新核对」代替通用「继续这句话」，且不得解释为批准旧提案。
  assert.match(markup, /isRecovery\?"重新核对":"继续这句话"/);
  assert.match(markup, /不会直接执行原提案/);
  // 能力开关只信回执：can_retry===false 隐藏开始；saved 撤回仅在 can_cancel===true 开放（新操作）；
  // queued 撤回仅被 can_cancel===false 显式关闭（旧服务 queued=true 兼容）。
  assert.match(markup, /turn\.can_retry===false\?"":/);
  assert.match(markup, /turn\.can_cancel===true\?/);
  assert.match(markup, /turn\.can_cancel===false\?"":/);
  // saved 未入场原因也要展示（message_handoffs.blocked_reason 随任务回执返回）。
  assert.match(markup, /turn\.blocked_reason\?/);
});

test("public tasks never pass through raw error; execution_limit maps to fixed copy", () => {
  assert.ok(!/turn\.error/.test(app), "turn.error must not be rendered anywhere");
  assert.match(app, /failure_code==="execution_limit"\?"已达到本轮执行上限，现有结果和查看记录已保留；这件事尚未完成。"/);
  assert.match(app, /turn\.status==="failed"\?"这次没有完成；已返回的结果仍然保留，可以稍后重新查看。"/);
});

test("start needs explicit confirm, re-reads can_retry first, no auto retry on unknown", () => {
  const dispatcher = app.slice(app.indexOf('const action=event.target.closest("[data-action]")'));
  assert.match(dispatcher, /name==="start"\|\|name==="cancel-message"/);
  assert.match(dispatcher, /再点一次确认开始/);
  assert.match(dispatcher, /再点一次确认撤回/);
  // 提交前重读同一任务回执；读不到只提示重读，不提交不自动重试。
  assert.match(dispatcher, /api\("\/api\/tasks\/"\+action\.dataset\.task\)/);
  assert.match(dispatcher, /task\.can_retry===false/);
  assert.match(dispatcher, /暂时读不到这条的最新状态，请稍后重新查看。/);
  // POST 响应丢失：仅提示重读，不自动重试。
  assert.match(dispatcher, /开始请求的结果未知；请重新查看这条，不要重复点击。/);
  // saved 撤回与 queued 撤回走同一端点。
  assert.match(dispatcher, /\/api\/tasks\/\$\{action\.dataset\.task\}\/\$\{name\}/);
});

test("turnMarkup behavior: recovery vs legacy drafts, capability gating, failure copy", () => {
  const slice = app.slice(app.indexOf("const failureText="), app.indexOf("async function loadConversation"));
  const context = {
    esc: text => String(text ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])),
    state: {connected: true},
    active: new Set(["starting", "running", "stopping", "waiting_for_approval"]),
    wearingFaceMarkup: () => "", artifactMarkup: () => "", researchMarkup: () => "", turnActions: () => "",
    WearingConfirmations: {pending: () => "", history: () => ""},
  };
  vm.runInNewContext(slice, context);
  const {turnMarkup} = context;

  // a) saved 恢复请求：重新核对 + 未开始原因 + saved 撤回；不再出现通用「继续这句话」。
  const recovery = turnMarkup({kind: "confirmation_recovery", queued: false, turn: {id: "t1", status: "draft",
    message_kind: "confirmation_recovery", can_retry: true, can_cancel: true, blocked_reason: "执行端暂不支持安全恢复。"}});
  assert.match(recovery, /重新核对<\/button>/);
  assert.match(recovery, /这次重新核对还没有开始/);
  assert.match(recovery, /执行端暂不支持安全恢复。/);
  assert.match(recovery, /撤回这条<\/button>/);
  assert.ok(!recovery.includes("继续这句话"), "recovery must not offer generic continue");

  // b) 旧服务普通 saved 草稿：无能力字段 → 沿用旧语义（继续这句话，无 saved 撤回）。
  const legacy = turnMarkup({kind: undefined, queued: false, turn: {id: "t2", status: "draft"}});
  assert.match(legacy, /继续这句话/);
  assert.ok(!legacy.includes("撤回这条"), "saved cancel is a new op; absent capability field keeps it closed");

  // c) 新服务普通 saved：can_retry=false 隐藏开始、can_cancel=true 开放撤回、显示未开始原因。
  const blocked = turnMarkup({kind: undefined, queued: false, turn: {id: "t3", status: "draft",
    can_retry: false, can_cancel: true, blocked_reason: "等待前面的运行结束或完成核对。"}});
  assert.ok(!blocked.includes("data-action=\"start\""), "can_retry=false must hide start");
  assert.match(blocked, /撤回这条/);
  assert.match(blocked, /等待前面的运行结束或完成核对。/);

  // d) queued：can_cancel=false 显式关闭撤回；true 保持。
  const queuedOff = turnMarkup({kind: undefined, queued: true, queue_state: "blocked", blocked_reason: "排队原因。",
    turn: {id: "t4", status: "draft", can_cancel: false}});
  assert.ok(!queuedOff.includes("撤回这条"));
  assert.match(queuedOff, /排队原因。/);
  const queuedOn = turnMarkup({kind: undefined, queued: true, queue_state: "queued",
    turn: {id: "t5", status: "draft", can_cancel: true}});
  assert.match(queuedOn, /撤回这条/);

  // e) 失败映射：execution_limit 固定文案；未知类型通用失败；turn.error 即使存在也不透传。
  const limit = turnMarkup({kind: undefined, turn: {id: "t6", status: "failed", failure_code: "execution_limit", error: "内部原始错误"}});
  assert.match(limit, /已达到本轮执行上限，现有结果和查看记录已保留；这件事尚未完成。/);
  assert.ok(!limit.includes("内部原始错误"));
  const unknown = turnMarkup({kind: undefined, turn: {id: "t7", status: "failed", error: "boom"}});
  assert.match(unknown, /这次没有完成；已返回的结果仍然保留/);
  assert.ok(!unknown.includes("boom"));
  const lost = turnMarkup({kind: undefined, turn: {id: "t8", status: "connection_lost", error: "boom"}});
  assert.match(lost, /这次连接没有完成，原消息仍然保留。/);
  assert.ok(!lost.includes("boom"));
});

test("no inline handlers or styles in the touched module; app.js version bumped", () => {
  assert.doesNotMatch(app, /onclick=|style="/);
  assert.match(html, /app\.js\?v=58/);
});
