import {ApiError, type RecordItem, type Store} from './core';
import {isBookmarkUrl} from './bookmark-url';
import {recordEdit, validRecordEdit, withRecordDraft, type RecordEdit} from './record-editor';
import {mergeRecordVersions, recordReceiptWrites, withRecordScope} from './record-sync';
export type RecordPatch = Pick<Partial<RecordItem>, 'title' | 'content' | 'start_at' | 'end_at' | 'all_day' | 'completed' | 'due_at' | 'url'>;
export type MutationAction = 'edit' | 'archive' | 'restore';
export type MutationAttempt = {action?: MutationAction; key: string; base: RecordItem; patch: RecordPatch; generation: number};
export type RecordMutation = {action?: MutationAction; version: 1; id: string; scope: string; base: RecordItem; patch: RecordPatch; generation: number; state: 'pending' | 'sending' | 'conflict' | 'attention'; attempts: number; nextAt: number; attempt?: MutationAttempt; latest?: RecordItem; error?: string};
export type MutationTransport = {update(record: RecordItem, patch: Partial<RecordItem>, action: MutationAction, requestKey: string): Promise<RecordItem>; record(id: string): Promise<RecordItem>};
type LocalStore = Pick<Store, 'get' | 'put' | 'batch'>;
type Runtime = {listeners: Map<string, Set<() => void>>; flushes: WeakMap<LocalStore, Map<string, Promise<number>>>};
const global = globalThis as typeof globalThis & {__pajioRecordMutationRuntimeV1?: Runtime};
const runtime = global.__pajioRecordMutationRuntimeV1 ??= {listeners: new Map(), flushes: new WeakMap()};
export const mutationKey = (scope: string) => `record-mutations:v1:${scope}`;
const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value));
export const mutationAction = (row: {action?: MutationAction}): MutationAction => row.action || 'edit';
export const lifecycleMutation = (row: {action?: MutationAction} | null | undefined) => !!row && mutationAction(row) !== 'edit';
export function observeRecordMutations(scope: string, listener: () => void) {
  const listeners = runtime.listeners.get(scope) || new Set(); listeners.add(listener); runtime.listeners.set(scope, listeners);
  return () => {listeners.delete(listener); if (!listeners.size) runtime.listeners.delete(scope);};
}
function changed(scope: string) {for (const callback of runtime.listeners.get(scope) || []) {try {callback();} catch {/* One mounted view must not break a committed save. */}}}
function validRecord(record: RecordItem) {return !!record && typeof record.id === 'string' && Number.isSafeInteger(record.revision) && record.revision > 0 && ['task', 'event', 'note'].includes(record.kind) && typeof record.content === 'string' && typeof record.title === 'string' && Number.isFinite(Date.parse(record.updated_at)) && (record.deleted_at === undefined || record.deleted_at === null || typeof record.deleted_at === 'string' && Number.isFinite(Date.parse(record.deleted_at)));}
function validPatch(patch: RecordPatch, base: RecordItem) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch) || !Object.keys(patch).length || Object.keys(patch).some(key => !['title', 'content', 'start_at', 'end_at', 'completed', 'all_day', 'due_at', 'url'].includes(key))) return false;
  if (patch.url !== undefined && (base.kind !== 'note' || patch.url !== null && !isBookmarkUrl(patch.url))) return false;
  if (patch.title !== undefined && (typeof patch.title !== 'string' || !patch.title.trim() || patch.title.length > 200)) return false;
  if (patch.content !== undefined && (typeof patch.content !== 'string' || patch.content.length > 12000)) return false;
  if (patch.completed !== undefined && (base.kind !== 'task' || typeof patch.completed !== 'boolean')) return false;
  if (patch.due_at !== undefined && (base.kind !== 'task' || patch.due_at !== null && (typeof patch.due_at !== 'string' || !Number.isFinite(Date.parse(patch.due_at))))) return false;
  if ((patch.start_at !== undefined || patch.end_at !== undefined || patch.all_day !== undefined) && base.kind !== 'event') return false;
  if (patch.all_day !== undefined && typeof patch.all_day !== 'boolean') return false;
  return ['start_at', 'end_at'].every(key => patch[key as 'start_at'] === undefined || (typeof patch[key as 'start_at'] === 'string' && Number.isFinite(Date.parse(patch[key as 'start_at']!))));
}
function validIntent(row: {action?: MutationAction; patch: RecordPatch; base: RecordItem}) {
  if (row.action !== undefined && !['edit', 'archive', 'restore'].includes(row.action)) return false;
  const action = mutationAction(row);
  if (action === 'edit') return validPatch(row.patch, row.base);
  return !!row.patch && typeof row.patch === 'object' && !Array.isArray(row.patch) && !Object.keys(row.patch).length && (action === 'archive' ? !row.base.deleted_at : !!row.base.deleted_at);
}
function validEntry(row: RecordMutation, scope: string) {
  return row?.version === 1 && row.scope === scope && row.id === row.base?.id && validRecord(row.base) && validIntent(row) && Number.isSafeInteger(row.generation) && row.generation > 0 && ['pending', 'sending', 'conflict', 'attention'].includes(row.state) && Number.isSafeInteger(row.attempts) && row.attempts >= 0 && Number.isFinite(row.nextAt) && (!row.latest || (row.latest.id === row.id && validRecord(row.latest))) && (!row.attempt || (typeof row.attempt.key === 'string' && /^[A-Za-z0-9_-]{16,120}$/.test(row.attempt.key) && row.attempt.base.id === row.id && validRecord(row.attempt.base) && validIntent(row.attempt) && mutationAction(row.attempt) === mutationAction(row) && Number.isSafeInteger(row.attempt.generation) && row.attempt.generation > 0 && row.attempt.generation <= row.generation));
}
export function projectRecordMutation(row: RecordMutation, record = row.base): RecordItem {return lifecycleMutation(row) ? record : {...record, ...row.patch};}
export function projectRecordMutations(records: RecordItem[], rows: RecordMutation[]): RecordItem[] {
  const canonical = mergeRecordVersions(records, rows.map(row => row.base));
  return canonical.map(record => {const row = rows.find(item => item.id === record.id); return row ? projectRecordMutation(row, record) : record;});
}
export class RecordMutations {
  constructor(private store: LocalStore, private newKey: () => string) {}
  private async read(scope: string): Promise<RecordMutation[]> {
    const value = await this.store.get<RecordMutation[]>(mutationKey(scope));
    if (value === null) return [];
    if (!Array.isArray(value) || value.length > 100 || value.some(row => !validEntry(row, scope)) || new Set(value.map(row => row.id)).size !== value.length) throw new Error('本机修改队列暂时无法核对，原输入已保留，请不要清除应用数据。');
    return value;
  }
  items(scope: string) {return withRecordScope(this.store, scope, () => this.read(scope));}
  private key() {const key = this.newKey(); if (typeof key !== 'string' || !/^[A-Za-z0-9_-]{16,120}$/.test(key)) throw new Error('无法生成修改编号，请保留输入后重试。'); return key;}
  enqueue(scope: string, base: RecordItem, patch: RecordPatch, clearDraft?: {key: string; value: RecordEdit}) {
    const capturedBase = copy(base), capturedPatch = copy(patch), capturedDraft = clearDraft ? copy(clearDraft) : undefined;
    if (!validRecord(base) || base.deleted_at || !validPatch(patch, base)) return Promise.reject(new Error('这条修改无法保存，请核对内容和记录状态。'));
    return withRecordScope(this.store, scope, async () => {
      const rows = await this.read(scope), old = rows.find(row => row.id === base.id);
      if (lifecycleMutation(old)) throw new Error('这条记录的移除或恢复还未确认，请先处理原操作。');
      if (old?.state === 'conflict') throw new Error('这条记录已有版本冲突，请先打开记录核对两份内容。');
      if (!old && rows.length >= 100) throw new Error('已有 100 条修改等待同步，请先处理一些再保存。');
      const entry: RecordMutation = old ? {...old, patch: {...old.patch, ...capturedPatch}, generation: old.generation + 1, state: old.state === 'sending' ? 'sending' : 'pending', nextAt: 0, error: undefined} : {version: 1, id: base.id, scope, base: capturedBase, patch: capturedPatch, generation: 1, state: 'pending', attempts: 0, nextAt: 0};
      const next = [...rows.filter(row => row.id !== base.id), entry];
      const write = async () => {
        const values: [string, unknown][] = [[mutationKey(scope), next]];
        if (capturedDraft && JSON.stringify(await this.store.get(capturedDraft.key)) === JSON.stringify(capturedDraft.value)) values.push([capturedDraft.key, null]);
        await this.store.batch(values);
      };
      if (capturedDraft) await withRecordDraft(capturedDraft.key, write); else await write();
      changed(scope); return copy(entry);
    });
  }
  /** Lifecycle uses the official action, never a deleted_at patch or optimistic tombstone. */
  enqueueLifecycle(scope: string, base: RecordItem, action: 'archive' | 'restore', preserveDraft?: {key: string; value: RecordEdit}, replaceConflictGeneration?: number) {
    const captured = copy(base), draft = preserveDraft ? copy(preserveDraft) : undefined;
    if (!validRecord(captured) || !validIntent({action, base: captured, patch: {}}) || draft && !validRecordEdit(draft.value)) return Promise.reject(new Error('记录状态不适合这项操作，请读取最新版本后核对。'));
    return withRecordScope(this.store, scope, async () => {
      const rows = await this.read(scope), old = rows.find(row => row.id === base.id);
      // A rejected edit may be saved as a draft before explicitly restoring its observed tombstone.
      if (old && !(action === 'restore' && mutationAction(old) === 'edit' && old.state === 'conflict' && old.generation === replaceConflictGeneration && old.latest?.revision === captured.revision && old.latest.deleted_at === captured.deleted_at && draft)) throw new Error('请先同步或核对原操作；结果未知时不能替换请求。');
      if (!old && rows.length >= 100) throw new Error('已有 100 条操作等待同步，请先处理一些再保存。');
      const entry: RecordMutation = {version: 1, scope, id: base.id, base: captured, action, patch: {}, generation: (old?.generation || 0) + 1, state: 'pending', attempts: 0, nextAt: 0};
      const write = async () => {
        const values: [string, unknown][] = [[mutationKey(scope), [...rows.filter(row => row.id !== base.id), entry]]];
        // A later editor's draft wins; lifecycle never erases or rebases text input.
        if (draft && await this.store.get(draft.key) === null) values.push([draft.key, draft.value]);
        await this.store.batch(values);
      };
      if (draft) await withRecordDraft(draft.key, write); else await write();
      changed(scope); return copy(entry);
    });
  }
  /** Only a proven conflict can adopt a newer revision, after an explicit user choice. */
  resolveLifecycle(scope: string, id: string, generation: number, latest: RecordItem, keepAction: boolean) {
    const captured = copy(latest);
    return withRecordScope(this.store, scope, async () => {
      const rows = await this.read(scope), row = rows.find(item => item.id === id);
      if (!row || !lifecycleMutation(row) || row.state !== 'conflict' || row.generation !== generation || captured.id !== id || !validRecord(captured) || captured.revision < Math.max(row.base.revision, row.latest?.revision || 0)) throw new Error('操作状态已有变化，请重新读取后核对。');
      const needsWrite = keepAction && (mutationAction(row) === 'archive' ? !captured.deleted_at : !!captured.deleted_at);
      const next = needsWrite ? rows.map(item => item.id === id ? {...item, base: captured, generation: item.generation + 1, state: 'pending' as const, attempt: undefined, latest: undefined, attempts: 0, nextAt: 0, error: undefined} : item) : rows.filter(item => item.id !== id);
      await this.store.batch([[mutationKey(scope), next], ...await recordReceiptWrites(this.store, scope, captured)]);
      changed(scope); return next.find(item => item.id === id) || null;
    });
  }
  retry(scope: string, id: string) {
    return withRecordScope(this.store, scope, async () => {const rows = await this.read(scope), row = rows.find(item => item.id === id); if (!row || row.state === 'conflict') return; row.state = 'pending'; row.nextAt = 0; row.attempts = 0; delete row.error; await this.store.put(mutationKey(scope), rows); changed(scope);});
  }
  inspect(scope: string, id: string, latest: RecordItem) {
    return withRecordScope(this.store, scope, async () => {
      if (!validRecord(latest) || latest.id !== id) throw new Error('最新版本无法核对，请重试。');
      const rows = await this.read(scope), row = rows.find(item => item.id === id);
      if (row && row.state !== 'sending' && (!row.attempt || row.state === 'conflict')) {row.state = 'conflict'; row.latest = copy(mergeRecordVersions(row.latest ? [row.latest] : [], [latest])[0]); row.error = '请核对本机修改和服务端版本。';}
      await this.store.batch([[mutationKey(scope), rows], ...await recordReceiptWrites(this.store, scope, latest)]);
      changed(scope); return row || null;
    });
  }
  /** A conflict can be replaced only by an explicit choice over that exact local generation. */
  resolve(scope: string, id: string, generation: number, latest: RecordItem, keepLocal: boolean, replacement?: RecordPatch, clearDraft?: {key: string; value: RecordEdit}) {
    return withRecordScope(this.store, scope, async () => {
      const rows = await this.read(scope), row = rows.find(item => item.id === id);
      if (!row || row.generation !== generation || row.state !== 'conflict' || latest.id !== id || !validRecord(latest) || latest.revision < Math.max(row.base.revision, row.latest?.revision || 0)) throw new Error('修改状态已有变化，请重新读取后核对。');
      if (lifecycleMutation(row)) throw new Error('请核对移除或恢复操作，不要把它当作正文修改。');
      if (keepLocal && latest.deleted_at) throw new Error('服务端已移除这条记录；请先恢复，再应用你的修改。本机输入仍在。');
      const patch = {...row.patch, ...replacement};
      if (keepLocal && !validPatch(patch, latest)) throw new Error('本机修改无法应用，请核对内容。');
      const next = keepLocal ? rows.map(item => item.id === id ? {...item, patch, base: copy(latest), generation: item.generation + 1, state: 'pending' as const, attempt: undefined, latest: undefined, attempts: 0, nextAt: 0, error: undefined} : item) : rows.filter(item => item.id !== id);
      const write = async () => {
        const values: [string, unknown][] = [[mutationKey(scope), next], ...await recordReceiptWrites(this.store, scope, latest)];
        if (clearDraft && JSON.stringify(await this.store.get(clearDraft.key)) === JSON.stringify(clearDraft.value)) values.push([clearDraft.key, null]);
        await this.store.batch(values);
      };
      if (clearDraft) await withRecordDraft(clearDraft.key, write); else await write();
      changed(scope); return next.find(item => item.id === id) || null;
    });
  }
  /** A network response may update the original scope, never another identity or newer intent. */
  flush(scope: string, transport: MutationTransport, current: () => boolean, now = Date.now(), onError?: (error: unknown) => void) {
    let scopes = runtime.flushes.get(this.store); if (!scopes) {scopes = new Map(); runtime.flushes.set(this.store, scopes);}
    const ongoing = scopes.get(scope); if (ongoing) return ongoing;
    const operation = this.run(scope, transport, current, now, onError); scopes.set(scope, operation);
    void operation.finally(() => {if (scopes!.get(scope) === operation) scopes!.delete(scope);}).catch(() => {});
    return operation;
  }
  private async run(scope: string, transport: MutationTransport, current: () => boolean, now: number, onError?: (error: unknown) => void) {
    let sent = 0;
    const ids = (await this.items(scope)).map(row => row.id);
    for (const id of ids) {
      if (!current()) break;
      const attempt = await withRecordScope(this.store, scope, async () => {
        const rows = await this.read(scope), row = rows.find(item => item.id === id);
        if (!row || row.state === 'conflict' || row.state === 'attention' || row.nextAt > now || !current()) return null;
        row.attempt ??= {action: mutationAction(row), key: this.key(), base: copy(row.base), patch: copy(row.patch), generation: row.generation};
        row.state = 'sending'; row.attempts++; await this.store.put(mutationKey(scope), rows); changed(scope); return copy(row.attempt);
      });
      if (!attempt) continue;
      if (!current()) {await this.fail(scope, id, attempt, new ApiError('身份已切换，修改仍在原身份待同步。'), null, now); break;}
      try {
        const receipt = await transport.update(attempt.base, attempt.patch, mutationAction(attempt), attempt.key);
        if (!validRecord(receipt) || receipt.id !== id || receipt.kind !== attempt.base.kind || receipt.revision < attempt.base.revision || (lifecycleMutation(attempt) ? receipt.revision !== attempt.base.revision + 1 || (mutationAction(attempt) === 'archive' ? !receipt.deleted_at : !!receipt.deleted_at) : !!receipt.deleted_at)) throw new ApiError('没有收到可核对的操作回执，请取回同一次操作结果。', 0);
        await withRecordScope(this.store, scope, async () => {
          const rows = await this.read(scope), row = rows.find(item => item.id === id);
          if (!row || row.attempt?.key !== attempt.key) return;
          const next = row.generation === attempt.generation ? rows.filter(item => item.id !== id) : rows.map(item => item.id === id ? {...item, base: receipt, state: 'pending' as const, attempt: undefined, nextAt: 0, attempts: 0, error: undefined} : item);
          await this.store.batch([[mutationKey(scope), next], ...await recordReceiptWrites(this.store, scope, receipt)]); changed(scope); sent++;
        });
      } catch (error) {
        try {onError?.(error);} catch {/* Diagnostics never change a durable write. */}
        let latest: RecordItem | null = null;
        if (error instanceof ApiError && error.status === 409 && current()) {try {latest = await transport.record(id);} catch {/* Both local intent and conflict remain durable; read can be retried. */}}
        await this.fail(scope, id, attempt, error, latest, now);
        // Loss of connectivity/auth is one attempt, not a storm across every record.
        if (!(error instanceof ApiError && error.status === 409)) break;
      }
    }
    return sent;
  }
  private fail(scope: string, id: string, attempt: MutationAttempt, error: unknown, latest: RecordItem | null, now: number) {
    return withRecordScope(this.store, scope, async () => {
      const rows = await this.read(scope), row = rows.find(item => item.id === id);
      if (!row || row.attempt?.key !== attempt.key) return;
      const conflict = error instanceof ApiError && error.status === 409;
      const permanent = error instanceof ApiError && [400, 401, 403, 404, 413, 422].includes(error.status);
      row.state = conflict ? 'conflict' : permanent || row.attempts >= 6 ? 'attention' : 'pending';
      row.error = error instanceof Error ? error.message : '修改已留在本机，暂时没同步上。';
      row.nextAt = now + Math.min(300000, 5000 * 2 ** Math.min(row.attempts - 1, 6));
      if (latest && latest.id === row.id && validRecord(latest)) row.latest = copy(mergeRecordVersions(row.latest ? [row.latest] : [], [latest])[0]);
      await this.store.batch([[mutationKey(scope), rows], ...(row.latest ? await recordReceiptWrites(this.store, scope, row.latest) : [])]); changed(scope);
    });
  }
}
export function mutationLabel(row: RecordMutation) {
  const action = mutationAction(row), noun = action === 'archive' ? '移除' : action === 'restore' ? '恢复' : '修改';
  return row.state === 'conflict' ? `${noun}有冲突，点开核对` : row.state === 'attention' ? `${noun}需重试，点开查看` : row.state === 'sending' ? `${noun}正在同步` : `${noun}已留在本机，待同步`;
}
/** The confirmed request may precede a newer canonical lifecycle change. */
export function mutationSyncedLabel(action: MutationAction, current: RecordItem, dirty: boolean) {
  if (action === 'archive') return current.deleted_at ? '已移到最近删除，本机草稿和原件仍保留。' : '这次移除的回执已取回，记录目前处于可用状态。';
  if (action === 'restore') return current.deleted_at ? '这次恢复的回执已取回，记录目前仍在最近删除中。' : '记录已恢复；本机输入仍在，核对后可继续保存。';
  if (current.deleted_at) return '修改回执已取回，记录目前在最近删除中；本机输入仍保留。';
  return dirty ? '上一份修改已同步，当前新输入还未保存。' : '修改已同步到 Pajio。';
}
export const mutationDraft = (row: RecordMutation) => recordEdit(projectRecordMutation(row));
