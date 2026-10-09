import {test} from 'node:test';
import assert from 'node:assert/strict';
import {deviceCollectionState, hubHelpDraft, hubIdentity, hubRuntime, memoryCollection, memoryCorrectionDraft, memoryRemovalDraft, memoryObservationLabel, PersonalHubApi, safeWorkspacePath, textPreviewAllowed, WORKSPACE_ORIGINAL_LIMIT, workspaceEntries, workspaceFileDraft, workspaceMimeType, workspaceSearch, workspaceSnapshot} from './personal-hub';

test('memory correction retains the viewed entry and labels bounded excerpts before handoff', () => {
  const entry = '出行偏好：安静的地方。\n备注：不住青旅。';
  const draft = memoryCorrectionDraft('user', entry);
  assert.ok(draft.includes(entry));
  assert.ok(draft.includes('关于你'));
  assert.ok(draft.endsWith('应改为：\n'));
  const longDraft = memoryCorrectionDraft('memory', '记'.repeat(13000));
  assert.ok(longDraft.length < 12000);
  assert.ok(longDraft.includes('[原记忆较长，以上为节选]'));
  assert.ok(memoryCorrectionDraft('memory').includes('长期记忆'));
});

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

test('memory removal and capability handoffs stay bounded and do not claim completion', () => {
  const removal = memoryRemovalDraft('user', '记忆'.repeat(10000));
  assert.ok(removal.length < 12000);
  assert.match(removal, /请先核对完整条目/);
  assert.match(removal, /仅删除这一条/);
  assert.doesNotMatch(removal, /已删除/);
  assert.match(hubHelpDraft('skills'), /先查看，不安装/);
  assert.match(hubHelpDraft('messaging'), /先不要发送任何外部消息/);
  assert.match(hubHelpDraft('devices', {id: 'mac_1', name: '家里的电脑', kind: 'computer', online: null}), /家里的电脑.*mac_1/);
});

test('file search stays inside a folder and retains nested paths for matching originals', () => {
  const files = [
    {path: 'work/Research/Notes.md', size: 10, modified: 1},
    {path: 'work/notes.txt', size: 5, modified: 1},
    {path: 'workshop/notes.md', size: 2, modified: 1},
  ];
  assert.deepEqual(workspaceSearch(files, 'work', 'NOTES').map(file => file.path), ['work/notes.txt', 'work/Research/Notes.md']);
  assert.match(workspaceFileDraft(files[0].path), /work\/Research\/Notes.md/);
  assert.throws(() => workspaceFileDraft('../secret.txt'));
});

test('original exports use authenticated read only requests and reject changed or oversized bodies', async () => {
  const connection = {endpoint: 'http://127.0.0.1:8765/', identity: 'daily'};
  const calls: {url: string; init?: RequestInit}[] = [];
  const bytes = new Uint8Array([0, 1, 2, 255]);
  const api = new PersonalHubApi(connection, (async (url, init) => {
    calls.push({url: String(url), init});
    return new Response(bytes);
  }) as typeof fetch);
  assert.deepEqual(await api.original({path: '私人资料/报告.pdf', size: 4, modified: 1}), bytes);
  assert.equal(new URL(calls[0].url).searchParams.get('path'), '私人资料/报告.pdf');
  assert.equal(calls[0].init?.redirect, 'error');
  assert.equal(calls[0].init?.method, undefined);
  assert.equal((calls[0].init?.headers as Record<string, string>)['X-Wearing-Identity'], 'daily');
  await assert.rejects(() => api.original({path: 'huge.pdf', size: WORKSPACE_ORIGINAL_LIMIT + 1, modified: 1}), /20 MB/);
  await assert.rejects(() => api.original({path: '../private.pdf', size: 4, modified: 1}));
  assert.equal(calls.length, 1);
  const changed = new PersonalHubApi(connection, (async () => new Response('hidden', {headers: {'content-length': String(WORKSPACE_ORIGINAL_LIMIT + 1)}})) as typeof fetch);
  await assert.rejects(() => changed.original({path: 'grew.pdf', size: 4, modified: 1}), /20 MB/);
  assert.equal(workspaceMimeType('REPORT.PDF'), 'application/pdf');
  assert.equal(workspaceMimeType('unknown.xyz'), 'application/octet-stream');
});

test('server workspace pages preserve continuation and never call an incomplete search empty', async () => {
  const {workspacePage, mergeWorkspacePages, workspaceProgress} = await import('./personal-hub');
  const first = workspacePage({files: [], truncated: true, complete: false, scan_id: 'a'.repeat(32), page_cursor: 'a'.repeat(43), next_cursor: 'b'.repeat(43), query: '报告', directory: 'work', scanned: 2000, phase: 'scanning'}, {query: '报告', directory: 'work'});
  assert.match(workspaceProgress(first), /还没有查完/);
  const final = workspacePage({files: [{path: 'work/2026/报告.md', size: 8, modified: 1}], truncated: false, complete: true, scan_id: first.scan_id, page_cursor: first.next_cursor, next_cursor: null, query: '报告', directory: 'work', scanned: 2300, phase: 'complete'}, {query: '报告', directory: 'work', cursor: first.next_cursor!});
  const merged = mergeWorkspacePages(first, final);
  assert.equal(merged.complete, true); assert.equal(merged.files[0].path, 'work/2026/报告.md');
  assert.match(workspaceProgress(merged), /1 份文件/);
  assert.throws(() => mergeWorkspacePages(first, {...final, scan_id: 'c'.repeat(32)}));
  assert.throws(() => mergeWorkspacePages(first, {...final, page_cursor: 'c'.repeat(43)}));
  assert.throws(() => mergeWorkspacePages(first, {...final, query: '另一个关键词'}));
  assert.throws(() => mergeWorkspacePages(first, {...final, scanned: 1}));
});

test('workspace parser rejects cross-folder files and inconsistent or missing continuation', async () => {
  const {workspacePage} = await import('./personal-hub');
  const base = {files: [{path: 'work/report.md', size: 8, modified: 1}], truncated: true, complete: false, scan_id: 'a'.repeat(32), page_cursor: 'a'.repeat(43), next_cursor: 'b'.repeat(43), query: '', directory: 'work', scanned: 10, phase: 'scanning'};
  for (const bad of [{...base, next_cursor: null}, {...base, scan_id: 'bad'}, {...base, complete: true}, {...base, files: [{path: 'workshop/report.md', size: 8, modified: 1}]}, {...base, directory: ''}]) assert.throws(() => workspacePage(bad, {directory: 'work'}));
});

test('file pagination and exact metadata keep auth scope and avoid a first-200 lookup', async () => {
  const token = 'x'.repeat(48), calls: {url: URL; init?: RequestInit}[] = [];
  const connection = {endpoint: 'http://127.0.0.1:8765/', identity: 'daily'};
  const api = new PersonalHubApi(connection, (async (input, init) => {
    const url = new URL(String(input)); calls.push({url, init});
    if (url.pathname.endsWith('/metadata')) return new Response(JSON.stringify({path: 'work/file-999.md', size: 2, modified: 1}));
    return new Response(JSON.stringify({files: [], truncated: false, complete: true, scan_id: 'a'.repeat(32), page_cursor: 'a'.repeat(43), next_cursor: null, query: '文件', directory: 'work', scanned: 2200, phase: 'complete'}));
  }) as typeof fetch);
  connection.identity = 'changed-after-construction';
  await api.workspacePage({directory: 'work', query: ' 文件 '});
  assert.equal(calls[0].url.searchParams.get('query'), '文件');
  assert.equal((calls[0].init?.headers as Record<string, string>)['X-Wearing-Identity'], 'daily');
  assert.equal(calls[0].init?.redirect, 'error');
  assert.equal((await api.workspaceMetadata('work/file-999.md')).path, 'work/file-999.md');
  assert.equal(calls[1].url.pathname, '/api/workspace/metadata');
  await assert.rejects(() => api.workspacePage({cursor: token}));
  await assert.rejects(() => api.workspaceMetadata('../private'));
  assert.equal(calls.length, 2);
});

test('cancelled searches abort network and expired cursor gives a restartable error', async () => {
  const stop = new AbortController();
  let observed: AbortSignal | undefined;
  const api = new PersonalHubApi({endpoint: 'http://127.0.0.1:8765', identity: 'daily'}, (async (_, init) => {
    observed = init?.signal as AbortSignal;
    return new Promise((_resolve, reject) => observed!.addEventListener('abort', () => reject(new Error('cancelled'))));
  }) as typeof fetch);
  const request = api.workspacePage({query: 'old'}, stop.signal);
  stop.abort(); await assert.rejects(request); assert.equal(observed?.aborted, true);
  const stale = new PersonalHubApi({endpoint: 'http://127.0.0.1:8765', identity: 'daily'}, (async () => new Response('internal details', {status: 409})) as typeof fetch);
  await assert.rejects(() => stale.workspacePage(), error => error instanceof Error && /重新读取/.test(error.message) && !/internal/.test(error.message));
});
