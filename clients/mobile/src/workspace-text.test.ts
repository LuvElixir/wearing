import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {test} from 'node:test';
import {ApiError, type Store} from './core';
import {accountCleanupPlan, fencedWrite} from './account-cleanup-model';
import {TEXT_LIMIT, TextDocument, TextRequest, WorkspaceTextApi, WorkspaceTextDrafts, comparisonSummary, editableDocument, parseDocument, parseTextDraft, textSize} from './workspace-text';

const connection = {endpoint: 'https://pajio.example/', identity: 'daily'};
const digest = async (text: string) => createHash('sha256').update(text).digest('hex');
const stamp = '2026-10-08T12:00:00Z';
const document: TextDocument = {identity_id: 'daily', path: 'note.md', text: 'Synthetic base', sha256: createHash('sha256').update('Synthetic base').digest('hex'), size: 14, revision: 'a'.repeat(64), modified: 1234, editable: true, blocked_reason: null, save_mode: 'replace', history: []};
const key = 'text-request-fixture-001';
function memory() {
  const data = new Map<string, unknown>();
  const store: Pick<Store, 'get' | 'put'> = {get: async <T>(key: string) => structuredClone(data.get(key) ?? null) as T | null, put: async (key, value) => {data.set(key, structuredClone(value));}};
  return {store, data};
}
async function receipt(body: TextRequest) {return {identity_id: 'daily', source_path: body.path, path: body.path.startsWith('imports/') ? `documents/${body.request_key}/${body.path.split('/').pop()}` : body.path, sha256: await digest(body.text), revision: 'b'.repeat(64), size: textSize(body.text), modified: 5678, request_key: body.request_key, recovery_id: body.request_key, saved_at: stamp, save_mode: body.path.startsWith('imports/') ? 'copy' : 'replace'};}
function api(handler: (url: string, body?: TextRequest) => Response | Promise<Response>) {
  const calls: {url: string; body?: TextRequest}[] = [];
  const client = new WorkspaceTextApi(connection, digest, (async (url, init) => {
    assert.equal(new Headers(init?.headers).get('X-Wearing-Identity'), 'daily');
    assert.equal(init?.redirect, 'error'); assert.ok(init?.signal);
    if (String(url).endsWith('/api/bootstrap')) return Response.json({token: 'test-csrf', identities: [{id: 'daily'}]});
    const body = init?.body ? JSON.parse(String(init.body)) as TextRequest : undefined;
    calls.push({url: String(url), body});
    if (body) assert.equal(new Headers(init?.headers).get('X-Wearing-Token'), 'test-csrf');
    return handler(String(url), body);
  }) as typeof fetch);
  return {client, calls};
}
test('editable files exclude configuration, skills, secrets and traversal', () => {
  assert.ok(editableDocument('projects/用户笔记.md'));
  assert.ok(editableDocument('imports/import-fixture-01/notes.txt'));
  for (const path of ['../notes.md', 'file.json', '.env', '.secret.txt', 'skills/demo/note.md', 'SOUL.md', 'MEMORY.md', 'config/text.txt', 'secret.pem']) assert.equal(editableDocument(path), false, path);
  assert.equal(editableDocument('note.md', TEXT_LIMIT + 1), false);
  assert.equal(textSize('中文'), 6);
});
test('documents and local drafts validate identity, text bytes and pending intent', () => {
  assert.equal(parseDocument(document, 'daily', 'note.md').text, document.text);
  for (const patch of [{identity_id: 'other'}, {size: 1}, {sha256: 'bad'}, {revision: 'bad'}, {save_mode: 'copy'}, {history: [{id: 'bad'}]}, {text: 'x\0'}]) assert.throws(() => parseDocument({...document, ...patch}, 'daily', 'note.md'));
  const draft = {schema: 1, base: document, text: 'edit', pending: null};
  assert.equal(parseTextDraft(draft, 'daily', 'note.md').text, 'edit');
  assert.throws(() => parseTextDraft({...draft, pending: {path: 'note.md', text: 'other', base_revision: document.revision, base_sha256: document.sha256, request_key: key}}, 'daily', 'note.md'));
});
test('load and recovery are read only and verify hashes', async () => {
  const {client, calls} = api(url => Response.json(url.includes('/recovery?') ? {identity_id: 'daily', path: 'note.md', id: key, created_at: stamp, text: document.text, size: document.size, sha256: document.sha256} : document));
  assert.equal((await client.load('note.md')).revision, document.revision);
  assert.equal((await client.recovery('note.md', key)).text, document.text);
  assert.ok(calls.every(call => call.body === undefined));
  await assert.rejects(api(() => Response.json({...document, sha256: 'f'.repeat(64)})).client.load('note.md'));
});
test('keystrokes persist in order and a reopened editor restores the current draft', async () => {
  const {store} = memory(), {client, calls} = api(() => {throw new Error('must not call');});
  const drafts = new WorkspaceTextDrafts(store, client, 'note.md');
  await Promise.all([drafts.update(document, 'first'), drafts.update(document, 'second')]);
  assert.equal((await new WorkspaceTextDrafts(store, client, 'note.md').get())?.text, 'second');
  assert.equal(calls.length, 0);
  await assert.rejects(drafts.update(document, '中'.repeat(TEXT_LIMIT)), ApiError);
  await assert.rejects(drafts.update(document, '\ud800'), ApiError);
  assert.equal((await drafts.get())?.text, 'second');
});
test('save persists exact request before HTTP and unknown response survives restart', async () => {
  const {store, data} = memory(); let fail = true;
  const {client, calls} = api(async (_url, body) => {
    const saved = [...data.values()].find(Boolean) as {pending: TextRequest};
    assert.deepEqual(saved.pending, body);
    if (fail) throw new Error('network lost');
    return Response.json(await receipt(body!));
  });
  const drafts = new WorkspaceTextDrafts(store, client, 'note.md');
  await drafts.update(document, 'my edit');
  await assert.rejects(drafts.save(document, 'my edit', key));
  const old = (await drafts.get())!;
  await assert.rejects(drafts.update(document, 'new text'), /先取回/);
  fail = false;
  const restarted = new WorkspaceTextDrafts(store, client, 'note.md');
  await restarted.save(old.base, old.text, 'different-new-key-ignored');
  assert.deepEqual(calls[0].body, calls[1].body);
  assert.equal(await drafts.get(), null);
});
test('disk failure prevents save and bad success retains pending request', async () => {
  const {client, calls} = api(async (_url, body) => Response.json({...await receipt(body!), path: 'other.md'}));
  const broken = {get: async () => null, put: async () => {throw new Error('disk-full');}};
  await assert.rejects(new WorkspaceTextDrafts(broken, client, 'note.md').save(document, 'new', key), /disk-full/);
  assert.equal(calls.length, 0);
  const {store} = memory(), drafts = new WorkspaceTextDrafts(store, client, 'note.md');
  await assert.rejects(drafts.save(document, 'new', key), (error: unknown) => error instanceof ApiError && error.status === 0);
  assert.equal((await drafts.get())?.pending?.request_key, key);
});
test('failed local receipt cleanup retries the same confirmed server save', async () => {
  const {store, data} = memory(); let fail = true;
  const disk = {...store, put: async (name: string, value: unknown) => {if (value === null && fail) throw new Error('cleanup failure'); await store.put(name, value);}};
  const {client, calls} = api(async (_url, body) => Response.json(await receipt(body!)));
  const drafts = new WorkspaceTextDrafts(disk, client, 'note.md');
  await assert.rejects(drafts.save(document, 'updated', key), /cleanup failure/);
  assert.ok(data.get(drafts.key)); fail = false;
  await drafts.save(document, 'updated', 'must-not-be-used-key');
  assert.deepEqual(calls[0].body, calls[1].body); assert.equal(await drafts.get(), null);
});
test('409 preserves draft until explicit rebase, then saves using latest revision', async () => {
  const {store} = memory(); let conflict = true;
  const {client, calls} = api(async (_url, body) => conflict ? Response.json({}, {status: 409}) : Response.json(await receipt(body!)));
  const drafts = new WorkspaceTextDrafts(store, client, 'note.md');
  await assert.rejects(drafts.save(document, 'my edit', key), (error: unknown) => error instanceof ApiError && error.status === 409);
  const latest = {...document, text: 'Updated remote', sha256: await digest('Updated remote'), revision: 'c'.repeat(64)};
  assert.equal((await drafts.get())?.text, 'my edit');
  await drafts.rebase(latest, 'my edit');
  assert.equal((await drafts.get())?.pending, null);
  conflict = false;
  await drafts.save(latest, 'my edit', 'rebased-new-request');
  assert.equal(calls[1].body?.base_revision, latest.revision);
  assert.equal(calls[1].body?.text, 'my edit');
});
test('imports save to a distinct document path and reject a rewritten original receipt', async () => {
  const input = {...document, path: 'imports/import-key-fixture/note.md', save_mode: 'copy' as const};
  const {store} = memory(), {client} = api(async (_url, body) => Response.json(await receipt(body!)));
  const saved = await new WorkspaceTextDrafts(store, client, input.path).save(input, 'copy content', key);
  assert.equal(saved.path, `documents/${key}/note.md`);
  const wrong = api(async (_url, body) => Response.json({...await receipt(body!), path: input.path})).client;
  await assert.rejects(new WorkspaceTextDrafts(memory().store, wrong, input.path).save(input, 'copy content', key));
});
test('single-flight saves freeze auth and isolate identity/path drafts', async () => {
  const {store} = memory(); let done!: (response: Response) => void;
  const response = new Promise<Response>(resolve => {done = resolve;});
  const {client, calls} = api(() => response), drafts = new WorkspaceTextDrafts(store, client, 'note.md');
  const saving = drafts.save(document, 'new', key);
  await assert.rejects(drafts.save(document, 'new', key), /请稍候/);
  assert.equal(await new WorkspaceTextDrafts(store, new WorkspaceTextApi({...connection, identity: 'other'}, digest), 'note.md').get(), null);
  assert.equal(await new WorkspaceTextDrafts(store, client, 'elsewhere.md').get(), null);
  done(Response.json(await receipt({path: 'note.md', text: 'new', base_revision: document.revision, base_sha256: document.sha256, request_key: key})));
  await saving; assert.equal(calls.length, 1);
});
test('scoped draft participates in account cleanup and account fences', async () => {
  const cloud = {...connection, endpoint: 'https://pajio.example/', session: {userId: 'user_' + 'a'.repeat(32), tenantId: 'tenant_test', credentialId: 'c'.repeat(32), accessToken: 't'.repeat(64), expiresAt: '2030-01-01T00:00:00Z'}};
  const {store} = memory(), drafts = new WorkspaceTextDrafts(store, new WorkspaceTextApi(cloud, digest), 'note.md');
  const plan = accountCleanupPlan(cloud, [{key: drafts.key, value: {text: 'private'}}]);
  assert.deepEqual(plan.remove, [drafts.key]);
  assert.ok(fencedWrite(drafts.key, {}, [plan.fence]));
});
test('comparison describes actual first differing line without pretending to merge', () => {
  assert.match(comparisonSummary('same', 'same'), /相同/);
  assert.match(comparisonSummary('first\nold', 'first\nnew'), /第 2 行/);
  assert.match(comparisonSummary('first', 'first\nnew'), /第 2 行/);
});
