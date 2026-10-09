import {ApiError, connectionEndpoint, connectionHeaders, type Connection} from './core';
import {bookmarkRecord, type BookmarkRecord} from './bookmark-model';
export type BookmarkPage = {identity_id: string; query: string; archived: boolean; version: number; items: BookmarkRecord[]; next_cursor: string | null};
export function bookmarkFetch(fetcher: typeof fetch, current: () => boolean, signal?: AbortSignal): typeof fetch {
  return async (input, init) => {
    if (!current() || signal?.aborted) throw new ApiError('身份或连接已切换。', 409);
    const controller = new AbortController();
    let rejectAbort!: (reason: ApiError) => void;
    const cancelled = new Promise<never>((_, reject) => {rejectAbort = reject;});
    const abort = () => {controller.abort();rejectAbort(new ApiError('收藏请求未完成，请稍后重试。', 0));}, timeout = setTimeout(abort,20000);
    signal?.addEventListener('abort',abort); init?.signal?.addEventListener('abort',abort);
    if (init?.signal?.aborted) abort();
    try {
      // These are JSON API requests. Keep the deadline and both abort signals
      // alive until the body has arrived, including WearingApi's own deadline.
      return await Promise.race([cancelled,(async()=>{
        const response = await fetcher(input,{...init,signal:controller.signal});
        if(!current()||controller.signal.aborted)throw new ApiError('身份或连接已切换。',409);
        // Decode with the network response first. React Native's Response
        // polyfill does not UTF-8-decode an ArrayBuffer passed to new Response.
        const body = await response.text();
        if(!current()||controller.signal.aborted)throw new ApiError('身份或连接已切换。',409);
        return new Response(body||null,{status:response.status,statusText:response.statusText,headers:response.headers});
      })()]);
    }
    finally {clearTimeout(timeout);signal?.removeEventListener('abort',abort);init?.signal?.removeEventListener('abort',abort);}
  };
}
export class BookmarkClient {
  constructor(readonly connection: Connection, private fetcher: typeof fetch, private current: () => boolean, private signal?: AbortSignal) {}
  async page(query = '', archived = false, cursor?: string): Promise<BookmarkPage> {
    if (!this.current()) throw new ApiError('身份或连接已切换。', 409);
    if (query.length > 120 || /[\x00-\x1f]/.test(query)) throw new ApiError('检索词最多 120 字。', 422);
    const params = new URLSearchParams({query: query.trim(), archived: String(archived), limit: '30'}); if (cursor) params.set('cursor', cursor);
    const response = await bookmarkFetch(this.fetcher,this.current,this.signal)(new URL('/api/bookmarks?' + params, connectionEndpoint(this.connection)), {headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity}, redirect: 'error'});
    if (!this.current()) throw new ApiError('身份或连接已切换。', 409);
    const data = await response.json();
    if (!this.current()) throw new ApiError('身份或连接已切换。', 409);
    if (!response.ok) throw new ApiError(typeof data.detail === 'string' ? data.detail : '收藏暂未读取。', response.status);
    if (data.identity_id !== this.connection.identity || data.query !== query.trim() || data.archived !== archived || !Number.isSafeInteger(data.version) || data.version < 0 || !Array.isArray(data.items) || data.items.length > 30 || data.next_cursor !== null && (typeof data.next_cursor !== 'string' || data.next_cursor.length > 2048)) throw new ApiError('收藏列表不完整，请刷新核对。', 422);
    const items = data.items.map(bookmarkRecord);
    if (items.some((r: BookmarkRecord) => !!r.deleted_at !== archived) || new Set(items.map((r: BookmarkRecord) => r.id)).size !== items.length) throw new ApiError('收藏列表状态不完整。', 422);
    return {...data, items};
  }
}
