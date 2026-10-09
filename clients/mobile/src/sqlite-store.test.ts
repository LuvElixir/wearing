import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createSqliteState, createSqliteStore, type StateDatabase} from './sqlite-store';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => {resolve = done;});
  return {promise, resolve};
}
function fixture(t: {after: (fn: () => void) => void}) {
  const directory = mkdtempSync(join(tmpdir(), 'wearing-storage-')), path = join(directory, 'state.db');
  const handles = new Set<DatabaseSync>(), state = createSqliteState();
  let opens = 0;
  const hooks: {before?: (sql: string, params: string[]) => Promise<void>} = {};
  const open = async (): Promise<StateDatabase> => {
    opens++; const db = new DatabaseSync(path); handles.add(db);
    const before = async (sql: string, params: string[] = []) => {await new Promise(resolve => setImmediate(resolve)); await hooks.before?.(sql, params);};
    return {
      async execAsync(sql) {await before(sql); db.exec(sql);},
      async runAsync(sql, ...params) {await before(sql, params); return db.prepare(sql).run(...params);},
      async getFirstAsync<T>(sql: string, ...params: string[]) {await before(sql, params); return (db.prepare(sql).get(...params) ?? null) as T | null;},
      async closeAsync() {db.close(); handles.delete(db);},
    };
  };
  t.after(() => {for (const db of handles) db.close(); rmSync(directory, {recursive: true, force: true});});
  return {store: createSqliteStore(open, state), remount: () => createSqliteStore(open, state), hooks, opens: () => opens, external: () => {const db = new DatabaseSync(path); handles.add(db); return db;}};
}

test('recording batch, draft autosave and hydration share order without observing partial records', async t => {
  const f = fixture(t), gate = deferred(), started = deferred();
  f.hooks.before = async (sql, params) => {if (sql.startsWith('INSERT') && params[0] === 'voice-copy') {started.resolve(); await gate.promise;}};
  const recording = f.store.batch([['voice', {text: '原话'}], ['voice-copy', {text: '原话'}]]);
  await started.promise;
  let draftSaved = false, readFinished = false;
  const draft = f.store.put('voice', {text: '后续编辑'}).then(() => {draftSaved = true;});
  const read = f.store.get('voice').then(value => {readFinished = true; return value;});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(draftSaved, false); assert.equal(readFinished, false);
  gate.resolve(); await Promise.all([recording, draft]);
  assert.deepEqual(await read, {text: '后续编辑'});
  assert.deepEqual(await f.store.get('voice-copy'), {text: '原话'});
});

test('Fast Refresh wrappers retain the same queue and connection while an old save is pending', async t => {
  const f = fixture(t), gate = deferred(), started = deferred();
  f.hooks.before = async (sql, params) => {if (sql.startsWith('INSERT') && params[1] === '"旧"') {started.resolve(); await gate.promise;}};
  const oldSave = f.store.put('draft', '旧'); await started.promise;
  const next = f.remount(), replacement = next.put('draft', '新');
  gate.resolve(); await Promise.all([oldSave, replacement]);
  assert.equal(await f.store.get('draft'), '新'); assert.equal(f.opens(), 1);
});

test('failed batch rolls back all rows, rejects and lets following saves proceed', async t => {
  const f = fixture(t); await f.store.put('draft', '保留');
  f.hooks.before = async (sql, params) => {if (sql.startsWith('INSERT') && params[0] === 'fail') throw new Error('disk full');};
  await assert.rejects(f.store.batch([['draft', '未完成'], ['fail', '失败']]), /disk full/);
  assert.equal(await f.store.get('draft'), '保留'); assert.equal(await f.store.get('fail'), null);
  await f.store.put('draft', '下一次'); assert.equal(await f.store.get('draft'), '下一次');
});

test('failed commit rolls back and never reports a recording as saved', async t => {
  const f = fixture(t); await f.store.put('recording', '原件');
  f.hooks.before = async sql => {if (sql === 'COMMIT') throw new Error('commit I/O error');};
  await assert.rejects(f.store.batch([['recording', '变更'], ['receipt', true]]), /commit I\/O error/);
  assert.equal(await f.store.get('recording'), '原件'); assert.equal(await f.store.get('receipt'), null);
});

test('a transient busy statement retries the complete rolled-back batch, never a partial tail', async t => {
  const f = fixture(t); await f.store.put('recording', '原件');
  let failed = false, begins = 0, rollbacks = 0;
  f.hooks.before = async (sql, params) => {
    if (sql === 'BEGIN IMMEDIATE') begins++;
    if (sql === 'ROLLBACK') rollbacks++;
    if (sql.startsWith('INSERT') && params[0] === 'receipt' && !failed) {failed = true; throw new Error('SQLITE_BUSY: database is locked');}
  };
  await f.store.batch([['recording', '完成'], ['receipt', true]]);
  assert.equal(begins, 2); assert.equal(rollbacks, 1);
  assert.equal(await f.store.get('recording'), '完成'); assert.equal(await f.store.get('receipt'), true);
});

test('rollback failure quarantines the connection and preserves the initial error for diagnosis', async t => {
  const f = fixture(t); await f.store.put('recording', '原件');
  f.hooks.before = async (sql, params) => {
    if (sql === 'ROLLBACK') throw new Error('rollback I/O error');
    if (sql.startsWith('INSERT') && params[0] === 'fail') throw new Error('write I/O error');
  };
  await assert.rejects(f.store.batch([['recording', '未完成'], ['fail', 1]]), error => {
    assert.match((error as Error & {cause: Error}).cause.message, /write I\/O error/); return true;
  });
  f.hooks.before = undefined;
  assert.equal(await f.store.get('recording'), '原件'); assert.equal(f.opens(), 2);
  await f.store.put('recording', '之后'); assert.equal(await f.store.get('recording'), '之后');
});

test('short external SQLite contention is retried without changing the saved value', async t => {
  const f = fixture(t); await f.store.put('draft', '旧');
  const external = f.external(); external.exec('BEGIN IMMEDIATE');
  let attempts = 0; f.hooks.before = async (sql, params) => {if (sql.startsWith('INSERT') && params[0] === 'draft') attempts++;};
  const write = f.store.put('draft', '新');
  setTimeout(() => external.exec('ROLLBACK'), 20);
  await write; assert.ok(attempts >= 2); assert.equal(await f.store.get('draft'), '新');
});

test('persistent contention has a finite retry budget and does not poison the queue', async t => {
  const f = fixture(t); await f.store.put('draft', '保留');
  const external = f.external(); external.exec('BEGIN IMMEDIATE');
  let attempts = 0; f.hooks.before = async sql => {if (sql === 'BEGIN IMMEDIATE') attempts++;};
  await assert.rejects(f.store.batch([['draft', '不能保存']]), /database is locked/);
  assert.equal(attempts, 3); external.exec('ROLLBACK');
  assert.equal(await f.store.get('draft'), '保留');
  await f.store.put('draft', '重试成功'); assert.equal(await f.store.get('draft'), '重试成功');
});

test('queued writes snapshot input and invalid JSON cannot partly overwrite a batch', async t => {
  const f = fixture(t), record = {text: '快照'};
  const saved = f.store.put('draft', record); record.text = '之后'; await saved;
  assert.deepEqual(await f.store.get('draft'), {text: '快照'});
  await assert.rejects(f.store.batch([['draft', '未保存'], ['invalid', undefined]]));
  assert.deepEqual(await f.store.get('draft'), {text: '快照'});
});

test('initialization failure can recover on a later call instead of caching a rejected promise', async t => {
  const f = fixture(t); let fail = true;
  f.hooks.before = async sql => {if (sql.includes('CREATE TABLE') && fail) {fail = false; throw new Error('temporary open error');}};
  await assert.rejects(f.store.get('draft'), /temporary open error/);
  await f.store.put('draft', '恢复'); assert.equal(await f.store.get('draft'), '恢复'); assert.equal(f.opens(), 2);
});
