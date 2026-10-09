import {ApiError, connectionEndpoint, connectionHeaders, scopeOf, type Connection, type Store} from './core';
import {utf8Size, type ChatImportMessage, type ChatImportPreview} from './chat-import-parser';
export type ChatImportRequest = {request_key: string; platform: 'wechat'; conversation_title: string; authors: string[]; self_author: string | null; source_sha256: string; messages: ChatImportMessage[]; confirmed: true};
export type ChatImportReceipt = {schema: 1; request_key: string; import_id: string; identity_id: string; status: 'imported' | 'deleted'; created_at: string};
export type ChatImportSummary = {schema: 1; import_id: string; identity_id: string; conversation_title: string; authors: string[]; self_author: string | null; source_sha256: string; message_count: number; attachment_count: number; created_at: string; status: 'imported'; attachments_imported: false};
export type ChatImportDetail = ChatImportSummary & {messages: ChatImportMessage[]};
export type ChatImportDraft = {version: 1; key: string; sourceHash: string; preview: ChatImportPreview; selfAuthor: string | null; shareId?: string};
export type ChatImportPending = {version: 1; key: string; request: ChatImportRequest | null; shareId?: string};
export const chatImportDraftKey = (scope: string) => 'chat-import-draft:v1:' + scope;
export const chatImportPendingKey = (scope: string) => 'chat-import-pending:v1:' + scope;
const KEY = /^[A-Za-z0-9_-]{16,120}$/, HASH = /^[a-f0-9]{64}$/;
export function makeChatImportRequest(draft: ChatImportDraft): ChatImportRequest {
  const p = draft.preview;
  if (!KEY.test(draft.key) || !HASH.test(draft.sourceHash) || !p.title.trim() || p.title.length > 160 || p.authors.length < 1 || p.authors.length > 50 || p.messages.length < 1 || p.messages.length > 500 || draft.selfAuthor !== null && !p.authors.includes(draft.selfAuthor)) throw new ApiError('聊天预览尚不完整，请重新选择文件。', 422);
  const body: ChatImportRequest = {request_key: draft.key, platform: 'wechat', conversation_title: p.title, authors: p.authors, self_author: draft.selfAuthor, source_sha256: draft.sourceHash, messages: p.messages, confirmed: true};
  if (utf8Size(JSON.stringify(body)) > 512 * 1024) throw new ApiError('这批聊天整理后超过 512 KB，请减少所选消息。', 413);
  return body;
}
function receipt(raw: unknown, identity: string, key: string): ChatImportReceipt {
  const r = raw as ChatImportReceipt | null;
  if (!r || r.schema !== 1 || r.identity_id !== identity || r.request_key !== key || typeof r.import_id !== 'string' || !/^[A-Za-z0-9_-]{1,120}$/.test(r.import_id) || !['imported', 'deleted'].includes(r.status) || typeof r.created_at !== 'string') throw new ApiError('导入回执尚未核对，请重试同一次导入。', 0);
  return r;
}
export class ChatImportApi {
  constructor(readonly connection: Connection, private fetcher: typeof fetch, readonly active: () => boolean = () => true, private signal?: AbortSignal) {}
  assertActive() {if (!this.active() || this.signal?.aborted) throw new ApiError('身份已切换，已停止本次操作。', 0);}
  private async call(path: string, method = 'GET', body?: unknown): Promise<unknown> {
    this.assertActive(); const controller = new AbortController(), stop = () => controller.abort(), timer = setTimeout(stop, 20000);
    this.signal?.addEventListener('abort', stop);
    try {
      let token = '';
      if (method !== 'GET') {
        const bootstrap = await this.call('/api/bootstrap') as {token?: string; identities?: {id: string}[]};
        if (!bootstrap.token || !bootstrap.identities?.some(i => i.id === this.connection.identity)) throw new ApiError('请重新核对当前身份。', 422);
        token = bootstrap.token;
      }
      this.assertActive();
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)), {method, redirect: 'error', signal: controller.signal, headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(method !== 'GET' ? {'X-Wearing-Token': token, 'Content-Type': 'application/json'} : {})}, ...(body ? {body: JSON.stringify(body)} : {})});
      this.assertActive();
      if (!response.ok) throw new ApiError(response.status === 409 ? method === 'DELETE' ? 'Pajio 正在处理任务，请先停止或等任务结束，再移除这批聊天。' : '这次导入的内容与原请求不一致，请先核对已导入批次。' : response.status === 404 ? '这台服务暂未找到对应聊天导入。' : response.status === 413 ? '聊天超出当前导入限制，可减少所选消息或移除旧批次后重试。' : response.status === 422 ? '聊天文件未通过导入检查，请减少选定范围后重试。' : '聊天导入暂时无法完成，请重试。', response.status);
      const result = await response.json(); this.assertActive(); return result;
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError(method === 'GET' ? '暂时无法读取聊天导入，请重试。' : '操作结果尚未确认，请重试核对同一次操作。', 0);}
    finally {clearTimeout(timer); this.signal?.removeEventListener('abort', stop);}
  }
  async receipt(key: string) {if (!KEY.test(key)) throw new ApiError('导入编号无效。', 422); try {return receipt(await this.call('/api/chat-imports/receipts/' + encodeURIComponent(key)), this.connection.identity, key);} catch (error) {if (error instanceof ApiError && error.status === 404) return null; throw error;}}
  async submit(body: ChatImportRequest) {return receipt(await this.call('/api/chat-imports', 'POST', body), this.connection.identity, body.request_key);}
  async list(cursor?: string): Promise<{items: ChatImportSummary[]; next_cursor: string | null}> {
    const value = await this.call('/api/chat-imports?' + new URLSearchParams({limit: '20', ...(cursor ? {cursor} : {})})) as {items?: ChatImportSummary[]; next_cursor?: string | null};
    if (!Array.isArray(value.items) || value.items.some(i => i.schema !== 1 || i.identity_id !== this.connection.identity || i.status !== 'imported' || typeof i.import_id !== 'string' || !/^[A-Za-z0-9_-]{1,120}$/.test(i.import_id) || typeof i.conversation_title !== 'string' || !Number.isSafeInteger(i.message_count)) || value.next_cursor != null && typeof value.next_cursor !== 'string') throw new ApiError('聊天批次列表不完整，请刷新。', 422);
    return {items: value.items, next_cursor: value.next_cursor || null};
  }
  async detail(id: string): Promise<ChatImportDetail> {
    if (!/^[A-Za-z0-9_-]{1,120}$/.test(id)) throw new ApiError('导入编号无效。', 422);
    const data = await this.call('/api/chat-imports/' + encodeURIComponent(id)) as ChatImportDetail;
    if (data.schema !== 1 || data.identity_id !== this.connection.identity || data.import_id !== id || data.status !== 'imported' || !Array.isArray(data.messages) || data.messages.length > 500 || data.messages.some(message => typeof message.id !== 'string' || typeof message.author !== 'string' || typeof message.text !== 'string' || message.sent_at !== null && typeof message.sent_at !== 'string')) throw new ApiError('聊天详情尚未完整读取，请重试。', 422);
    return data;
  }
  async remove(id: string) {
    if (!/^[A-Za-z0-9_-]{1,120}$/.test(id)) throw new ApiError('导入编号无效。', 422);
    const data = await this.call('/api/chat-imports/' + encodeURIComponent(id), 'DELETE') as {schema?: number; identity_id?: string; import_id?: string; status?: string};
    if (data.schema !== 1 || data.identity_id !== this.connection.identity || data.import_id !== id || data.status !== 'deleted') throw new ApiError('删除回执尚未确认，请重试同一批聊天。', 0);
  }
}
/** Scoped durable journal. Previews never reach the network until confirm(). */
export class ChatImportJournal {
  readonly draftKey: string; readonly pendingKey: string;
  private tail: Promise<unknown> = Promise.resolve();
  constructor(private store: Pick<Store, 'get' | 'put'>, readonly api: ChatImportApi) {const scope = scopeOf(api.connection); this.draftKey = chatImportDraftKey(scope); this.pendingKey = chatImportPendingKey(scope);}
  private serial<T>(fn: () => Promise<T>): Promise<T> {const next = this.tail.catch(() => {}).then(() => {this.api.assertActive(); return fn();}); this.tail = next; return next;}
  async draft() {return this.store.get<ChatImportDraft>(this.draftKey);}
  async pending() {return this.store.get<ChatImportPending>(this.pendingKey);}
  retain(draft: ChatImportDraft) {return this.serial(async () => {if (await this.pending()) throw new ApiError('请先核对上次导入。', 409); this.api.assertActive(); makeChatImportRequest(draft); await this.store.put(this.draftKey, draft);});}
  discard() {return this.serial(async () => {if (await this.pending()) throw new ApiError('上次导入结果尚需核对，请先重试。', 409); await this.store.put(this.draftKey, null);});}
  confirm() {return this.serial(async () => {
    let pending = await this.pending(); this.api.assertActive();
    if (!pending) {
      const draft = await this.draft(); if (!draft) throw new ApiError('请先选择并预览聊天。', 422);
      pending = {version: 1, key: draft.key, request: makeChatImportRequest(draft), ...(draft.shareId ? {shareId: draft.shareId} : {})};
      this.api.assertActive(); await this.store.put(this.pendingKey, pending);
    }
    this.api.assertActive();
    let result = await this.api.receipt(pending.key);
    if (!result) {
      if (!pending.request) throw new ApiError('服务尚无这次导入记录。本机聊天已随退出账户清除，请重新选择文件。', 410);
      result = await this.api.submit(pending.request);
    }
    this.api.assertActive(); await this.store.put(this.draftKey, null);
    await this.store.put(this.pendingKey, {...pending, request: null});
    return {receipt: result, shareId: pending.shareId};
  });}
  finish() {return this.serial(async () => {await this.store.put(this.draftKey, null); await this.store.put(this.pendingKey, null);});}
  clearMissing() {return this.serial(async () => {const pending = await this.pending(); if (!pending || pending.request) throw new ApiError('请先重试核对原导入。', 409); if (await this.api.receipt(pending.key)) throw new ApiError('服务已有这次导入，请先核对结果。', 409); this.api.assertActive(); await this.store.put(this.pendingKey, null);});}
}
