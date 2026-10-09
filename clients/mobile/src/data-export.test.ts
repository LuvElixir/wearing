import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError} from './core';
import {dataExport, DataExportApi, handoffDataExport, EXPORT_LIMIT} from './data-export';
const item = {id: 'a'.repeat(32), identity_id: 'daily', created_at: 100, expires_at: 1900, size: 3, sha256: 'b'.repeat(64), counts: {tasks: 1, conversation: 1}, omitted: [], workspace_count: 0, filename: 'pajio-data-aaaaaaaa.zip'};
const connection = {endpoint: 'http://127.0.0.1:8765/', identity: 'daily'};
test('wrong identity, unsafe filenames and oversized receipts cannot be shared', () => {
  assert.equal(dataExport(item, 'daily').size, 3);
  assert.throws(() => dataExport(item, 'work'));
  assert.throws(() => dataExport({...item, filename: '../credentials.zip'}, 'daily'));
  assert.throws(() => dataExport({...item, size: EXPORT_LIMIT + 1}, 'daily'));
});
test('export creation bootstraps CSRF and retries use caller-owned stable request key', async () => {
  const requests: {url: string; init: RequestInit}[] = [];
  const fetcher = (async (url, init) => {requests.push({url: String(url), init: init!}); return new Response(JSON.stringify(String(url).endsWith('bootstrap') ? {version: '0.2.0', token: 'csrf-fixture', identities: [{id: 'daily'}]} : item));}) as typeof fetch;
  const api = new DataExportApi(connection, fetcher);
  await api.create('stable-request-key'); await api.create('stable-request-key');
  assert.equal(requests[1].init.body, requests[3].init.body);
  assert.equal((requests[1].init.headers as Record<string, string>)['X-Wearing-Token'], 'csrf-fixture');
  assert.equal((requests[1].init.headers as Record<string, string>)['X-Wearing-Identity'], 'daily');
  assert.equal(requests[1].init.redirect, 'error');
  assert.equal(requests[1].url, connection.endpoint + 'api/data-exports');
});
test('download validates size and type and keeps expiry error actionable', async () => {
  const api = new DataExportApi(connection, (async () => new Response(new Uint8Array([1, 2, 3]), {headers: {'content-length': '3', 'content-type': 'application/zip'}})) as typeof fetch);
  assert.deepEqual(await api.bytes(item), new Uint8Array([1, 2, 3]));
  const bad = new DataExportApi(connection, (async () => new Response('abc', {headers: {'content-length': '3', 'content-type': 'text/html'}})) as typeof fetch);
  await assert.rejects(bad.bytes(item), /格式/);
  const expired = new DataExportApi(connection, (async () => new Response(JSON.stringify({detail: '导出包已过期'}), {status: 410})) as typeof fetch);
  await assert.rejects(expired.bytes(item), error => error instanceof ApiError && error.status === 410);
});
test('share failure can retry same receipt and scope change suppresses external handoff', async () => {
  const api = new DataExportApi(connection, (async () => new Response(new Uint8Array([1, 2, 3]), {headers: {'content-length': '3', 'content-type': 'application/zip'}})) as typeof fetch);
  let shares = 0, active = true;
  const share = async () => {shares++; if (shares === 1) throw new Error('sheet failed');};
  await assert.rejects(handoffDataExport(api, item, () => active, async () => item.sha256, share), /sheet failed/);
  assert.equal(await handoffDataExport(api, item, () => active, async () => item.sha256, share), true);
  assert.equal(shares, 2);
  await assert.rejects(handoffDataExport(api, item, () => active, async () => 'wrong-sha', share), /校验/);
  await handoffDataExport(api, item, () => active, async () => {active = false; return item.sha256;}, share);
  assert.equal(shares, 2);
});
test('reopening data panel can recover a ready receipt without generating another package', async () => {
  const api = new DataExportApi(connection, (async () => new Response(JSON.stringify({exports: [item]}))) as typeof fetch);
  assert.equal((await api.latest())?.id, item.id);
  const foreign = new DataExportApi(connection, (async () => new Response(JSON.stringify({exports: [{...item, identity_id: 'work'}]}))) as typeof fetch);
  await assert.rejects(foreign.latest(), /核对/);
});
