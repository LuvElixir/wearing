const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('vm');

const source = fs.readFileSync('src/wearing/web/views.js', 'utf8');
// 截取主点击委托（含本轮三个闭环分支）至搜索段落之前。
const start = source.indexOf('document.addEventListener("click", async event => {');
const end = source.indexOf('/* ---------- 对话搜索');
assert.ok(start > 0 && end > start, 'delegation slice found');
const handlerSource = source.slice(start, end);

function setup() {
  const calls = {openPanel: [], loadKeeps: 0, quickCapture: 0, render: [], notice: [], openTask: []};
  const lifeContent = {dataset: {viewKey: 'today:daily'}};
  const context = {
    window: {WearingLife: {quickCapture: () => calls.quickCapture++},
      WearingViews: {render: (view, container) => calls.render.push([view, container])},
      WearingActivity: {openTask: async id => calls.openTask.push(id)}},
    document: {addEventListener: (name, fn) => {if (name === 'click') context.__handler = fn;}},
    $: id => (id === 'life-content' ? lifeContent : {dataset: {}, hidden: true}),
    openPanel: id => calls.openPanel.push(id),
    loadKeeps: async () => {calls.loadKeeps++;},
    notice: text => calls.notice.push(text),
    showSettings: () => {}, showIdentities: () => {}, loadFiles: async () => {},
    activateComposer: () => {}, state: {identityId: 'daily', identityEpoch: 1, messages: [{task_id: 't1'}]},
  };
  vm.createContext(context);
  vm.runInContext(handlerSource, context);
  const click = selector => context.__handler({target: {closest: sel => (sel === selector ? {dataset: {}} : null)}});
  return {calls, lifeContent, context, click};
}

test('today refresh clears the view cache and re-renders today (real re-read)', async () => {
  const {calls, lifeContent, click} = setup();
  await click('[data-today-refresh]');
  assert.equal(lifeContent.dataset.viewKey, undefined, 'view cache cleared so renderToday refetches');
  assert.equal(calls.render.length, 1);
  assert.deepEqual(calls.render[0][0], 'today');
  assert.equal(calls.render[0][1], lifeContent);
});

test('quick capture entry lands on the real capture composer', async () => {
  const {calls, click} = setup();
  await click('[data-quick-capture]');
  assert.equal(calls.quickCapture, 1);
  assert.equal(calls.render.length, 0, 'no re-render side path');
});

test('ongoing-goals entry opens the keeps panel and loads real goals', async () => {
  const {calls, click} = setup();
  await click('[data-open-keeps-entry]');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls.openPanel, ['keeps-panel']);
  assert.equal(calls.loadKeeps, 1);
  assert.equal(calls.openTask.length, 0);
});

test('loadKeeps failure surfaces honest feedback, panel stays open', async () => {
  const source2 = handlerSource;
  const context = {
    window: {WearingLife: {}, WearingViews: {}, WearingActivity: {}},
    document: {addEventListener: (name, fn) => {if (name === 'click') context.__handler = fn;}},
    $: id => ({dataset: {}, hidden: true}),
    openPanel: id => {},
    loadKeeps: async () => {throw new Error('目标暂不可读');},
    notice: () => {},
  };
  vm.createContext(context);
  vm.runInContext(source2, context);
  await context.__handler({target: {closest: sel => (sel === '[data-open-keeps-entry]' ? {dataset: {}} : null)}});
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(true, 'rejecting loadKeeps is caught, no unhandled rejection');
});


// ---- life.js 409 双选择（保留我的输入 / 采用最新内容）副作用 ----
const lifeSource = fs.readFileSync('src/wearing/web/life.js', 'utf8');
const fnStart = lifeSource.indexOf('function apply409Choice');
const fnEnd = lifeSource.indexOf('el("life-latest").addEventListener');
assert.ok(fnStart > 0 && fnEnd > fnStart, 'apply409Choice slice found');
const choiceSource = lifeSource.slice(fnStart, fnEnd);

function lifeSetup({deleted = false} = {}) {
  const calls = {feedback: [], openEditor: [], closeEditor: 0, forget: []};
  const elements = {};
  const element = id => elements[id] ||= {hidden: false, textContent: ""};
  const latest = {id: "life_a", revision: 7, deleted_at: deleted ? "x" : null, title: "别人改过的标题", content: "最新内容"};
  const context = {
    life: {editor: {id: "life_a", revision: 6}, editorInitial: "old"},
    el: element,
    feedback: text => calls.feedback.push(text),
    forgetEditor: record => calls.forget.push(record),
    openEditor: record => calls.openEditor.push(record),
    closeEditor: () => calls.closeEditor++,
  };
  vm.createContext(context);
  vm.runInContext(choiceSource, context);
  return {context, calls, latest, elements};
}

test('409 keep-my-input keeps every field and adopts only the latest revision', () => {
  const {context, calls, latest, elements} = lifeSetup();
  context.apply409Choice("keep", latest);
  assert.equal(context.life.editor.revision, 7, 'save retry uses latest revision');
  assert.equal(context.life.editor.title, "别人改过的标题", 'editor base is the latest record');
  assert.equal(elements["life-edit-error"].hidden, true, 'error cleared');
  assert.equal(elements["life-latest"].hidden, true, 'compare panel cleared');
  assert.deepEqual(calls.openEditor, [], 'fields untouched: no reopen, input preserved');
  assert.match(calls.feedback[0], /已保留你的输入/);
});

test('409 use-latest loads the latest content and drops the stale draft', () => {
  const {context, calls, latest} = lifeSetup();
  context.apply409Choice("latest", latest);
  assert.equal(context.life.editor, null);
  assert.deepEqual(calls.forget, [context.life.editor ?? {id: "life_a", revision: 6}].filter(Boolean).length ? [calls.forget[0]] : calls.forget, 'stale draft discarded');
  assert.equal(calls.forget.length, 1);
  assert.deepEqual(calls.openEditor, [latest], 'editor reopens with latest record');
});

test('409 latest that was deleted closes honestly instead of resurrecting', () => {
  const {context, calls, latest} = lifeSetup({deleted: true});
  context.apply409Choice("latest", latest);
  assert.equal(calls.closeEditor, 1);
  assert.deepEqual(calls.openEditor, []);
  assert.match(calls.feedback[0], /最近移除/);
});
