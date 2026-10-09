import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {composerScript, readComposerState, type ComposerCommand, type ComposerState} from './native-composer';

const connection = {endpoint: 'https://wearing.example/', identity: 'daily'};
const source = 'https://wearing.example/?host=mobile&composer=native';
const voiceId = 'voice-01234567-89ab-cdef-0123-456789abcdef';
const state: ComposerState = {
  type: 'wearing-composer-state', identity: 'daily', pageId: 'page-0123456789',
  contextKey: JSON.stringify({identity: 'daily', goal: null, life: null}),
  text: '等待编辑的原话', sending: false, ready: true, ackSeq: 0,
};
const read = (patch: Record<string, unknown> = {}, url = source) => readComposerState(JSON.stringify({...state, ...patch}), url, connection);

test('same-origin presentation state keeps literal text, contextual data, and optional receipts', () => {
  const patch = {text: '<script>原文</script>\n第二行', error: '保留输入', contextLabel: '日程 · 明天', ackVoiceId: voiceId, ackSeq: 7};
  assert.deepEqual(read(patch), {...state, ...patch});
  assert.deepEqual(read({}, 'https://wearing.example/conversation?identity=daily'), state);
  assert.deepEqual(read({ready: false, text: ''}), {...state, ready: false, text: ''});
});

test('foreign source schemes, hosts, ports, and identities fail closed', () => {
  for (const url of ['https://evil.example/', 'https://wearing.example.evil.example/', 'http://wearing.example/', 'https://wearing.example:8443/', 'file:///tmp/page.html', 'data:text/html,x', 'about:blank', 'not a URL']) {
    assert.equal(read({}, url), null, url);
  }
  assert.equal(read({identity: 'overseas'}), null);
  assert.equal(read({contextKey: JSON.stringify({identity: 'overseas'})}), null);
});

test('malformed messages and page-to-native capability requests are not state receipts', () => {
  for (const raw of ['', '{broken', 'null', '[]', '"state"', JSON.stringify({type: 'open-url', url: 'https://example.com'}), JSON.stringify({type: 'record-audio'}), ' '.repeat(30001)]) {
    assert.equal(readComposerState(raw, source, connection), null);
  }
  assert.equal(read({type: 'wearing-composer-command'}), null);
  for (const contextKey of ['not JSON', 'null', '[]', '{}', '"daily"', 'x'.repeat(4001)]) assert.equal(read({contextKey}), null);
});

test('state bounds and primitive types reject corrupt or oversized bridge data', () => {
  for (const patch of [
    {pageId: ''}, {pageId: 'short'}, {pageId: 'x'.repeat(101)}, {pageId: null},
    {text: null}, {text: {}}, {text: 'x'.repeat(12001)}, {ready: 1}, {sending: 'false'},
    {ackSeq: -1}, {ackSeq: 0.5}, {ackSeq: Number.MAX_SAFE_INTEGER + 1}, {ackSeq: '1'}, {ackSeq: null},
    {error: null}, {error: {}}, {error: 'x'.repeat(2001)},
    {contextLabel: null}, {contextLabel: false}, {contextLabel: 'x'.repeat(1001)},
    {ackVoiceId: null}, {ackVoiceId: 123}, {ackVoiceId: '../voice-id'}, {ackVoiceId: 'voice-short'},
  ]) assert.equal(read(patch), null, JSON.stringify(patch).slice(0, 100));
  assert.notEqual(read({text: 'x'.repeat(12000), error: 'x'.repeat(2000), contextLabel: 'x'.repeat(1000), ackSeq: Number.MAX_SAFE_INTEGER}), null);
});

test('generated edit scripts execute exactly one literal command without evaluating user text', () => {
  const text = '\"); globalThis.compromised = true; //\n</script><script>evil()</script>\n` ${danger()} \\ \u2028 \u2029';
  const calls: unknown[] = [], sandbox = {window: {WearingHost: {composerCommand: (payload: unknown) => calls.push(payload)}}, compromised: false};
  assert.equal(vm.runInNewContext(composerScript(state, 12, {kind: 'change', text}), sandbox), true);
  assert.equal(sandbox.compromised, false); assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0])), {kind: 'change', text, identity: 'daily', pageId: state.pageId, contextKey: state.contextKey, seq: 12});
});

test('each command preserves the exact host-selected page, context, and sequence', () => {
  const context = JSON.stringify({identity: 'daily', goal: {id: 'goal-a', objective: 'literal "context"', revision: 4, mode: 'note'}, life: null});
  const selected = {...state, contextKey: context};
  for (const command of [{kind: 'sync'}, {kind: 'send', text: '真正发送'}, {kind: 'append', voiceId, text: '语音原文'}] as ComposerCommand[]) {
    let received: unknown;
    vm.runInNewContext(composerScript(selected, 9, command), {window: {WearingHost: {composerCommand: (payload: unknown) => {received = payload;}}}});
    assert.deepEqual(JSON.parse(JSON.stringify(received)), {...command, identity: selected.identity, pageId: selected.pageId, contextKey: context, seq: 9});
  }
});

test('runtime command extras cannot override the host-selected routing fields', () => {
  const command = {kind: 'change', text: '原话', identity: 'foreign', pageId: 'old-page', contextKey: '{}', seq: 999} as ComposerCommand;
  let received: Record<string, unknown> = {};
  vm.runInNewContext(composerScript(state, 2, command), {window: {WearingHost: {composerCommand: (payload: Record<string, unknown>) => {received = payload;}}}});
  assert.equal(received.identity, 'daily'); assert.equal(received.pageId, state.pageId); assert.equal(received.contextKey, state.contextKey); assert.equal(received.seq, 2);
});

test('scripts remain harmless when the supported bridge has not mounted', () => {
  assert.equal(vm.runInNewContext(composerScript(state, 1, {kind: 'send', text: '保留'}), {window: {}}), true);
  assert.equal(vm.runInNewContext(composerScript(state, 1, {kind: 'send', text: '保留'}), {window: {WearingHost: {}}}), true);
});
