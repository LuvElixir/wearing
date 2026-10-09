import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ApiError, type Store} from './core';
import {BriefPreferenceApi, PreferenceChanges, parseSettings, preferenceValues, sourceAvailabilityLabel, sourceIds} from './briefing-preferences';
import {parseBriefing, validBriefingRequest} from './briefing';

const connection = {endpoint: 'https://pajio.example/', identity: 'daily'};
const stamp = '2026-10-08T12:00:00Z';
const values = {interests: ['设计'], priorities: '关注上线', sources: ['note' as const], max_items: 2};
const preferences = {schema: 1, identity_id: 'daily', revision: 0, updated_at: null, ...values};
const request = {...values, revision: 0, request_key: 'preference-save-fixture'};
const receipt = {...preferences, ...request, revision: 1, updated_at: stamp};
const settings = {preferences, available_sources: sourceIds.map(id => ({id, label: id, state: id === 'feishu' ? 'not_connected' : 'empty', count: id === 'feishu' ? null : 0, observed_at: stamp, truncated: false, selected: id === 'note'}))};
function memory() {
  const data = new Map<string, unknown>();
  const store: Pick<Store, 'get' | 'put'> = {get: async <T>(key: string) => structuredClone(data.get(key) ?? null) as T | null, put: async (key, value) => {data.set(key, structuredClone(value));}};
  return {store, data};
}
function api(handler: (body?: Record<string, unknown>) => Response | Promise<Response>) {
  const calls: unknown[] = [];
  const client = new BriefPreferenceApi(connection, (async (url, init) => {
    assert.equal(new Headers(init?.headers).get('X-Wearing-Identity'), 'daily');
    assert.equal(init?.redirect, 'error'); assert.ok(init?.signal);
    if (String(url).endsWith('/api/bootstrap')) return Response.json({token: 'csrf-synthetic', identities: [{id: 'daily'}]});
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push(body);
    if (body) assert.equal(new Headers(init?.headers).get('X-Wearing-Token'), 'csrf-synthetic');
    return handler(body);
  }) as typeof fetch);
  return {client, calls};
}
test('settings refuse foreign identity, invented sources, inconsistent selection and invalid inputs', () => {
  assert.equal(parseSettings(settings, 'daily').preferences.revision, 0);
  assert.throws(() => parseSettings(settings, 'other'));
  assert.throws(() => parseSettings({...settings, available_sources: settings.available_sources.slice(0, 4)}, 'daily'));
  assert.throws(() => parseSettings({...settings, available_sources: settings.available_sources.map(row => ({...row, selected: true}))}, 'daily'));
  for (const patch of [{sources: []}, {sources: ['mail']}, {sources: ['note', 'note']}, {max_items: 4}, {max_items: 1.2}, {interests: ['a', ' a']}, {interests: ['a'.repeat(61)]}, {priorities: 'a'.repeat(1001)}]) assert.throws(() => preferenceValues({...values, ...patch}));
});
test('source labels distinguish unread authorization from available files and failures', () => {
  assert.equal(sourceAvailabilityLabel({state: 'authorized', count: null, truncated: false}), '已授权，生成时才读取');
  assert.match(sourceAvailabilityLabel({state: 'failed', count: null, truncated: false}), /失败/);
  assert.match(sourceAvailabilityLabel({state: 'not_connected', count: null, truncated: false}), /尚未授权/);
  assert.match(sourceAvailabilityLabel({state: 'available', count: 30, truncated: true}), /30 项 · 部分列表/);
});
test('read only settings never bootstrap or save', async () => {
  const {client, calls} = api(() => Response.json(settings));
  assert.equal((await client.load()).available_sources.length, 5);
  assert.deepEqual(calls, [undefined]);
});
test('request is durable before HTTP and lost response resumes exact request after restart', async () => {
  const {store, data} = memory(); let fail = true;
  const {client, calls} = api(body => {
    assert.deepEqual([...data.values()].find(value => !!value), body);
    if (fail) throw new Error('lost response');
    return Response.json(receipt);
  });
  const editor = new PreferenceChanges(store, client);
  await assert.rejects(editor.save(request));
  assert.deepEqual(await editor.pending(), request);
  fail = false;
  const restored = new PreferenceChanges(store, client);
  assert.equal((await restored.save()).revision, 1);
  assert.deepEqual(calls, [request, request]); assert.equal(await restored.pending(), null);
});
test('disk failure blocks transmission and malformed success keeps original request', async () => {
  const {client, calls} = api(() => Response.json({...receipt, sources: ['event']}));
  const failedStore = {get: async () => null, put: async () => {throw new Error('disk full');}};
  await assert.rejects(new PreferenceChanges(failedStore, client).save(request), /disk full/);
  assert.equal(calls.length, 0);
  const {store} = memory(), changes = new PreferenceChanges(store, client);
  await assert.rejects(changes.save(request), (error: unknown) => error instanceof ApiError && error.status === 0);
  assert.deepEqual(await changes.pending(), request);
});
test('conflict never overwrites the pending intent and explicit rebase can retain user inputs', async () => {
  const {store} = memory(); let conflict = true;
  const {client, calls} = api(body => conflict ? Response.json({}, {status: 409}) : Response.json({...receipt, ...body, revision: Number(body?.revision) + 1}));
  const changes = new PreferenceChanges(store, client);
  await assert.rejects(changes.save(request), (error: unknown) => error instanceof ApiError && error.status === 409);
  assert.deepEqual(await changes.pending(), request);
  await assert.rejects(changes.save({...request, request_key: 'different-request-key'}), /先取回/);
  assert.equal(calls.length, 1);
  await changes.discardConflict(); conflict = false;
  assert.equal((await changes.save({...request, revision: 2, request_key: 'new-after-conflict-key'})).revision, 3);
});
test('parallel save is single flight and pending storage is identity isolated', async () => {
  const {store} = memory(); let resolve!: (response: Response) => void;
  const pending = new Promise<Response>(done => {resolve = done;});
  const {client, calls} = api(() => pending), changes = new PreferenceChanges(store, client);
  const first = changes.save(request);
  await assert.rejects(changes.save(request), /请稍候/);
  const other = new PreferenceChanges(store, new BriefPreferenceApi({...connection, identity: 'other'}));
  assert.equal(await other.pending(), null);
  resolve(Response.json(receipt)); await first;
  assert.equal(calls.length, 1);
});
test('generation accepts legacy protocol and verifies optional preference snapshot', () => {
  const request = {date: '2026-10-08', timezone: 'Asia/Shanghai', request_key: 'briefing-fixture-key', base_version: 0};
  assert.ok(validBriefingRequest(request)); assert.ok(validBriefingRequest({...request, preferences_revision: 1}));
  assert.equal(validBriefingRequest({...request, preferences_revision: true}), false);
  const brief = {id: 'brief_one', identity_id: 'daily', date: request.date, timezone: request.timezone, version: 1, created_at: stamp, updated_at: stamp, state: 'not_started', task_id: null, task_status: null, output: '', error: '', delivery: {queued: false, blocked_reason: null}, sources: [], artifacts: []};
  assert.equal(parseBriefing(brief, 'daily').preferences, undefined);
  assert.equal(parseBriefing({...brief, preferences}, 'daily').preferences?.max_items, 2);
  assert.throws(() => parseBriefing({...brief, preferences: {...preferences, identity_id: 'other'}}, 'daily'));
});
