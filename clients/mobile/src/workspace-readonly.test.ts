import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';
import React from 'react';
import ts from 'typescript';
import * as core from './core';
import * as workspace from './personal-hub';

// Evaluate the real component branches with inert native ports. No network, native
// module, editor or AI component is mounted by this harness.
type Element = React.ReactElement<Record<string, unknown>>;
type Props = Record<string, unknown>;
const source = readFileSync(new URL('./PersonalHub.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source + '\nexport {WorkspaceFilesContent, WorkspaceBrowser, FileReader};', {
  compilerOptions: {module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true},
}).outputText;
function harness(states: unknown[] = []) {
  let index = 0;
  const updates: unknown[] = [];
  const react = {...React, useEffect: () => {}, useLayoutEffect: () => {}, useMemo: (read: () => unknown) => read(), useRef: (current: unknown) => ({current}),
    useState: (initial: unknown) => {
      const position = index++;
      return [position < states.length ? states[position] : typeof initial === 'function' ? initial() : initial, (next: unknown) => updates.push(next)];
    }};
  const exports: Record<string, (props: Props) => Element> = {};
  const noopModule = new Proxy({}, {get: (_, key) => key === '__esModule' ? true : String(key)});
  const require = (name: string) => {
    if (name === 'react') return {__esModule: true, default: react, ...react};
    if (name === './core') return core;
    if (name === './personal-hub') return workspace;
    if (name === './app-theme') return {useAppTheme: () => ({colors: {}}), useThemedStyles: () => ({})};
    if (name === './workspace-text') return {editableDocument: () => true};
    return noopModule;
  };
  vm.runInNewContext(compiled, {exports, require, AbortController, setTimeout, clearTimeout});
  return {components: exports, updates};
}
function elements(tree: unknown): Element[] {
  if (Array.isArray(tree)) return tree.flatMap(elements);
  if (!React.isValidElement(tree)) return [];
  const element = tree as Element;
  return [element, ...elements(element.props.children)];
}
function named(tree: unknown, name: string) {
  return elements(tree).filter(item => typeof item.type === 'function' ? item.type.name === name : item.type === name);
}
const connection: core.Connection = {
  endpoint: 'https://pajio.luckyloading.com/', identity: 'daily',
  session: {userId: 'user_' + 'a'.repeat(32), tenantId: 'tenant-a', credentialId: 'c'.repeat(32), expiresAt: new Date(Date.now() + 3600000).toISOString(), accessToken: 't'.repeat(64)},
};
const nothing = () => {};

test('account file entry remounts on credential, tenant and identity changes without putting token in key', () => {
  const {components} = harness();
  const render = (current: core.Connection) => components.WorkspaceFilesPanel({connection: current, onBack: nothing});
  const first = render(connection);
  const credential = render({...connection, session: {...connection.session!, credentialId: 'd'.repeat(32)}});
  const tenant = render({...connection, session: {...connection.session!, tenantId: 'tenant-b'}});
  const identity = render({...connection, identity: 'work'});
  for (const next of [credential, tenant, identity]) assert.notEqual(next.key, first.key);
  assert.ok(first.key?.includes(connection.session!.credentialId));
  assert.ok(!first.key?.includes(connection.session!.accessToken!));
});

test('read-only entry starts directly in files and validates local folder and file transitions', () => {
  const {components, updates} = harness();
  const tree = components.WorkspaceFilesContent({connection, onBack: nothing});
  const browser = named(tree, 'WorkspaceBrowser')[0];
  assert.equal((browser.props.access as {mode: string}).mode, 'read-only');
  assert.equal(browser.props.onRootBack, nothing);
  assert.equal(named(tree, 'MemoryLibraryContent').length, 0);
  const open = browser.props.open as (next: Props) => void;
  open({memoryPath: '../private'}); open({memoryFile: '/etc/passwd'}); open({memoryFile: 'x/../secret'});
  assert.equal(updates.length, 0);
  open({memoryPath: 'imports/资料', memoryFile: 'imports/资料/report.pdf'});
  assert.equal(JSON.stringify(updates), JSON.stringify([{directory: 'imports/资料', path: 'imports/资料/report.pdf'}]));
});

test('read-only selected file keeps metadata reader keyed to its safe path and has no mutation callback', () => {
  const {components} = harness([{directory: 'imports', path: 'imports/report.pdf'}]);
  const tree = components.WorkspaceFilesContent({connection, onBack: nothing});
  const reader = named(tree, 'WorkspaceFileView')[0];
  assert.equal(reader.key, 'imports/report.pdf');
  assert.equal((reader.props.access as {mode: string}).mode, 'read-only');
  assert.equal(reader.props.onChat, undefined);
  for (const name of ['MemoryEditor', 'WorkspaceImportButton', 'WorkspaceTextEditor']) assert.equal(named(tree, name).length, 0);
});

test('read-only browser retains refresh and return but excludes import and AI content search', () => {
  const {components} = harness();
  let backs = 0;
  const tree = components.WorkspaceBrowser({connection, api: {}, directory: '', open: nothing, access: {mode: 'read-only'}, onRootBack: () => backs++});
  assert.equal(named(tree, 'WorkspaceImportButton').length, 0);
  const rows = named(tree, 'HubRow');
  assert.deepEqual(rows.map(row => row.props.title), ['重新读取文件列表']);
  const back = named(tree, 'BackLabel')[0];
  assert.equal(back.props.title, '我的数据');
  (back.props.onPress as () => void)();
  assert.equal(backs, 1);
  assert.ok(JSON.stringify(tree).includes('256 KB'));
  assert.ok(JSON.stringify(tree).includes('20 MB'));
});

test('read-only reader excludes editor even with a previously true editing state and preserves original sharing', () => {
  // text, error, loading, generation, sharing, shareError, editing
  const {components} = harness(['original text', '', false, 0, false, '', true]);
  const tree = components.FileReader({connection, api: {}, file: {path: 'notes.md', size: 13, modified: 1}, access: {mode: 'read-only'}, onOpen: nothing, onSaved: nothing});
  assert.equal(named(tree, 'WorkspaceTextEditor').length, 0);
  assert.equal(named(tree, 'HubRow').length, 0);
  assert.equal(named(tree, 'TactilePressable').filter(item => item.props.accessibilityLabel === '打开或分享原件').length, 1);
  assert.equal(named(tree, 'Text').filter(item => item.props.selectable).length, 1);
});

test('oversize original remains honestly unavailable while the editable entry keeps its existing capabilities', () => {
  const readonly = harness().components.FileReader({connection, api: {}, file: {path: 'large.pdf', size: workspace.WORKSPACE_ORIGINAL_LIMIT + 1, modified: 1}, access: {mode: 'read-only'}, onOpen: nothing, onSaved: nothing});
  assert.equal(named(readonly, 'TactilePressable').filter(item => item.props.accessibilityLabel === '打开或分享原件').length, 0);
  assert.ok(JSON.stringify(readonly).includes('当前无法在此取回'));
  const browser = harness().components.WorkspaceBrowser({connection, api: {}, directory: '', open: nothing, access: {mode: 'editable', onChat: nothing}});
  assert.equal(named(browser, 'WorkspaceImportButton').length, 1);
  assert.ok(named(browser, 'HubRow').some(item => item.props.title === '按内容查找文件'));
  const reader = harness().components.FileReader({connection, api: {}, file: {path: 'notes.md', size: 13, modified: 1}, access: {mode: 'editable', onChat: nothing}, onOpen: nothing, onSaved: nothing});
  assert.deepEqual(named(reader, 'HubRow').map(item => item.props.title), ['编辑这份文档', '让 Pajio 读这份文件']);
});
