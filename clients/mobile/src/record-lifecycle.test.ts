import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ApiError, type RecordItem} from './core';
import {RecordMutations, mutationAction, mutationKey, mutationSyncedLabel, projectRecordMutation, type MutationTransport} from './record-mutations';
import {commitRecordReceipt, localRecords} from './record-sync';
import {recordEdit} from './record-editor';
import {fencedWrite, type AccountFence} from './account-cleanup-model';
const clone = <T>(value: T): T => structuredClone(value);
class Memory {
  data = new Map<string, unknown>(); fences: AccountFence[] = []; fail = false;
  async get<T>(key: string): Promise<T | null> {return clone(this.data.get(key) ?? null) as T | null;}
  async put(key: string, value: unknown) {await this.batch([[key, value]]);}
  async batch(values: [string, unknown][]) {if (this.fail || values.some(([key, value]) => fencedWrite(key, value, this.fences))) throw new Error('synthetic store fence'); for (const [key, value] of values) this.data.set(key, clone(value));}
}
const scope = 'https://fixture.example/|user_' + 'a'.repeat(32) + '|tenant_a|daily', other = scope.replace('tenant_a', 'tenant_b');
const stamp = '2026-10-08T12:00:00Z';
const record = (patch: Partial<RecordItem> = {}): RecordItem => ({id: 'life_' + 'a'.repeat(32), kind: 'note', title: '原始', content: '原始', timezone: 'Asia/Shanghai', revision: 1, updated_at: stamp, deleted_at: null, ...patch});
const tombstone = record({revision: 2, deleted_at: stamp});
function queue(store: Memory) {let key = 0; return new RecordMutations(store, () => `lifecycle-request-${++key}`);}
const unread = async () => {throw new Error('unexpected read');};
function deferred<T>() {let resolve!: (value: T) => void; const promise = new Promise<T>(done => {resolve = done;}); return {promise, resolve};}

test('notes, tasks and events archive and restore through official actions with persistent drafts', async () => {
  for (const kind of ['note', 'task', 'event'] as const) {
    const store = new Memory(), mutations = queue(store), original = record({kind, ...(kind === 'event' ? {start_at: '2026-10-08', end_at: '2026-10-09', all_day: true} : {})});
    const key = `record-edit:${scope}:${original.id}`, draft = {...recordEdit(original), text: '未提交输入'};
    const entry = await mutations.enqueueLifecycle(scope, original, 'archive', {key, value: draft});
    assert.equal(projectRecordMutation(entry).deleted_at, null);
    assert.equal((await store.get<typeof draft>(key))?.text, '未提交输入');
    const reopened = queue(store); assert.equal(mutationAction((await reopened.items(scope))[0]), 'archive');
    const archived = {...original, revision: 2, deleted_at: stamp};
    await reopened.flush(scope, {update: async (base, patch, action) => {assert.equal(base.revision, 1); assert.deepEqual(patch, {}); assert.equal(action, 'archive'); return archived;}, record: unread}, () => true);
    assert.deepEqual(await reopened.items(scope), []); assert.equal((await localRecords(store, scope))[0].deleted_at, stamp);
    await reopened.enqueueLifecycle(scope, archived, 'restore');
    assert.equal(projectRecordMutation((await reopened.items(scope))[0]).deleted_at, stamp);
    await reopened.flush(scope, {update: async (base, patch, action) => {assert.equal(base.revision, 2); assert.deepEqual(patch, {}); assert.equal(action, 'restore'); return {...original, revision: 3};}, record: unread}, () => true);
    assert.equal((await localRecords(store, scope))[0].deleted_at, null); assert.deepEqual(await store.get(key), draft);
  }
});
test('archive acknowledgement loss repeats exact frozen action and key after restart, never hides a later restored version', async () => {
  const store = new Memory(), mutations = queue(store), calls: unknown[] = [];
  await mutations.enqueueLifecycle(scope, record(), 'archive');
  await mutations.flush(scope, {update: async (...args) => {calls.push(args); throw new ApiError('unknown', 0);}, record: unread}, () => true, 100);
  await commitRecordReceipt(store, scope, record({revision: 3}));
  const reopened = new RecordMutations(store, () => {throw Error('must preserve request key');});
  await reopened.flush(scope, {update: async (...args) => {calls.push(args); return tombstone;}, record: unread}, () => true, 10000);
  assert.deepEqual(calls[0], calls[1]); assert.equal((calls[0] as unknown[])[2], 'archive');
  assert.equal((await localRecords(store, scope))[0].revision, 3); assert.equal((await localRecords(store, scope))[0].deleted_at, null);
  assert.match(mutationSyncedLabel('archive', (await localRecords(store, scope))[0], false), /目前处于可用状态/);
  assert.deepEqual(await reopened.items(scope), []);
});
test('unknown restoration cannot rebase against a newly deleted version or resurrect it on old acknowledgement', async () => {
  const store = new Memory(), mutations = queue(store), later = record({revision: 4, deleted_at: '2026-10-08T13:00:00Z'});
  await mutations.enqueueLifecycle(scope, tombstone, 'restore');
  await mutations.flush(scope, {update: async () => {throw new ApiError('reply lost', 0);}, record: unread}, () => true, 100);
  const inspected = await mutations.inspect(scope, record().id, later);
  assert.equal(inspected?.state, 'pending');
  await assert.rejects(() => mutations.resolveLifecycle(scope, record().id, 1, later, true), /状态已有变化/);
  await assert.rejects(() => mutations.enqueueLifecycle(scope, later, 'restore'), /结果未知/);
  await assert.rejects(() => mutations.enqueue(scope, record(), {content: 'overwrite'}), /还未确认/);
  await mutations.flush(scope, {update: async (base, patch, action, key) => {assert.equal(base.revision, 2); assert.equal(action, 'restore'); assert.deepEqual(patch, {}); assert.equal(key, 'lifecycle-request-1'); return record({revision: 3});}, record: unread}, () => true, 10000);
  assert.equal((await localRecords(store, scope))[0].revision, 4); assert.equal((await localRecords(store, scope))[0].deleted_at, later.deleted_at);
  assert.match(mutationSyncedLabel('restore', (await localRecords(store, scope))[0], true), /目前仍在最近删除/);
});
test('stale restore pauses on 409; only explicit current generation review creates a new attempt over the newer tombstone', async () => {
  const store = new Memory(), mutations = queue(store), later = record({revision: 4, deleted_at: '2026-10-08T13:00:00Z'});
  await mutations.enqueueLifecycle(scope, tombstone, 'restore');
  await mutations.flush(scope, {update: async () => {throw new ApiError('conflict', 409);}, record: async () => later}, () => true);
  const entry = (await mutations.items(scope))[0]; assert.equal(entry.state, 'conflict'); assert.equal(entry.latest?.revision, 4);
  assert.equal(await mutations.flush(scope, {update: async () => {throw Error('must not rebase');}, record: unread}, () => true), 0);
  await assert.rejects(() => mutations.resolveLifecycle(scope, entry.id, 2, later, true));
  await assert.rejects(() => mutations.resolveLifecycle(scope, entry.id, 1, tombstone, true));
  await mutations.resolveLifecycle(scope, entry.id, 1, later, true);
  await mutations.flush(scope, {update: async (base, patch, action, key) => {assert.equal(base.revision, 4); assert.equal(action, 'restore'); assert.equal(key, 'lifecycle-request-2'); assert.deepEqual(patch, {}); return record({revision: 5});}, record: unread}, () => true);
  assert.deepEqual(await mutations.items(scope), []); assert.equal((await localRecords(store, scope))[0].revision, 5);
});
test('archive conflict cancellation adopts current state but retains newer text draft and other identity', async () => {
  const store = new Memory(), mutations = queue(store), key = `record-edit:${scope}:${record().id}`, newer = {...recordEdit(record()), text: '更晚草稿'};
  await store.put(key, newer); await mutations.enqueueLifecycle(scope, record(), 'archive', {key, value: recordEdit(record())});
  await mutations.enqueueLifecycle(other, record(), 'archive');
  const server = record({revision: 2, content: '另一端修改'}); await mutations.inspect(scope, record().id, server);
  await mutations.resolveLifecycle(scope, record().id, 1, server, false);
  assert.deepEqual(await mutations.items(scope), []); assert.equal((await mutations.items(other)).length, 1);
  assert.deepEqual(await store.get(key), newer); assert.equal((await localRecords(store, scope))[0].deleted_at, null);
});
test('a rejected content edit can become an explicit restore while its text is preserved as a separate draft', async () => {
  const store = new Memory(), mutations = queue(store), key = `record-edit:${scope}:${record().id}`, draft = {...recordEdit(record()), text: '本机尚未保存的稿'};
  await mutations.enqueue(scope, record(), {content: draft.text});
  await mutations.flush(scope, {update: async () => {throw new ApiError('deleted', 409);}, record: async () => tombstone}, () => true);
  const restored = await mutations.enqueueLifecycle(scope, tombstone, 'restore', {key, value: draft}, 1);
  assert.equal(mutationAction(restored), 'restore'); assert.deepEqual(restored.patch, {}); assert.equal(restored.generation, 2);
  await mutations.flush(scope, {update: async (base, patch, action) => {assert.equal(base.revision, 2); assert.deepEqual(patch, {}); assert.equal(action, 'restore'); return record({revision: 3});}, record: unread}, () => true);
  assert.deepEqual(await mutations.items(scope), []); assert.deepEqual(await store.get(key), draft);
  assert.equal((await localRecords(store, scope))[0].content, '原始');
});
test('unknown edit and stale generation cannot be replaced by restoring, even after reading server state', async () => {
  const store = new Memory(), mutations = queue(store), key = 'draft-fixture';
  await mutations.enqueue(scope, record(), {content: 'pending'});
  await mutations.flush(scope, {update: async () => {throw new ApiError('unknown');}, record: unread}, () => true, 100);
  assert.equal((await mutations.inspect(scope, record().id, tombstone))?.state, 'pending');
  await assert.rejects(() => mutations.enqueueLifecycle(scope, tombstone, 'restore', {key, value: recordEdit(record())}, 1));
  await assert.rejects(() => mutations.resolve(scope, record().id, 1, tombstone, false));
  assert.equal((await mutations.items(scope))[0].patch.content, 'pending');
});
test('malformed lifecycle queues and deleted_at patches fail closed', async () => {
  const store = new Memory(), mutations = queue(store);
  await assert.rejects(() => mutations.enqueue(scope, record(), {deleted_at: stamp} as never));
  await assert.rejects(() => mutations.enqueueLifecycle(scope, record(), 'restore'));
  await assert.rejects(() => mutations.enqueueLifecycle(scope, tombstone, 'archive'));
  const valid = await mutations.enqueueLifecycle(scope, record(), 'archive');
  for (const bad of [{...valid, action: 'purge'}, {...valid, patch: {deleted_at: stamp}}, {...valid, base: {...record(), deleted_at: 'invalid'}}, {...valid, action: 'restore'}]) {
    await store.put(mutationKey(scope), [bad]); await assert.rejects(() => mutations.items(scope)); assert.deepEqual(await store.get(mutationKey(scope)), [bad]);
  }
});
test('unverified success and failed local receipt commits retain same request for recovery', async () => {
  const store = new Memory(), mutations = queue(store), keys: string[] = [];
  await mutations.enqueueLifecycle(scope, record(), 'archive');
  await mutations.flush(scope, {update: async (_b, _p, _a, key) => {keys.push(key); return record({revision: 2});}, record: unread}, () => true, 100);
  assert.equal((await mutations.items(scope))[0].state, 'pending'); assert.deepEqual(await localRecords(store, scope), []);
  const batch = store.batch.bind(store); let fail = true;
  store.batch = async values => {if (fail && values.some(([key]) => key.startsWith('receipts:'))) {fail = false; throw Error('receipt not durable');} await batch(values);};
  const transport: MutationTransport = {update: async (_b, _p, _a, key) => {keys.push(key); return tombstone;}, record: unread};
  await mutations.flush(scope, transport, () => true, 10000); assert.equal((await mutations.items(scope)).length, 1);
  await mutations.flush(scope, transport, () => true, 100000); assert.deepEqual(keys, Array(3).fill('lifecycle-request-1')); assert.deepEqual(await mutations.items(scope), []);
});
test('account cleanup fence and identity switch block later queued actions and stale receipt resurrection', async () => {
  const store = new Memory(), mutations = queue(store), gate = deferred<RecordItem>(), entered = deferred<void>(); let active = true, calls = 0;
  await mutations.enqueueLifecycle(scope, record(), 'archive'); await mutations.enqueueLifecycle(scope, record({id: 'life_second'}), 'archive');
  const flight = mutations.flush(scope, {update: async () => {calls++; entered.resolve(); return gate.promise;}, record: unread}, () => active);
  await entered.promise; active = false;
  store.fences = [{address: 'https://fixture.example/', userId: 'user_' + 'a'.repeat(32)}];
  store.data.delete(mutationKey(scope)); gate.resolve(tombstone); await flight;
  assert.equal(calls, 1); assert.deepEqual(await localRecords(store, scope), []); assert.deepEqual(await localRecords(store, other), []);
  await assert.rejects(() => mutations.enqueueLifecycle(scope, record(), 'archive'), /fence/);
});
test('durable sending state after cold start is retried with exact restore key, not stuck or recreated', async () => {
  const old = new Memory(), mutations = queue(old), gate = deferred<RecordItem>(), entered = deferred<void>();
  await mutations.enqueueLifecycle(scope, tombstone, 'restore');
  const first = mutations.flush(scope, {update: async () => {entered.resolve(); return gate.promise;}, record: unread}, () => true);
  await entered.promise;
  const fresh = new Memory(); await fresh.put(mutationKey(scope), await old.get(mutationKey(scope)));
  const reopened = new RecordMutations(fresh, () => {throw Error('no new id after restart');});
  assert.equal((await reopened.items(scope))[0].state, 'sending');
  await reopened.retry(scope, record().id);
  await reopened.flush(scope, {update: async (base, patch, action, key) => {assert.equal(base.revision, 2); assert.deepEqual(patch, {}); assert.equal(action, 'restore'); assert.equal(key, 'lifecycle-request-1'); return record({revision: 3});}, record: unread}, () => true);
  assert.deepEqual(await reopened.items(scope), []); gate.resolve(record({revision: 3})); await first;
});
