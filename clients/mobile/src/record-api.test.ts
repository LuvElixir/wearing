import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError, WearingApi, type Connection, type RecordItem} from './core';

const connection: Connection = {endpoint: 'https://synthetic-pajio.invalid/', identity: 'audit-only'};
const record = (patch: Partial<RecordItem> = {}): RecordItem => ({id: 'life_synthetic', kind: 'note', title: '合成验收', content: '仅用于请求契约测试', timezone: 'Asia/Shanghai', revision: 7, updated_at: '2026-10-07T10:00:00Z', ...patch});
const bootstrap = (token = 'csrf-synthetic') => ({version: '0.2.0', deployment: 'local', token, identities: [{id: connection.identity, name: '合成身份'}]});
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers: {'Content-Type': 'application/json'}});
type Call = {url: URL; init: RequestInit; headers: Headers; body: unknown};
function harness(replies: (() => Response)[], selected = connection) {
  const calls: Call[] = [];
  const api = new WearingApi(selected, (async (input, init = {}) => {
    calls.push({url: new URL(String(input)), init, headers: new Headers(init.headers), body: typeof init.body === 'string' ? JSON.parse(init.body) : null});
    const reply = replies.shift();
    assert.ok(reply, 'unexpected network request');
    return reply();
  }) as typeof fetch);
  return {api, calls, remaining: () => replies.length};
}
const status = (expected: number) => (error: unknown) => error instanceof ApiError && error.status === expected;

test('reading one record uses GET, a safely encoded id and identity headers without a mutation token', async () => {
  const value = record({id: 'synthetic id/#?'});
  const {api, calls, remaining} = harness([() => response(value)]);
  assert.deepEqual(await api.record(value.id), value);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url.pathname, '/api/life/synthetic%20id%2F%23%3F');
  assert.equal(calls[0].url.search, '');
  assert.equal(calls[0].init.method, 'GET');
  assert.equal(calls[0].headers.get('X-Wearing-Identity'), 'audit-only');
  assert.equal(calls[0].headers.has('X-Wearing-Token'), false);
  assert.equal(calls[0].init.redirect, 'error');
  assert.equal(remaining(), 0);
});

test('editing sends the observed revision and exact patch and returns only a validated receipt', async () => {
  const before = record(), after = record({revision: 8, content: '新内容', title: '新内容'});
  const {api, calls} = harness([() => response(bootstrap()), () => response(after)]);
  const patch = {title: '新内容', content: '新内容'};
  assert.deepEqual(await api.update(before, patch), after);
  assert.deepEqual(calls.map(call => [call.init.method, call.url.pathname]), [['GET', '/api/bootstrap'], ['PATCH', '/api/life/life_synthetic']]);
  assert.deepEqual(calls[1].body, {revision: 7, patch, action: 'edit'});
  assert.equal(calls[1].headers.get('X-Wearing-Token'), 'csrf-synthetic');
  assert.equal(calls[1].headers.get('X-Wearing-Identity'), 'audit-only');
  assert.equal(before.revision, 7);
  assert.equal(before.content, '仅用于请求契约测试');
});

test('archive and restore use reversible PATCH actions with the new observed revision', async () => {
  const deleted = record({revision: 8, deleted_at: '2026-10-07T10:05:00Z'});
  const restored = record({revision: 9, deleted_at: null});
  const {api, calls} = harness([() => response(bootstrap()), () => response(deleted), () => response(restored)]);
  const archived = await api.update(record(), {}, 'archive');
  assert.ok(archived.deleted_at);
  assert.deepEqual(await api.update(archived, {}, 'restore'), restored);
  assert.deepEqual(calls.slice(1).map(call => [call.init.method, call.body]), [
    ['PATCH', {revision: 7, patch: {}, action: 'archive'}],
    ['PATCH', {revision: 8, patch: {}, action: 'restore'}],
  ]);
  assert.equal(calls.filter(call => call.url.pathname === '/api/bootstrap').length, 1);
});

test('a mutation 403 refreshes the token once and replays the identical revision and action', async () => {
  const {api, calls} = harness([
    () => response(bootstrap('old-token')), () => response({detail: 'token expired'}, 403),
    () => response(bootstrap('new-token')), () => response(record({revision: 8})),
  ]);
  await api.update(record(), {content: '确切修改'}, 'edit');
  assert.deepEqual(calls.map(call => call.init.method), ['GET', 'PATCH', 'GET', 'PATCH']);
  assert.deepEqual(calls[3].body, calls[1].body);
  assert.equal(calls[1].headers.get('X-Wearing-Token'), 'old-token');
  assert.equal(calls[3].headers.get('X-Wearing-Token'), 'new-token');
  assert.ok(calls.every(call => call.headers.get('X-Wearing-Identity') === 'audit-only'));
});

test('persistent 403 stops after a single refreshed replay instead of retrying forever', async () => {
  const {api, calls} = harness([
    () => response(bootstrap()), () => response({detail: 'denied'}, 403),
    () => response(bootstrap('new')), () => response({detail: 'denied again'}, 403),
  ]);
  await assert.rejects(() => api.update(record(), {}, 'archive'), status(403));
  assert.equal(calls.length, 4);
});

test('a revision conflict is returned without silently refetching or overwriting the record', async () => {
  const input = record(), patch = {content: '保留本机输入'};
  const {api, calls} = harness([() => response(bootstrap()), () => response({detail: 'revision conflict'}, 409)]);
  await assert.rejects(() => api.update(input, patch), status(409));
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1].body, {revision: 7, patch, action: 'edit'});
  assert.equal(input.revision, 7);
});

test('a failed record read never performs a mutation or automatic token refresh', async () => {
  for (const failure of [401, 403, 404, 409, 500]) {
    const {api, calls} = harness([() => response({detail: '合成错误'}, failure)]);
    await assert.rejects(() => api.record('life_synthetic'), status(failure));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].init.method, 'GET');
  }
});

test('malformed record receipts cannot replace the editor with another or partial record', async () => {
  const invalid: unknown[] = [null, {}, [], record({id: 'life_other'}), record({revision: 0}), record({revision: 1.5}), record({updated_at: 'invalid'}),
    {...record(), kind: 'invented'}, {...record(), content: null}, {...record(), title: false}, {...record(), revision: Number.MAX_SAFE_INTEGER + 1}];
  for (const value of invalid) {
    const {api} = harness([() => response(value)]);
    await assert.rejects(() => api.record('life_synthetic'), status(422));
  }
});

test('a successful HTTP write with the wrong receipt id is still an unconfirmed edit', async () => {
  const {api, calls} = harness([() => response(bootstrap()), () => response(record({id: 'life_another', revision: 8}))]);
  await assert.rejects(() => api.update(record(), {content: '修改'}), status(422));
  assert.equal(calls.length, 2);
});

test('retrying organization posts only the selected capture id, never uploads or recreates its record', async () => {
  const before = record({capture: {id: 'capture_synthetic/#', state: 'failed', original_text: '合成原话', assets: [{id: 'asset_synthetic', name: 'synthetic.jpg', mime: 'image/jpeg'}]}});
  const after = {...before, capture: {...before.capture!, state: 'queued'}};
  const {api, calls} = harness([() => response(bootstrap()), () => response({record: after})]);
  assert.deepEqual(await api.retryCapture(before), after);
  assert.deepEqual(calls.map(call => [call.init.method, call.url.pathname]), [['GET', '/api/bootstrap'], ['POST', '/api/captures/capture_synthetic%2F%23/retry']]);
  assert.deepEqual(calls[1].body, {});
  assert.equal(calls[1].headers.get('X-Wearing-Identity'), 'audit-only');
  assert.equal(calls[1].headers.get('X-Wearing-Token'), 'csrf-synthetic');
});

test('retry without a capture id is rejected before network access', async () => {
  for (const value of [record(), record({capture: {state: 'failed', original_text: '合成', assets: []}})]) {
    const {api, calls} = harness([]);
    await assert.rejects(() => api.retryCapture(value), status(422));
    assert.equal(calls.length, 0);
  }
});

test('capture retries preserve conflict errors and validate the returned original record identity', async () => {
  const captured = record({capture: {id: 'capture_synthetic', state: 'paused', original_text: '合成', assets: []}});
  const conflicted = harness([() => response(bootstrap()), () => response({detail: 'newer user edit'}, 409)]);
  await assert.rejects(() => conflicted.api.retryCapture(captured), status(409));
  assert.equal(conflicted.calls.length, 2);
  for (const receipt of [null, {}, {record: null}, {record: record({id: 'life_other'})}]) {
    const {api} = harness([() => response(bootstrap()), () => response(receipt)]);
    await assert.rejects(() => api.retryCapture(captured), status(422));
  }
});

test('development bearer credentials stay in headers for read and write while identity remains scoped', async context => {
  const prior = Object.getOwnPropertyDescriptor(globalThis, '__DEV__');
  Object.defineProperty(globalThis, '__DEV__', {value: true, configurable: true});
  context.after(() => {if (prior) Object.defineProperty(globalThis, '__DEV__', prior); else Reflect.deleteProperty(globalThis, '__DEV__');});
  const development: Connection = {endpoint: 'http://192.168.1.25:8795/', identity: 'audit-only', development: {accessToken: 'q'.repeat(48), expiresAt: new Date(Date.now() + 600000).toISOString()}};
  const {api, calls} = harness([() => response(record()), () => response(bootstrap()), () => response(record({revision: 8}))], development);
  await api.record('life_synthetic');
  await api.update(record(), {content: '合成修改'});
  for (const call of calls) {
    assert.equal(call.headers.get('Authorization'), 'Bearer ' + 'q'.repeat(48));
    assert.equal(call.headers.get('X-Wearing-Identity'), 'audit-only');
    assert.equal(call.url.href.includes('q'.repeat(48)), false);
    assert.equal(call.url.search, '');
  }
});

test('a bootstrap response missing the chosen identity prevents mutation', async () => {
  const {api, calls} = harness([() => response({...bootstrap(), identities: [{id: 'other', name: '另一身份'}]})]);
  await assert.rejects(() => api.update(record(), {content: 'never sent'}), status(404));
  assert.deepEqual(calls.map(call => call.init.method), ['GET']);
});

test('a network failure and a non-JSON response remain actionable errors without implicit retries', async () => {
  let count = 0;
  const offline = new WearingApi(connection, (async () => {count++;throw new TypeError('synthetic transport detail');}) as typeof fetch);
  await assert.rejects(() => offline.record('life_synthetic'), error => status(0)(error) && error instanceof Error && !error.message.includes('synthetic transport detail'));
  assert.equal(count, 1);
  const html = new WearingApi(connection, (async () => new Response('<html>upstream failure</html>', {status: 503})) as typeof fetch);
  await assert.rejects(() => html.record('life_synthetic'), status(503));
});

test('idempotent edit token and its original revision survive the single CSRF refresh replay', async () => {
  const {api,calls}=harness([()=>response(bootstrap('old')),()=>response({detail:'refresh'},403),()=>response(bootstrap('new')),()=>response(record({revision:8}))]);
  await api.update(record(),{content:'修改'},'edit','synthetic-request-fixed');
  assert.deepEqual(calls[1].body,{revision:7,patch:{content:'修改'},action:'edit',request_key:'synthetic-request-fixed'});
  assert.deepEqual(calls[1].body,calls[3].body);
});
test('invalid or duplicate snapshot records cannot poison a later offline base',async()=>{
  for(const data of [{version:1,items:[{}]},{version:-1,items:[]},{version:1,items:[record(),record()]},{version:1,items:[record({revision:0})]}]){
    const {api}=harness([()=>response(data)]);await assert.rejects(()=>api.snapshot(),status(422));
  }
});
