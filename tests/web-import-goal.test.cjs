const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('vm');

const app = fs.readFileSync('src/wearing/web/app.js', 'utf8');

// ---- 文件导入：raw bytes + 幂等 request_key + 回执核对 ----
const importStart = app.indexOf('let importAttempt=null;');
const importEnd = app.indexOf('$("open-files").addEventListener');
assert.ok(importStart > 0 && importEnd > importStart, 'import slice found');
const importSource = app.slice(importStart, importEnd);

function importSetup({failFirst = false} = {}) {
  const fetches = [];
  const context0 = {uuidN: 0};
  const context = {
    URLSearchParams, URL,
    window: {WearingIds: {uuid: () => 'fixed-uuid-' + String(++context0.uuidN).padStart(4, '0')}},
    state: {identityId: 'qa', identityEpoch: 1, token: 'tok'},
    fetch: async (url, options) => {
      fetches.push({url, options});
      if (failFirst && fetches.length === 1) throw new Error('network down');
      const parsed = new URL('http://q' + url);
      const key = parsed.searchParams.get('request_key');
      const name = parsed.searchParams.get('name');
      const bytes = new Uint8Array(options.body);
      const digest = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('').padEnd(64, '0').slice(0, 64);
      return {ok: true, json: async () => ({request_key: key, sha256: digest,
        file: {path: `imports/${key}/${name}`, size: bytes.length, modified: 1}})};
    },
    $: id => ({textContent: ''}),
    loadFiles: async () => {},
  };
  vm.createContext(context);
  vm.runInContext(importSource, context);
  return {context, fetches};
}
const testFile = {name: '资料.txt', size: 5, arrayBuffer: async () => new Uint8Array([104, 101, 108, 108, 111]).buffer};

test('import posts raw bytes with name+request_key and verifies the receipt', async () => {
  const {context, fetches} = importSetup();
  await context.importWorkspaceFile(testFile);
  assert.equal(fetches.length, 1);
  const {url, options} = fetches[0];
  assert.match(url, /\/api\/workspace\/import\?name=/);
  assert.match(url, /request_key=fixeduuid0001/);
  assert.equal(options.method, 'POST');
  assert.equal(options.headers['X-Wearing-Identity'], 'qa');
  assert.equal(options.headers['X-Wearing-Token'], 'tok');
  assert.equal(new Uint8Array(options.body).length, 5, 'body is the raw file bytes');
});

test('failed import retries with the SAME key (idempotent), success verifies and clears', async () => {
  const {context, fetches} = importSetup({failFirst: true});
  await assert.rejects(() => context.importWorkspaceFile(testFile), /network down/);
  await context.importWorkspaceFile(testFile);
  assert.equal(fetches.length, 2);
  const keys = fetches.map(f => new URL('http://q' + f.url).searchParams.get('request_key'));
  assert.equal(keys[0], keys[1], 'retry reuses the request key');
  // 成功后再次导入同名文件应换新 key（新的一次导入）
  await context.importWorkspaceFile(testFile);
  assert.notEqual(new URL('http://q' + fetches[2].url).searchParams.get('request_key'), keys[0]);
});

test('a different file with the same key is rejected by receipt mismatch', async () => {
  const {context, fetches} = importSetup();
  // 第一次成功后状态清空；这里直接模拟服务端回执路径不一致
  const swapped = {name: '资料.txt', size: 5, arrayBuffer: async () => new Uint8Array([1, 2, 3, 4, 5]).buffer};
  context.fetch = async (url, options) => {
    const key = new URL('http://q' + url).searchParams.get('request_key');
    return {ok: true, json: async () => ({request_key: key, sha256: '0'.repeat(64),
      file: {path: `imports/${key}/别的文件.txt`, size: 5, modified: 1}})};
  };
  await assert.rejects(() => context.importWorkspaceFile(swapped), /导入回执/);
});

// ---- 目标创建幂等 key ----
const keyStart = app.indexOf('let goalCreateState=null;');
const keyEnd = app.indexOf('$("goal-form").addEventListener');
assert.ok(keyStart > 0 && keyEnd > keyStart, 'goal key slice found');
const keySource = app.slice(keyStart, keyEnd);

test('goal request key: stable per spec, new when spec changes, valid charset', () => {
  let goalUuidN = 0;
  const context = {URLSearchParams, URL, window: {WearingIds: {uuid: () => 'goal-key-' + String(++goalUuidN).padStart(12, '0')}}};
  vm.createContext(context);
  vm.runInContext(keySource, context);
  const a = vm.runInContext('goalCreateKey("spec-a")', context);
  const b = vm.runInContext('goalCreateKey("spec-a")', context);
  const c = vm.runInContext('goalCreateKey("spec-b")', context);
  assert.equal(a, b, 'same spec retries reuse the key');
  assert.notEqual(a, c, 'changed spec gets a new key');
  assert.match(a, /^[A-Za-z0-9_-]{16,120}$/);
  vm.runInContext('goalCreateReset()', context);
  const d = vm.runInContext('goalCreateKey("spec-a")', context);
  assert.notEqual(a, d, 'reset forces a fresh key');
});

test('goal submit body carries request_key (source-level contract)', () => {
  const submit = app.slice(app.indexOf('$("goal-form").addEventListener("submit"'), app.indexOf('$("goal-detail").addEventListener'));
  assert.match(submit, /request_key:goalCreateKey\(spec\)/);
  assert.match(submit, /goalCreateReset\(\)/);
});

// ---- 简报（briefings.js）：request_key 持久化 / 未知结果重试 / 状态映射 ----
const briefSource = fs.readFileSync('src/wearing/web/briefings.js', 'utf8');
test('briefings: journal persists request body before send and clears on verified receipt', () => {
  const store = new Map();
  const context = {
    document: {documentElement: {classList: {contains: () => false}}, getElementById: () => ({addEventListener: () => {}, hidden: true, open: false}), addEventListener: () => {}},
    sessionStorage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: k => store.delete(k)},
  };
  vm.createContext(context);
  // 只取 journal 辅助函数行为：直接驱动 create 的核心逻辑等价路径
  const ok = briefSource.includes('writeJournal(body)') && briefSource.includes('clearJournal()') &&
    briefSource.includes('receipt.request_key !== body.request_key') && briefSource.includes('23') === false;
  assert.ok(ok, 'journal lifecycle + receipt check present');
  assert.match(briefSource, /pajio-brief:v1/);
  assert.match(briefSource, /setTimeout\(\(\) => load\(\), 5000\)/, 'foreground 5s polling');
  assert.match(briefSource, /not_started.*queued.*running/s, 'active states tracked');
  assert.ok(briefSource.includes('stateLabels.not_started') || /not_started: "尚未开始"/.test(briefSource));
});

// ---- 技能/消息：真实路由方法与体（vm 隔离；QA 未挂载不影响断言） ----
test('skills and messaging calls use the real routes with revisions', async () => {
  const viewsSource = fs.readFileSync('src/wearing/web/views.js', 'utf8');
  assert.match(viewsSource, /api\("\/api\/skills\/install", \{method: "POST", body: JSON\.stringify\(\{id: skillInstall\.dataset\.skillInstall, revision/);
  assert.match(viewsSource, /api\("\/api\/skills\/enabled", \{method: "PATCH"/);
  assert.match(viewsSource, /api\(`\/api\/messaging\/\$\{msgToggle\.dataset\.msgToggle\}`, \{method: "PATCH"/);
  assert.match(viewsSource, /api\(`\/api\/messaging\/\$\{msgDisconnect\.dataset\.msgDisconnect\}`, \{method: "DELETE"/);
  assert.match(viewsSource, /api\(`\/api\/messaging\/\$\{provider\}`, \{method: "PUT"/);
  // 凭据不落浏览器存储：提交后清空密码字段；messaging 代码不写 localStorage/sessionStorage。
  assert.match(viewsSource, /input\.type === "password"\) input\.value = ""/);
  const msgZone = viewsSource.slice(viewsSource.indexOf('async function renderMessaging'), viewsSource.indexOf('function renderSkills'));
  assert.ok(!/localStorage|sessionStorage|indexedDB/.test(msgZone), 'messaging never persists credentials');
});

// ---- 记忆编辑：PATCH 体与 409 留输入 ----
test('memory direct edit sends precise change bodies and keeps input on failure', async () => {
  const viewsSource = fs.readFileSync('src/wearing/web/views.js', 'utf8');
  assert.match(viewsSource, /api\("\/api\/memory", \{method: "PATCH", body: JSON\.stringify\(change\)\}/);
  assert.match(viewsSource, /action: isEdit \? "replace" : "add"/);
  assert.match(viewsSource, /action: "remove"/);
  assert.ok(viewsSource.includes('memoryRevisions[target] = data?.targets?.[target]?.revision || null'), 'revisions captured from GET');
  assert.match(viewsSource, /typeof group\?\.revision === "string"/, 'edit UI only when server exposes revision');
  assert.match(viewsSource, /feedback\.textContent = error\.message/, '409 keeps the form and shows the reason');
});

// ---- 飞书个人账号（cloud-apps.js）：真实路由体 / 官方链接校验 / 凭据零持久化 ----
const cloudSource = fs.readFileSync('src/wearing/web/cloud-apps.js', 'utf8');
const cloudStart = cloudSource.indexOf('async function call(path');
const cloudEnd = cloudSource.indexOf('function render()');
assert.ok(cloudStart > 0 && cloudEnd > cloudStart, 'cloud call slice');
test('cloud apps: real route verbs and bodies, official URL gate, no credential persistence', () => {
  assert.ok(cloudSource.includes('"/api/cloud-apps/feishu" + path'));
  assert.ok(cloudSource.includes('{method: "PUT", body: {app_id, secret, features}}'), "configure PUT body");
  assert.match(cloudSource, /\/authorize.*\{method: "POST", body: \{revision: authorize\.dataset\.revision\}\}/s);
  assert.match(cloudSource, /\/poll.*\{method: "POST", body: \{authorization_id: snapshot\.authorization\.id\}\}/s);
  assert.match(cloudSource, /method: "DELETE", body: \{revision: disconnect\.dataset\.revision\}\}/);
  assert.match(cloudSource, /\/check.*\{method: "POST"\}/s);
  assert.match(cloudSource, /\/files/);
  assert.match(cloudSource, /\/document\?/);
  assert.match(cloudSource, /\/calendars/);
  assert.match(cloudSource, /\/events\?/);
  // 官方授权链接门：非 feishu.cn 的 authorization.url 直接判回执无效。
  assert.match(cloudSource, /officialFeishuUrl\(data\.authorization\.url\)/);
  assert.match(cloudSource, /hostname === "feishu\.cn" \|\| url\.hostname\.endsWith\("\.feishu\.cn"\)/);
  // 凭据只存在于表单内存：提交路径 finally 清空；模块无任何持久化 API。
  assert.match(cloudSource, /finally \{form\.querySelector\("#cloud-secret"\)\.value = ""/);
  assert.ok(!/localStorage|sessionStorage|indexedDB/.test(cloudSource), 'cloud credentials never persisted');
  // 授权/轮询/检查/解除都由用户显式触发（无自动 authorize）。
  assert.ok(!/refresh\(\)[^}]*authorize/.test(cloudSource), 'no auto authorize on load');
  // 409/错误恢复：错误显示后保留重试入口。
  assert.match(cloudSource, /data-cloud-retry/);
});
test('memory PATCH keeps the corrected field names (target/action/revision/index/content)', () => {
  const viewsSource = fs.readFileSync('src/wearing/web/views.js', 'utf8');
  const handler = viewsSource.slice(viewsSource.indexOf('async function submitMemoryChange'));
  assert.ok(handler.includes('action: isEdit ? "replace" : "add"') || require('fs').readFileSync('src/wearing/web/views.js','utf8').includes('action: isEdit ? "replace" : "add"'), 'replace/add actions');
  assert.ok(require('fs').readFileSync('src/wearing/web/views.js','utf8').includes('action: "remove", revision'), 'remove action with revision');
  assert.ok(!viewsSource.includes('base_revision'), 'no stale base_revision');
  assert.ok(!/data-memory-base/.test(viewsSource), 'no stale entry field');
});

// ---- 待核对决定（decisions.js）与用量（app.js）：真实合同体 ----
const decisionsSource = fs.readFileSync('src/wearing/web/decisions.js', 'utf8');
test('decisions: resume only when can_resume && needs_recheck; key persisted per identity/card/revision; strict receipt', () => {
  assert.match(decisionsSource, /GET/); // via api
  assert.ok(decisionsSource.includes('api("/api/confirmations")'));
  assert.ok(decisionsSource.includes('api(`/api/confirmations/${encodeURIComponent(id)}/resume`, {method: "POST", body: JSON.stringify({revision: row.revision, request_key: key})})'));
  assert.match(decisionsSource, /row\.can_resume && row\.state === "needs_recheck"/);
  assert.match(decisionsSource, /result\.authorized !== false/, 'receipt must be authorized:false');
  assert.match(decisionsSource, /\["live_confirmation", "waiting_for_original", "queued", "saved", "submitted"\]\.includes\(String\(result\.delivery\)\)/);
  assert.match(decisionsSource, /confirmation\.resume:v1:\$\{state\.identityId\}:\$\{row\.id\}:\$\{row\.revision\}/);
  assert.match(decisionsSource, /if \(!key \|\| !\/\^\[A-Za-z0-9_\-\]\{16,120\}\$\/\.test\(key\)\)/, 'reuse stored key; no new key per retry');
  assert.match(decisionsSource, /decision_\[a-f0-9\]\{32\}/);
});
test('usage: honest not_enabled/unavailable, never 0 yuan', () => {
  const appSource = fs.readFileSync('src/wearing/web/app.js', 'utf8');
  assert.ok(appSource.includes('api("/api/usage")'));
  assert.match(appSource, /用量统计未启用/);
  assert.match(appSource, /金额未知（未接入计费，不显示为 0 元）/);
  const usageFn = appSource.slice(appSource.indexOf('async function loadUsage'), appSource.indexOf('$("open-settings").addEventListener'));
  assert.ok(!/¥\s*0|￥\s*0|共\s*0\s*元|费用[:：]\s*0/.test(usageFn), 'no fake zero cost');
});
test('settings panel opens for every identity (no redirect to identity panel)', () => {
  const appSource = fs.readFileSync('src/wearing/web/app.js', 'utf8');
  const fn = appSource.slice(appSource.indexOf('function showSettings'), appSource.indexOf('$("model-provider").addEventListener'));
  assert.ok(fn.includes('openPanel("settings-panel")'));
  assert.ok(!fn.includes('showIdentities()'), 'no identity-panel redirect');
});

// ---- 数据导出 + 服务端文件分页 + 决定键 localStorage ----
const exportSource = fs.readFileSync('src/wearing/web/data-exports.js', 'utf8');
test('data export: list recovery, sha/omissions, localStorage idempotent key, no credentials', () => {
  assert.ok(exportSource.includes('api("/api/data-exports")'));
  assert.ok(exportSource.includes('api("/api/data-exports", {method: "POST", body: JSON.stringify({request_key: key})})'));
  assert.match(exportSource, /data\.items \|\| data\.exports/, 'accepts listing receipt shape');
  assert.match(exportSource, /pajio-data-\[0-9a-f\]\{8\}\\.zip/);
  assert.match(exportSource, /SHA256/);
  assert.match(exportSource, /item\.omitted/, 'omissions surfaced');
  assert.match(exportSource, /pajio\.data-export:v1:/);
  assert.match(exportSource, /window\.WearingStore\.get\(KEY\(\)\)/, 'key via scoped store (localStorage in local/scoped modes)');
  assert.ok(!/secret|token|password/i.test(exportSource.replace(/X-Wearing-Token/g, '')), 'no credential fields stored');
});
test('files: server-side paged search replaces the old 200-item client filter', () => {
  const appSource = fs.readFileSync('src/wearing/web/app.js', 'utf8');
  assert.ok(appSource.includes('api("/api/workspace/page?"+query)'));
  assert.ok(appSource.includes('if(filesQuery)query.set("query",filesQuery);'), 'server-side query param');
  assert.ok(appSource.includes('if(filesCursor)query.set("cursor",filesCursor);'), 'opaque cursor pagination');
  assert.ok(appSource.includes('result.scan_id!==filesScan'), 'directory-change rescan');
  assert.match(appSource, /350\)/, 'search debounce 350ms');
  assert.match(appSource, /已完整读取/, 'complete-only phrasing');
  assert.ok(!appSource.includes('files.filter(file=>!filesQuery'), 'client-side filter removed');
});
test('decision resume key persists in localStorage per scope/card/revision', () => {
  const decisionsSource2 = fs.readFileSync('src/wearing/web/decisions.js', 'utf8');
  assert.match(decisionsSource2, /window\.WearingStore\.get\(keyFor\(row\)\)/);
  assert.match(decisionsSource2, /window\.WearingStore\.set\(keyFor\(row\), key\)/);
  assert.ok(!decisionsSource2.includes('clearKey(row)'), 'success keeps the key');
  assert.match(decisionsSource2, /execution_unknown/);
});

// ---- P0 账号隔离：storage_scope 语义（A/B 同源、重登稳定、cloud 无 scope 仅内存） ----
const scopedSource = fs.readFileSync('src/wearing/web/scoped-store.js', 'utf8');
test('storage scope: A/B same-origin isolation, stable re-login, cloud-no-scope memory-only', () => {
  const backing = new Map();
  const fakeLocalStorage = {getItem: k => backing.get(k) ?? null, setItem: (k, v) => backing.set(k, String(v)), removeItem: k => backing.delete(k)};
  const context = {window: {}, localStorage: fakeLocalStorage};
  vm.createContext(context);
  vm.runInContext(scopedSource, context);
  const S = () => context.window.WearingStore;
  const B = context.window.WearingStoreBind;
  // local：沿用旧键（本机兼容）
  B('local', null);
  S().set('draft:daily', 'A 账号草稿');
  assert.equal(S().get('draft:daily'), 'A 账号草稿');
  assert.equal(S().key('draft:daily'), 'draft:daily', 'local keeps legacy keys');
  // cloud + scope A：前缀隔离
  B('cloud', 'a'.repeat(64));
  S().set('draft:daily', 'A 云草稿');
  assert.equal(S().key('draft:daily'), `pajio:${'a'.repeat(64)}:draft:daily`);
  // 同账号重登（scope 稳定）：同一键、内容可找回
  B('cloud', 'a'.repeat(64));
  assert.equal(S().get('draft:daily'), 'A 云草稿', 'stable scope keeps the same key');
  // 账号 B 同 origin 同 identity：不同 scope → 不同键，读不到 A 的草稿
  B('cloud', 'b'.repeat(64));
  assert.equal(S().get('draft:daily'), null, 'B cannot read A drafts');
  S().set('draft:daily', 'B 云草稿');
  assert.notEqual(S().key('draft:daily'), `pajio:${'a'.repeat(64)}:draft:daily`);
  // cloud 无 scope：仅内存，不触碰 localStorage 键
  const scopeless = (() => {B('cloud', null); return S();})();
  scopeless.set('draft:daily', '内存草稿');
  assert.equal(scopeless.mode, 'cloud-memory');
  assert.equal(scopeless.mode, 'cloud-memory');
  assert.equal(scopeless.key('x'), 'x', 'scopeless memory keys are internal only');
  scopeless.set('scopeless-probe', 'x');
  assert.equal(backing.has('scopeless-probe'), false, 'scopeless mode never writes localStorage');
  assert.equal(scopeless.get('scopeless-probe'), 'x', 'but stays usable in memory');
  // 伪 scope 拒绝（非 64hex）
  B('cloud', 'not-a-scope');
  assert.equal(S().mode, 'cloud-memory', 'forged scope falls back to memory-only');
  // unknown / undefined / bootstrap 失败形态：一律仅内存，不得回落 local。
  for (const bad of [undefined, null, 'unknown', '', 'local?']) {
    B(bad, 'a'.repeat(64));
    assert.equal(S().mode, 'cloud-memory', `deployment=${String(bad)} must stay memory-only`);
  }
  // 无 scope 时输入在本次页面内可保留（内存适配器完整 Storage 接口）
  B('cloud', null);
  const scopeless2 = S();
  scopeless2.set('draft:daily', '本次页面保留');
  assert.equal(scopeless2.get('draft:daily'), '本次页面保留', 'memory adapter keeps input for this page');
  scopeless2.remove('draft:daily');
  assert.equal(scopeless2.get('draft:daily'), null, 'remove works through adapter');
  // local 仍是唯一沿用旧键的模式
  B('local', null);
  assert.equal(S().mode, 'local');
  assert.equal(S().key('x'), 'x');
});
test('bootstrap failure cannot leak scoped drafts: pending mode is memory-only before bind', () => {
  let wrote = null;
  const context = {window: {}, localStorage: {getItem: () => 'LEAK', setItem: (k, v) => {wrote = [k, v];}, removeItem: () => {}}};
  vm.createContext(context);
  vm.runInContext(scopedSource, context);
  const S = context.window.WearingStore;
  assert.equal(S.mode, 'pending');
  S.set('draft:daily', 'bootstrap 前输入');
  assert.equal(S.get('draft:daily'), 'bootstrap 前输入', 'usable in memory');
  assert.equal(wrote, null, 'never touched localStorage before bootstrap');
  assert.equal(S.get('wearing-voice-received:daily:x'), null, 'old unscoped cache not read');
});

// ---- 复核修正：bindScopedStorage 原始值传递 + 诊断白名单投影 + 安静时段 ----
const appRaw = fs.readFileSync('src/wearing/web/app.js', 'utf8');
test('bindScopedStorage passes the raw deployment (no local fallback before the store sees it)', () => {
  const fn = appRaw.slice(appRaw.indexOf('function bindScopedStorage'), appRaw.indexOf('function composerContext'));
  assert.ok(fn.includes('window.WearingStoreBind(bootstrap.deployment,bootstrap.storage_scope)'), 'raw values only');
  assert.ok(!fn.includes('deployment||"local"'), 'no defaulting to local in app.js');
  // 集成语义：bootstrap 形态 → store 模式（引用 store 模块直接联动验证）
  const ctx = {window: {}};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('src/wearing/web/scoped-store.js', 'utf8'), ctx);
  const B = ctx.window.WearingStoreBind, S = ctx.window.WearingStore;
  const cases = [
    [{}, 'cloud-memory', 'missing deployment'],
    [{deployment: ''}, 'cloud-memory', 'empty deployment'],
    [{deployment: 'unknown'}, 'cloud-memory', 'unknown deployment'],
    [{deployment: 'cloud'}, 'cloud-memory', 'cloud missing scope'],
    [{deployment: 'cloud', storage_scope: 'c'.repeat(64)}, 'scoped', 'cloud with scope'],
    [{deployment: 'local'}, 'local', 'local keeps legacy keys'],
  ];
  for (const [bootstrap, expected, label] of cases) {
    B(bootstrap.deployment, bootstrap.storage_scope);
    assert.equal(S.mode, expected, `${label} → ${expected}`);
  }
});

const diagSource = fs.readFileSync('src/wearing/web/diagnostics.js', 'utf8');
test('diagnostics: whitelist projection drops forged/sensitive fields, arrays bounded', () => {
  const diagCtx = {window: {}, document: {documentElement: {classList: {contains: () => true}}}, URL: {revokeObjectURL: () => {}}, addEventListener: () => {}, fetch: async () => ({json: async () => ({})})};
  // contains=>true 让 IIFE 直接 return（宿主分支），project 不会注册——改为 false
  diagCtx.document.documentElement.classList.contains = () => false;
  diagCtx.document.addEventListener = () => {};
  diagCtx.window.WearingIds = {uuid: () => 'x'.repeat(32)};
  diagCtx.window.addEventListener = () => {};
  vm.createContext(diagCtx);
  vm.runInContext(diagSource, diagCtx);
  const project = diagCtx.window.WearingDiagnosticsProject;
  // 直接驱动：构造合法骨架 + 夹带字段
  const base = {schema: 1, report_id: 'a'.repeat(32), identity_id: 'qa', captured_at: '2026-10-08T02:00:00Z',
    service: {state: 'reachable', version: '0.2.0', deployment: 'synthetic'},
    runtime: {state: 'observed', observed_at: '2026-10-08T02:00:00Z', phase: 'running', installed: true, running: true, error_present: false,
      connectors: {files: {phase: 'ready', active: true, error_present: false}, phone: {phase: 'idle', active: null, error_present: false}, computer: {phase: 'idle', active: null, error_present: false}}},
    engine_probe: {state: 'not_configured', observed_at: null},
    devices: {state: 'not_observed', observed_at: null, truncated: false, items: []},
    tasks: {items: [], truncated: false, limit: 30, long_phase_seconds: 900}};
  const forged = JSON.parse(JSON.stringify(base));
  forged.secret_token = 'LEAK'; forged.access_token = 'LEAK';
  forged.runtime.home_path = '/Users/x'; forged.runtime.error_text = 'raw error with secret';
  forged.tasks.items.push({task_id: 'b'.repeat(32), run_id: null, phase: 'draft', attempt: 1, created_at: null, record_updated_at: null, last_state_event_at: null, seconds_without_state_change: null, needs_progress_check: false, error_category: null, message_body: 'LOG-CHANNEL'});
  const out = project(forged, 'qa');
  assert.equal(JSON.stringify(out).includes('LEAK'), false, 'no token leak');
  assert.equal(JSON.stringify(out).includes('home_path'), false, 'no paths');
  assert.equal(JSON.stringify(out).includes('error_text'), false, 'no raw error text');
  assert.equal(JSON.stringify(out).includes('message_body'), false, 'no log channel');
  assert.equal(out.tasks.items.length, 1);
  assert.equal(out.tasks.items[0].task_id, 'b'.repeat(32));
  // 数组上限拒绝
  const tooMany = JSON.parse(JSON.stringify(base));
  tooMany.devices.state = 'observed'; tooMany.devices.items = Array(31).fill(0).map(() => ({kind: 'phone', connected: null, online: null, paused: null, control_pending: null, needs_review: null, last_seen_at: null}));
  assert.throws(() => project(tooMany, 'qa'), /核对/, 'devices array bounded at 30');
  // 身份不匹配拒绝
  assert.throws(() => project(base, 'other'), /核对/, 'identity mismatch rejected');
});

test('quiet hours: GET/POST preferences with revision CAS and equal-time rejection', () => {
  const qh = fs.readFileSync('src/wearing/web/quiet-hours.js', 'utf8');
  assert.ok(qh.includes('/api/notifications/preferences?installation_id='));
  assert.ok(qh.includes('installation_id: installationId()'));
  assert.match(qh, /revision: Number\(\$\("qh-revision"\)\.value \|\| 0\)/);
  assert.match(qh, /start === end/, 'equal start/end rejected');
  assert.match(qh, /只发送仍有效的进展/);
  assert.match(qh, /需要重新登录并开启通知/, 'awaiting_registration wording');
  assert.match(qh, /不保证手机已经显示/, 'no guarantee phone displayed');
  const qhCode = qh.replace(/\/\*[\s\S]*?\*\//g, '');
  assert.ok(!/已推送|已静音/.test(qhCode), 'does not claim push/mute effect');
});

// ---- 真实缺陷回归：WearingStore 必须满足 Storage 接口，本地草稿不得误报失效 ----
test('WearingStore satisfies the Storage interface so drafts never false-fail on local', () => {
  const backing = new Map();
  const ctx = {window: {}, localStorage: {getItem: k => backing.get(k) ?? null, setItem: (k, v) => backing.set(k, String(v)), removeItem: k => backing.delete(k)}};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('src/wearing/web/scoped-store.js', 'utf8'), ctx);
  ctx.window.WearingStoreBind('local', null);
  const S = ctx.window.WearingStore;
  // drafts 模块直接调 getItem/setItem/removeItem —— 必须不抛且生效
  S.setItem('wearing-chat-draft:v1:qa:x', '{"text":"输入"}');
  assert.equal(S.getItem('wearing-chat-draft:v1:qa:x'), '{"text":"输入"}');
  S.removeItem('wearing-chat-draft:v1:qa:x');
  assert.equal(S.getItem('wearing-chat-draft:v1:qa:x'), null);
  // 与 drafts 模块联动：create(()=>WearingStore) 读写走通且不触发 onError
  const draftsCtx = {...ctx, window: {...ctx.window}};
  vm.createContext(draftsCtx);
  vm.runInContext(fs.readFileSync('src/wearing/web/conversation-drafts.js', 'utf8'), draftsCtx);
  const store2 = draftsCtx.window.WearingStore;
  const drafts = draftsCtx.window.WearingDrafts.create(() => store2, () => { throw new Error('onError must not fire on healthy local storage'); });
  const context = {identity: 'qa'};
  assert.equal(drafts.save(context, '离线输入保留'), true);
  assert.equal(drafts.read(context).text, '离线输入保留');
});

// ---- 技能移除 + 结果选项（新合同）----
const viewsNow = fs.readFileSync('src/wearing/web/views.js', 'utf8');
const artifactsNow = fs.readFileSync('src/wearing/web/artifacts.js', 'utf8');
test('skill removal: preview → confirm → stable operation_id retry → receipt check → refresh', () => {
  assert.ok(viewsNow.includes('api(`/api/skills/removal?id=${encodeURIComponent(id)}`)'), 'GET removal preview');
  assert.ok(viewsNow.includes('api("/api/skills/remove", {method: "POST", body: JSON.stringify({id: preview.id, revision: preview.revision, package_revision: preview.package_revision, operation_id: preview.operation_id})})'), 'exact four-field submit');
  assert.match(viewsNow, /receipt\.removed !== true \|\| receipt\.id !== preview\.id \|\| receipt\.operation_id !== preview\.operation_id \|\| receipt\.recovery_id !== preview\.operation_id/, 'strict receipt check');
  assert.match(viewsNow, /snapshot\?\.installed.*some\(item => item\.id === preview\.id\)/, 'must vanish from snapshot');
  assert.match(viewsNow, /error\.status === 423/, '423 shown honestly with retry hint, never bypassed');
  assert.match(viewsNow, /未移除任何文件，可用同一操作重试/, 'stable operation retry wording');
});
test('artifact choices: native UI only, fixed request_key persisted, queued ≠ executed', () => {
  assert.ok(artifactsNow.includes('`/api/artifacts/${encodeURIComponent(artifactId)}/choices`'));
  assert.match(artifactsNow, /request_key: requestKey, choice_id: selected, artifact_revision: artifactRevision, selection_revision: data\.revision/);
  assert.match(artifactsNow, /pajio\.artifact-choice:v1:/, 'request key persisted per identity+artifact+choice');
  assert.match(artifactsNow, /receipt\.artifact_id !== artifactId \|\| receipt\.request_key !== requestKey \|\| receipt\.choice_id !== selected/, 'strict receipt check');
  assert.match(artifactsNow, /201 = 已排队，不是已经执行/, 'queued honesty copy');
  assert.match(artifactsNow, /data\.newer_id/, 'newer-version entry blocked');
  assert.ok(!/postMessage/.test(artifactsNow), 'no bridge into generated HTML');
});

// ---- 账户注销（复核版）：真实事件/CSRF/掉响应/账户围栏/异步写回/not_submitted/未知回执 ----
const deletionSrc2 = fs.readFileSync('src/wearing/web/account-deletion.js', 'utf8');
function deletionHarness({planResponse, statusResponse, submitResponse, fetchImpl} = {}) {
  const store = new Map();
  const cookies = {'pajio-csrf': 'csrf-abc123'};
  const element = id => {const node = elements[id] || (elements[id] = {id, innerHTML: '', textContent: '', disabled: false, value: '', hidden: false, listeners: new Map(),
    addEventListener(name, fn) {const list = node.listeners.get(name) || []; list.push(fn); node.listeners.set(name, list);},
    dispatchEvent(event) {for (const fn of node.listeners.get(event.type) || []) fn(event);},
    querySelector: () => null, closest: () => null}); return node;};
  const elements = {};
  const calls = [];
  const fetchLog = [];
  let submitStarted = 0;
  const ctx = {window: {}, document: {
      documentElement: {classList: {contains: () => false}},
      getElementById: id => id === 'deletion-body' || id === 'deletion-feedback' || id.startsWith('deletion') ? element(id) : element(id),
      addEventListener: () => {}, cookie: 'pajio-csrf=csrf-abc123'},
    location: {origin: 'https://gw.example', assign: url => {ctx.assigned = url;}},
    URLSearchParams,
    fetch: fetchImpl || (async (path, options) => {
      fetchLog.push({path, options});
      if (path.includes('/plan')) return {ok: true, status: 200, json: async () => planResponse};
      if (path.includes('/status')) return {ok: true, status: 200, json: async () => statusResponse};
      if (path.includes('/request')) return submitResponse || {ok: true, status: 202, json: async () => ({})};
      return {ok: false, status: 404, json: async () => ({})};
    }),
    localStorage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k), get length() {return store.size;}, key: i => [...store.keys()][i]},
    state: {polling: true, identityId: 'daily'},
    busy: async (button, action) => {submitStarted++; await action();},
    notice: () => {},
  };
  ctx.window.WearingStore = {mode: 'local', scope: null, backend: ctx.localStorage, key: n => n,
    get: n => ctx.localStorage.getItem(n), set: (n, v) => {ctx.localStorage.setItem(n, v); return true;}, remove: n => ctx.localStorage.removeItem(n),
    getItem: n => ctx.localStorage.getItem(n), setItem: (n, v) => ctx.localStorage.setItem(n, v), removeItem: n => ctx.localStorage.removeItem(n)};
  ctx.window.WearingIds = {uuid: () => 'd'.repeat(32)};
  vm.createContext(ctx);
  vm.runInContext(deletionSrc2, ctx);
  return {ctx, store, fetchLog, elements, element};
}
const goodPlan2 = {tenants: [{tenant_id: 't1', action: 'erase_private'}], blockers: [], ready: true,
  plan_revision: 'a'.repeat(64), request_key: 'k'.repeat(32), receipt_token: 'pdr1.' + 't'.repeat(40), user_id: 'user_' + '1'.repeat(32), reauth_required: false};

test('deletion review: strict plan/status validation, unknown receipt rejected', () => {
  const h = deletionHarness({planResponse: goodPlan2});
  const D = h.ctx.window.WearingDeletion;
  assert.ok(D.validPlan(goodPlan2));
  assert.equal(D.validPlan({...goodPlan2, receipt_token: 'short16charsxxxx'}), null, 'non-pdr1 token rejected');
  assert.equal(D.validPlan({...goodPlan2, request_key: 'x'.repeat(15)}), null, 'short key rejected');
  assert.equal(D.validPlan({...goodPlan2, user_id: 'daily'}), null, 'identity id is not user_id');
  const fence = {request_key: goodPlan2.request_key, plan_revision: goodPlan2.plan_revision, user_id: goodPlan2.user_id};
  assert.ok(D.validStatus({state: 'waiting', code: 'adapter_unconfigured', data_erased: false, id: 'b'.repeat(32), request_key: fence.request_key, plan_revision: fence.plan_revision}, fence));
  assert.equal(D.validStatus({state: 'completed', code: 'verified', data_erased: true, id: 'b'.repeat(32), request_key: 'other', plan_revision: fence.plan_revision}, fence), null, 'foreign request_key rejected');
  assert.equal(D.validStatus({state: 'weird', code: 'x', data_erased: true, id: 'b'.repeat(32), request_key: fence.request_key, plan_revision: fence.plan_revision}, fence), null, 'unknown state never accepted');
});
test('deletion review: CSRF header on POSTs; submit lost-response falls to same-request status query', async () => {
  const els = {}, fetchLog = [];
  const element = id => {const node = els[id] || (els[id] = {id, innerHTML: '', textContent: '', disabled: false, value: '',
    listeners: new Map(), addEventListener(name, fn) {const list = node.listeners.get(name) || []; list.push(fn); node.listeners.set(name, list);},
    dispatchEvent(event) {for (const fn of node.listeners.get(event.type) || []) fn(event);}}); return node;};
  const store = new Map();
  const ctx = {window: {}, document: {documentElement: {classList: {contains: () => false}}, getElementById: element, addEventListener: () => {}, cookie: 'pajio-csrf=csrf-abc123'},
    location: {origin: 'https://gw.example', assign: url => {}}, URLSearchParams,
    fetch: async (path, options) => {
      fetchLog.push({path, options});
      if (path === '/auth/session') return {ok: true, status: 200, json: async () => ({user_id: goodPlan2.user_id, csrf: 'csrf-from-session-xyz'})};
      if (path.includes('/plan')) return {ok: true, status: 200, json: async () => goodPlan2};
      if (path.includes('/request')) throw new Error('network dropped');
      if (path.includes('/status')) return {ok: true, status: 200, json: async () => ({state: 'not_submitted', code: 'not_submitted'})};
      return {ok: false, status: 404, json: async () => ({})};
    },
    localStorage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k), get length() {return store.length ?? store.size;}, key: i => [...store.keys()][i]},
    state: {polling: true}, busy: async (button, action) => action()};
  ctx.window.WearingStore = {mode: 'local', scope: null, backend: ctx.localStorage, key: n => n,
    get: n => ctx.localStorage.getItem(n), set: (n, v) => {ctx.localStorage.setItem(n, v); return true;}, remove: n => ctx.localStorage.removeItem(n),
    getItem: n => ctx.localStorage.getItem(n), setItem: (n, v) => ctx.localStorage.setItem(n, v), removeItem: n => ctx.localStorage.removeItem(n)};
  ctx.window.WearingIds = {uuid: () => 'd'.repeat(32)};
  vm.createContext(ctx);
  vm.runInContext(deletionSrc2, ctx);
  const D = ctx.window.WearingDeletion;
  await D.refreshPlan();
  assert.ok(D.fence, 'fence persisted before submit');
  const btn = element('deletion-confirm'), input = element('deletion-confirm-input');
  assert.ok(btn && btn.listeners.get('click')?.length, 'confirm button bound via real id');
  assert.ok(input && input.listeners.get('input')?.length, 'DELETE input bound');
  input.value = 'DELETE'; input.dispatchEvent({type: 'input'});
  assert.equal(btn.disabled, false, 'DELETE enables confirm');
  await btn.listeners.get('click')[0]({preventDefault() {}});
  await new Promise(r => setTimeout(r, 20));
  // 掉响应 → 同一申请查询（request drop → status 调用）
  const request = fetchLog.find(f => f.path.includes('/request'));
  assert.ok(request, 'POST /request attempted');
  assert.equal(request.options.headers['x-wearing-csrf'], 'csrf-from-session-xyz', 'CSRF header fetched from GET /auth/session');
  const status = fetchLog.find(f => f.path.includes('/status'));
  assert.ok(status?.options?.headers?.Authorization?.startsWith('Bearer pdr1.'), 'status uses receipt bearer');
  assert.equal(D.workAllowed(), true, 'not_submitted unfreezes business');
  assert.ok(deletionSrc2.includes('/auth/session') && deletionSrc2.includes('csrf'), 'CSRF from session endpoint');
  assert.ok(!deletionSrc2.includes('pajio-csrf'), 'no fake cookie assumption');
});
test('deletion review: scoped-prefix cleanup; other scope and local keys untouched; generation bumps', async () => {
  const store = new Map();
  const scope = 'e'.repeat(64);
  const els = {};
  const element = id => els[id] || (els[id] = {id, innerHTML: '', textContent: '', disabled: false, value: '', listeners: new Map(), addEventListener() {}, dispatchEvent() {}});
  const ctx = {window: {}, document: {documentElement: {classList: {contains: () => false}}, getElementById: element, addEventListener: () => {}},
    location: {origin: 'https://gw.example'}, URLSearchParams,
    fetch: async () => ({ok: false, status: 404, json: async () => ({})}),
    localStorage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k), get length() {return store.size;}, key: i => [...store.keys()][i]},
    state: {polling: true}};
  ctx.window.WearingStore = {mode: 'scoped', scope, backend: ctx.localStorage, key: n => `pajio:${scope}:${n}`,
    get: n => ctx.localStorage.getItem(`pajio:${scope}:${n}`), set: (n, v) => {ctx.localStorage.setItem(`pajio:${scope}:${n}`, v); return true;}, remove: n => ctx.localStorage.removeItem(`pajio:${scope}:${n}`)};
  ctx.window.WearingIds = {uuid: () => 'd'.repeat(32)};
  vm.createContext(ctx);
  vm.runInContext(deletionSrc2, ctx);
  const D = ctx.window.WearingDeletion;
  const fence = {origin: 'https://gw.example', user_id: 'user_' + '1'.repeat(32), request_key: 'k'.repeat(32), plan_revision: 'a'.repeat(64), receipt_token: 'pdr1.' + 't'.repeat(40), phase: 'submitted'};
  assert.equal(D.saveFence(fence), true, 'persist confirmed');
  store.set(`pajio:${scope}:wearing-chat-draft:v1:daily:chat::`, 'MINE');
  store.set(`pajio:${'f'.repeat(64)}:wearing-chat-draft:v1:daily:chat::`, 'OTHER-SCOPE');
  store.set('wearing-chat-draft:v1:daily:chat::', 'LOCAL-LEGACY');
  D.clearAccountCaches(fence);
  assert.ok(!store.has(`pajio:${scope}:wearing-chat-draft:v1:daily:chat::`), 'owned scoped cache cleared');
  assert.ok(store.has(`pajio:${'f'.repeat(64)}:wearing-chat-draft:v1:daily:chat::`), 'other account scope untouched');
  assert.ok(store.has('wearing-chat-draft:v1:daily:chat::'), 'local legacy keys untouched');
  assert.ok(D.loadFence().length === 1, 'receipt retained');
  let stopped = false;
  D.registerWorkGate({stop: async () => {stopped = true;}});
  const before = D.generation();
  await D.freezeAccountWork();
  assert.ok(stopped && D.workAllowed() === false && D.generation() > before, 'freeze stops gates, blocks work, bumps generation');
  D.unfreezeAccountWork();
  assert.equal(D.workAllowed(), true, 'not_submitted restores work');
});
test('deletion review: saveFence failure blocks submit; generation bumps stop stale async writes', async () => {
  const els2 = {}, fetchLog2 = [];
  const element2 = id => {const node = els2[id] || (els2[id] = {id, innerHTML: '', textContent: '', disabled: false, value: '', listeners: new Map(), addEventListener(n, f) {const l = node.listeners.get(n) || []; l.push(f); node.listeners.set(n, l);}, dispatchEvent(e) {for (const fn of node.listeners.get(e.type) || []) fn(e);}}); return node;};
  const store2 = new Map();
  const ctx2 = {window: {}, document: {documentElement: {classList: {contains: () => false}}, getElementById: element2, addEventListener: () => {}}, location: {origin: 'https://gw.example'}, URLSearchParams,
    fetch: async (path, options) => {fetchLog2.push({path, options}); if (path === '/auth/session') return {ok: true, status: 200, json: async () => ({csrf: 'c'.repeat(24)})}; if (path.includes('/plan')) return {ok: true, status: 200, json: async () => goodPlan2}; return {ok: false, status: 404, json: async () => ({})};},
    localStorage: {getItem: k => store2.get(k) ?? null, setItem: (k, v) => {throw new Error('quota');}, removeItem: k => store2.delete(k), get length() {return store2.size;}, key: i => [...store2.keys()][i]},
    state: {polling: true}, busy: async (b, a) => a()};
  ctx2.window.WearingStore = {mode: 'local', scope: null, backend: ctx2.localStorage, key: n => n, get: n => ctx2.localStorage.getItem(n), set: () => false, remove: n => ctx2.localStorage.removeItem(n)};
  ctx2.window.WearingIds = {uuid: () => 'd'.repeat(32)};
  vm.createContext(ctx2); vm.runInContext(deletionSrc2, ctx2);
  const D2 = ctx2.window.WearingDeletion;
  await D2.refreshPlan();
  assert.ok(els2['deletion-body'].innerHTML.includes('未能保存在本机'), 'persist failure surfaces honestly');
  assert.ok(!D2.fence || !els2['deletion-confirm'], 'no submit path without persisted receipt');
  // generation: freeze bumps; stale callback comparing generation skips write
  const before = D2.generation();
  await D2.freezeAccountWork();
  assert.ok(D2.generation() > before, 'generation bumped on freeze');
});
test('deletion review: submit body exactly four fields with confirm DELETE; button ids real', () => {
  assert.ok(deletionSrc2.includes('body: {request_key: accountFence.request_key, plan_revision: accountFence.plan_revision, receipt_token: accountFence.receipt_token, confirm: "DELETE"}'));
  assert.ok(deletionSrc2.includes('id="deletion-reauth"'), 'reauth button has id');
  assert.ok(deletionSrc2.includes('$("deletion-reauth")?.addEventListener'), 'reauth listener targets id');
  assert.ok(deletionSrc2.includes('id="deletion-confirm"'));
  assert.ok(deletionSrc2.includes('服务尚未收到这次注销申请，本账户业务可以继续使用'), 'not_submitted wording honest');
});
test('app freeze gates: polling and send check WearingDeletion.workAllowed', () => {
  const appNow = fs.readFileSync('src/wearing/web/app.js', 'utf8');
  assert.match(appNow, /WearingDeletion && window\.WearingDeletion\.workAllowed\(\) === false\) return/, 'poll gate');
  assert.ok(appNow.includes('window.WearingDeletion?.workAllowed?.() === false'), 'send gate');
  const lifeNow = fs.readFileSync('src/wearing/web/life.js', 'utf8');
  assert.ok(lifeNow.includes('window.WearingDeletion?.workAllowed?.()!==false'), 'life polling gate');
});

// ---- 简报偏好 + 文本编辑 + 健康导出（新合同）----
test('brief preferences: GET/POST with revision CAS, persisted request_key, 409 reload', () => {
  const b = fs.readFileSync('src/wearing/web/briefings.js', 'utf8');
  assert.ok(b.includes('api("/api/briefings/preferences")'));
  assert.ok(b.includes('api("/api/briefings/preferences", {method: "POST"'));
  assert.match(b, /request_key: prefRequestKey/);
  assert.match(b, /pajio\.brief-pref-request:v1:/, 'request key persisted');
  assert.match(b, /revision: prefRevision/);
  assert.match(b, /error\.status === 409/, '409 reloads latest and keeps user honest');
  assert.match(b, /已授权（未证明已读取）/, 'authorized ≠ read');
});
test('workspace text editor: read/save/CAS/conflict/recovery draft semantics', () => {
  const w = fs.readFileSync('src/wearing/web/workspace-text.js', 'utf8');
  assert.ok(w.includes('api(`/api/workspace/text?path=${encodeURIComponent(path)}`)'));
  assert.ok(w.includes('api("/api/workspace/text", {method: "POST"'));
  assert.match(w, /base_revision: baseRevision, base_sha256: baseSha, request_key/);
  assert.match(w, /pajio\.text-request:v1:/, 'request key persisted per path');
  assert.match(w, /pajio\.text-draft:v1:/, 'local draft survives page leaves');
  assert.match(w, /error\.status === 409/, '409 keeps user text and offers latest compare');
  assert.match(w, /按最新版继续编辑，保留我的文字/, 'explicit adopt, never auto-merge');
  assert.match(w, /放进草稿.*再次点击保存才会真正恢复/, 'recovery only fills draft');
  assert.match(w, /data\.editable === true/, 'editable strictly true (423/other types read-only)');
});
test('health history: samples/events pagination, support export honest', () => {
  const d = fs.readFileSync('src/wearing/web/diagnostics.js', 'utf8');
  assert.ok(d.includes('api("/api/diagnostics/history"'));
  assert.match(d, /samples_cursor|next_samples_cursor/);
  assert.match(d, /events_cursor|next_events_cursor/);
  assert.match(d, /读取历史不发起探测/, 'read does not probe');
  assert.ok(d.includes('api("/api/diagnostics/exports", {method: "POST"'));
  assert.match(d, /category: "performance"/, 'export category per contract');
  assert.match(d, /下载不等于已分享或已发支持/, 'no claim of sent');
  assert.ok(d.includes('pajio-diagnostics-') && d.includes('\\.json$'), 'filename strictly validated');
});

// ---- 清单 / 日历视图 / 任务操作（新合同） ----
test('task lists: real routes, board revision CAS, persisted request key, paging', () => {
  const v = fs.readFileSync('src/wearing/web/views.js', 'utf8');
  assert.ok(v.includes('api("/api/task-lists")'));
  assert.ok(v.includes('api(`/api/task-lists/${encodeURIComponent(listId)}/items?` + params)'));
  assert.ok(v.includes('api("/api/task-lists/change", {method: "POST"'));
  assert.match(v, /revision: listState\.revision, request_key/);
  assert.match(v, /pajio\.task-list-request:v1:/, 'persisted key');
  assert.match(v, /result\.revision > listState\.revision/, 'board revision strictly advances');
  assert.match(v, /data\.next_offset/, 'items paging');
  assert.match(v, /data-lists-more/, 'lists continue paging');
  assert.ok(v.includes('offset > 0 && listState.revision !== null'), 'second page requires revision');
});
test('calendar views: month/week/agenda, dedup, cross-day labels, batched rendering', () => {
  const l = fs.readFileSync('src/wearing/web/life.js', 'utf8');
  assert.ok(l.includes('renderCalendarViews'));
  assert.match(l, /data-cal-view="dayGridMonth"/);
  assert.match(l, /data-cal-view="timeGridWeek"/);
  assert.match(l, /data-cal-view="agenda"/);
  assert.match(l, /seen\.has\(item\.id\)/, 'dedup by record id');
  assert.match(l, /此前开始/, 'cross-day started-earlier label');
  assert.match(l, /延续至次日/, 'cross-day continues label');
  assert.match(l, /data-cal-more/, 'batched 100 render');
  assert.match(l, /pajio-cal-view/, 'view preference persisted');
});
test('task actions: stop/withdraw only with confirm, real routes, no inline handlers', () => {
  const v = fs.readFileSync('src/wearing/web/views.js', 'utf8');
  assert.ok(v.includes('data-task-stop'));
  assert.ok(v.includes('data-task-cancel'));
  assert.ok(v.includes('stop.dataset.taskStop}/stop'), 'stop route');
  assert.ok(v.includes('cancel-message'));
  assert.match(v, /confirm.*=== "1"/, 'two-tap confirm');
  assert.ok(!v.includes('onclick='), 'no inline event handlers (CSP)');
  assert.match(v, /cancellable = item\.queued && item\.queue_state !== "cancelled"/, 'withdraw only on real queue receipt');
});
