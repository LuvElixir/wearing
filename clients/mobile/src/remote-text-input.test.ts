import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {runInNewContext} from 'node:vm';
import * as ts from 'typescript';
import {remoteTextIssue, remoteTextLimits, remoteTextNotice, type RemoteTextCapabilities} from './remote-text-input';

const linux: RemoteTextCapabilities = {text: 'unicode', text_max_chars: 64, text_max_bytes: 4096};
const android: RemoteTextCapabilities = {text: 'unicode', text_max_chars: 4096, text_max_bytes: 4096};
test('device code-point limits count astral characters once without normalizing combining text', () => {
  for (const text of ['a'.repeat(64), '中'.repeat(64), '😀'.repeat(64), 'e\u0301'.repeat(32)]) assert.equal(remoteTextIssue(text, linux), null);
  for (const text of ['a'.repeat(65), '中'.repeat(65), '😀'.repeat(65), 'e\u0301'.repeat(33)]) assert.equal(remoteTextIssue(text, linux), 'text_too_long');
});
test('UTF-8 ceiling remains independent of code-point count and malformed Unicode cannot be silently replaced', () => {
  assert.equal(remoteTextIssue('😀'.repeat(1024), android), null);
  assert.equal(remoteTextIssue('😀'.repeat(1025), android), 'text_too_large');
  assert.equal(remoteTextIssue('中'.repeat(1365) + 'a', android), null);
  assert.equal(remoteTextIssue('中'.repeat(1366), android), 'text_too_large');
  for (const text of ['\ud800', '\udfff', 'private\ud800text']) assert.equal(remoteTextIssue(text, android), 'text_invalid');
  assert.equal(remoteTextIssue('中a', {...android, text_max_bytes: 3}), 'text_too_large');
});
test('old or malformed capabilities are conservative and cannot expand the wire ceiling', () => {
  for (const value of [undefined, null, {}, [], {text_max_chars: '4096'}, {text_max_chars: 0}, {text_max_chars: -1}, {text_max_chars: 2.5}, {text_max_chars: Infinity}]) assert.deepEqual(remoteTextLimits(value), {chars: 32, bytes: 4096});
  assert.deepEqual(remoteTextLimits({text_max_chars: 5000, text_max_bytes: 9000}), {chars: 4096, bytes: 4096});
  assert.equal(remoteTextIssue('a'.repeat(32), {text: 'unicode'}), null);
  assert.equal(remoteTextIssue('a'.repeat(33), {text: 'unicode'}), 'text_too_long');
  assert.equal(remoteTextIssue('😀'.repeat(32), {...linux, text_max_chars: 32}), null);
  assert.equal(remoteTextIssue('😀'.repeat(33), {...linux, text_max_chars: 32}), 'text_too_long');
  for (const text of [undefined, 'ascii', 'unavailable'] as const) assert.equal(remoteTextIssue('Private123', {text}), 'text_unavailable');
});
test('trusted Android kind preserves the existing Unicode ceiling while unknown and computer hosts stay conservative', () => {
  const legacy: RemoteTextCapabilities = {text: 'unicode'};
  for (const kind of ['computer', undefined] as const) assert.equal(remoteTextIssue('x'.repeat(33), legacy, kind), 'text_too_long');
  assert.equal(remoteTextIssue('x'.repeat(4096), legacy, 'android'), null);
  assert.equal(remoteTextIssue('x'.repeat(4097), legacy, 'android'), 'text_too_long');
  assert.equal(remoteTextIssue('😀'.repeat(1024), legacy, 'android'), null);
  assert.equal(remoteTextIssue('😀'.repeat(1025), legacy, 'android'), 'text_too_large');
  assert.equal(remoteTextIssue('x'.repeat(33), {...legacy, text_max_chars: 32}, 'android'), 'text_too_long');
  assert.equal(remoteTextIssue('x'.repeat(64), {...legacy, text_max_chars: 64}, 'computer'), null);
  assert.deepEqual(remoteTextLimits({text_max_chars: -1}, 'android'), {chars: 4096, bytes: 4096});
});
test('only a device explicitly prohibiting control characters rejects C0 and DEL before sending', () => {
  for (const value of [...Array.from({length: 32}, (_, i) => i), 127]) {
    const text = `before${String.fromCodePoint(value)}after`;
    assert.equal(remoteTextIssue(text, {...linux, text_disallow_controls: true}), 'text_invalid');
    assert.equal(remoteTextIssue(text, android), null);
  }
});

const file = ts.createSourceFile('NativeRemoteDevicePanel.tsx', readFileSync(new URL('./NativeRemoteDevicePanel.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const component = file.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'NativeRemoteDevicePanel') as ts.FunctionDeclaration;
const submit = component.body!.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'submitText')!;
const code = ts.transpileModule(ts.createPrinter().printNode(ts.EmitHint.Unspecified, submit, file), {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
function harness(text: string, capabilities: RemoteTextCapabilities = linux, kind: 'computer' | 'android' = 'computer') {
  const sent: object[] = [], errors: string[] = [];
  const context = {alive: {current: true}, foreground: {current: true}, viewing: {current: {} as object | null}, controlling: true,
    capabilities: {...capabilities, keyboard: true}, text, kind, remoteTextIssue, remoteTextNotice,
    setText: (next: string) => {context.text = next;}, setError: (message: string) => {errors.push(message);}, send: (message: object) => {sent.push(message);},
    // Any accidental private persistence or logging is a test failure.
    localStorage: {setItem() {assert.fail('private text persisted');}}, console: {log() {assert.fail('private text logged');}}};
  runInNewContext(code, context);
  return Object.assign(context as typeof context & {submitText: () => void}, {sent, errors});
}
test('actual native submit rejects whole oversized draft before bridge injection and requires a fresh user action after edit', () => {
  const privateDraft = '密'.repeat(65), h = harness(privateDraft);
  h.submitText(); assert.equal(h.sent.length, 0); assert.equal(h.text, privateDraft);
  assert.match(h.errors[0], /64/); assert.equal(h.errors.join('').includes(privateDraft), false);
  h.text = '😀'.repeat(64); assert.equal(h.sent.length, 0);
  h.submitText(); assert.equal(h.sent.length, 1); assert.equal(h.text, '');
  assert.equal(JSON.stringify(h.sent[0]), JSON.stringify({type: 'text', text: '😀'.repeat(64)}));
  h.submitText(); assert.equal(h.sent.length, 1);
});
test('actual native submit applies byte limits and refuses input after background or capability withdrawal', () => {
  const h = harness('😀'.repeat(1025), android); h.submitText(); assert.equal(h.sent.length, 0); assert.match(h.errors[0], /大小限制/);
  h.text = 'safe'; h.foreground.current = false; h.submitText(); assert.equal(h.sent.length, 0);
  h.foreground.current = true; h.capabilities.text = 'unavailable'; h.submitText(); assert.equal(h.sent.length, 0);
  assert.match(h.errors.at(-1)!, /尚未就绪/); assert.equal(h.text, 'safe');
});
test('actual native submit retains a device-rejected control-character draft without logging or replaying it', () => {
  const h = harness('private\nline', {...linux, text_disallow_controls: true});
  h.submitText(); assert.equal(h.sent.length, 0); assert.equal(h.text, 'private\nline');
  assert.match(h.errors[0], /不支持/); assert.equal(h.errors[0].includes('private'), false);
});
test('actual native handler applies the trusted panel kind when an older service omits limits', () => {
  const draft = 'x'.repeat(33), caps: RemoteTextCapabilities = {text: 'unicode'};
  const phone = harness(draft, caps, 'android'); phone.submitText(); assert.equal(phone.sent.length, 1);
  const computer = harness(draft, caps, 'computer'); computer.submitText(); assert.equal(computer.sent.length, 0);
  assert.equal(computer.text, draft); assert.match(computer.errors[0], /32/);
});
