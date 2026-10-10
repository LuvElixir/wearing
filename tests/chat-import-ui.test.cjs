"use strict";
// 第二十三轮：选定聊天导入 Web 侧检查（解析器移植 + 幂等 journal + 生命周期）。
const {test} = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const vm = require("node:vm");

const module_ = fs.readFileSync("src/wearing/web/chat-import.js", "utf8");
const fflateSrc = fs.readFileSync("src/wearing/web/vendor/fflate/index.js", "utf8");
const app = fs.readFileSync("src/wearing/web/app.js", "utf8");
const views = fs.readFileSync("src/wearing/web/views.js", "utf8");
const deletion = fs.readFileSync("src/wearing/web/account-deletion.js", "utf8");
const html = fs.readFileSync("src/wearing/web/index.html", "utf8");
const FIX = "clients/mobile/test-fixtures/chat-import/";

test("chat-import.js and touched modules compile (syntax gate)", () => {
  new vm.Script(module_);
  new vm.Script(app);
  new vm.Script(views);
});

test("wiring: panel, dual entries, vendor fflate (local, no CDN), versions, reset hook, search branch", () => {
  assert.match(html, /chat-import\.js\?v=6/);
  assert.match(html, /id="chat-import-panel"/);
  assert.match(html, /id="chat-import-entry"/);
  assert.match(html, /id="ci-files-entry"/);
  assert.match(html, /vendor\/fflate\/index\.js\?v=0\.8\.3/);
  assert.doesNotMatch(html, /cdn\./);
  assert.match(html, /app\.js\?v=59/);
  assert.match(html, /views\.js\?v=17/);
  assert.match(html, /pajio\.css\?v=22/);
  assert.match(html, /account-deletion\.js\?v=8/);
  assert.match(app, /window\.WearingChatImport\?\.reset\(\);/);
  assert.match(views, /chat_import: "聊天来源"/);
  assert.match(views, /WearingChatImport\?\.openSearchResult\?\.\(item\.target\)/);
  assert.match(deletion, /chat-import-draft:v1/);
  assert.match(deletion, /chat-import-pending:v1/);
  // 私密远控未开放：不出现任何远控/远程登录入口。
  assert.doesNotMatch(module_, /远程登录|remote[-_ ]?login|device_access/);
  assert.doesNotMatch(module_, /onclick=|style="/);
});

test("parser: real fixture ZIP parses with attachments declared not-imported", async () => {
  const h = harness();
  const bytes = new Uint8Array(fs.readFileSync(FIX + "合成选定聊天.zip"));
  const preview = await h.mod._test.parseChatImport(bytes, "合成选定聊天.zip");
  assert.ok(preview.messages.length >= 1);
  assert.ok(preview.authors.length >= 1);
  assert.match(preview.messages[0].sent_at, /^\d{4}年/);
  // 附件只声明：非聊天条目列为未导入，messages 的 attachments 为空。
  assert.ok(Array.isArray(preview.attachments) && preview.attachments.length >= 1);
  assert.ok(preview.messages.every(m => m.attachments.length === 0));
});

test("parser: plain TXT and strict rejections (nested/traversal/ambiguous/bad-date/case-alias)", async () => {
  const h = harness();
  const txt = new Uint8Array(fs.readFileSync(FIX + "合成聊天记录.txt"));
  const preview = await h.mod._test.parseChatImport(txt, "合成聊天记录.txt");
  assert.ok(preview.messages.length >= 1);
  for (const name of ["nested.zip", "path-traversal.zip", "ambiguous.zip", "bad-date.zip", "case-alias.zip"]) {
    const bytes = new Uint8Array(fs.readFileSync(FIX + name));
    await assert.rejects(() => h.mod._test.parseChatImport(bytes, name), /不支持|不安全|没有唯一|无法核对|重名|目录|校验|格式|确认哪份/);
  }
  // 非 UTF-8（GBK 风格字节）拒绝，不乱码导入。
  await assert.rejects(async () => h.mod._test.parseChatText(new Uint8Array([0xff,0xfe]), "x.txt"), /UTF-8/);
  // 未知扩展名拒绝。
  await assert.rejects(() => h.mod._test.parseChatImport(new Uint8Array([65]), "a.docx"), /ZIP 或 UTF-8 TXT/);
});

/* ---------- 行为 harness（加载真实 vendored fflate） ---------- */
function harness({get, post, del, receiptGet, deletion = null, hangPost = false, hangReceipt = false, failRemove = false, denyStorage = false} = {}) {
  const store = {}, elements = {};
  const element = id => elements[id] || (elements[id] = {id, innerHTML: "", textContent: "", hidden: false, dataset: {}, listeners: {}, open: false,
    addEventListener(type, fn) {(this.listeners[type] = this.listeners[type] || []).push(fn);},
    setAttribute() {}, close() {}, click() {}});
  const calls = [];
  const releasers = [];
  const api = async (path, options = {}) => {
    const method = options.method || "GET";
    calls.push({path, method, body: options.body, storePendingAtCall: store["chat-import-pending:v1:qa"] || null});
    if (method === "POST") {
      if (hangPost) return new Promise((resolve, reject) => {releasers.push(() => {try {resolve(post(path, options.body));} catch (e) {reject(e);}});});
      return post(path, options.body);
    }
    if (path.includes("/receipts/") && hangReceipt) return new Promise((resolve, reject) => {releasers.push(() => {try {resolve(receiptGet(path));} catch (e) {reject(e);}});});
    if (method === "DELETE") return del(path, options.body);
    if (path.includes("/receipts/")) return receiptGet(path);
    return get(path);
  };
  const opened = [];
  const context = {
    window: {}, crypto, TextEncoder, TextDecoder, URLSearchParams, location: {search: ""},
    document: {
      documentElement: {classList: {contains: () => false}},
      getElementById: element, querySelector: () => null,
      addEventListener(type, fn) {(element("document").listeners[type] = element("document").listeners[type] || []).push(fn);},
      body: {classList: {contains: () => false}},
    },
    state: {identityId: "qa", identityEpoch: 1, connected: true},
    api, notice() {},
    openPanel(id) {opened.push(id); element(id).open = true;},
    closePanel(id) {opened.push("close:" + id); element(id).open = false;},
    setTimeout, clearTimeout, Date, JSON, Number, Array, Object, String, Boolean, Math, Error, Promise, RegExp, Uint8Array, DataView, Set, Map,
  };
  const storage = {denied: denyStorage};
  context.window.WearingStore = {get: name => {if (storage.denied) throw new DOMException("denied", "SecurityError"); return store[name] ?? null;},
    set: (name, v) => {if (storage.denied) return false; store[name] = String(v); return true;},
    remove: name => {if (failRemove) return false; if (storage.denied) throw new DOMException("denied", "SecurityError"); delete store[name]; return true;}};
  context.window.WearingIds = {uuid: () => "k0123456789abcdef0123456789abcdef"};
  if (deletion) context.window.WearingDeletion = deletion;
  vm.createContext(context);
  vm.runInNewContext(fflateSrc, context);
  context.window.fflate = context.fflate;
  vm.runInNewContext(module_, context);
  const flush = () => new Promise(r => setTimeout(r, 5));
  const journal = name => {try {return JSON.parse(store[name] || "null");} catch {return null;}};
  const fileOf = (path, name) => {const buf = fs.readFileSync(path); const copy = new Uint8Array(buf.length); copy.set(buf); return {name: name || path.split("/").at(-1), arrayBuffer: async () => copy.buffer.slice(0, copy.length)};};
  return {context, calls, store, opened, journal, element, flush, fileOf, mod: context.window.WearingChatImport, releasePost: () => releasers.splice(0).forEach(release => release()), denyStorage: v => {storage.denied = v;}};
}
const fixtureHash = () => {const crypto = require("node:crypto"); return crypto.createHash("sha256").update(fs.readFileSync(FIX + "合成选定聊天.zip")).digest("hex");};
const receiptOf = (key, over = {}) => ({schema: 1, request_key: key, import_id: "imp_test01", identity_id: "qa", status: "imported", created_at: "2026-10-09T05:00:00Z", ...over});

test("preview is local: pick parses fixture with ZERO network, journal persisted", async () => {
  const h = harness({get: () => ({items: [], next_cursor: null}), post: () => {throw new Error("no POST in preview");}, receiptGet: () => {throw new Error("no receipt in preview");}});
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip"));
  await h.flush();
  assert.equal(h.calls.filter(c => c.method !== "GET" || !c.path.includes("/api/chat-imports?")).filter(c => c.path.includes("chat-imports")).length, 0, "preview touches no chat-import endpoint beyond the list GET");
  assert.ok(t.ui.draft, "draft retained locally");
  assert.equal(h.journal("chat-import-draft:v1:qa").draft.sourceHash, fixtureHash());
  assert.match(h.element("ci-body").innerHTML, /消息预览/);
});

test("confirm persists request before POST, verifies receipt, clears journals", async () => {
  const posted = [];
  let receiptServed = false;
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {if (receiptServed) return receiptOf("k0123456789abcdef0123456789abcdef"); const e = new Error("nf"); e.status = 404; throw e;},
    post: (path, body) => {posted.push(body); receiptServed = true; return receiptOf(JSON.parse(body).request_key);},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  await t.confirm(); await h.flush();
  const post = h.calls.find(c => c.method === "POST");
  assert.ok(post, "POST sent");
  const pendingAtCall = post.storePendingAtCall && JSON.parse(post.storePendingAtCall);
  assert.equal(pendingAtCall.pending.request.request_key, JSON.parse(post.body).request_key, "pending journal persisted BEFORE POST");
  assert.equal(JSON.parse(post.body).platform, "wechat");
  assert.equal(JSON.parse(post.body).confirmed, true);
  assert.ok(JSON.parse(post.body).messages.length >= 1);
  assert.equal(t.ui.draft, null); assert.equal(t.ui.pending, null);
  assert.equal(h.journal("chat-import-draft:v1:qa"), null);
  assert.equal(h.journal("chat-import-pending:v1:qa"), null);
  assert.match(t.ui.notice, /已导入当前身份/);
});

test("unknown result keeps pending; retry checks receipt FIRST without re-POST", async () => {
  let fail = true, receiptServed = false;
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {if (receiptServed) return receiptOf("k0123456789abcdef0123456789abcdef"); const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {if (fail) throw new Error("network down"); receiptServed = true; return receiptOf("k0123456789abcdef0123456789abcdef");},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  await t.confirm(); await h.flush();
  assert.ok(t.ui.pending, "pending retained after unknown result");
  assert.match(t.ui.error, /尚未确认|核对/);
  // 服务端其实已收到：重试先查回执，命中即不再 POST。
  receiptServed = true;
  await t.confirm(); await h.flush();
  assert.equal(h.calls.filter(c => c.method === "POST").length, 1, "no duplicate POST after receipt hit");
  assert.equal(t.ui.pending, null);
  assert.match(t.ui.notice, /已导入当前身份/);
});

test("deleted receipt does not re-import; mismatched receipt rejected", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => receiptOf("k0123456789abcdef0123456789abcdef", {status: "deleted"}),
    post: () => {throw new Error("must not re-import after deleted receipt");},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  await t.confirm(); await h.flush();
  assert.equal(h.calls.filter(c => c.method === "POST").length, 0, "deleted receipt never re-submits");
  assert.match(t.ui.notice, /此前已删除，没有重新导入/);
});

test("duplicate source warning via list; delete two-step with honest 409", async () => {
  const hash = fixtureHash();
  let items = [{schema: 1, import_id: "imp_dup01", identity_id: "qa", conversation_title: "旧批次", authors: ["a"], self_author: null, source_sha256: hash, message_count: 3, attachment_count: 0, created_at: "2026-10-09T01:00:00Z", status: "imported", attachments_imported: false}];
  let delCount = 0;
  const h = harness({
    get: () => ({items, next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => receiptOf("k0123456789abcdef0123456789abcdef"),
    del: () => {if (delCount++ === 0) {const e = new Error("Pajio 正在处理任务，请先停止或等任务结束，再移除这批聊天。"); e.status = 409; throw e;} return {schema: 1, identity_id: "qa", import_id: "imp_dup01", status: "deleted"};},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  assert.match(h.element("ci-body").innerHTML, /已在当前列表中导入过/, "duplicate warning shown");
  // 删除：两步确认；第一次 409 如实提示，第二次成功。
  t.ui.deleting = "imp_dup01";
  await t.removeBatch("imp_dup01"); await h.flush();
  assert.match(t.ui.error, /正在处理任务/);
  await t.removeBatch("imp_dup01"); await h.flush();
  assert.match(t.ui.notice, /已移除这批聊天来源/);
  items = [];
});

test("identity reset clears state; stale in-flight op never writes the new session", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => receiptOf("k0123456789abcdef0123456789abcdef"), hangPost: true,
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  const confirming = t.confirm();
  await h.flush();
  assert.equal(t.ui.busy, true);
  h.mod.reset();
  assert.equal(t.ui.busy, false, "reset releases busy");
  h.releasePost(); // 旧请求终于返回（身份已切换）
  await confirming; await h.flush();
  assert.equal(t.ui.error, "", "stale op wrote nothing");
  assert.equal(t.ui.pending, null, "new session untouched");
});

test("deletion freeze blocks pick/confirm/delete with honest notice", async () => {
  const gates = [];
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("must not POST when frozen");},
    deletion: {workAllowed: () => true, registerWorkGate(g) {gates.push(g);}},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  h.context.window.WearingDeletion.workAllowed = () => false;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  assert.match(t.ui.error, /注销申请已受理/);
  assert.equal(h.journal("chat-import-draft:v1:qa"), null, "no local write while frozen");
  t.ui.draft = {version: 1, key: "k0123456789abcdef0123456789abcdef", sourceHash: fixtureHash(), preview: {title: "t", authors: ["a"], messages: [{id: "message-1", author: "a", sent_at: null, text: "x", attachments: []}], attachments: []}, selfAuthor: null};
  await t.confirm(); await h.flush();
  assert.equal(h.calls.filter(c => c.method === "POST").length, 0);
  assert.equal(gates.length, 1);
  t.ui.busy = true; gates[0].stop();
  assert.equal(t.ui.busy, false);
});

test("settings and files entries close their parent dialogs before opening", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
  });
  h.element("settings-panel").open = true;
  for (const fn of (h.element("document").listeners.click || []))
    fn({target: {closest: sel => sel === "#chat-import-entry" ? {} : null}});
  await h.flush();
  assert.ok(h.opened.includes("close:settings-panel"), "settings closed on entry");
  assert.ok(h.opened.includes("chat-import-panel"), "import panel opened");
  assert.notEqual(h.element("settings-panel").open, true);
  h.mod.close(); await h.flush();
  h.element("files-panel").open = true;
  for (const fn of (h.element("document").listeners.click || []))
    fn({target: {closest: sel => sel === "#ci-files-entry" ? {} : null}});
  await h.flush();
  assert.ok(h.opened.includes("close:files-panel"), "files panel closed on entry");
  assert.ok(h.opened.includes("chat-import-panel"));
});

test("list shows human-readable local import time, not raw ISO", async () => {
  const h = harness({
    get: () => ({items: [{schema: 1, import_id: "imp_t1", identity_id: "qa", conversation_title: "批", authors: ["a"], self_author: null, source_sha256: "f".repeat(64), message_count: 3, attachment_count: 0, created_at: "2026-10-09T05:23:36.350998+00:00", status: "imported", attachments_imported: false}], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
  });
  h.mod.open(); await h.flush();
  const markup = h.element("ci-body").innerHTML;
  assert.ok(!/T05:23:36\.350998\+00:00/.test(markup), "no raw ISO timestamp");
  assert.match(markup, /导入于 2026\/10\/9[^<]*/, "local readable import time");
});

test("scoped journals are per-identity; other identity's rows invisible", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
  });
  h.context.window.WearingStore.set("chat-import-draft:v1:other", JSON.stringify({identity: "other", draft: {version: 1, key: "x", sourceHash: "y", preview: {title: "别的人"}, selfAuthor: null}}));
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  assert.equal(t.ui.draft, null, "other identity's journal is invisible");
  assert.ok(!h.element("ci-body").innerHTML.includes("别的人"));
});

test("P1-1 regression: identity switch during pick never writes the other identity's journal", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  const buf = fs.readFileSync(FIX + "合成选定聊天.zip");
  const copy = new Uint8Array(buf.length); copy.set(buf);
  // 文件读取途中切换账户+身份并 reset：pick 的任何后续存储写必须被围栏拦下。
  const delayedFile = {name: "合成选定聊天.zip", arrayBuffer: async () => {
    h.context.state.identityId = "other"; h.context.state.identityEpoch++; h.mod.reset();
    return copy.buffer.slice(0, copy.length);
  }};
  await t.pick(delayedFile); await h.flush();
  assert.equal(h.journal("chat-import-draft:v1:other"), null, "old chat must not land in the new identity's journal");
  assert.equal(h.journal("chat-import-draft:v1:qa"), null, "no write for the stale session either");
  assert.equal(t.ui.draft, null);
});

test("P1-1 regression: parser rechecks active after the final yield", async () => {
  const h = harness();
  const bytes = new Uint8Array(fs.readFileSync(FIX + "合成选定聊天.zip"));
  let calls = 0;
  const active = () => calls++ < 2; // 在解压让出线程后失效
  await assert.rejects(() => h.mod._test.parseChatImport(bytes, "合成选定聊天.zip", active), /读取已停止/);
});

test("P1-2 regression: close during receipt GET never POSTs or clears journals", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("must not POST after panel closed");},
    hangReceipt: true,
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  const confirming = t.confirm();
  await h.flush();
  assert.equal(t.ui.busy, true);
  h.mod.close(); // 关面板：作废在途 operation
  h.releasePost(); // GET 回执返回 404
  await confirming; await h.flush();
  assert.equal(h.calls.filter(c => c.method === "POST").length, 0, "no POST after close");
  const pending = h.journal("chat-import-pending:v1:qa");
  assert.ok(pending && pending.pending.request, "unknown submission keeps the same request key for later retry");
  assert.equal(t.ui.error, "", "stale op wrote no error");
});

test("P1-2 regression: deletion freeze during receipt GET blocks POST and journal clears", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("must not POST when frozen");},
    hangReceipt: true,
    deletion: {workAllowed: () => true, registerWorkGate() {}},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  const confirming = t.confirm();
  await h.flush();
  h.context.window.WearingDeletion.workAllowed = () => false;
  h.mod._test.ui.generation++; // 模拟冻结门 stop() 作废围栏
  h.releasePost();
  await confirming; await h.flush();
  assert.equal(h.calls.filter(c => c.method === "POST").length, 0, "no POST after freeze");
  assert.ok(h.journal("chat-import-pending:v1:qa"), "journals not cleared after freeze");
});

test("P2-1: oversized File rejected by size BEFORE any read", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
  });
  h.mod.open(); await h.flush();
  let reads = 0;
  const huge = {name: "huge.zip", size: 2 * 1024 * 1024 * 1024, arrayBuffer: async () => {reads++; return new ArrayBuffer(8);}};
  await h.mod._test.pick(huge); await h.flush();
  assert.equal(reads, 0, "arrayBuffer must not be called for oversized files");
  assert.match(h.mod._test.ui.error, /不超过 15 MB/);
  assert.equal(h.journal("chat-import-draft:v1:qa"), null);
});

test("P2-2: failed journal removal never claims removed; draft survives reopen", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
    failRemove: true,
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  assert.ok(t.ui.draft);
  t.discard();
  assert.match(t.ui.error, /暂时没能移除这份预览/, "honest failure shown");
  assert.ok(t.ui.draft, "draft still live in UI");
  assert.ok(h.journal("chat-import-draft:v1:qa"), "storage still holds the draft");
  assert.ok(!document_note(h).includes("已移除本机聊天预览"), "no false success notice");
  // 重开后正文又出现——与存储一致（不是静默丢失）。
  h.mod.open(); await h.flush();
  assert.ok(h.mod._test.ui.draft, "reopen shows the retained draft consistently");
  function document_note(hh){return hh.element("ci-body").innerHTML;}
});

test("P2-2 boundary: fully denied storage (get+remove both throw) never reports removed", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  assert.ok(t.ui.draft, "draft stored while storage worked");
  // 存储随后整体被拒（SecurityError：remove 与 get 同时抛）。
  h.denyStorage(true);
  t.discard();
  assert.match(t.ui.error, /暂时没能移除这份预览/, "honest failure when storage fully denied");
  assert.ok(t.ui.draft, "draft stays live");
  assert.ok(!h.element("ci-body").innerHTML.includes("已移除本机聊天预览"), "no false success notice");
});

test("P2-2 success path: verifiable removal clears draft and notice", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  t.discard();
  assert.equal(t.ui.error, "");
  assert.match(h.element("ci-body").innerHTML, /已移除本机聊天预览/);
  assert.equal(h.journal("chat-import-draft:v1:qa"), null);
});

test("close buttons wired: icon close closes panel and invalidates ops", async () => {
  const h = harness({
    get: () => ({items: [], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
  });
  h.mod.open(); await h.flush();
  const listeners = h.element("chat-import-panel").listeners.click || [];
  listeners[0]({target: {closest: sel => sel === "[data-ci-close-btn]" ? {} : null}});
  await h.flush();
  assert.ok(h.opened.includes("close:chat-import-panel"), "panel closed via icon button");
  assert.equal(h.mod._test.ui.open, false);
});

test("no nested buttons in any rendered state", async () => {
  const h = harness({
    get: () => ({items: [{schema: 1, import_id: "imp_x1", identity_id: "qa", conversation_title: "批", authors: ["a"], self_author: null, source_sha256: "f".repeat(64), message_count: 1, attachment_count: 0, created_at: "t", status: "imported", attachments_imported: false}], next_cursor: null}),
    receiptGet: () => {const e = new Error("nf"); e.status = 404; throw e;},
    post: () => {throw new Error("unused");},
  });
  h.mod.open(); await h.flush();
  const t = h.mod._test;
  const audit = markup => {
    let depth = 0;
    for (const m of markup.matchAll(/<\/?button/g)) {depth += m[0] === "<button" ? 1 : -1; if (depth > 1) return false; if (depth < 0) return false;}
    return depth === 0;
  };
  assert.ok(audit(h.element("ci-body").innerHTML), "idle+list state");
  await t.pick(h.fileOf(FIX + "合成选定聊天.zip")); await h.flush();
  assert.ok(audit(h.element("ci-body").innerHTML), "preview state");
  t.ui.deleting = "imp_x1"; t.paint();
  assert.ok(audit(h.element("ci-body").innerHTML), "delete-confirm state");
  t.ui.selectedBatch = "imp_x1"; t.ui.batchDetail = {import_id: "imp_x1", messages: [{id: "message-1", author: "a", sent_at: null, text: "x"}]}; t.paint();
  assert.ok(audit(h.element("ci-body").innerHTML), "detail state");
});

test("scoped-store remove returns verifiable boolean (cross-file)", () => {
  const storeSrc = fs.readFileSync("src/wearing/web/scoped-store.js", "utf8");
  assert.match(storeSrc, /remove\(name\) \{ try \{ this\.backend\.removeItem\(this\.key\(name\)\); return true; \} catch \{ return false; \} \}/);
});
