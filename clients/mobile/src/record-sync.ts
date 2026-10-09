import type {RecordItem, Store} from './core';
type LocalStore = Pick<Store, 'get' | 'put' | 'batch'>;
const runtime = globalThis as typeof globalThis & {__pajioRecordScopeQueues?: WeakMap<LocalStore, Map<string, Promise<unknown>>>};
const queues = runtime.__pajioRecordScopeQueues ??= new WeakMap<LocalStore, Map<string, Promise<unknown>>>();
export function withRecordScope<T>(store: LocalStore, scope: string, work: () => Promise<T>): Promise<T> {
  let keys = queues.get(store); if (!keys) {keys = new Map(); queues.set(store, keys);}
  const next = (keys.get(scope) || Promise.resolve()).catch(() => {}).then(work);
  const settled = next.catch(() => {}); keys.set(scope, settled);
  void settled.then(() => {if (keys!.get(scope) === settled) keys!.delete(scope);});
  return next;
}
export function mergeRecordVersions(...groups: RecordItem[][]): RecordItem[] {
  const result = new Map<string, RecordItem>();
  for (const group of groups) for (const item of group) {const old = result.get(item.id); if (!old || item.revision > old.revision || (item.revision === old.revision && item.updated_at >= old.updated_at)) result.set(item.id, item);}
  return [...result.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}
export async function recordReceiptWrites(store: LocalStore, scope: string, record: RecordItem): Promise<[string, unknown][]> {
  const receipts = await store.get<RecordItem[]>(`receipts:${scope}`) || [];
  return [[`receipts:${scope}`, mergeRecordVersions(receipts, [record])]];
}
export function commitRecordReceipt(store: LocalStore, scope: string, record: RecordItem) {
  return withRecordScope(store, scope, async () => {await store.batch(await recordReceiptWrites(store, scope, record));});
}
export function commitRecordSnapshot(store: LocalStore, scope: string, snapshot: {items: RecordItem[]; version: number}) {
  return withRecordScope(store, scope, async () => {
    const version = await store.get<number>(`snapshot-version:${scope}`) || 0;
    if (snapshot.version < version) return;
    const cache = await store.get<RecordItem[]>(`snapshot:${scope}`) || [], receipts = await store.get<RecordItem[]>(`receipts:${scope}`) || [];
    // Include-deleted snapshots use monotone revisions. Older network replies can
    // never erase a newer receipt or replace a newer canonical record.
    const merged = mergeRecordVersions(cache, snapshot.items);
    await store.batch([[`snapshot:${scope}`, merged], [`snapshot-version:${scope}`, snapshot.version], [`receipts:${scope}`, receipts.filter(row => !snapshot.items.some(item => item.id === row.id && item.revision >= row.revision))]]);
  });
}
export function localRecords(store: LocalStore, scope: string): Promise<RecordItem[]> {
  return withRecordScope(store, scope, async () => mergeRecordVersions(await store.get<RecordItem[]>(`snapshot:${scope}`) || [], await store.get<RecordItem[]>(`receipts:${scope}`) || []));
}
