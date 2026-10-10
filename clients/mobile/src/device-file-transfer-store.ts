import {type Connection, ApiError, scopeOf} from './core';
import {accountWorkAllowed} from './account-work';
import {assertAccountWritable} from './account-cleanup-state';
import {storage, withNativeState} from './storage';
import {parseTransferRequest, type DeviceTransferStore} from './device-file-transfer';

/** Same native queue as account cleanup; delete only the exact request that was confirmed. */
export function deviceTransferStore(connection: Connection): DeviceTransferStore {
  const target = {...connection, session: connection.session && {...connection.session}, development: connection.development && {...connection.development}};
  return {...storage, clearIfSame: async (key, expected, active) => withNativeState(async db => {
    const allowed = () => active() && accountWorkAllowed(target);
    const prefix = `device-file-transfer:v1:${scopeOf(target)}|`;
    if (!key.startsWith(prefix) || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(key.slice(prefix.length))) throw new ApiError('等待记录不属于当前设备身份。', 403);
    if (!allowed()) throw new ApiError('当前页面或账号已变化，等待记录未修改。', 403);
    if (target.session) await assertAccountWritable(db, target);
    const row = await db.getFirstAsync<{value: string}>('SELECT value FROM local_state WHERE key = ?', key);
    if (!row) return true;
    const value: unknown = JSON.parse(row.value);
    if (!value || typeof value !== 'object' || !('schema' in value) || value.schema !== 1 || !('request' in value) ||
      JSON.stringify(parseTransferRequest(value.request)) !== JSON.stringify(parseTransferRequest(expected))) return false;
    if (!allowed()) throw new ApiError('当前页面或账号已变化，等待记录未修改。', 403);
    await db.runAsync('DELETE FROM local_state WHERE key = ? AND value = ?', key, row.value);
    return !await db.getFirstAsync('SELECT value FROM local_state WHERE key = ?', key);
  })};
}
