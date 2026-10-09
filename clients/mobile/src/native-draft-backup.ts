import type {Store} from './core';

export type NativeDraftBackupValue = {id: string; text: string; contextKey: string};
type Draft = Pick<NativeDraftBackupValue, 'text' | 'contextKey'>;
type BackupStore = Pick<Store, 'get' | 'put'>;

// All component instances using the same storage object/key share this queue.
// A replacement screen must observe unfinished writes from the previous screen.
const queues = new WeakMap<BackupStore, Map<string, Promise<unknown>>>();
function exclusive<T>(store: BackupStore, key: string, operation: () => Promise<T>): Promise<T> {
  let keys = queues.get(store);
  if (!keys) {keys = new Map(); queues.set(store, keys);}
  const result = (keys.get(key) ?? Promise.resolve()).then(operation, operation);
  const settled = result.catch(() => {});
  keys.set(key, settled);
  void settled.then(() => {if (keys!.get(key) === settled) keys!.delete(key);});
  return result;
}

function validDraft(value: unknown): value is Draft {
  if (!value || typeof value !== 'object') return false;
  const draft = value as Partial<Draft>;
  return typeof draft.text === 'string' && draft.text.length <= 12000 &&
    typeof draft.contextKey === 'string' && draft.contextKey.length > 0 && draft.contextKey.length <= 4000;
}
function validId(value: unknown): value is string {return typeof value === 'string' && value.length > 0 && value.length <= 200;}

/** Every save creates a version. A receipt may clear only that exact version.
 * newId must supply unique IDs across instances, e.g. Expo Crypto.randomUUID.
 * Keep the backing store object stable so remounts share the serialization key.
 */
export class NativeDraftBackup {
  constructor(private store: BackupStore, private key: string, private newId: () => string) {}

  private id(): string {
    const id = this.newId();
    if (!validId(id)) throw new Error('无法生成草稿版本，请保留当前输入。');
    return id;
  }

  save(draft: Draft): Promise<NativeDraftBackupValue> {
    // Capture now; a caller mutating its object while an older write waits must
    // not silently change the input associated with this save operation.
    if (!validDraft(draft)) return Promise.reject(new Error('草稿内容无效，请保留当前输入。'));
    const captured = {text: draft.text, contextKey: draft.contextKey};
    return exclusive(this.store, this.key, async () => {
      const saved = {id: this.id(), ...captured};
      await this.store.put(this.key, {...saved});
      return saved;
    });
  }

  load(): Promise<NativeDraftBackupValue | null> {
    return exclusive(this.store, this.key, async () => {
      const value = await this.store.get<unknown>(this.key);
      if (value === null || value === undefined) return null;
      if (!validDraft(value)) throw new Error('本机草稿暂时无法读取，请保留当前页面。');
      const id = (value as Partial<NativeDraftBackupValue>).id;
      if (id !== undefined && !validId(id)) throw new Error('本机草稿版本无法读取，请保留当前页面。');
      const result = {id: id ?? this.id(), text: value.text, contextKey: value.contextKey};
      // Preserve backups written before version IDs were introduced.
      if (id === undefined) await this.store.put(this.key, {...result});
      return result;
    });
  }

  clear(id: string): Promise<boolean> {
    if (!validId(id)) return Promise.resolve(false);
    return exclusive(this.store, this.key, async () => {
      const current = await this.store.get<Partial<NativeDraftBackupValue>>(this.key);
      if (!current || current.id !== id) return false;
      await this.store.put(this.key, null);
      return true;
    });
  }
}
