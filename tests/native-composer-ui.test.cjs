const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/wearing/web/native-composer.js', 'utf8');
const drafts = fs.readFileSync('src/wearing/web/conversation-drafts.js', 'utf8');
const app = fs.readFileSync('src/wearing/web/app.js', 'utf8');
const submitHandler = app.slice(app.indexOf('$("conversation-form").addEventListener("submit"'), app.indexOf('$("message-input").addEventListener("keydown"'));
const voiceId = 'voice-01234567-89ab-cdef-0123-456789abcdef';
let pages = 0;
function setup({query = '?host=mobile&composer=native', host = true, ready = true, initial, data = new Map(), goal = null, life = null} = {}) {
  const events = new Map(), messages = [], requests = [], submits = [], writes = [];
  function element(value = '') {
    const listeners = new Map(), classes = new Set();
    return {value, hidden: true, textContent: '', disabled: false, checkValidity: () => true,
      classList: {contains: name => classes.has(name), add: name => classes.add(name), remove: name => classes.delete(name)},
      addEventListener(name, fn) {const items = listeners.get(name) || []; items.push(fn); listeners.set(name, items);},
      dispatchEvent(event) {for (const fn of listeners.get(event.type) || []) fn(event);},
      requestSubmit() {const event = {preventDefault() {}}; for (const fn of listeners.get('submit') || []) submits.push(fn(event));},
    };
  }
  const input = element(), form = element(), notice = element(), dock = element();
  const elements = {'message-input': input, 'conversation-form': form, notice, 'open-identities': element(), 'send-message': element()};
  const h = {messages, requests, submits, writes, input, form, data, failRead: false, failDraft: false, failReceipt: false, failJournal: false};
  const storage = {
    getItem(key) {if (h.failRead) throw Error('read denied'); return data.get(key) ?? null;},
    setItem(key, value) {
      if ((h.failDraft && key.startsWith('wearing-chat-draft:')) ||
          (h.failJournal && key.startsWith('wearing-native-voice:')) ||
          (h.failReceipt && key.startsWith('wearing-native-voice:') && JSON.parse(value).status === 'received')) throw Error('quota');
      data.set(key, value); writes.push(key);
    },
    removeItem(key) {if (h.failDraft) throw Error('quota'); data.delete(key);},
  };
  const context = {
    URLSearchParams, Event, location: {search: query}, localStorage: storage,
    state: {identityId: 'daily', goalFocus: goal, lifeFocus: life, sending: false}, composerReady: ready, draftStorageWarning: false,
    window: {WearingHost: {setActive() {}}, crypto: {randomUUID: () => 'test-page-' + (++pages)},
      ...(host ? {ReactNativeWebView: {postMessage: raw => messages.push(JSON.parse(raw))}} : {})},
    document: {getElementById: id => elements[id], querySelector: () => dock,
      addEventListener(name, fn) {const items = events.get(name) || []; items.push(fn); events.set(name, items);}},
    composerContext() {return {identity: context.state.identityId, goal: context.state.goalFocus, life: context.state.goalFocus ? null : context.state.lifeFocus};},
    rememberComposer() {return context.composerReady ? context.composerDrafts.save(context.composerContext(), input.value) : false;},
    publishComposer() {for (const fn of events.get('wearing-composer-state') || []) fn();},
    $: id => elements[id], updateCompanion() {}, scrollToLatest() {}, loadConversation: async () => {},
    busy: async (_, action) => action(),
    notice(text, error = false) {notice.textContent = text; notice.hidden = !text; notice.classList[error ? 'add' : 'remove']('error');},
    conversationSubmissions: {prepare(identity, text) {h.prepared = {identity, text}; return 'request-stable';}, acknowledge(identity, id) {h.acknowledged = {identity, id};}},
    async api(path, options) {requests.push({path, ...options}); return h.response ? h.response() : {task: {id: 'task-real'}, delivery: 'submitted'};},
  };
  vm.createContext(context); vm.runInContext(drafts, context);
  context.composerDrafts = context.window.WearingDrafts.create(() => storage, () => {context.draftStorageWarning = true;});
  input.value = initial ?? context.composerDrafts.read(context.composerContext())?.text ?? '原有草稿';
  context.activateComposer = () => {};
  vm.runInContext(source, context); vm.runInContext(submitHandler, context);
  h.context = context;
  h.emit = name => {for (const fn of events.get(name) || []) fn();};
  h.latest = () => messages.at(-1);
  h.command = (kind, seq, extra = {}) => context.window.WearingHost.composerCommand({
    identity: context.state.identityId, pageId: h.latest().pageId, contextKey: JSON.stringify(context.composerContext()), kind, seq, ...extra,
  });
  return h;
}

test('bridge is inert outside the explicit native composer host', () => {
  for (const options of [{query: ''}, {query: '?host=mobile'}, {query: '?composer=native'}, {host: false}]) {
    const h = setup(options);
    assert.equal(h.context.window.WearingHost.composerCommand, undefined); assert.equal(h.messages.length, 0);
    assert.equal(h.input.value, '原有草稿'); assert.equal(h.writes.length, 0);
  }
});

test('initial state exposes only current composer presentation and context', () => {
  const goal = {id: 'goal-a', objective: '周末出行', mode: 'note', revision: 3}, h = setup({goal});
  assert.equal(h.latest().ready, true); assert.equal(h.latest().text, '原有草稿'); assert.equal(h.latest().ackSeq, 0);
  assert.equal(h.latest().contextLabel, '补充新情况 · 周末出行');
  assert.deepEqual(JSON.parse(h.latest().contextKey), {identity: 'daily', goal, life: null});
  assert.equal(h.latest().type, 'wearing-composer-state'); assert.equal(h.requests.length, 0);
});

test('full literal edits persist once and duplicate or older sequences cannot overwrite them', () => {
  const h = setup(); h.command('change', 2, {text: '<script>原文</script>'});
  assert.equal(h.input.value, '<script>原文</script>'); assert.equal(h.latest().ackSeq, 2);
  h.command('change', 2, {text: '重复'}); h.command('change', 1, {text: '晚到'});
  assert.equal(h.input.value, '<script>原文</script>'); assert.equal(h.requests.length, 0);
  assert.equal(h.context.composerDrafts.read(h.context.composerContext()).text, h.input.value);
});

test('sync accepts a low sequence without regressing the acknowledgement or mutating', () => {
  const h = setup(); h.command('change', 5, {text: '新内容'}); const writes = h.writes.length;
  assert.equal(h.command('sync', 0), true); assert.equal(h.latest().ackSeq, 5); assert.equal(h.writes.length, writes);
});

test('commands from an old page, identity, or contextual revision are rejected', () => {
  const h = setup(), first = h.latest();
  for (const extra of [{pageId: 'previous-page'}, {identity: 'other'}, {contextKey: JSON.stringify({identity: 'daily', goal: {id: 'old'}, life: null})}]) {
    h.command('change', 1, {text: '错误位置', ...extra}); assert.equal(h.input.value, '原有草稿');
  }
  h.context.state.goalFocus = {id: 'goal-a', objective: '新上下文', mode: 'discuss', revision: 2};
  h.command('change', 1, {text: '晚到旧上下文', contextKey: first.contextKey});
  assert.equal(h.input.value, '原有草稿'); assert.equal(h.latest().ackSeq, 0);
});

test('bootstrap cannot accept a mutation and never publishes unrestored input as ready', () => {
  const h = setup({ready: false}); assert.equal(h.latest().ready, false); assert.equal(h.latest().text, '');
  h.command('change', 1, {text: '太早'}); assert.equal(h.input.value, '原有草稿');
  h.context.composerReady = true; h.input.value = '恢复的草稿'; h.emit('wearing-composer-ready');
  assert.equal(h.latest().text, '恢复的草稿'); assert.equal(h.latest().ready, true);
  h.command('change', 1, {text: '可以了'}); assert.equal(h.input.value, '可以了');
});

test('malformed, oversized and unknown capability commands never invoke any handler', () => {
  const h = setup();
  for (const extra of [{text: 'x'.repeat(12001)}, {text: null}, {seq: 1.5}, {seq: -1}, {kind: 'record'}, {kind: 'open-url'}]) h.command('change', 1, {text: 'x', ...extra});
  h.command('append', 1, {voiceId: '../voice', text: '语音'}); h.command('append', 1, {voiceId, text: ' '});
  assert.equal(h.input.value, '原有草稿'); assert.equal(h.latest().ackSeq, 0); assert.equal(h.requests.length, 0); assert.equal(h.writes.length, 0);
});

test('send enters only the real conversation submit handler with its stable request key', async () => {
  const h = setup(); assert.equal(h.command('send', 1, {text: '  真正的原话  '}), true);
  assert.equal(h.latest().sending, true); assert.equal(h.latest().ackSeq, 1);
  h.command('send', 1, {text: '重复发送'}); h.command('send', 2, {text: '正在发送时重试'});
  assert.equal(h.requests.length, 1); assert.equal(h.requests[0].path, '/api/conversation');
  assert.deepEqual(JSON.parse(h.requests[0].body), {content: '真正的原话', request_id: 'request-stable'});
  await Promise.all(h.submits); h.emit('wearing-composer-state');
  assert.equal(h.latest().sending, false); assert.equal(h.latest().text, ''); assert.equal(h.acknowledged.id, 'request-stable');
});

test('goal and life sends preserve existing context and revision handler logic', async () => {
  for (const [options, fields] of [
    [{goal: {id: 'goal-a', objective: '出行', mode: 'note', revision: 3}}, {goal_id: 'goal-a', goal_mode: 'note', goal_revision: 3}],
    [{life: {id: 'life-a', title: '出行', kind: 'note', revision: 5}}, {life_record_id: 'life-a', life_revision: 5}],
  ]) {
    const h = setup(options); h.command('send', 1, {text: '补充'}); await Promise.all(h.submits);
    assert.deepEqual(JSON.parse(h.requests[0].body), {content: '补充', ...fields}); assert.equal(h.prepared, undefined);
  }
});

test('late send completion cannot erase a newer native edit', async () => {
  const h = setup(); let resolve;
  h.response = () => new Promise(done => {resolve = done;});
  h.command('send', 1, {text: '第一条'}); h.command('change', 2, {text: '下一条正在写'});
  resolve({task: {id: 'task-real'}, delivery: 'submitted'}); await Promise.all(h.submits); h.emit('wearing-composer-state');
  assert.equal(h.latest().text, '下一条正在写'); assert.equal(h.latest().ackSeq, 2); assert.equal(h.latest().sending, false);
});

test('native send reports form validation failure instead of acknowledging a silent blocked submit', () => {
  const h = setup(); h.form.checkValidity = () => false; h.input.validationMessage = '请至少补充三个字';
  h.command('send', 1, {text: '好'});
  assert.equal(h.input.value, '好'); assert.equal(h.latest().ackSeq, 0); assert.equal(h.latest().sending, false);
  assert.equal(h.latest().error, '请至少补充三个字'); assert.equal(h.requests.length, 0); assert.equal(h.submits.length, 0);
  h.form.checkValidity = () => true; h.command('change', 2, {text: '新的补充'});
  assert.equal(h.latest().error, undefined); assert.equal(h.latest().ackSeq, 2);
});

test('late notification publishes the current identity and scope instead of stale data', () => {
  const h = setup(), old = h.latest();
  h.context.state.identityId = 'overseas'; h.input.value = '另一个身份'; h.emit('wearing-composer-ready');
  h.command('change', 1, {identity: old.identity, contextKey: old.contextKey, text: '旧身份'});
  h.emit('wearing-composer-state');
  assert.equal(h.latest().identity, 'overseas'); assert.equal(h.latest().text, '另一个身份'); assert.equal(h.latest().ackSeq, 0);
});

test('voice appends once, persists an acknowledgement, and survives reload after send', async () => {
  const data = new Map(), h = setup({data});
  h.command('append', 1, {voiceId, text: '语音原话'}); assert.equal(h.input.value, '原有草稿\n语音原话'); assert.equal(h.latest().ackVoiceId, voiceId);
  h.command('append', 2, {voiceId, text: '语音原话'}); assert.equal(h.input.value, '原有草稿\n语音原话'); assert.equal(h.requests.length, 0);
  h.command('send', 3, {text: h.input.value}); await Promise.all(h.submits);
  const next = setup({data, initial: ''}); next.command('append', 1, {voiceId, text: '语音原话'});
  assert.equal(next.input.value, ''); assert.equal(next.latest().ackVoiceId, voiceId); assert.equal(next.requests.length, 0);
});

test('voice read or journal storage failure cannot mutate or acknowledge the transcript', () => {
  for (const flag of ['failRead', 'failJournal']) {
    const h = setup(); h[flag] = true; h.command('append', 1, {voiceId, text: '保留语音'});
    assert.equal(h.input.value, '原有草稿'); assert.equal(h.latest().ackVoiceId, undefined); assert.equal(h.latest().ackSeq, 0); assert.match(h.latest().error, /无法保存/);
  }
});

test('failed voice draft or receipt persistence cannot acknowledge, and retry cannot duplicate', () => {
  for (const flag of ['failDraft', 'failReceipt']) {
    const h = setup(); h[flag] = true; h.command('append', 1, {voiceId, text: '保留语音'});
    assert.equal(h.input.value, '原有草稿\n保留语音'); assert.equal(h.latest().ackVoiceId, undefined); assert.equal(h.latest().ackSeq, 0);
    h[flag] = false; h.command('append', 2, {voiceId, text: '保留语音'});
    assert.equal(h.input.value, '原有草稿\n保留语音'); assert.equal(h.latest().ackVoiceId, voiceId); assert.equal(h.latest().ackSeq, 2);
  }
});

test('a reload between saving voice text and receipt recovers without appending twice', () => {
  const data = new Map(), h = setup({data}); h.failReceipt = true;
  h.command('append', 1, {voiceId, text: '已保存的语音'});
  const next = setup({data}); next.command('append', 1, {voiceId, text: '已保存的语音'});
  assert.equal(next.input.value, '原有草稿\n已保存的语音'); assert.equal(next.latest().ackVoiceId, voiceId);
});

test('a pending voice receipt cannot overwrite later edits or move to another context', () => {
  const h = setup(); h.failReceipt = true; h.command('append', 1, {voiceId, text: '语音'}); h.failReceipt = false;
  h.command('change', 2, {text: '随后修改的内容'}); h.command('append', 3, {voiceId, text: '语音'});
  assert.equal(h.input.value, '随后修改的内容'); assert.equal(h.latest().ackVoiceId, undefined);
  assert.match(h.latest().error, /草稿已经变化/);
  h.context.state.lifeFocus = {id: 'other', title: '另一条', kind: 'note', revision: 1};
  h.command('append', 4, {voiceId, text: '语音'}); assert.equal(h.input.value, '随后修改的内容'); assert.equal(h.latest().ackVoiceId, undefined);
});

test('failed edit persistence retains input, blocks send, and rejects an older delayed edit', () => {
  const h = setup(); h.failDraft = true;
  h.command('send', 3, {text: '原文仍在'}); assert.equal(h.input.value, '原文仍在'); assert.equal(h.requests.length, 0);
  h.command('change', 2, {text: '晚到的旧输入'}); assert.equal(h.input.value, '原文仍在'); assert.equal(h.latest().ackSeq, 0);
  h.failDraft = false; h.command('change', 4, {text: '现在已保存'}); assert.equal(h.latest().ackSeq, 4); assert.equal(h.latest().error, undefined);
});

test('input and notice events reflect edits, sending, and errors without triggering execution', () => {
  const h = setup(); h.input.value = '网页补充'; h.input.dispatchEvent(new Event('input'));
  assert.equal(h.latest().text, '网页补充');
  h.context.notice('服务未返回保存回执', true); h.context.state.sending = false; h.emit('wearing-composer-state');
  assert.equal(h.latest().error, '服务未返回保存回执'); assert.equal(h.requests.length, 0);
});
