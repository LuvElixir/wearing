import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError, type Connection} from './core';
import {accountCleanupPlan} from './account-cleanup-model';
import {stopDeletedAccountWork} from './account-work';
import {DEVICE_FILE_LIMIT, DeviceFilesApi, DeviceTransferJournal, parseDeviceFile, parseDeviceFilesCapability, parseDeviceTransfer,
  parseTransferRequest, transferLabel, type DeviceTransferRequest, type DeviceTransferStore} from './device-file-transfer';

const connection = (): Connection => ({endpoint: 'https://transfer.invalid', identity: 'daily', session: {accessToken: 'a'.repeat(64),
  expiresAt: new Date(Date.now() + 3600000).toISOString(), userId: 'user_' + 'a'.repeat(32), tenantId: 'qa', credentialId: 'c'.repeat(32)}});
const source = {file_id: 'd'.repeat(32), name: '合成.pdf', size: 4, sha256: 'e'.repeat(64)};
const request: DeviceTransferRequest = {request_id: 'f'.repeat(32), direction: 'to_device', source};
const receipt = (patch: Record<string, unknown> = {}) => ({...request, resource_id: 'android_qa', state: 'queued', bytes_completed: 0, ...patch});
const capability = {supported: true, available: true, reason: null, max_bytes: DEVICE_FILE_LIMIT, inbox_label: 'Pajio/Inbox', outbox_label: 'Pajio/Outbox'};
const bootstrap = {version: '0.2.0', token: 'synthetic-csrf', identities: [{id: 'daily'}]};
const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), {status, headers: {'Content-Type': 'application/json'}});
const isStatus = (status: number) => (error: unknown) => error instanceof ApiError && error.status === status;
function fixture(replies: (() => Response | Promise<Response>)[] = [], chosen = connection()) {
  const calls: {url: URL; headers: Headers; method: string; body: unknown}[] = [], rows = new Map<string, unknown>();
  const store: DeviceTransferStore = {get: async <T>(key: string) => structuredClone(rows.get(key) ?? null) as T | null,
    put: async (key, value) => {rows.set(key, structuredClone(value));},
    clearIfSame: async (key, expected, active) => {
      if (!active()) throw new ApiError('inactive', 403);
      const row = rows.get(key) as {request?: DeviceTransferRequest} | undefined;
      if (row && JSON.stringify(row.request) !== JSON.stringify(expected)) return false;
      rows.delete(key); return true;
    }};
  const api = new DeviceFilesApi(chosen, 'android_qa', (async (url, init) => {
    calls.push({url: new URL(String(url)), headers: new Headers(init?.headers), method: init?.method || 'GET', body: init?.body ? JSON.parse(String(init.body)) : null});
    assert.equal(init?.redirect, 'error'); const next = replies.shift(); assert.ok(next, 'unexpected request'); return next();
  }) as typeof fetch);
  return {api, calls, store, rows, journal: new DeviceTransferJournal(store, api)};
}

test('fixed directories, bounded names, bytes and hash are checked before a file can be selected', () => {
  assert.deepEqual(parseDeviceFilesCapability(capability), capability);
  assert.deepEqual(parseDeviceFile(source), source);
  for (const patch of [{name: '../file'}, {name: 'bad\\file'}, {name: 'a\n.pdf'}, {size: DEVICE_FILE_LIMIT + 1}, {sha256: 'missing'}, {file_id: 'https://evil.invalid'}]) {
    assert.throws(() => parseDeviceFile({...source, ...patch}));
  }
  for (const patch of [{supported: false}, {inbox_label: '/etc'}, {max_bytes: DEVICE_FILE_LIMIT + 1}]) assert.throws(() => parseDeviceFilesCapability({...capability, ...patch}));
  assert.throws(() => parseTransferRequest({...request, direction: 'list'}));
});

test('file names use NFC and a 180 UTF8 byte limit; empty files are not accepted', () => {
  for (const name of ['中'.repeat(60), 'é'.repeat(90), 'a'.repeat(180)]) assert.equal(parseDeviceFile({...source, name, size: 1}).name, name);
  for (const name of ['中'.repeat(60) + 'a', 'é'.repeat(90) + 'a', 'e\u0301.pdf', '.hidden', ' leading', 'trailing ']) {
    assert.throws(() => parseDeviceFile({...source, name}));
  }
  assert.throws(() => parseDeviceFile({...source, size: 0}));
  assert.equal(parseDeviceFile({...source, size: DEVICE_FILE_LIMIT}).size, DEVICE_FILE_LIMIT);
});

test('a successful HTTP body is not completion without matching resource, request, direction and immutable source', () => {
  assert.equal(parseDeviceTransfer(receipt(), 'android_qa', request).state, 'queued');
  for (const patch of [{resource_id: 'android_other'}, {request_id: 'a'.repeat(32)}, {direction: 'from_device'},
    {source: {...source, sha256: 'a'.repeat(64)}}, {state: 'completed', bytes_completed: 0}, {bytes_completed: 5}, {error: 'secret body\n'}]) {
    assert.throws(() => parseDeviceTransfer(receipt(patch), 'android_qa', request));
  }
  const done = parseDeviceTransfer(receipt({state: 'completed', bytes_completed: 4}), 'android_qa', request);
  assert.equal(transferLabel(done), '已送达设备收件箱');
});

test('listing and import receipts require their actual result, and disallow external or traversing workspace paths', () => {
  const list = {request_id: request.request_id, direction: 'list' as const};
  assert.throws(() => parseDeviceTransfer({...list, resource_id: 'android_qa', state: 'completed', bytes_completed: 0}, 'android_qa', list));
  const rows = {...list, resource_id: 'android_qa', state: 'completed', bytes_completed: 0, files: [source], truncated: true};
  assert.equal(parseDeviceTransfer(rows, 'android_qa').truncated, true);
  assert.throws(() => parseDeviceTransfer({...rows, files: [source, source]}, 'android_qa'));
  const incoming = {...request, direction: 'from_device' as const};
  const done = receipt({direction: 'from_device', state: 'completed', bytes_completed: 4, workspace_file: {path: 'imports/device/合成.pdf', size: 4, modified: 1}});
  assert.equal(parseDeviceTransfer(done, 'android_qa', incoming).workspace_file?.size, 4);
  for (const path of ['/etc/passwd', '../secrets', 'a/../b', 'a\\b']) assert.throws(() => parseDeviceTransfer({...done, workspace_file: {path, size: 4, modified: 1}}, 'android_qa', incoming));
});

test('snapshot and transfer use authenticated fixed routes, never browser downloads or editable destinations', async () => {
  const f = fixture([() => json(bootstrap), () => json(source), () => json(receipt())]);
  assert.deepEqual(await f.api.source('documents/合成.pdf'), source);
  await f.journal.create(request);
  assert.deepEqual(f.calls.map(call => [call.url.pathname, call.method]), [
    ['/api/bootstrap', 'GET'], ['/api/devices/android_qa/files/workspace-source', 'POST'], ['/api/devices/android_qa/files/transfers', 'POST'],
  ]);
  assert.deepEqual(f.calls[1].body, {path: 'documents/合成.pdf'});
  assert.deepEqual(f.calls[2].body, request);
  assert.equal(f.calls[2].headers.get('X-Wearing-Token'), 'synthetic-csrf');
  for (const call of f.calls) {assert.equal(call.headers.get('Authorization'), 'Bearer ' + 'a'.repeat(64)); assert.equal(call.headers.get('X-Wearing-Identity'), 'daily'); assert.equal(call.url.search, '');}
});

test('caller session changes during bootstrap cannot switch the mutation to a different account', async () => {
  const chosen = connection(), f = fixture([() => {chosen.session!.accessToken = 'b'.repeat(64); chosen.session!.tenantId = 'other'; return json(bootstrap);}, () => json(receipt())], chosen);
  await f.journal.create(request);
  assert.equal(f.calls[1].headers.get('Authorization'), 'Bearer ' + 'a'.repeat(64));
  assert.equal(f.calls[1].headers.get('X-Pajio-Expected-Tenant'), 'qa');
});

test('closing the page while bootstrap is pending does not submit a transfer', async () => {
  let active = true;
  const f = fixture([() => {active = false; return json(bootstrap);}]);
  await assert.rejects(() => f.journal.create(request, () => active), isStatus(403));
  assert.equal(f.calls.length, 1); assert.deepEqual(await f.journal.pending(), request);
});

test('unknown POST outcome survives restart; GET 404 preserves it and never repeats POST', async () => {
  const f = fixture([() => json(bootstrap), () => {throw new Error('private transport diagnostic');}, () => json({}, 404), () => json(receipt({state: 'completed', bytes_completed: 4}))]);
  await assert.rejects(() => f.journal.create(request), error => error instanceof Error && !error.message.includes('private'));
  const reopened = new DeviceTransferJournal(f.store, f.api);
  assert.deepEqual(await reopened.pending(), request);
  await assert.rejects(() => reopened.create({...request, request_id: 'b'.repeat(32)}), /核对上次/);
  await assert.rejects(() => reopened.check(), isStatus(404));
  assert.deepEqual(await reopened.pending(), request);
  assert.equal((await reopened.check())?.state, 'completed');
  assert.equal(await reopened.pending(), null);
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 1);
});

test('queued and unknown receipts remain recoverable, but definite failure clears the pending gate', async () => {
  const f = fixture([() => json(bootstrap), () => json(receipt()), () => json(receipt({state: 'unknown'})), () => json(receipt({state: 'failed', error: 'connector_offline'}))]);
  await f.journal.create(request); assert.ok(await f.journal.pending());
  assert.equal((await f.journal.check())?.state, 'unknown'); assert.ok(await f.journal.pending());
  assert.equal((await f.journal.check())?.state, 'failed'); assert.equal(await f.journal.pending(), null);
});

test('gateway 4xx, private-session rejection and server errors all retain the original request without replay', async () => {
  for (const status of [403, 409, 423, 500]) {
    const f = fixture([() => json(bootstrap), () => json({detail: 'device_private_or_paused'}, status)]);
    await assert.rejects(() => f.journal.create(request), isStatus(status));
    assert.equal(f.calls.length, 2);
    assert.deepEqual(await f.journal.pending(), request);
  }
});

test('storage failure before POST and malformed pending state both prevent new device actions', async () => {
  const f = fixture(), broken = new DeviceTransferJournal({...f.store, put: async () => {throw new Error('disk unavailable');}}, f.api);
  await assert.rejects(() => broken.create(request)); assert.equal(f.calls.length, 0);
  await f.store.put(f.journal.key, {schema: 1, request: {request_id: 'broken'}});
  await assert.rejects(() => f.journal.create(request)); assert.equal(f.calls.length, 0);
});

test('a concurrent tap cannot enqueue another request while the first request is awaiting its receipt', async () => {
  let finish!: (response: Response) => void;
  const f = fixture([() => json(bootstrap), () => new Promise(resolve => {finish = resolve;})]);
  const first = f.journal.create(request);
  await assert.rejects(() => f.journal.create({...request, request_id: 'b'.repeat(32)}), isStatus(409));
  while (!finish) await new Promise(resolve => setImmediate(resolve));
  finish(json(receipt())); await first;
  assert.equal(f.calls.filter(call => call.method === 'POST').length, 1);
});

test('scoped journals are isolated by account and device and participate in account cleanup', async () => {
  const f = fixture([() => json(bootstrap), () => json(receipt())]); await f.journal.create(request);
  const other = new DeviceTransferJournal(f.store, new DeviceFilesApi({...connection(), identity: 'work'}, 'android_qa'));
  assert.equal(await other.pending(), null);
  const plan = accountCleanupPlan(connection(), [...f.rows].map(([key, value]) => ({key, value})));
  assert.deepEqual(plan.remove, [f.journal.key]);
});

test('frozen accounts cannot snapshot or submit files even with old client objects', async () => {
  const chosen = connection(); chosen.session!.userId = 'user_' + '9'.repeat(32);
  const f = fixture([], chosen); await stopDeletedAccountWork(chosen);
  await assert.rejects(() => f.api.source('documents/synthetic.pdf'), isStatus(403));
  await assert.rejects(() => f.journal.create(request), isStatus(403));
  assert.equal(f.calls.length, 0);
  assert.equal(f.rows.size, 0);
});

test('navigation during pending journal read cannot create a new key or send a command', async () => {
  let active = true;
  const f = fixture(), journal = new DeviceTransferJournal({...f.store, get: async () => {active = false; return null;}}, f.api);
  await assert.rejects(() => journal.create(request, () => active), isStatus(403));
  assert.equal(f.rows.size, 0); assert.equal(f.calls.length, 0);
});

test('a completion after account cleanup cannot recreate the removed journal with a null value', async () => {
  const chosen = connection(); chosen.session!.userId = 'user_' + '8'.repeat(32);
  const f = fixture([() => json(bootstrap), async () => {
    await stopDeletedAccountWork(chosen); f.rows.clear(); return json(receipt({state: 'completed', bytes_completed: 4}));
  }], chosen);
  await f.journal.create(request);
  assert.equal(f.rows.size, 0);
});

test('late check result after leaving the page keeps the journal for the next explicit visit', async () => {
  let active = true;
  const f = fixture([() => json(bootstrap), () => json(receipt()), () => {active = false; return json(receipt({state: 'completed', bytes_completed: 4}));}]);
  await f.journal.create(request);
  await f.journal.check(() => active);
  assert.deepEqual(await f.journal.pending(), request);
});

test('stopping local waiting requires confirmation, verifies the same request, and never sends a cancellation or replacement', async () => {
  const f = fixture([() => json(bootstrap), () => {throw Error('network');}]);
  await assert.rejects(() => f.journal.create(request));
  await assert.rejects(() => f.journal.stopWaiting(request, false), isStatus(422));
  await assert.rejects(() => f.journal.stopWaiting({...request, request_id: 'b'.repeat(32)}, true), isStatus(409));
  await f.journal.stopWaiting(request, true);
  assert.equal(await f.journal.pending(), null); assert.equal(f.calls.length, 2);
});

test('a storage refusal or a lying delete receipt cannot report waiting stopped', async () => {
  for (const clearIfSame of [async () => false, async () => true, async () => {throw Error('disk refused');}]) {
    const f = fixture(); await f.store.put(f.journal.key, {schema: 1, request});
    const journal = new DeviceTransferJournal({...f.store, clearIfSame}, f.api);
    await assert.rejects(() => journal.stopWaiting(request, true));
    assert.deepEqual(await journal.pending(), request); assert.equal(f.calls.length, 0);
  }
});

test('replacement during local discard is preserved by the compare-and-delete boundary', async () => {
  const f = fixture(), newer = {...request, request_id: 'b'.repeat(32)};
  await f.store.put(f.journal.key, {schema: 1, request});
  const journal = new DeviceTransferJournal({...f.store, clearIfSame: async (key, expected, active) => {
    await f.store.put(key, {schema: 1, request: newer});
    return f.store.clearIfSame(key, expected, active);
  }}, f.api);
  await assert.rejects(() => journal.stopWaiting(request, true), isStatus(409));
  assert.deepEqual(await journal.pending(), newer);
});
