import {ApiError, Connection, connectionEndpoint, connectionHeaders} from './core';

export type SearchKind = 'all' | 'task' | 'record' | 'message';
export type SearchTarget = {kind: 'task'; task_id: string} | {kind: 'record'; record_id: string} | {kind: 'message'; task_id: string; message_id: number};
export type SearchItem = {key: string; id: string; kind: Exclude<SearchKind, 'all'>; title: string; snippet: string; matched_field: 'title' | 'content' | 'output'; record_kind: 'note' | 'task' | 'event' | null; created_at: string; updated_at: string; target: SearchTarget};
export type SearchPage = {identity_id: string; query: string; kind: SearchKind; items: SearchItem[]; next_cursor: string | null; as_of: string; files_included: false};
export type SearchMessage = {identity_id: string; id: number; task_id: string; content: string; output: string; status: string; created_at: string; updated_at: string};
const object = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);
const id = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(value);
const text = (value: unknown): value is string => typeof value === 'string';
const instant = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));
const integer = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;
const failure = () => new ApiError('搜索结果不完整，请重新搜索。', 422);
export function searchQuery(value: string): string {
  const query = value.trim();
  if (!query || [...query].length > 120 || /[\u0000-\u001f]/.test(value)) throw new ApiError('请输入 1–120 个字的关键词。', 422);
  return query;
}
export function parseSearchPage(value: unknown, identity: string, query: string, kind: SearchKind): SearchPage {
  if (!object(value) || value.identity_id !== identity || value.query !== query || value.kind !== kind || value.files_included !== false ||
    !instant(value.as_of) || !Array.isArray(value.items) || value.items.length > 50 || !(value.next_cursor === null || (text(value.next_cursor) && value.next_cursor.length <= 2048))) throw failure();
  for (const item of value.items) {
    if (!object(item) || !['task', 'record', 'message'].includes(item.kind) || (kind !== 'all' && item.kind !== kind) || !id(item.id) || item.key !== `${item.kind}:${item.id}` ||
      !text(item.title) || [...item.title].length > 100 || !text(item.snippet) || [...item.snippet].length > 212 || !['title', 'content', 'output'].includes(item.matched_field) ||
      !(item.record_kind === null || ['note', 'task', 'event'].includes(item.record_kind)) || !instant(item.created_at) || !instant(item.updated_at) || !object(item.target) || item.target.kind !== item.kind) throw failure();
    const target = item.target;
    if (item.kind === 'record') {
      if (target.record_id !== item.id || Object.keys(target).sort().join(',') !== 'kind,record_id') throw failure();
    } else if (item.kind === 'task') {
      if (target.task_id !== item.id || !id(target.task_id) || Object.keys(target).sort().join(',') !== 'kind,task_id') throw failure();
    } else if (!id(target.task_id) || !integer(target.message_id) || String(target.message_id) !== item.id || Object.keys(target).sort().join(',') !== 'kind,message_id,task_id') throw failure();
  }
  if (new Set(value.items.map(item => item.key)).size !== value.items.length) throw failure();
  return value as SearchPage;
}
export function parseSearchMessage(value: unknown, identity: string, messageId: number, taskId: string): SearchMessage {
  if (!object(value) || value.identity_id !== identity || value.id !== messageId || value.task_id !== taskId || !text(value.content) || !text(value.output) ||
    !text(value.status) || !instant(value.created_at) || !instant(value.updated_at)) throw failure();
  return value as SearchMessage;
}
export function mergeSearchPages(previous: SearchItem[], incoming: SearchItem[]): SearchItem[] {
  const seen = new Set(previous.map(item => item.key));
  return [...previous, ...incoming.filter(item => !seen.has(item.key))];
}
export class NativeSearchApi {
  private readonly connection: Connection;
  constructor(connection: Connection, private readonly fetcher: typeof fetch = fetch) {this.connection = {...connection};}
  private async read(path: string, signal?: AbortSignal): Promise<unknown> {
    const controller = new AbortController(), abort = () => controller.abort(), timeout = setTimeout(abort, 20000);
    signal?.addEventListener('abort', abort, {once: true}); if (signal?.aborted) abort();
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {signal: controller.signal, redirect: 'error',
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity}});
      const value = await response.json().catch(() => {throw failure();});
      if (!response.ok) throw new ApiError(object(value) && text(value.detail) ? value.detail : '搜索暂时不可用，请稍后重试。', response.status);
      return value;
    } catch (cause) {
      if (cause instanceof ApiError) throw cause;
      throw new ApiError('暂时连不上 Pajio，检查连接后可以重试。');
    } finally {clearTimeout(timeout); signal?.removeEventListener('abort', abort);}
  }
  async page(query: string, kind: SearchKind, cursor?: string | null, signal?: AbortSignal) {
    query = searchQuery(query);
    if (!['all', 'task', 'record', 'message'].includes(kind) || (cursor && cursor.length > 2048)) throw failure();
    const path = `/api/search?q=${encodeURIComponent(query)}&kind=${kind}&limit=20${cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`;
    return parseSearchPage(await this.read(path, signal), this.connection.identity, query, kind);
  }
  async message(messageId: number, taskId: string, signal?: AbortSignal) {
    if (!integer(messageId) || !id(taskId)) throw failure();
    return parseSearchMessage(await this.read(`/api/search/messages/${messageId}`, signal), this.connection.identity, messageId, taskId);
  }
}
