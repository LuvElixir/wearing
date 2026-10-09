/** Read-only repository verification. All database rows below are synthetic and in-memory. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {DatabaseSync} from 'node:sqlite';
import {scopeOf, type Connection} from '../../../clients/mobile/src/core';
import {chatImportDraftKey, chatImportPendingKey} from '../../../clients/mobile/src/chat-import-client';
import {accountFences, prepareAccountCleanup, upsertState} from '../../../clients/mobile/src/account-cleanup-state';
import {fencedWrite} from '../../../clients/mobile/src/account-cleanup-model';
import {createSqliteStore, type StateDatabase} from '../../../clients/mobile/src/sqlite-store';

test('actual account cleanup SQL removes both chat-import namespaces for all own identities and blocks late restoration', async t => {
  const sql = new DatabaseSync(':memory:'); t.after(() => sql.close());
  sql.exec('CREATE TABLE local_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)');
  const db: StateDatabase = {async execAsync(q) {sql.exec(q);}, async runAsync(q, ...p) {return sql.prepare(q).run(...p);}, async getFirstAsync<T>(q: string, ...p: string[]) {return (sql.prepare(q).get(...p) || null) as T | null;}, async closeAsync() {}};
  const account: Connection = {endpoint:'https://pajio.synthetic.example/',identity:'daily',session:{userId:'user_'+'a'.repeat(32),tenantId:'home',credentialId:'c'.repeat(32),expiresAt:'2099-01-01T00:00:00Z'}};
  const sameAccountOtherIdentity = {...account,identity:'work'};
  const otherAccount = {...account,session:{...account.session!,userId:'user_'+'b'.repeat(32)}};
  const ownKeys = [account,sameAccountOtherIdentity].flatMap(c => [chatImportDraftKey(scopeOf(c)),chatImportPendingKey(scopeOf(c))]);
  const foreignKeys = [chatImportDraftKey(scopeOf(otherAccount)),chatImportPendingKey(scopeOf(otherAccount))];
  for (const key of ownKeys) await upsertState(db,key,{synthetic:'must remove'});
  for (const key of foreignKeys) await upsertState(db,key,{synthetic:'must retain'});
  const get = (key: string) => {const row = sql.prepare('SELECT value FROM local_state WHERE key=?').get(key); return row ? JSON.parse(String(row.value)) : null;};
  const report = await prepareAccountCleanup(db,account);
  assert.equal(report.rowsRemoved,4);
  for (const key of ownKeys) assert.equal(get(key),null);
  for (const key of foreignKeys) assert.deepEqual(get(key),{synthetic:'must retain'});
  const restartedStore = createSqliteStore(async () => db,undefined,async(handle,key,value) => {if(fencedWrite(key,JSON.parse(value),await accountFences(handle))) throw Error('account fenced');});
  for (const key of ownKeys) await assert.rejects(restartedStore.put(key,{synthetic:'late request'}),/account fenced/);
  await assert.rejects(restartedStore.batch([[foreignKeys[0],{synthetic:'must roll back'}],[ownKeys[1],{synthetic:'late request'}]]),/account fenced/);
  assert.deepEqual(get(foreignKeys[0]),{synthetic:'must retain'});
});
