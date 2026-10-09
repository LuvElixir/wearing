import {ApiError, type Draft, type Pending, type RecordItem, type Store} from './core';
import {bookmarkUrl, isBookmarkUrl} from './bookmark-url';
export type BookmarkFields = {title: string; url: string; notes: string};
export type BookmarkEdit = BookmarkFields & {version: 1; revision: number; requestId: string};
export type BookmarkRecord = RecordItem & {kind: 'note'; url: string};
export const bookmarkDraftKey = (scope: string, id = 'new') => `bookmark-edit:v1:${scope}:${id}`;
export function bookmarkFields(record: BookmarkRecord): BookmarkFields {return {title: record.title, url: record.url, notes: record.content};}
export function bookmarkDraft(fields: BookmarkFields, timezone: string): Draft {
  const title = fields.title.trim(), url = bookmarkUrl(fields.url.trim());
  if (!title || title.length > 200 || typeof fields.notes !== 'string' || fields.notes.length > 12000) throw new Error('请填写 1–200 字标题，备注最多 12000 字。');
  return {kind: 'note', title, url, content: fields.notes, timezone};
}
export function bookmarkRecord(value: unknown): BookmarkRecord {
  const r = value as BookmarkRecord;
  if (!r || r.kind !== 'note' || !isBookmarkUrl(r.url) || typeof r.id !== 'string' || !/^life_[a-f0-9]{32}$/.test(r.id) || !Number.isSafeInteger(r.revision) || r.revision < 1 || typeof r.title !== 'string' || !r.title.trim() || r.title.length > 200 || typeof r.content !== 'string' || r.content.length > 12000 || typeof r.timezone !== 'string' || !Number.isFinite(Date.parse(r.updated_at)) || r.deleted_at != null && !Number.isFinite(Date.parse(r.deleted_at))) throw new ApiError('没有收到完整的收藏记录，请刷新核对。', 422);
  return r;
}
/** Drafts deliberately accept incomplete URLs/titles: unfinished input is user data. */
export function bookmarkEdit(value: unknown): BookmarkEdit {
  const v = value as BookmarkEdit;
  if (!v || v.version !== 1 || !Number.isSafeInteger(v.revision) || v.revision < 0 || !/^[A-Za-z0-9_-]{16,120}$/.test(v.requestId) || typeof v.title !== 'string' || v.title.length > 200 || typeof v.url !== 'string' || v.url.length > 4096 || typeof v.notes !== 'string' || v.notes.length > 12000) throw new Error('本机收藏草稿暂时无法核对，原输入仍保留。');
  return v;
}
export function bookmarkPending(scope: string, edit: BookmarkEdit, timezone: string): Pending {
  return {id: edit.requestId, scope, draft: bookmarkDraft(edit, timezone), media: [], uploaded: [], organize: false, state: 'pending', attempts: 0, nextAt: 0, createdAt: new Date().toISOString()};
}
const locks = new WeakMap<Store, Map<string, Promise<unknown>>>();
export function withBookmarkDraft<T>(store: Store, key: string, fn: () => Promise<T>): Promise<T> {
  let scopes = locks.get(store); if (!scopes) {scopes = new Map(); locks.set(store, scopes);}
  const result = (scopes.get(key) || Promise.resolve()).catch(() => {}).then(fn), tail = result.catch(() => {}); scopes.set(key, tail);
  void tail.then(() => {if (scopes!.get(key) === tail) scopes!.delete(key);}); return result;
}
export async function openBookmark(value: unknown, open: (url: string) => Promise<unknown>) {await open(bookmarkUrl(value));}
