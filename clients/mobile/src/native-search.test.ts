import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ApiError} from './core';
import {NativeSearchApi, SearchItem, mergeSearchPages, parseSearchMessage, parseSearchPage, searchQuery} from './native-search';

const stamp = '2026-10-08T00:00:00Z';
const item: SearchItem = {key: 'message:7', id: '7', kind: 'message', title: '去旅行', snippet: '周五出发旅行', matched_field: 'output', record_kind: null, created_at: stamp, updated_at: stamp, target: {kind: 'message', message_id: 7, task_id: 'task_1'}};
const page = {identity_id: 'daily', query: '旅行', kind: 'all', items: [item], next_cursor: null, as_of: stamp, files_included: false};
const detail = {identity_id: 'daily', id: 7, task_id: 'task_1', content: '去旅行', output: '周五出发旅行', status: 'completed_unverified', created_at: stamp, updated_at: stamp};
test('search parser accepts typed exact targets and rejects identity/query/type mismatch or arbitrary URL', () => {
  assert.equal(parseSearchPage(page, 'daily', '旅行', 'all').items[0].key, item.key);
  for (const value of [{...page, identity_id: 'other'}, {...page, query: '别的'}, {...page, kind: 'task'}, {...page, files_included: true}, {...page, items: [item, item]}, {...page, items: [{...item, target: {...item.target, url: 'https://evil.example'}}]}, {...page, items: [{...item, target: {...item.target, message_id: 99}}]}]) assert.throws(() => parseSearchPage(value, 'daily', '旅行', 'all'), /不完整/);
});
test('message details must match both the selected message and task', () => {
  assert.equal(parseSearchMessage(detail, 'daily', 7, 'task_1').content, '去旅行');
  for (const value of [{...detail, identity_id: 'other'}, {...detail, id: 8}, {...detail, task_id: 'other'}]) assert.throws(() => parseSearchMessage(value, 'daily', 7, 'task_1'));
});
test('query is literal, trimmed, bounded and can include Chinese and punctuation', () => {
  assert.equal(searchQuery('  50% [旅行]  '), '50% [旅行]');
  for (const value of ['', ' ', 'a'.repeat(121), 'a\n']) assert.throws(() => searchQuery(value));
});
test('read requests include authenticated identity and expected tenant without sending secrets in URL', async () => {
  const connection = {endpoint: 'https://pajio.example/', identity: 'daily', session: {accessToken: 'a'.repeat(64), credentialId: 'c'.repeat(32), userId: 'user_' + 'f'.repeat(32), tenantId: 'tenant_qa', expiresAt: '2099-01-01T00:00:00Z'}};
  const seen: URL[] = [];
  const api = new NativeSearchApi(connection, (async (url, init) => {
    const parsed = new URL(String(url)); seen.push(parsed);
    const headers = new Headers(init?.headers);
    assert.equal(headers.get('authorization'), 'Bearer ' + 'a'.repeat(64)); assert.equal(headers.get('x-pajio-expected-tenant'), 'tenant_qa'); assert.equal(headers.get('x-wearing-identity'), 'daily');
    assert.equal(init?.redirect, 'error'); assert.ok(init?.signal); assert.equal(init?.body, undefined); assert.ok(!parsed.href.includes('a'.repeat(64)));
    return Response.json(parsed.pathname.endsWith('/7') ? detail : page);
  }) as typeof fetch);
  await api.page(' 旅行 ', 'all'); await api.message(7, 'task_1');
  assert.equal(seen[0].searchParams.get('q'), '旅行'); assert.equal(seen[1].pathname, '/api/search/messages/7');
});
test('paging errors remain retryable and continuation appends without duplicate results', async () => {
  let calls = 0;
  const api = new NativeSearchApi({endpoint: 'https://pajio.example/', identity: 'daily'}, (async () => {calls++; return Response.json({detail: '重新搜索'}, {status: 409});}) as typeof fetch);
  await assert.rejects(api.page('旅行', 'all', 'opaque-cursor'), (error: unknown) => error instanceof ApiError && error.status === 409);
  assert.equal(calls, 1);
  const next: SearchItem = {...item, key: 'task:task_2', id: 'task_2', kind: 'task', target: {kind: 'task', task_id: 'task_2'}};
  assert.deepEqual(mergeSearchPages([item], [item, next]), [item, next]);
});
