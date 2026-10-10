import {type Connection} from './core';
import {credentialsKey, registerAccountCredential, upsertState} from './account-cleanup-state';
import {EnrollmentError} from './enrollment-model';
import {saveConnection, type Vault} from './session-protocol';
import {type StateDatabase} from './sqlite-store';

/** Caller holds the shared native-state queue. A cancelled admission cannot become a restored login. */
export async function commitNativeConnection(db: StateDatabase, vault: Vault, connection: Connection, isCurrent: () => boolean) {
  const ensure = () => {if (!isCurrent()) throw new EnrollmentError('enrollment_inactive');};
  ensure();
  const keys = ['connection', ...(connection.session ? [credentialsKey(connection)] : [])];
  const previous = new Map<string, string | null>();
  const tokenKey = connection.session ? 'pajio.session.' + connection.session.credentialId : null;
  const priorToken = tokenKey ? await vault.get(tokenKey) : null;
  ensure();
  let committed = false;
  await db.execAsync('BEGIN IMMEDIATE');
  try {
    for (const key of keys) previous.set(key, (await db.getFirstAsync<{value:string}>('SELECT value FROM local_state WHERE key = ?', key))?.value ?? null);
    ensure(); await registerAccountCredential(db, connection); ensure();
    await saveConnection(connection, {put: async (key, value) => {ensure(); await upsertState(db, key, value); ensure();}}, vault);
    ensure(); await db.execAsync('COMMIT'); committed = true;
    ensure();
  } catch (error) {
    try {
      if (committed) {
        // Cancellation can arrive while COMMIT itself awaits. No other in-app save
        // can enter this queue; restore only the exact metadata just committed.
        await db.execAsync('BEGIN IMMEDIATE');
        const current = await db.getFirstAsync<{value:string}>('SELECT value FROM local_state WHERE key = ?', 'connection');
        const value = current ? JSON.parse(current.value) as Connection : null;
        if (value?.session?.credentialId !== connection.session?.credentialId || value?.endpoint !== connection.endpoint || value?.identity !== connection.identity) throw new Error('connection changed during cancellation');
        for (const [key, raw] of previous) {
          if (raw === null) await db.runAsync('DELETE FROM local_state WHERE key = ?', key);
          else await db.runAsync('INSERT INTO local_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', key, raw);
        }
        await db.execAsync('COMMIT');
      } else await db.execAsync('ROLLBACK');
    } catch {
      try {await db.execAsync('ROLLBACK');} catch { /* Discard an uncertain connection below. */ }
      try {await db.closeAsync();} catch { /* Never reuse an uncertain transaction. */ }
      throw Object.assign(new EnrollmentError('enrollment_storage'), {discardDatabase:true});
    } finally {
      // The new UUID key never removes an older account's credential. A pre-existing
      // key is restored rather than deleted (normal identity switches reuse it).
      if (tokenKey) {
        if (priorToken === null) await vault.remove(tokenKey);
        else await vault.put(tokenKey, priorToken);
      }
    }
    throw error;
  }
}
