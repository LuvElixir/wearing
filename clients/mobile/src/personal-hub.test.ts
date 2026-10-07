import {test} from 'node:test';
import assert from 'node:assert/strict';
import {deviceCollectionState, hubIdentity, hubRuntime, memoryCollection, memoryObservationLabel, PersonalHubApi, safeWorkspacePath, textPreviewAllowed, workspaceEntries, workspaceSnapshot} from './personal-hub';

test('workspace browser derives exact directory counts from real returned files', () => {
  const snapshot = workspaceSnapshot({files: [
    {path: 'work/brief.md', size: 30, modified: 1},
    {path: 'work/research/sources.json', size: 50, modified: 2},
    {path: 'workshop/notes.txt', size: 10, modified: 3},
    {path: 'README.md', size: 100, modified: 4},
  ], truncated: false});
  assert.deepEqual(workspaceEntries(snapshot.files).map(({name, count, kind}) => ({name, count, kind})), [
    {name: 'work', count: 2, kind: 'folder'}, {name: 'workshop', count: 1, kind: 'folder'}, {name: 'README.md', count: 1, kind: 'file'},
  ]);
  assert.deepEqual(workspaceEntries(snapshot.files, 'work').map(({path}) => path), ['work/research', 'work/brief.md']);
  assert.deepEqual(workspaceEntries(snapshot.files, '../work'), []);
});

test('workspace responses reject traversal, duplicates and invalid metadata', () => {
  for (const path of ['/etc/passwd', '../memory.md', 'work/../../keys', 'a\\b', 'a//b', 'a/./b', 'a\u0000b', '']) assert.equal(safeWorkspacePath(path), false);
  assert.equal(safeWorkspacePath('我的资料/项目.md'), true);
  const file = {path: 'memory.md', size: 10, modified: 1};
  for (const files of [[{...file, size: -1}], [{...file, modified: Infinity}], [file, file]]) assert.throws(() => workspaceSnapshot({files, truncated: false}));
});

test('native text preview never renders executable files or oversized originals', () => {
  const file = {path: 'notes.md', size: 1024, modified: 1};
  assert.equal(textPreviewAllowed(file), true);
  assert.equal(textPreviewAllowed({...file, path: 'page.html'}), false);
  assert.equal(textPreviewAllowed({...file, path: 'portrait.png'}), false);
  assert.equal(textPreviewAllowed({...file, size: 262145}), false);
});

test('capability parsing exposes only actual flags and does not invent device availability', () => {
  assert.deepEqual(hubRuntime({running: true, product: {applied: true}, model: {provider: 'example', state: 'configured'}, files: {active: true}, phone: {installed: true, active: false}, computer: {active: false}, secret: 'never exposed'}), {
    running: true, applied: true, provider: 'example', modelReady: true, files: true, computer: false, phone: false,
  });
  assert.deepEqual(hubIdentity({accounts: 'not_connected', devices: [{id: 'mac', name: '电脑', kind: 'computer'}, {id: 'phone', name: '手机', kind: 'phone', online: false}]}), {
    cloudAccountsConnected: false, devices: [{id: 'mac', name: '电脑', kind: 'computer', online: null}, {id: 'phone', name: '手机', kind: 'phone', online: false}],
  });
  assert.throws(() => hubRuntime({running: true}));
  assert.equal(hubIdentity({devices: []}).cloudAccountsConnected, null);
});

test('unread and unavailable memory never become an empty collection or a zero count', () => {
  assert.deepEqual(memoryCollection(null, 'user', true), {state: 'loading', entries: null, countLabel: '正在读取'});
  assert.deepEqual(memoryCollection(null, 'user', false), {state: 'unavailable', entries: null, countLabel: '未读取'});
  assert.deepEqual(memoryCollection({available: false, identity_id: 'daily'}, 'user', false), {state: 'unavailable', entries: null, countLabel: '未读取'});
  const snapshot = {available: true, identity_id: 'daily', targets: {user: {enabled: true, entries: []}, memory: {enabled: true, entries: ['actual memory']}}};
  assert.deepEqual(memoryCollection(snapshot, 'user', false), {state: 'available', entries: [], countLabel: '0 条记忆'});
  assert.deepEqual(memoryCollection(snapshot, 'memory', false), {state: 'available', entries: ['actual memory'], countLabel: '1 条记忆'});
  assert.equal(memoryCollection({...snapshot, available: false}, 'memory', false).entries, null);
});

test('memory observations are labelled as read time, never a claimed content update', () => {
  for (const observed_at of ['2026-10-07T10:00:00Z', '2026-10-08T11:00:00Z']) {
    const label = memoryObservationLabel({available: true, identity_id: 'daily', observed_at});
    assert.match(label!, /^读取于 /);
    assert.doesNotMatch(label!, /更新/);
  }
  assert.equal(memoryObservationLabel({available: false, identity_id: 'daily', observed_at: '2026-10-07T10:00:00Z'}), null);
  assert.equal(memoryObservationLabel({available: true, identity_id: 'daily', observed_at: 'invalid'}), null);
});

test('device empty state is reserved for a successfully observed empty inventory', () => {
  assert.equal(deviceCollectionState(null, true), 'loading');
  assert.equal(deviceCollectionState(null, false), 'unavailable');
  assert.equal(deviceCollectionState({devices: [], cloudAccountsConnected: false}, false), 'empty');
  assert.equal(deviceCollectionState({devices: [{id: 'mac', name: '电脑', kind: 'computer', online: null}], cloudAccountsConnected: false}, false), 'available');
});

test('read-only API keeps identity and auth in headers, never URLs, and encodes file paths', async context => {
  const dev = Object.getOwnPropertyDescriptor(globalThis, '__DEV__');
  Object.defineProperty(globalThis, '__DEV__', {configurable: true, value: true});
  context.after(() => {if (dev) Object.defineProperty(globalThis, '__DEV__', dev); else Reflect.deleteProperty(globalThis, '__DEV__');});
  const calls: {url: string; init?: RequestInit}[] = [];
  const api = new PersonalHubApi({endpoint: 'http://192.168.1.25:8795/', identity: 'daily', development: {accessToken: 'x'.repeat(48), expiresAt: new Date(Date.now() + 3600000).toISOString()}}, (async (url, init) => {
    calls.push({url: String(url), init});
    return new Response('actual memory', {status: 200, headers: {'content-length': '13'}});
  }) as typeof fetch);
  const file = {path: 'work/notes #1.md', size: 13, modified: 1};
  assert.equal(await api.textFile(file), 'actual memory');
  assert.equal(new URL(calls[0].url).searchParams.get('path'), file.path);
  assert.equal(calls[0].url.includes('xxxxxxxx'), false);
  assert.equal(calls[0].init?.redirect, 'error');
  assert.equal((calls[0].init?.headers as Record<string, string>)['X-Wearing-Identity'], 'daily');
  assert.equal((calls[0].init?.headers as Record<string, string>).Authorization, 'Bearer ' + 'x'.repeat(48));
  assert.equal(calls[0].init?.method, undefined);
  await assert.rejects(() => api.textFile({...file, path: '../notes.md'}));
  assert.equal(calls.length, 1);
});

test('changed file length and service failures produce safe readable errors', async () => {
  const connection = {endpoint: 'http://127.0.0.1:8765/', identity: 'daily'};
  const large = new PersonalHubApi(connection, (async () => new Response('never shown', {headers: {'content-length': '300000'}})) as typeof fetch);
  await assert.rejects(() => large.textFile({path: 'notes.md', size: 1, modified: 1}), /文件较大/);
  const failed = new PersonalHubApi(connection, (async () => new Response('secret server stack', {status: 500})) as typeof fetch);
  await assert.rejects(() => failed.workspace(), error => error instanceof Error && !error.message.includes('secret') && error.message.includes('暂时无法读取'));
});
