import assert from 'node:assert/strict';
import {test} from 'node:test';
import type {ActivityQuery, ActivitySnapshot, Connection} from './core';
import {activityScope, createActivityStore} from './activity-store';

const daily: Connection = {endpoint: 'https://pajio.example/', identity: 'daily'};
const snapshot = (version = 'a', checked = '2026-10-07T10:00:00Z'): ActivitySnapshot => ({checked_at: checked,
  total: 0, unread: 0, counts: {attention: 0, active: 0, waiting: 0, results: 0}, items: [], has_more: false,
  filtered_total: 0, next_cursor: null, revision: version.repeat(64), changed_since: null});
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
function harness() {
  let now = 0;
  const timers = new Set<() => void>();
  const requests: {connection: Connection; query: ActivityQuery; reply: ReturnType<typeof deferred<ActivitySnapshot>>}[] = [];
  const store = createActivityStore({now: () => now, schedule: callback => {timers.add(callback); return () => {timers.delete(callback);};},
    load: (connection, query) => {const reply = deferred<ActivitySnapshot>(); requests.push({connection, query, reply}); return reply.promise;}});
  return {store, timers, requests, advance: (ms: number) => {now += ms;}, tick: () => {for (const timer of [...timers]) timer();}};
}
const settle = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};

test('all first-page consumers share one request, snapshot and polling clock', async () => {
  const h = harness();
  let updates = 0;
  const stopA = h.store.subscribe(daily, () => {updates++;});
  const stopB = h.store.subscribe({...daily}, () => {updates++;});
  const one = h.store.refresh(daily), two = h.store.refresh({...daily});
  assert.equal(one, two);
  await settle();
  assert.equal(h.requests.length, 1); assert.equal(h.timers.size, 1);
  h.requests[0].reply.resolve(snapshot()); await one;
  assert.equal(h.store.getSnapshot(daily), h.store.getSnapshot({...daily}));
  assert.equal(h.store.getSnapshot(daily).snapshot?.revision, 'a'.repeat(64));
  assert.ok(updates > 1);
  h.tick(); h.tick(); await settle(); assert.equal(h.requests.length, 2);
  stopA(); assert.equal(h.timers.size, 1);
  stopB(); assert.equal(h.timers.size, 0);
  h.requests[1].reply.resolve(snapshot('b')); await settle();
  assert.equal(h.store.getSnapshot(daily).snapshot?.revision, 'a'.repeat(64));
});

test('quick navigation reuses the checked snapshot without another request; old cache refreshes', async () => {
  const h = harness(); let stop = h.store.subscribe(daily, () => {});
  await settle(); h.requests[0].reply.resolve(snapshot()); await settle();
  stop(); h.advance(5000); stop = h.store.subscribe({...daily}, () => {}); await settle();
  assert.equal(h.requests.length, 1); assert.equal(h.store.getSnapshot(daily).stale, false);
  stop(); h.advance(15000); stop = h.store.subscribe(daily, () => {}); await settle();
  assert.equal(h.requests.length, 2);
  assert.deepEqual(h.requests[1].query, {since: 'a'.repeat(64)});
  stop(); h.requests[1].reply.resolve(snapshot('b')); await settle();
});

test('identity, endpoint and renewed development credentials each isolate snapshots', async () => {
  const h = harness();
  const scopes: Connection[] = [daily, {...daily, identity: 'work'}, {...daily, endpoint: 'https://other.example/'},
    {...daily, development: {accessToken: 'one', expiresAt: '2026-10-07T12:00:00Z'}},
    {...daily, development: {accessToken: 'two', expiresAt: '2026-10-07T12:00:00Z'}},
    {...daily, development: {accessToken: 'two', expiresAt: '2026-10-07T13:00:00Z'}}];
  assert.equal(new Set(scopes.map(activityScope)).size, scopes.length);
  const stops = scopes.map(scope => h.store.subscribe(scope, () => {})); await settle();
  assert.equal(h.requests.length, scopes.length);
  h.requests.forEach((request, index) => request.reply.resolve(snapshot(String(index)))); await settle();
  scopes.forEach((scope, index) => assert.equal(h.store.getSnapshot(scope).snapshot?.revision, String(index).repeat(64)));
  stops.forEach(stop => stop()); assert.equal(h.timers.size, 0);
});

test('switching scope cannot publish an old inflight response into the new view', async () => {
  const h = harness(), work = {...daily, identity: 'work'};
  let oldUpdates = 0;
  const stopDaily = h.store.subscribe(daily, () => {oldUpdates++;}); await settle();
  stopDaily(); const atStop = oldUpdates;
  const stopWork = h.store.subscribe(work, () => {}); await settle();
  h.requests[0].reply.resolve(snapshot('a')); await settle();
  assert.equal(oldUpdates, atStop); assert.equal(h.store.getSnapshot(work).snapshot, null);
  assert.equal(h.store.getSnapshot(daily).snapshot, null);
  h.requests[1].reply.resolve(snapshot('b')); await settle();
  assert.equal(h.store.getSnapshot(work).snapshot?.revision, 'b'.repeat(64)); stopWork();
});

test('unsubscribe and resubscribe during a request discards its error and serializes the replacement', async () => {
  const h = harness(); const first = h.store.subscribe(daily, () => {}); await settle();
  first(); const second = h.store.subscribe(daily, () => {}); await settle();
  assert.equal(h.requests.length, 1);
  h.requests[0].reply.reject(new Error('expired old view')); await settle();
  assert.equal(h.requests.length, 2); assert.equal(h.store.getSnapshot(daily).error, '');
  h.requests[1].reply.resolve(snapshot('b')); await settle();
  assert.equal(h.store.getSnapshot(daily).snapshot?.revision, 'b'.repeat(64)); second();
});

test('background pauses polling, preserves a labeled stale snapshot and refreshes on return', async () => {
  const h = harness(); const stop = h.store.subscribe(daily, () => {}); await settle();
  h.requests[0].reply.resolve(snapshot()); await settle();
  h.tick(); await settle(); h.store.setForeground(false);
  assert.equal(h.timers.size, 0); assert.equal(h.store.getSnapshot(daily).stale, true);
  h.requests[1].reply.resolve(snapshot('b')); await settle();
  assert.equal(h.store.getSnapshot(daily).snapshot?.revision, 'a'.repeat(64));
  assert.equal(await h.store.refresh(daily), null);
  h.store.setForeground(true); await settle(); assert.equal(h.requests.length, 3); assert.equal(h.timers.size, 1);
  assert.deepEqual(h.requests[2].query, {since: 'a'.repeat(64)});
  h.requests[2].reply.resolve(snapshot('c')); await settle();
  assert.equal(h.store.getSnapshot(daily).stale, false); stop();
});

test('failed refresh preserves data and checked time, labels it stale and recovers without optimistic state', async () => {
  const h = harness(); const stop = h.store.subscribe(daily, () => {}); await settle();
  const original = snapshot(); h.requests[0].reply.resolve(original); await settle();
  const failed = h.store.refresh(daily); await settle(); h.requests[1].reply.reject(new Error('network unavailable')); await failed;
  const stale = h.store.getSnapshot(daily);
  assert.equal(stale.snapshot, original); assert.equal(stale.stale, true); assert.equal(stale.error, 'network unavailable'); assert.equal(stale.loading, false);
  const retry = h.store.refresh(daily); await settle(); h.requests[2].reply.resolve(snapshot('b', '2026-10-07T10:02:00Z')); await retry;
  const fresh = h.store.getSnapshot(daily); assert.equal(fresh.error, ''); assert.equal(fresh.stale, false); assert.notEqual(fresh.snapshot, original); stop();
});

test('unsubscribing before dispatch makes no request; unobserved refresh stays read-only and idle', async () => {
  const h = harness(); const stop = h.store.subscribe(daily, () => {}); stop(); await settle();
  assert.equal(h.requests.length, 0); assert.equal(h.timers.size, 0);
  assert.equal(await h.store.refresh(daily), null); assert.equal(h.requests.length, 0);
});

test('connection credentials are captured by value for an inflight scoped read', async () => {
  const h = harness(), connection = {...daily, development: {accessToken: 'original', expiresAt: 'later'}};
  const stop = h.store.subscribe(connection, () => {});
  connection.identity = 'other'; connection.development.accessToken = 'mutated'; await settle();
  assert.equal(h.requests[0].connection.identity, 'daily'); assert.equal(h.requests[0].connection.development?.accessToken, 'original');
  stop(); h.requests[0].reply.resolve(snapshot()); await settle();
});


test('cloud accounts and rotated sessions never share a retained activity snapshot or mutable credentials', async () => {
  const h=harness();
  const a:Connection={...daily,session:{userId:'user_'+'a'.repeat(32),tenantId:'one',credentialId:'b'.repeat(32),accessToken:'c'.repeat(64),expiresAt:'2099-01-01T00:00:00Z'}};
  const b:Connection={...a,session:{...a.session!,userId:'user_'+'d'.repeat(32)}};
  const renewed:Connection={...a,session:{...a.session!,accessToken:'e'.repeat(64)}};
  const stops=[a,b,renewed].map(c=>h.store.subscribe(c,()=>{}));
  await settle();assert.equal(h.requests.length,3);
  const original=a.session!.accessToken;a.session!.accessToken='f'.repeat(64);
  assert.equal(h.requests[0].connection.session?.accessToken,original);
  h.requests[0].reply.resolve(snapshot('a'));h.requests[1].reply.resolve(snapshot('b'));h.requests[2].reply.resolve(snapshot('c'));await settle();
  assert.equal(h.store.getSnapshot(b).snapshot?.revision,'b'.repeat(64));
  assert.equal(h.store.getSnapshot(renewed).snapshot?.revision,'c'.repeat(64));
  assert.equal(h.store.getSnapshot(daily).snapshot,null);
  stops.forEach(stop=>stop());
});
