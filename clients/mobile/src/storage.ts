import * as SQLite from 'expo-sqlite';
import {Directory, File, Paths} from 'expo-file-system';
import {scopeOf, type Connection, type Media, type Store} from './core';
import {createSqliteState, createSqliteStore, type SqliteState, type StateDatabase} from './sqlite-store';
import {ACCOUNT_FENCES_KEY, fencedWrite} from './account-cleanup-model';
import {accountFences, assertAccountWritable, upsertState} from './account-cleanup-state';
import {managedRecordingUri} from './account-media';

// Fast Refresh can leave old async saves alive. Keep their queue and connection together.
const runtime = globalThis as typeof globalThis & {__wearingSqliteStateV1?: SqliteState};
const state = runtime.__wearingSqliteStateV1 ??= createSqliteState();
const records = createSqliteStore(() => SQLite.openDatabaseAsync('wearing-inbox.db', {useNewConnection: true}), state, async (db, key, encoded) => {
  const fences = await accountFences(db);
  if (fencedWrite(key, JSON.parse(encoded), fences)) throw new Error('此账户正在注销，本机内容已停止保存。');
});
export const storage: Store = {
  ...records,
  async blob(id) {const file = new File(Paths.document, 'originals', id); if (!file.exists) throw new Error('这份手机原件暂时无法读取，请保留记录并检查存储。'); return file;}
};
export async function keepMedia(uri: string, media: Media, connection?: Connection, recoverCopy = false) {
  return withNativeState(async db => {
    if (connection?.session) {
      await assertAccountWritable(db, connection);
      const key = 'media-index:v1:' + scopeOf(connection), row = await db.getFirstAsync<{value: string}>('SELECT value FROM local_state WHERE key = ?', key);
      const prior = row ? JSON.parse(row.value) as Media[] : [];
      if (!Array.isArray(prior)) throw new Error('本机原件目录无法读取。');
      // Inventory comes first so a failed or interrupted copy can be cleaned up.
      await upsertState(db, key, [...prior.filter(item => item.id !== media.id), {...media, ...(managedRecordingUri(uri, Paths.document.uri, Paths.cache.uri) ? {uri} : {})}]);
    }
    const directory = new Directory(Paths.document, 'originals'); directory.create({idempotent: true, intermediates: true});
    const destination = new File(directory, media.id), source = new File(uri);
    if (recoverCopy) {
      if (!source.exists || source.size <= 0 || source.size > 15*1024*1024) throw Error('这份照片暂时无法恢复，或超过了 15 MB。');
      // A killed copy may leave a nonempty partial file. Repair only this
      // journal's private UUID while sharing the account cleanup queue/fence.
      if (!destination.exists || !destination.md5 || destination.size !== source.size || destination.md5 !== source.md5) await source.copy(destination,{overwrite:true});
      if (!destination.exists || destination.size !== source.size || !destination.md5 || destination.md5 !== source.md5) throw Error('照片副本还未完整保存，请稍后重试恢复。');
    } else await source.copy(destination);
    if (!destination.exists || !destination.size) throw new Error('这份原件没有保存在手机里，请重新选择。');
    media.size = destination.size;
    return media;
  });
}
export async function preview(id: string) {return new File(Paths.document, 'originals', id).uri;}

/** Account cleanup shares the exact queue/connection used by every async save. */
export async function withNativeState<T>(operation: (db: StateDatabase) => Promise<T>): Promise<T> {
  await records.get(ACCOUNT_FENCES_KEY); // initialize and finish earlier writes
  const result = state.tail.then(async () => {
    try {return await operation(await state.database!);} catch (error) {if (error && typeof error === 'object' && 'discardDatabase' in error) state.database = undefined; throw error;}
  });
  state.tail = result.then(() => undefined, () => undefined);
  return result;
}
