import type {MemorySnapshot, MemoryChange} from './core';

export type MemoryHistoryItem = {id: string; action: 'add' | 'replace' | 'remove' | 'undo'; source: 'user'; created_at: string; before: string[]; after: string[]; before_revision: string; after_revision: string; undoable: boolean; undo_of?: string};
export type MemoryHistory = {coverage: 'user_explicit'; limit: number; unconfirmed_changes: boolean; items: MemoryHistoryItem[]};
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const revision = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
export const memoryHistoryId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
const entries = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === 'string') && value.reduce((total, item) => total + item.length, 0) <= 131072;

export function validMemoryHistory(value: unknown, page: {enabled: boolean; revision?: string}): value is MemoryHistory {
  if (!object(value) || value.coverage !== 'user_explicit' || !Number.isSafeInteger(value.limit) || (value.limit as number) < 1 || (value.limit as number) > 20 || typeof value.unconfirmed_changes !== 'boolean' || !Array.isArray(value.items) || value.items.length > (value.limit as number)) return false;
  const ids = new Set<string>();
  for (const item of value.items) {
    if (!object(item) || !memoryHistoryId(item.id) || ids.has(item.id) || !['add', 'replace', 'remove', 'undo'].includes(String(item.action)) || item.source !== 'user' || typeof item.created_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T/.test(item.created_at) || !Number.isFinite(Date.parse(item.created_at)) || !entries(item.before) || !entries(item.after) || !revision(item.before_revision) || !revision(item.after_revision) || typeof item.undoable !== 'boolean') return false;
    if ((item.action === 'undo' || item.undo_of !== undefined) && !memoryHistoryId(item.undo_of)) return false;
    if (item.undoable && (!page.enabled || item.after_revision !== page.revision)) return false;
    ids.add(item.id);
  }
  return true;
}

/** Multiset differences preserve repeated entries and the service's ordering. */
export function memoryHistoryChanges(item: Pick<MemoryHistoryItem, 'before' | 'after'>) {
  function difference(left: string[], right: string[]) {
    const remaining = new Map<string, number>();
    for (const text of right) remaining.set(text, (remaining.get(text) || 0) + 1);
    return left.filter(text => {const count = remaining.get(text) || 0; if (count) {remaining.set(text, count - 1); return false;} return true;});
  }
  return {before: difference(item.before, item.after), after: difference(item.after, item.before)};
}
export const memoryHistoryTitle = (action: MemoryHistoryItem['action']) => ({add: '新增记忆', replace: '修改记忆', remove: '删除记忆', undo: '撤销修改'})[action];
export function memoryUndoRequest(target: 'user' | 'memory', snapshot: MemorySnapshot, id: string): MemoryChange | null {
  const page = snapshot.targets?.[target], item = page?.history?.items.find(item => item.id === id);
  if (!snapshot.available || !page?.enabled || !page.revision || !item?.undoable || item.after_revision !== page.revision) return null;
  return {target, action: 'undo', history_id: item.id, revision: page.revision};
}

export type MemoryChangeResult = {state: 'confirmed'; snapshot: MemorySnapshot} | {state: 'conflict'; snapshot?: MemorySnapshot; error: unknown} | {state: 'unconfirmed'; error: unknown};
/** A failed mutation is never replayed. Only a read is allowed after conflict. */
export async function applyMemoryChange(api: {changeMemory: (change: MemoryChange) => Promise<MemorySnapshot>; memory: () => Promise<MemorySnapshot>}, change: MemoryChange): Promise<MemoryChangeResult> {
  try {return {state: 'confirmed', snapshot: await api.changeMemory(change)};}
  catch (error) {
    if (object(error) && error.status === 409) {
      try {return {state: 'conflict', snapshot: await api.memory(), error};}
      catch {return {state: 'conflict', error};}
    }
    return {state: 'unconfirmed', error};
  }
}
