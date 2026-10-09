import {connectionEndpoint, type Connection} from './core';
export const ACCOUNT_FENCES_KEY = 'account-deletion-fences:v1';
export type AccountFence = {address: string; userId: string};
export type LocalRow = {key: string; value: unknown};
export const fenceFor = (connection: Connection): AccountFence => {
  const address = connectionEndpoint(connection, true);
  if (!connection.session) throw new Error('账户清理需要明确的账户身份。');
  return {address, userId: connection.session.userId};
};
export function ownedScope(scope: unknown, fence: AccountFence): scope is string {
  if (typeof scope !== 'string' || !scope.startsWith(`${fence.address}|${fence.userId}|`)) return false;
  return /^[A-Za-z0-9_-]{1,128}\|[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(scope.slice(`${fence.address}|${fence.userId}|`.length));
}
export function keyScope(key: string): string | null {
  // Every application namespace may add a suffix, but the canonical account scope
  // is fixed. This includes ongoing-create's |kind and future scoped features.
  const match = key.match(/^[a-z][a-z0-9:-]*:(https:\/\/[^|]+\/\|user_[a-f0-9]{32}\|[A-Za-z0-9_-]{1,128}\|[A-Za-z0-9][A-Za-z0-9_.-]{0,63})(?=[:|]|$)/);
  return match?.[1] ?? null;
}
export function fencedWrite(key: string, value: unknown, fences: AccountFence[]) {
  const scope = keyScope(key);
  if (scope && fences.some(fence => ownedScope(scope, fence))) return true;
  if (['share-intake:v1','picker-recovery:v1'].includes(key) && Array.isArray(value)) return value.some(row => row && typeof row === 'object' && fences.some(fence => ownedScope((row as {scope?: unknown}).scope, fence)));
  return false;
}
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
function references(value: unknown, media: Set<string>, uris: Set<string>) {
  if (typeof value === 'string') {
    if (uuid.test(value)) media.add(value);
    if (value.startsWith('file://')) {uris.add(value); for (const segment of value.split('/')) if (uuid.test(segment)) media.add(segment);}
    return;
  }
  if (Array.isArray(value)) {for (const child of value) references(child, media, uris); return;}
  if (!value || typeof value !== 'object') return;
  const row = value as Record<string, unknown>;
  for (const child of Object.values(row)) references(child, media, uris);
}
export function accountCleanupPlan(connection: Connection, rows: LocalRow[]) {
  const fence = fenceFor(connection), remove: string[] = [], scopes = new Set<string>();
  const ownedMedia = new Set<string>(), retainedMedia = new Set<string>(), ownedUris = new Set<string>(), retainedUris = new Set<string>();
  const shares: string[] = [], replacements: LocalRow[] = [];
  let unownedLegacy = 0;
  for (const row of rows) {
    const scope = keyScope(row.key);
    if (scope && ownedScope(scope, fence)) {
      remove.push(row.key); scopes.add(scope); references(row.value, ownedMedia, ownedUris);
    } else if (['share-intake:v1','picker-recovery:v1'].includes(row.key) && Array.isArray(row.value)) {
      const retained = row.value.filter(value => {
        if (value && typeof value === 'object' && ownedScope(value.scope, fence)) {
          if (row.key === 'share-intake:v1' && typeof value.id === 'string' && uuid.test(value.id)) shares.push(value.id);
          scopes.add(value.scope); references(value, ownedMedia, ownedUris); return false;
        }
        references(value, retainedMedia, retainedUris); return true;
      });
      if (retained.length !== row.value.length) replacements.push({key: row.key, value: retained});
    } else {
      references(row.value, retainedMedia, retainedUris);
      if (row.key.startsWith(`memory-edit:v1:${encodeURIComponent(fence.address)}:`) && row.value !== null) unownedLegacy++;
    }
  }
  return {fence, remove, replacements, scopes: [...scopes], originals: [...ownedMedia].filter(id => !retainedMedia.has(id)),
    uris: [...ownedUris].filter(uri => !retainedUris.has(uri)), shareIds: shares.filter(id => !retainedMedia.has(id)), retainedIds: [...retainedMedia], retainedUris: [...retainedUris], unownedLegacy};
}
