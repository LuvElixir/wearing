import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {DatabaseSync} from 'node:sqlite';
import * as ts from 'typescript';
import {ApiError, scopeOf, type Connection} from './core';
import {parseTransferRequest, type DeviceTransferStore} from './device-file-transfer';

const source = {file_id: 'a'.repeat(32), name: 'QA.pdf', size: 4, sha256: 'b'.repeat(64)};
const request = {request_id: 'c'.repeat(32), direction: 'to_device' as const, source};
function extract(file: string, names: string[], inside?: string) {
  const ast = ts.createSourceFile(file, readFileSync(new URL('./' + file, import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const statements = inside ? (ast.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === inside) as ts.FunctionDeclaration).body!.statements : ast.statements;
  const picked = statements.filter(n => ts.isFunctionDeclaration(n) && names.includes(n.name!.text)); assert.equal(picked.length, names.length);
  return ts.transpileModule(picked.map(n => ts.createPrinter().printNode(ts.EmitHint.Unspecified, n, ast)).join('\n').replace('export function', 'function'), {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
}
function handlers() {
  const state = {busy: '', error: '', notice: '', pending: request as typeof request | null, choice: {direction: 'to_device', source} as unknown, choosing: true, applied: [] as unknown[]};
  const h = {state, alive: {current: true}, lock: {current: false}, refreshing: {current: false}, ready: true,
    capability: {available: true}, pending: null as unknown, confirmStop: true, active: () => h.alive.current,
    api: {source: async () => source},
    journal: {create: async (_request: unknown, _active: () => boolean): Promise<unknown> => ({...request, state: 'queued'}), pending: async () => state.pending, stopWaiting: async () => {state.pending = null;}},
    apply: (row: unknown) => state.applied.push(row), setChoice: (value: unknown) => {state.choice = value;}, setChoosing: (value: boolean) => {state.choosing = value;},
    setBusy: (value: string) => {state.busy = value;}, setError: (value: string) => {state.error = value;}, setNotice: (value: string) => {state.notice = value;},
    setPending: (value: typeof request | null) => {state.pending = value;}, setReady: () => {}, setMissingChecks: () => {}, setConfirmStop: () => {},
    issue: (value: unknown) => value instanceof Error ? value.message : 'error',
  };
  runInNewContext(extract('NativeDeviceFilesPanel.tsx', ['run', 'submit', 'selectFile', 'stopWaiting'], 'DeviceFilesContent'), h);
  return h as typeof h & {submit: (request: unknown) => Promise<void>; selectFile: (file: unknown) => Promise<void>; stopWaiting: () => Promise<void>};
}

test('the real panel handler waits for a matched receipt and never turns an unknown send into visible success', async () => {
  const h = handlers(); h.journal.create = async () => {throw new ApiError('尚未确认');};
  await assert.rejects(() => h.submit(request));
  assert.equal(h.state.applied.length, 0); assert.notEqual(h.state.choice, null);
  h.journal.create = async () => ({...request, state: 'queued'});
  await h.submit(request); assert.equal(h.state.applied.length, 1); assert.equal(h.state.choice, null);
});

test('snapshot returning after navigation cannot select or send a file into a later page', async () => {
  const h = handlers(); h.api.source = async () => {h.alive.current = false; return source;};
  const previous = h.state.choice;
  await h.selectFile({path: 'documents/QA.pdf'});
  assert.equal(h.state.choice, previous); assert.equal(h.state.applied.length, 0);
});

test('the actual local-stop handler reports success only after verified journal deletion and clears the old choice', async () => {
  const h = handlers(); h.pending = request; h.journal.stopWaiting = async () => {throw new ApiError('等待记录未清除');};
  await h.stopWaiting(); assert.equal(h.state.notice, ''); assert.notEqual(h.state.choice, null); assert.match(h.state.error, /未清除/);
  h.journal.stopWaiting = async () => {h.state.pending = null;};
  await h.stopWaiting(); assert.match(h.state.notice, /仍可能完成/); assert.equal(h.state.choice, null); assert.equal(h.state.choosing, false);
});

function nativeStore() {
  const db = new DatabaseSync(':memory:'); db.exec('CREATE TABLE local_state (key TEXT PRIMARY KEY, value TEXT)');
  const connection: Connection = {endpoint: 'https://qa.invalid', identity: 'daily', session: {accessToken: 'a'.repeat(64), expiresAt: '2099-01-01', userId: 'user_' + 'a'.repeat(32), tenantId: 'qa', credentialId: 'c'.repeat(32)}};
  let frozen = false, afterRead: (() => void) | null = null;
  const h = {ApiError, scopeOf, parseTransferRequest, storage: {}, accountWorkAllowed: () => !frozen,
    assertAccountWritable: async () => {if (frozen) throw new ApiError('frozen', 403);},
    withNativeState: async (work: (sql: unknown) => Promise<unknown>) => work({
      getFirstAsync: async (sql: string, ...params: string[]) => {const row = db.prepare(sql).get(...params) || null; const mutate = afterRead; afterRead = null; mutate?.(); return row;},
      runAsync: async (sql: string, ...params: string[]) => db.prepare(sql).run(...params),
    }),
  };
  runInNewContext(extract('device-file-transfer-store.ts', ['deviceTransferStore']), h);
  const store = (h as typeof h & {deviceTransferStore: (connection: Connection) => DeviceTransferStore}).deviceTransferStore(connection);
  const key = 'device-file-transfer:v1:' + scopeOf(connection) + '|android_qa';
  const put = (value: unknown) => db.prepare('INSERT OR REPLACE INTO local_state VALUES (?, ?)').run(key, JSON.stringify(value));
  return {db, store, key, put, frozen: () => {frozen = true;}, afterRead: (work: () => void) => {afterRead = work;}};
}

test('actual native store compare-and-delete SQL preserves a concurrently replaced request', async () => {
  const h = nativeStore();
  try {
    h.put({schema: 1, request});
    h.afterRead(() => h.put({schema: 1, request: {...request, request_id: 'd'.repeat(32)}}));
    assert.equal(await h.store.clearIfSame(h.key, request, () => true), false);
    const row = h.db.prepare('SELECT value FROM local_state WHERE key = ?').get(h.key)!;
    assert.equal(JSON.parse(String(row.value)).request.request_id, 'd'.repeat(32));
  } finally {h.db.close();}
});

test('actual native store rechecks account freeze after read and cannot write after cleanup', async () => {
  const h = nativeStore();
  try {
    h.put({schema: 1, request}); h.afterRead(() => {h.frozen(); h.db.exec('DELETE FROM local_state');});
    await assert.rejects(() => h.store.clearIfSame(h.key, request, () => true), (error: unknown) => error instanceof ApiError && error.status === 403);
    assert.equal(h.db.prepare('SELECT COUNT(*) AS count FROM local_state').get()!.count, 0);
  } finally {h.db.close();}
});

test('actual native store rejects a different account or identity journal without reading or deleting it', async () => {
  const h = nativeStore();
  try {
    h.put({schema: 1, request});
    for (const key of [h.key.replace('daily', 'work'), h.key.replace('qa.invalid', 'other.invalid'), h.key + '/other']) {
      await assert.rejects(() => h.store.clearIfSame(key, request, () => true), (error: unknown) => error instanceof ApiError && error.status === 403);
    }
    assert.equal(h.db.prepare('SELECT COUNT(*) AS count FROM local_state').get()!.count, 1);
  } finally {h.db.close();}
});

test('actual native store propagates SQLite write rejection and verifies absence after successful deletion', async () => {
  const h = nativeStore();
  try {
    h.put({schema: 1, request}); h.db.exec('PRAGMA query_only = ON');
    await assert.rejects(() => h.store.clearIfSame(h.key, request, () => true));
    assert.equal(h.db.prepare('SELECT COUNT(*) AS count FROM local_state').get()!.count, 1);
    h.db.exec('PRAGMA query_only = OFF'); assert.equal(await h.store.clearIfSame(h.key, request, () => true), true);
    assert.equal(h.db.prepare('SELECT COUNT(*) AS count FROM local_state').get()!.count, 0);
  } finally {h.db.close();}
});
