import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import * as ts from 'typescript';
import {remoteTextIssue, remoteTextNotice} from './remote-text-input';

// Run the real component handlers without mocking away their capability/session checks.
function handlers(keyboard: unknown) {
  const ast = ts.createSourceFile('NativeRemoteDevicePanel.tsx', readFileSync(new URL('./NativeRemoteDevicePanel.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const component = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'NativeRemoteDevicePanel') as ts.FunctionDeclaration;
  const picked = component.body!.statements.filter(node => ts.isFunctionDeclaration(node) && ['submitText', 'sendKey'].includes(node.name!.text));
  assert.equal(picked.length, 2);
  const code = ts.transpileModule(picked.map(node => ts.createPrinter().printNode(ts.EmitHint.Unspecified, node, ast)).join('\n'), {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
  const h = {alive: {current: true}, foreground: {current: true}, viewing: {current: {} as object | null}, controlling: true,
    capabilities: {keyboard, text: 'unicode'}, kind: 'android', text: 'SYNTHETIC', error: '', sent: [] as unknown[],
    remoteTextIssue, remoteTextNotice,
    send: (value: unknown) => h.sent.push(value), setText: (value: string) => {h.text = value;}, setError: (value: string) => {h.error = value;}};
  runInNewContext(code, h);
  return h as typeof h & {sendKey: (key: string) => void; submitText: () => void};
}

test('native shortcut and text submit handlers require strict keyboard capability and preserve unsent draft', () => {
  for (const capability of [false, undefined, null, 0, 1, 'true', {}, []]) {
    const h = handlers(capability);
    for (const key of ['Back', 'Home', 'Recents', 'Enter', 'Backspace', 'Tab']) h.sendKey(key);
    h.submitText();
    assert.equal(h.sent.length, 0); assert.equal(h.text, 'SYNTHETIC'); assert.equal(h.error, '');
  }
});

test('native enabled key/text handlers retain the session and explicit-control boundaries', () => {
  for (const deactivate of [
    (h: ReturnType<typeof handlers>) => {h.alive.current = false;},
    (h: ReturnType<typeof handlers>) => {h.foreground.current = false;},
    (h: ReturnType<typeof handlers>) => {h.viewing.current = null;},
    (h: ReturnType<typeof handlers>) => {h.controlling = false;},
  ]) {
    const h = handlers(true); deactivate(h); h.sendKey('Enter'); h.submitText();
    assert.equal(h.sent.length, 0); assert.equal(h.text, 'SYNTHETIC');
  }
  const h = handlers(true); h.sendKey('Home'); h.submitText();
  assert.equal(JSON.stringify(h.sent), JSON.stringify([{type: 'key', key: 'Home'}, {type: 'text', text: 'SYNTHETIC'}]));
  assert.equal(h.text, '');
});
