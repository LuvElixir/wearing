import type {Store} from './core';

/** The small async surface shared by Expo SQLite and the storage regression harness. */
export interface StateDatabase {
  execAsync(sql: string): Promise<void>;
  runAsync(sql: string, ...params: string[]): Promise<unknown>;
  getFirstAsync<T>(sql: string, ...params: string[]): Promise<T | null>;
  closeAsync(): Promise<void>;
}

export type SqliteState = {tail: Promise<void>; database?: Promise<StateDatabase>};
export const createSqliteState = (): SqliteState => ({tail: Promise.resolve()});
const upsert = 'INSERT INTO local_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value = excluded.value';

function isBusy(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return /database (?:table |schema )?is locked|SQLITE_(?:BUSY|LOCKED)\b/i.test(message);
}

/** Serializes reads too: no caller can observe half a batch or join another transaction. */
export function createSqliteStore(open: () => Promise<StateDatabase>, state = createSqliteState()): Pick<Store, 'get' | 'put' | 'batch'> {
  const enqueue = <T>(task: () => Promise<T>) => {
    const result = state.tail.then(task);
    state.tail = result.then(() => undefined, () => undefined);
    return result;
  };
  const retryBusy = async <T>(task: () => Promise<T>): Promise<T> => {
    // External/dev-tool contention is exceptional. Never block indefinitely or retry disk errors.
    for (let attempt = 0; ; attempt++) {
      try {return await task();} catch (error) {
        if (!isBusy(error) || attempt >= 2) throw error;
        await new Promise(resolve => setTimeout(resolve, 50 * (attempt + 1)));
      }
    }
  };
  const database = async () => {
    if (!state.database) {
      state.database = (async () => {
        const db = await open();
        try {
          await db.execAsync('PRAGMA busy_timeout = 250;');
          await retryBusy(() => db.execAsync('PRAGMA journal_mode = WAL; CREATE TABLE IF NOT EXISTS local_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);'));
          return db;
        } catch (error) {
          try {await db.closeAsync();} catch {/* Preserve the initialization failure. */}
          throw error;
        }
      })();
    }
    try {return await state.database;} catch (error) {state.database = undefined; throw error;}
  };
  const encode = (value: unknown) => {
    const encoded = JSON.stringify(value);
    if (encoded === undefined) throw new TypeError('这条内容无法保存，请重试。');
    return encoded;
  };
  return {
    get<T>(key: string) {
      return enqueue(async () => {
        const db = await database();
        const row = await retryBusy(() => db.getFirstAsync<{value: string}>('SELECT value FROM local_state WHERE key = ?', key));
        return row ? JSON.parse(row.value) as T : null;
      });
    },
    async put(key, value) {
      // Snapshot before waiting so a mutable draft cannot change underneath the queued write.
      const encoded = encode(value);
      return enqueue(async () => {const db = await database(); await retryBusy(() => db.runAsync(upsert, key, encoded));});
    },
    async batch(values) {
      const entries = values.map(([key, value]) => [key, encode(value)] as const);
      return enqueue(async () => {
        if (!entries.length) return;
        const db = await database();
        await retryBusy(async () => {
          // A single private connection and queue avoid Expo's second transaction connection.
          // Acquire the write lock before the first row, not halfway through saving a recording.
          await db.execAsync('BEGIN IMMEDIATE');
          try {
            for (const [key, value] of entries) await db.runAsync(upsert, key, value);
            await db.execAsync('COMMIT');
          } catch (error) {
            try {await db.execAsync('ROLLBACK');} catch (rollbackError) {
              // Never let later writes accidentally join a failed, still-open transaction.
              state.database = undefined;
              try {await db.closeAsync();} catch {/* This connection remains quarantined. */}
              const failure = new Error('本机保存未完成，请重试。');
              Object.assign(failure, {cause: error, rollbackError});
              throw failure;
            }
            throw error;
          }
        });
      });
    },
  };
}
