import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ApiError, scopeOf, type Connection, type Store} from './core';
import {TaskListApi, TaskListChanges, appendListPage, listRequest, parseCatalog, parseListPage, parseListReceipt, type ListRequest} from './task-lists';
import {mutationKey} from './record-mutations';
import {localRecords} from './record-sync';
import {accountCleanupPlan, fencedWrite} from './account-cleanup-model';
const connection = {endpoint: 'https://pajio.example/', identity: 'daily'}, stamp = '2026-10-08T12:00:00Z';
const id = 'list_' + 'a'.repeat(32), otherId = 'list_' + 'b'.repeat(32);
const list = {id, name: '购物', revision: 1, archived_at: null, created_at: stamp, updated_at: stamp, total: 1, open: 1};
const record = {id: 'life_' + 'a'.repeat(32), identity_id: 'daily', revision: 1, kind: 'task' as const, title: '牛奶', content: '', timezone: 'Asia/Shanghai', list_name: '购物', completed: false, deleted_at: null, updated_at: stamp, position: 1};
const request: ListRequest = {action: 'add', revision: 1, request_key: 'task-list-add-request-001', list_id: id, title: '牛奶', content: ''};
const receipt = {identity_id: 'daily', revision: 3, request_key: request.request_key, action: 'add', lists: [list], record, changed_records: 1};
function memory() {
  const data = new Map<string, unknown>();
  const store: Pick<Store, 'get' | 'put' | 'batch'> = {get: async <T>(key: string) => structuredClone(data.get(key) ?? null) as T | null, put: async (key, value) => {data.set(key, structuredClone(value));}, batch: async values => {for (const [key, value] of values) data.set(key, structuredClone(value));}};
  return {data, store};
}
function client(handler: (body?: ListRequest) => Response | Promise<Response>) {
  const calls: (ListRequest | undefined)[] = [];
  const api = new TaskListApi(connection, (async (url, init) => {
    assert.equal(new Headers(init?.headers).get('X-Wearing-Identity'), 'daily');
    assert.equal(init?.redirect, 'error'); assert.ok(init?.signal);
    if (String(url).endsWith('/api/bootstrap')) return Response.json({token: 'synthetic-csrf', identities: [{id: 'daily'}]});
    const body = init?.body ? JSON.parse(String(init.body)) : undefined; calls.push(body);
    if (body) assert.equal(new Headers(init?.headers).get('X-Wearing-Token'), 'synthetic-csrf');
    return handler(body);
  }) as typeof fetch);
  return {api, calls};
}
test('catalog validates identity, metadata and duplicate lists; no first-ten cut-off', () => {
  const lists = Array.from({length: 23}, (_, i) => ({...list, id: 'list_' + i.toString(16).padStart(32, '0')}));
  assert.equal(parseCatalog({identity_id: 'daily', revision: 24, lists}, 'daily').lists.length, 23);
  for (const value of [{identity_id: 'other', revision: 1, lists}, {identity_id: 'daily', revision: 1, lists: [list, list]}, {identity_id: 'daily', revision: -1, lists}, {identity_id: 'daily', revision: 1, lists: [{...list, open: 2}]}]) assert.throws(() => parseCatalog(value, 'daily'));
});
test('request allowlist rejects foreign scope and irrelevant fields', () => {
  assert.deepEqual(listRequest({...request, title: ' 牛奶 '}), listRequest(request));
  for (const value of [{...request, identity_id: 'other'}, {...request, revision: 1.5}, {...request, title: ''}, {...request, record_id: record.id}, {...request, list_id: 'bad'}, {...request, request_key: 'short'}]) assert.throws(() => listRequest(value));
});
test('117 items paginate completely, reject missing/overlap/stale/foreign pages', () => {
  const all = Array.from({length: 117}, (_, i) => ({...record, id: 'life_' + i.toString(16).padStart(32, '0'), position: i + 1}));
  const base = {identity_id: 'daily', revision: 2, list: {...list, total: 117, open: 117}};
  const first = parseListPage({...base, items: all.slice(0, 100), offset: 0, next_offset: 100}, 'daily', id);
  const last = parseListPage({...base, items: all.slice(100), offset: 100, next_offset: null}, 'daily', id);
  assert.equal(appendListPage(first, last).items.length, 117);
  assert.equal(appendListPage(null, first).items.length, 100);
  for (const next of [{...last, revision: 3}, {...last, identity_id: 'other'}, {...last, offset: 101}, {...last, items: [first.items[0], ...last.items.slice(1)]}]) assert.throws(() => appendListPage(first, next));
  assert.throws(() => appendListPage(null, last));
  for (const value of [{...base, items: all.slice(0, 100), offset: 0, next_offset: null}, {...base, items: [record, record], offset: 0, next_offset: 2}, {...base, items: [{...record, identity_id: 'other'}], offset: 0, next_offset: 1}]) assert.throws(() => parseListPage(value, 'daily', id));
});
test('receipts bind original action, identity, request, canonical task and target', () => {
  assert.equal(parseListReceipt(receipt, 'daily', request).record?.id, record.id);
  for (const value of [{...receipt, request_key: 'different-request'}, {...receipt, identity_id: 'other'}, {...receipt, revision: 1}, {...receipt, record: {...record, title: 'other'}}, {...receipt, lists: [{...list, id: otherId}]}, {...receipt, record: null}]) assert.throws(() => parseListReceipt(value, 'daily', request));
  assert.throws(() => parseListReceipt({...receipt, action: 'reorder'}, 'daily', request));
});
test('lost response survives restart, retries identical request and saves record with receipt atomically', async () => {
  const {store, data} = memory(); let lost = true;
  const {api, calls} = client(body => {
    assert.deepEqual((data.get(`task-list-request:${scopeOf(connection)}`) as {request: unknown}).request, body);
    if (lost) throw new Error('response lost after commit');
    return Response.json(receipt);
  });
  const changes = new TaskListChanges(store, api);
  await assert.rejects(() => changes.save(request));
  assert.equal((await changes.pending())?.phase, 'pending');
  await assert.rejects(() => changes.discardRejected());
  await assert.rejects(() => changes.save({...request, title: 'paper'}));
  lost = false;
  const reopened = new TaskListChanges(store, api);
  assert.equal((await reopened.save()).record?.id, record.id);
  assert.equal(await reopened.pending(), null);
  assert.equal((await localRecords(store, scopeOf(connection)))[0].id, record.id);
  assert.equal((data.get(`task-list-last-receipt:${scopeOf(connection)}`) as typeof receipt).request_key, request.request_key);
  assert.deepEqual(calls, [listRequest(request), listRequest(request)]);
});
test('unverified successful response remains unknown; conflict/rejection require explicit re-read workflow', async () => {
  const {store} = memory(); let result: Response = Response.json({...receipt, record: {...record, identity_id: 'other'}});
  const {api} = client(() => result.clone()), changes = new TaskListChanges(store, api);
  await assert.rejects(() => changes.save(request), (e: unknown) => e instanceof ApiError && e.status === 0);
  assert.equal((await changes.pending())?.phase, 'pending');
  result = new Response('', {status: 409});
  await assert.rejects(() => changes.save());
  assert.equal((await changes.pending())?.phase, 'conflict');
  await assert.rejects(() => changes.save());
  await changes.discardRejected(); assert.equal(await changes.pending(), null);
  result = new Response('', {status: 413});
  await assert.rejects(() => changes.save({...request, request_key: 'task-list-add-request-002'}));
  assert.equal((await changes.pending())?.phase, 'rejected');
});
test('failed local commit retains exact request even after verified server success', async () => {
  const {store} = memory(), realBatch = store.batch; let fail = true;
  store.batch = async values => {if (fail) throw new Error('disk full'); return realBatch(values);};
  const {api, calls} = client(() => Response.json(receipt)), changes = new TaskListChanges(store, api);
  await assert.rejects(() => changes.save(request), /disk full/);
  assert.equal((await changes.pending())?.phase, 'pending');
  fail = false; await new TaskListChanges(store, api).save();
  assert.equal(await changes.pending(), null); assert.deepEqual(calls[0], calls[1]);
});
test('same-scope concurrent panels cannot supersede an unresolved request', async () => {
  const {store} = memory(); let release!: () => void; const gate = new Promise<void>(done => {release = done;});
  const {api, calls} = client(async () => {await gate; throw new Error('lost');});
  const one = new TaskListChanges(store, api), two = new TaskListChanges(store, api);
  const a = one.save(request), b = two.save({...request, request_key: 'task-list-add-request-002'});
  const checks = [assert.rejects(() => a), assert.rejects(() => b)]; release(); await Promise.all(checks);
  assert.equal(calls.length, 1); assert.equal((await one.pending())?.request.request_key, request.request_key);
});
test('pending record edits prevent structural mutation; scopes and auth objects stay isolated', async () => {
  const {store} = memory(), {api, calls} = client(() => Response.json(receipt));
  await store.put(mutationKey(scopeOf(connection)), [{id: record.id}]);
  const changes = new TaskListChanges(store, api);
  await assert.rejects(() => changes.save(request), /先同步/); assert.equal(calls.length, 0);
  assert.equal(await changes.pending(), null);
  const other = new TaskListChanges(store, {connection: {...connection, identity: 'work'}, change: api.change.bind(api)});
  assert.notEqual(changes.key, other.key); assert.equal(await other.pending(), null);
  const mutable = {...connection, identity: 'original'}, frozen = new TaskListApi(mutable);
  mutable.identity = 'later'; assert.equal(frozen.connection.identity, 'original');
});
test('new durable list keys participate in account deletion fence and preserve other accounts', () => {
  const owner: Connection = {...connection, session: {userId: 'user_' + 'a'.repeat(32), tenantId: 'tenant_a', credentialId: 'c'.repeat(32), expiresAt: '2099-01-01T00:00:00Z'}};
  const other = {...owner, session: {...owner.session!, userId: 'user_' + 'b'.repeat(32)}};
  const rows = [owner, other].flatMap(c => ['task-list-request:', 'task-list-last-receipt:'].map(prefix => ({key: prefix + scopeOf(c), value: {sample: true}})));
  const plan = accountCleanupPlan(owner, rows);
  assert.deepEqual(plan.remove, rows.slice(0, 2).map(row => row.key));
  assert.equal(fencedWrite(rows[0].key, request, [plan.fence]), true);
  assert.equal(fencedWrite(rows[2].key, request, [plan.fence]), false);
});
