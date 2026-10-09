import {connectionEndpoint, scopeOf, type Connection} from './core';
import {ACCOUNT_FENCES_KEY, accountCleanupPlan, fenceFor, ownedScope, type AccountFence, type LocalRow} from './account-cleanup-model';
import type {StateDatabase} from './sqlite-store';

export const credentialsKey = (c: Connection) => `account-credentials:v1:${connectionEndpoint(c, true)}|${c.session!.userId}`;
const journalKey = (c: Connection) => `account-cleanup:v1:${connectionEndpoint(c, true)}|${c.session!.userId}`;
export const upsertState = (db: StateDatabase, key: string, value: unknown) => db.runAsync('INSERT INTO local_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', key, JSON.stringify(value));
export async function accountFences(db: StateDatabase): Promise<AccountFence[]> {
  const raw = await db.getFirstAsync<{value: string}>('SELECT value FROM local_state WHERE key = ?', ACCOUNT_FENCES_KEY);
  const rows = raw ? JSON.parse(raw.value) as unknown : [];
  if (!Array.isArray(rows) || rows.some(row => !row || typeof row.address !== 'string' || !row.address.startsWith('https://') || !/^user_[a-f0-9]{32}$/.test(row.userId))) throw new Error('本机账户清理记录无法核对，已暂停保存。');
  return rows;
}
export async function assertAccountWritable(db: StateDatabase, connection: Connection) {
  if (!connection.session) return;
  const fence = fenceFor(connection);
  if ((await accountFences(db)).some(row => row.address === fence.address && row.userId === fence.userId)) throw new Error('此账户正在注销，已停止保存和连接。');
}
export type CredentialIndex = {credentialIds: string[]; scopes: string[]};
export function credentialIndex(value: unknown, connection: Connection): CredentialIndex {
  const raw = value as Partial<CredentialIndex> | null;
  if (!raw || !Array.isArray(raw.credentialIds) || !raw.credentialIds.every(id => typeof id === 'string' && /^[A-Za-z0-9_-]{32,64}$/.test(id)) || !Array.isArray(raw.scopes) || !raw.scopes.every(scope => ownedScope(scope, fenceFor(connection)))) throw new Error('本机账户凭据目录无法核对。');
  return {credentialIds: [...new Set(raw.credentialIds)], scopes: [...new Set(raw.scopes)]};
}
export async function registerAccountCredential(db: StateDatabase, connection: Connection) {
  await assertAccountWritable(db, connection);
  if (!connection.session) return;
  const key = credentialsKey(connection), raw = await db.getFirstAsync<{value: string}>('SELECT value FROM local_state WHERE key = ?', key);
  const prior = raw ? credentialIndex(JSON.parse(raw.value), connection) : {credentialIds: [], scopes: []};
  if (prior.credentialIds.includes(connection.session.credentialId) && prior.scopes.includes(scopeOf(connection))) return;
  await upsertState(db, key, {credentialIds: [...new Set([...prior.credentialIds, connection.session.credentialId])], scopes: [...new Set([...prior.scopes, scopeOf(connection)])]});
}
export type CleanupJournal = {version: 1; originals: string[]; uris: string[]; shareIds: string[]; scopes: string[]; credentialIds: string[]; rowsRemoved: number; unownedLegacy: number};
const unique = (items: string[]) => [...new Set(items)];
/** Caller owns the shared SQLite queue. Commit an inventory before removing any files. */
export async function prepareAccountCleanup(db: StateDatabase, connection: Connection): Promise<CleanupJournal> {
  const fence = fenceFor(connection);
  await db.execAsync('BEGIN IMMEDIATE');
  try {
    const packed = await db.getFirstAsync<{rows: string}>('SELECT json_group_array(json_object(\'key\',key,\'value\',value)) AS rows FROM local_state');
    // Invalid storage cannot be interpreted as empty; never lose a retained account's references.
    const rows: LocalRow[] = (JSON.parse(packed?.rows || '[]') as {key: string; value: string}[]).map(row => ({key: row.key, value: JSON.parse(row.value)}));
    const plan = accountCleanupPlan(connection, rows.filter(row => row.key !== journalKey(connection))), current = rows.find(row => row.key === 'connection')?.value as Connection | undefined;
    const prior = rows.find(row => row.key === journalKey(connection))?.value as CleanupJournal | undefined;
    if (prior && (prior.version !== 1 || !['originals', 'uris', 'shareIds', 'scopes', 'credentialIds'].every(key => Array.isArray(prior[key as keyof CleanupJournal]) && (prior[key as keyof CleanupJournal] as unknown[]).every(value => typeof value === 'string')) || ![...prior.originals, ...prior.shareIds].every(id => /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(id)) || !prior.scopes.every(scope => ownedScope(scope, fence)) || !prior.credentialIds.every(id => /^[A-Za-z0-9_-]{32,64}$/.test(id)) || !Number.isSafeInteger(prior.rowsRemoved) || prior.rowsRemoved < 0)) throw new Error('本机清理回执无法核对。');
    const registry = rows.find(row => row.key === credentialsKey(connection));
    const index = registry ? credentialIndex(registry.value, connection) : {credentialIds: [], scopes: []};
    const journal: CleanupJournal = {version: 1, originals: unique([...(prior?.originals || []), ...plan.originals]).filter(id => !plan.retainedIds.includes(id)), uris: unique([...(prior?.uris || []), ...plan.uris]).filter(uri => !plan.retainedUris.includes(uri)), shareIds: unique([...(prior?.shareIds || []), ...plan.shareIds]).filter(id => !plan.retainedIds.includes(id)), scopes: unique([...(prior?.scopes || []), ...plan.scopes, ...index.scopes, scopeOf(connection)]), credentialIds: unique([...(prior?.credentialIds || []), ...index.credentialIds, connection.session!.credentialId]), rowsRemoved: (prior?.rowsRemoved || 0) + plan.remove.length, unownedLegacy: plan.unownedLegacy};
    const fences = await accountFences(db);
    if (!fences.some(row => row.address === fence.address && row.userId === fence.userId)) fences.push(fence);
    await upsertState(db, ACCOUNT_FENCES_KEY, fences);
    await upsertState(db, journalKey(connection), journal);
    for (const key of [...plan.remove, credentialsKey(connection)]) await db.runAsync('DELETE FROM local_state WHERE key = ?', key);
    for (const row of plan.replacements) await upsertState(db, row.key, row.value);
    if (current?.session && connectionEndpoint(current, true) === fence.address && current.session.userId === fence.userId) {
      journal.credentialIds = unique([...journal.credentialIds, current.session.credentialId]);
      const {accessToken: _discarded, ...session} = current.session;
      await upsertState(db, 'connection', {...current, session});
      await upsertState(db, journalKey(connection), journal);
    }
    await db.execAsync('COMMIT'); return journal;
  } catch (error) {
    try {await db.execAsync('ROLLBACK');} catch {try {await db.closeAsync();} catch {} throw Object.assign(new Error('本机清理事务未完成，请重新打开后重试。'), {cause: error, discardDatabase: true});}
    throw error;
  }
}
export const updateCleanupJournal = (db: StateDatabase, connection: Connection, journal: CleanupJournal) => upsertState(db, journalKey(connection), journal);
