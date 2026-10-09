import {scopeOf, type Connection, type Store} from './core';
export type MemoryDraft = {version: 1; index?: number; revision: string; baseText?: string; text: string};
export const memoryDraftKey = (connection: Connection, target: 'user' | 'memory') => connection.session ? `memory-edit:v2:${scopeOf(connection)}:${target}` : `memory-edit:v1:${encodeURIComponent(connection.endpoint)}:${encodeURIComponent(connection.identity)}:${target}`;
export function memoryDraft(value: unknown): MemoryDraft | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Partial<MemoryDraft>;
  if (row.version !== 1 || typeof row.revision !== 'string' || !/^[a-f0-9]{64}$/.test(row.revision) || typeof row.text !== 'string' || row.text.length > 12000 || (row.index !== undefined && (!Number.isSafeInteger(row.index) || row.index < 0 || typeof row.baseText !== 'string' || row.baseText.length > 65536))) return null;
  return row as MemoryDraft;
}
/** Rebind only an exact, unique original; never guess that an old index is the same entry. */
export function rebaseMemoryDraft(draft: MemoryDraft, entries: string[], revision: string): {draft: MemoryDraft | null; alreadyPresent: boolean} {
  if (entries.includes(draft.text.trim()) && draft.text.trim()) return {draft: null, alreadyPresent: true};
  if (draft.index === undefined) return {draft: {...draft, revision}, alreadyPresent: false};
  const matches = entries.flatMap((text, index) => text === draft.baseText ? [index] : []);
  return {draft: matches.length === 1 ? {...draft, revision, index: matches[0]} : null, alreadyPresent: false};
}
/** One queue per scope also survives Fast Refresh/unmount; a clear cannot race an older save. */
const runtime = globalThis as typeof globalThis & {__pajioMemoryDraftQueues?: Map<string, Promise<void>>};
const queues = runtime.__pajioMemoryDraftQueues ??= new Map<string, Promise<void>>();
export async function persistMemoryDraft(store: Pick<Store, 'put'>, key: string, draft: MemoryDraft | null) {
  const next = (queues.get(key) || Promise.resolve()).catch(() => {}).then(() => store.put(key, draft));
  queues.set(key, next);
  try {await next;} finally {if (queues.get(key) === next) queues.delete(key);}
}
export async function readMemoryDraft(store: Pick<Store, 'get'>, key: string) {await queues.get(key)?.catch(() => {}); return memoryDraft(await store.get(key));}
