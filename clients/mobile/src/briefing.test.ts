import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ApiError} from './core';
import {BriefingApi, parseBriefing, validBriefingRequest} from './briefing';

const connection = {endpoint: 'https://pajio.example/', identity: 'daily'};
const stamp = '2026-10-07T12:00:00Z';
const item = {id: 'brief_1', identity_id: 'daily', date: '2026-10-07', timezone: 'Asia/Shanghai', version: 1, created_at: stamp, updated_at: stamp,
  state: 'running', task_id: 'task_1', task_status: 'running', output: '', error: '', delivery: {queued: false, blocked_reason: null},
  sources: [{id: 'note', label: '笔记', state: 'available', count: 2, observed_at: stamp, truncated: false}], artifacts: []};
const request = {date: '2026-10-07', timezone: 'Asia/Shanghai', request_key: 'test-briefing-request-01', base_version: 0};
const bootstrap = {version: '0.2.0', token: 'qa-csrf', identities: [{id: 'daily'}]};
type Call = {path: string; method: string; body: any};
function fake(handler: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const api = new BriefingApi(connection, (async (url, init) => {
    const headers = new Headers(init?.headers);
    assert.equal(headers.get('X-Wearing-Identity'), 'daily'); assert.equal(init?.redirect, 'error'); assert.ok(init?.signal);
    const parsed = new URL(String(url)), call = {path: parsed.pathname + parsed.search, method: init?.method || 'GET', body: init?.body ? JSON.parse(String(init.body)) : null};
    calls.push(call); return handler(call);
  }) as typeof fetch);
  return {api, calls};
}
test('briefing request validation enforces exact day, zone, version and stable key', () => {
  assert.ok(validBriefingRequest(request));
  for (const override of [{date: '2026-02-30'}, {date: '../file'}, {timezone: 'bad/zone'}, {base_version: 1.2}, {base_version: -1}, {request_key: 'short'}]) assert.equal(validBriefingRequest({...request, ...override}), false);
});
test('briefing parser refuses foreign identity/date/artifact task and unbacked ready state', () => {
  assert.equal(parseBriefing(item, 'daily').state, 'running');
  assert.throws(() => parseBriefing({...item, identity_id: 'other'}, 'daily'), /不完整/);
  assert.throws(() => parseBriefing(item, 'daily', '2026-10-08'), /不完整/);
  assert.throws(() => parseBriefing({...item, state: 'ready'}, 'daily'), /不完整/);
  const artifact = {id: 'art_1', task_id: 'other_task', title: '结果', summary: '摘要', revision: 1, sources: [], limitations: [], checks: {file: 'verified', render: 'not_verified', content: 'not_verified'}};
  assert.throws(() => parseBriefing({...item, artifacts: [artifact]}, 'daily'), /不完整/);
  assert.equal(parseBriefing({...item, state: 'ready', task_status: 'completed_unverified', artifacts: [{...artifact, task_id: 'task_1'}]}, 'daily').artifacts[0].checks.content, 'not_verified');
});
test('opening a day is read-only and accepts source failure without inventing available content', async () => {
  const entry = {...item, sources: [{...item.sources[0], state: 'failed', count: null}]};
  const {api, calls} = fake(() => Response.json({identity_id: 'daily', date: request.date, timezone: request.timezone, items: [entry]}));
  assert.equal((await api.list(request.date, request.timezone))[0].sources[0].state, 'failed');
  assert.equal(calls.length, 1); assert.equal(calls[0].method, 'GET'); assert.equal(calls[0].body, null);
  assert.match(calls[0].path, /timezone=Asia%2FShanghai/);
});
test('create uses original exact request and does not retry uncertain network outcome', async () => {
  let fail = true;
  const {api, calls} = fake(call => {if (call.path === '/api/bootstrap') return Response.json(bootstrap); if (fail) throw new Error('response lost'); return Response.json(item);});
  await assert.rejects(api.create(request), (cause: unknown) => cause instanceof ApiError && cause.status === 0);
  assert.equal(calls.length, 2);
  fail = false;
  assert.equal((await api.create(request)).task_id, item.task_id);
  assert.deepEqual(calls[1].body, calls[2].body); assert.deepEqual(calls[2].body, request);
});
test('concurrent clicks are single-flight and CSRF recovery retains the exact intent once', async () => {
  let resolve!: (value: Response) => void;
  const gate = new Promise<Response>(done => {resolve = done;});
  const {api, calls} = fake(call => call.path === '/api/bootstrap' ? Response.json(bootstrap) : gate);
  const first = api.create(request);
  await assert.rejects(api.create(request), /请稍候/);
  resolve(Response.json(item)); await first;
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  const forbidden = fake(call => call.path === '/api/bootstrap' ? Response.json(bootstrap) : Response.json({detail: 'token invalid'}, {status: 403}));
  await assert.rejects(forbidden.api.create(request), (cause: unknown) => cause instanceof ApiError && cause.status === 403);
  assert.equal(forbidden.calls.length, 4); assert.deepEqual(forbidden.calls[1].body, forbidden.calls[3].body);
});
test('version conflict does not fetch a new version or automatically generate again', async () => {
  const {api, calls} = fake(call => call.path === '/api/bootstrap' ? Response.json(bootstrap) : Response.json({detail: '已有新版本'}, {status: 409}));
  await assert.rejects(api.create(request), (cause: unknown) => cause instanceof ApiError && cause.status === 409);
  assert.equal(calls.length, 2);
});
