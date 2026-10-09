import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError, scopeOf, type Connection, type Store} from './core';
import {ChatImportApi, ChatImportJournal, chatImportDraftKey, chatImportPendingKey, makeChatImportRequest, type ChatImportDraft} from './chat-import-client';
import {parseChatText} from './chat-import-parser';
import {accountCleanupPlan} from './account-cleanup-model';
const connection: Connection = {endpoint: 'http://localhost:8765', identity: 'personal'};
const draft = (): ChatImportDraft => ({version: 1, key: 'synthetic-request-00001', sourceHash: 'a'.repeat(64), selfAuthor: null, preview: parseChatText(new TextEncoder().encode('·合成作者甲\n2026年10月9日 09:00\n合成消息，不是真实聊天。\n·合成作者乙\n2026年10月9日 09:01\n收到。'))});
function memory() {const map = new Map<string, unknown>(); return {map, get: async <T>(key: string) => (map.get(key) ?? null) as T | null, put: async (key: string, value: unknown) => {map.set(key, structuredClone(value));}} as Pick<Store, 'get' | 'put'> & {map: Map<string, unknown>};}
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
const receipt = (key: string, status = 'imported') => ({schema: 1, identity_id: 'personal', request_key: key, import_id: 'chatimp_synthetic001', status, created_at: '2026-10-09T00:00:00Z'});
test('preview and optional author changes stay local until explicit confirmation', async () => {
  let calls = 0; const store = memory(), journal = new ChatImportJournal(store, new ChatImportApi(connection, async () => {calls++; throw Error();}));
  await journal.retain(draft()); await journal.retain({...draft(), selfAuthor: '合成作者甲'});
  assert.equal(calls, 0); assert.equal((await journal.draft())?.selfAuthor, '合成作者甲'); await journal.discard(); assert.equal(await journal.draft(), null);
});
test('lost POST response recovers exact request key through receipt without a second import', async () => {
  const store = memory(); let posts = 0, committed = false, posted: unknown;
  const fetcher: typeof fetch = async (input, init) => {
    const path = new URL(String(input)).pathname;
    if (path === '/api/bootstrap') return json({token: 'synthetic-token', identities: [{id: 'personal'}]});
    if (path.startsWith('/api/chat-imports/receipts/')) return committed ? json(receipt(draft().key)) : json({}, 404);
    assert.equal(init?.method, 'POST'); posts++; posted = JSON.parse(String(init?.body)); committed = true; throw Error('synthetic network loss after commit');
  };
  const first = new ChatImportJournal(store, new ChatImportApi(connection, fetcher)); await first.retain(draft());
  await assert.rejects(first.confirm(), /结果尚未确认/); assert.equal(posts, 1); assert.deepEqual(posted, makeChatImportRequest(draft()));
  const reopened = new ChatImportJournal(store, new ChatImportApi(connection, fetcher));
  const result = await reopened.confirm(); assert.equal(result.receipt.status, 'imported'); assert.equal(posts, 1);
  assert.equal(await reopened.draft(), null); assert.equal((await reopened.pending())?.request, null); await reopened.finish(); assert.equal(await reopened.pending(), null);
});
test('unknown-result retry freezes author and original content', async () => {
  const store = memory(), api = new ChatImportApi(connection, async () => {throw Error('offline');}); const journal = new ChatImportJournal(store, api);
  await journal.retain(draft()); await assert.rejects(journal.confirm()); await assert.rejects(journal.retain({...draft(), selfAuthor: '合成作者乙'}), /先核对/);
  await assert.rejects(journal.discard(), /尚需核对/); assert.equal((await journal.pending())?.request?.self_author, null);
});
test('another identity cannot see or replay the private draft', async () => {
  const store = memory(), first = new ChatImportJournal(store, new ChatImportApi(connection, fetch)); await first.retain(draft());
  const other = new ChatImportJournal(store, new ChatImportApi({...connection, identity: 'work'}, fetch));
  assert.equal(await other.draft(), null); assert.equal(await other.pending(), null); await assert.rejects(other.confirm(), /先选择/);
});
test('identity change after GET response prevents POST and preserves the original journal', async () => {
  const store = memory(); let active = true, calls = 0;
  const api = new ChatImportApi(connection, async () => {calls++; active = false; return json({}, 404);}, () => active);
  const journal = new ChatImportJournal(store, api); await journal.retain(draft()); await assert.rejects(journal.confirm(), /身份已切换/);
  assert.equal(calls, 1); assert.equal((await journal.pending())?.key, draft().key);
});
test('receipt from the wrong identity never clears the pending body', async () => {
  const store = memory(), journal = new ChatImportJournal(store, new ChatImportApi(connection, async () => json({...receipt(draft().key), identity_id: 'someone-else'})));
  await journal.retain(draft()); await assert.rejects(journal.confirm(), /回执尚未核对/); assert.ok((await journal.pending())?.request);
});
test('deleted receipt cannot resurrect a previously removed batch', async () => {
  let calls = 0; const store = memory(), journal = new ChatImportJournal(store, new ChatImportApi(connection, async () => {calls++; return json(receipt(draft().key, 'deleted'));}));
  await journal.retain(draft()); const result = await journal.confirm(); assert.equal(result.receipt.status, 'deleted'); assert.equal(calls, 1); assert.equal(await journal.draft(), null);
});
test('logout-retained request only queries status and never submits a guessed replacement', async () => {
  const store = memory(); let calls = 0; await store.put(chatImportPendingKey(scopeOf(connection)), {version: 1, key: draft().key, request: null});
  const journal = new ChatImportJournal(store, new ChatImportApi(connection, async (_url, init) => {calls++; assert.equal(init?.method, 'GET'); return json({}, 404);}));
  await assert.rejects(journal.confirm(), (error: unknown) => error instanceof ApiError && error.status === 410); assert.equal(calls, 1); await journal.clearMissing(); assert.equal(await journal.pending(), null);
});
test('author must be observed in transcript; entire request remains bounded', () => {
  assert.throws(() => makeChatImportRequest({...draft(), selfAuthor: 'unobserved'}));
  const large = draft(); large.preview.messages = Array.from({length: 100}, (_, i) => ({...large.preview.messages[0], id: String(i), text: 'a'.repeat(8000)}));
  assert.throws(() => makeChatImportRequest(large), /512 KB/);
});
test('account deletion removes private import contents only from its owner', () => {
  const c: Connection = {endpoint:'https://pajio.test', identity:'personal', session:{userId:'user_'+'a'.repeat(32),tenantId:'tenant_a',credentialId:'x'.repeat(32),expiresAt:'2099-01-01T00:00:00Z'}};
  const other = {...c, session: {...c.session!, userId:'user_'+'b'.repeat(32)}};
  const mine = chatImportDraftKey(scopeOf(c)), theirs = chatImportDraftKey(scopeOf(other));
  const plan = accountCleanupPlan(c, [{key:mine,value:draft()},{key:chatImportPendingKey(scopeOf(c)),value:{request:makeChatImportRequest(draft())}},{key:theirs,value:draft()}]);
  assert.deepEqual(plan.remove.sort(), [mine,chatImportPendingKey(scopeOf(c))].sort()); assert.ok(!plan.remove.includes(theirs));
});
