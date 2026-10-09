import {makeDraft, type RecordItem} from './core';
export type RecordEdit = {revision: number; text: string; start: string; end: string; due?: string};
export const recordEdit = (record: RecordItem): RecordEdit => ({revision: record.revision, text: record.content || record.title, start: record.start_at || '', end: record.end_at || '', ...(record.kind === 'task' ? {due: record.due_at || ''} : {})});
export function recordPatch(record: RecordItem, edit: RecordEdit): Partial<RecordItem> {
  // Date-only all-day values stay date-only unless the user actually changes them.
  const unchangedTime = record.kind === 'event' && edit.start === record.start_at && edit.end === record.end_at;
  const draft = makeDraft(edit.text, unchangedTime ? 'note' : record.kind, new Date(edit.start), new Date(edit.end));
  if (record.kind === 'task' && edit.due && !Number.isFinite(Date.parse(edit.due))) throw new Error('请核对截止时间。');
  return {title: draft.title, content: draft.content, ...(record.kind === 'event' && !unchangedTime ? {start_at: draft.start_at, end_at: draft.end_at, all_day: false} : {}), ...(record.kind === 'task' && edit.due !== undefined && edit.due !== (record.due_at || '') ? {due_at: edit.due || null} : {})};
}
export function recordEditChanged(record: RecordItem, edit: RecordEdit) {
  const initial = recordEdit(record);
  return initial.text !== edit.text || initial.start !== edit.start || initial.end !== edit.end || record.kind === 'task' && edit.due !== undefined && initial.due !== edit.due;
}

// One queue per persisted draft, shared across unmount/remount and identity switches.
const runtime = globalThis as typeof globalThis & {__pajioRecordDraftQueues?: Map<string, Promise<unknown>>};
const draftQueues = runtime.__pajioRecordDraftQueues ??= new Map<string, Promise<unknown>>();
export function withRecordDraft<T>(key: string, work: () => Promise<T>): Promise<T> {
  const next = (draftQueues.get(key) || Promise.resolve()).catch(() => {}).then(work);
  draftQueues.set(key, next);
  void next.finally(() => {if(draftQueues.get(key)===next)draftQueues.delete(key);}).catch(() => {});
  return next;
}

export function validRecordEdit(value: unknown): value is RecordEdit {
  const draft = value as RecordEdit;
  return !!draft && Number.isSafeInteger(draft.revision) && draft.revision >= 1 && typeof draft.text === 'string' && draft.text.length <= 12000 && typeof draft.start === 'string' && typeof draft.end === 'string' && (draft.due === undefined || typeof draft.due === 'string' && (!draft.due || Number.isFinite(Date.parse(draft.due))));
}
