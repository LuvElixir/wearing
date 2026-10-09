import assert from 'node:assert/strict';
import test from 'node:test';
import {ApiError, MemoryChange, MemorySnapshot, WearingApi} from './core';
import {applyMemoryChange, memoryHistoryChanges, memoryUndoRequest, validMemoryHistory, type MemoryHistory, type MemoryHistoryItem} from './memory-history';

const before = 'a'.repeat(64), after = 'b'.repeat(64), id = '1'.repeat(32);
const change: MemoryHistoryItem = {id, action: 'replace', source: 'user', created_at: '2026-10-10T00:00:00+00:00', before: ['旧偏好'], after: ['新偏好'], before_revision: before, after_revision: after, undoable: true};
const history = (items = [change]): MemoryHistory => ({coverage: 'user_explicit', limit: 20, unconfirmed_changes: false, items});
const snapshot = (): MemorySnapshot => ({identity_id: 'daily', available: true, targets: {
  user: {enabled: true, entries: ['新偏好'], revision: after, history: history()},
  memory: {enabled: true, entries: [], revision: before, history: history([])},
}});
const connection = {endpoint: 'https://pajio.example/', identity: 'daily'};
const command: MemoryChange = {target: 'user', action: 'undo', history_id: id, revision: after};
const bootstrap = () => Response.json({version: '0.2.0', deployment: 'cloud', token: 'fixture-only', identities: [{id: 'daily'}]});

test('history only accepts bounded acknowledged user changes; old snapshots remain readable', async () => {
  assert.ok(validMemoryHistory(history(), snapshot().targets!.user));
  for (const invalid of [{...history(), coverage: 'all'}, {...history(), items: [change, change]}, {...history(), limit: 21}, {...history(), unconfirmed_changes: 'false'}, {...history(), items: [{...change, source: 'agent'}]}, {...history(), items: [{...change, created_at: 'unknown'}]}, {...history(), items: [{...change, before: [1]}]}, {...history(), items: [{...change, action: 'undo'}]}]) {
    assert.equal(validMemoryHistory(invalid, snapshot().targets!.user), false);
  }
  const legacy = snapshot(); delete legacy.targets!.user.history; delete legacy.targets!.memory.history;
  const api = new WearingApi(connection, async () => Response.json(legacy));
  assert.deepEqual(await api.memory(), legacy);
  assert.equal(memoryUndoRequest('user', legacy, id), null);
});

test('undo uses the current page revision and server undoability, never the old entry index', () => {
  assert.deepEqual(memoryUndoRequest('user', snapshot(), id), command);
  assert.equal(memoryUndoRequest('memory', snapshot(), id), null);
  const paused = snapshot(); paused.targets!.user.enabled = false;
  assert.equal(memoryUndoRequest('user', paused, id), null);
  assert.equal(validMemoryHistory(history(), paused.targets!.user), false);
  const stale = snapshot(); stale.targets!.user.revision = 'c'.repeat(64);
  assert.equal(memoryUndoRequest('user', stale, id), null);
  assert.equal(validMemoryHistory(history(), stale.targets!.user), false);
  const undone = snapshot(); undone.targets!.user.history!.items[0] = {...change, undoable: false};
  assert.equal(memoryUndoRequest('user', undone, id), null);
});

test('entry diff preserves duplicates and reports only changed content', () => {
  assert.deepEqual(memoryHistoryChanges({before: ['same', 'twice', 'twice', 'old'], after: ['same', 'twice', 'new']}), {before: ['twice', 'old'], after: ['new']});
  assert.deepEqual(memoryHistoryChanges({before: [], after: ['new']}), {before: [], after: ['new']});
});

test('undo has no optimistic result; a complete server snapshot is the only success', async () => {
  let resolve!: (data: MemorySnapshot) => void, completed = false;
  const updated = snapshot(); updated.targets!.user.entries = ['旧偏好']; updated.targets!.user.revision = before; updated.targets!.user.history = history([{...change, undoable: false}]);
  const promise = applyMemoryChange({changeMemory: () => new Promise(done => {resolve = done;}), memory: async () => {throw Error('not needed');}}, command).then(result => {completed = true; return result;});
  await Promise.resolve(); assert.equal(completed, false);
  resolve(updated);
  assert.deepEqual(await promise, {state: 'confirmed', snapshot: updated});
});

test('a conflict reads once and never replays the mutation or marks it successful', async () => {
  let writes = 0, reads = 0;
  const updated = snapshot(), error = new ApiError('changed', 409);
  const result = await applyMemoryChange({changeMemory: async () => {writes++; throw error;}, memory: async () => {reads++; return updated;}}, command);
  assert.deepEqual(result, {state: 'conflict', snapshot: updated, error});
  assert.equal(writes, 1); assert.equal(reads, 1);
});

test('unconfirmed mutation and failed conflict refresh never claim success or retry', async () => {
  for (const error of [new Error('disconnected'), new ApiError('conflict', 409)]) {
    let writes = 0, reads = 0;
    const result = await applyMemoryChange({changeMemory: async () => {writes++; throw error;}, memory: async () => {reads++; throw Error('offline');}}, command);
    assert.notEqual(result.state, 'confirmed');
    assert.equal('snapshot' in result, false); assert.equal(writes, 1);
    assert.equal(reads, error instanceof ApiError ? 1 : 0);
  }
});

test('undo API sends exact scoped command and never retries a 403 mutation', async () => {
  const sent: RequestInit[] = [];
  const api = new WearingApi(connection, (async (url, init) => {
    if (String(url).endsWith('/api/bootstrap')) return bootstrap();
    sent.push(init!); return Response.json({detail: 'changed authorization'}, {status: 403});
  }) as typeof fetch);
  await assert.rejects(api.changeMemory(command), /changed authorization/);
  assert.equal(sent.length, 1); assert.deepEqual(JSON.parse(String(sent[0].body)), command);
  assert.equal(new Headers(sent[0].headers).get('X-Wearing-Identity'), 'daily');
});

test('malformed or cross-identity undo receipt remains unconfirmed', async () => {
  for (const changed of [{...snapshot(), identity_id: 'other'}, {...snapshot(), targets: {...snapshot().targets, user: {...snapshot().targets!.user, history: history([{...change, source: 'agent'} as never])}}}]) {
    const api = new WearingApi(connection, (async url => String(url).endsWith('/api/bootstrap') ? bootstrap() : Response.json(changed)) as typeof fetch);
    assert.equal((await applyMemoryChange(api, command)).state, 'unconfirmed');
  }
  let calls = 0;
  const api = new WearingApi(connection, async () => {calls++; throw Error('must not call');});
  await assert.rejects(api.changeMemory({...command, action: 'undo', history_id: '../other'}));
  assert.equal(calls, 0);
});

test('clear receipt replaces both entries and history; no client-created undo survives', async () => {
  const empty = snapshot(); empty.targets!.user.entries = []; empty.targets!.user.history = history([]);
  const api = new WearingApi(connection, (async url => String(url).endsWith('/api/bootstrap') ? bootstrap() : Response.json(empty)) as typeof fetch);
  const result = await applyMemoryChange(api, {target: 'user', action: 'clear', revision: after});
  assert.equal(result.state, 'confirmed');
  if (result.state === 'confirmed') {assert.deepEqual(result.snapshot.targets!.user.history!.items, []); assert.equal(memoryUndoRequest('user', result.snapshot, id), null);}
});
