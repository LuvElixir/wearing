import * as SQLite from 'expo-sqlite';
import {Directory, File, Paths} from 'expo-file-system';
import type {Media, Store} from './core';
import {createSqliteState, createSqliteStore, type SqliteState} from './sqlite-store';

// Fast Refresh can leave old async saves alive. Keep their queue and connection together.
const runtime = globalThis as typeof globalThis & {__wearingSqliteStateV1?: SqliteState};
const state = runtime.__wearingSqliteStateV1 ??= createSqliteState();
const records = createSqliteStore(() => SQLite.openDatabaseAsync('wearing-inbox.db', {useNewConnection: true}), state);
export const storage: Store = {
  ...records,
  async blob(id) {const file = new File(Paths.document, 'originals', id); if (!file.exists) throw new Error('这份手机原件暂时无法读取，请保留记录并检查存储。'); return file;}
};
export async function keepMedia(uri: string, media: Media) {
  const directory = new Directory(Paths.document, 'originals'); directory.create({idempotent: true, intermediates: true});
  const destination = new File(directory, media.id); await new File(uri).copy(destination);
  if (!destination.exists || !destination.size) throw new Error('这份原件没有保存在手机里，请重新选择。');
  media.size = destination.size;
  return media;
}
export async function preview(id: string) {return new File(Paths.document, 'originals', id).uri;}
