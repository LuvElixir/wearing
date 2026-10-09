import {ApiError, Connection, connectionEndpoint, connectionHeaders, WearingApi} from './core';

export type CloudFeature = 'documents' | 'calendar';
export type CloudState = {provider: 'feishu'; state: 'not_configured' | 'configured' | 'authorizing' | 'authorization_expired' | 'connected' | 'expired'; configured: boolean; revision: string | null; app_id: string | null; account_name: string | null; account_id: string | null; checked_at: number | null; error: string | null; revocation_pending: boolean; capabilities: {id: CloudFeature; label: string; requested: boolean; authorized: boolean; scopes: string[]}[]; authorization: {id: string; url: string; user_code: string; expires_at: number; interval: number} | null};
export type CloudFile = {name: string; token: string; type: string; url?: string};
export type CloudCalendar = {calendar_id: string; summary?: string; summary_alias?: string; role?: string};
export type CloudEvent = {event_id: string; summary?: string; description?: string; status?: string; start_time?: {date?: string; timestamp?: string; timezone?: string}; end_time?: {date?: string; timestamp?: string; timezone?: string}; location?: {name?: string}};
export type CloudPage<T> = {items: T[]; has_more: boolean; next_page_token: string | null};
export type CloudDocument = {content: string; document_id: string; title: string | null; offset: number; next_offset: number | null; total_characters: number};
export function upcomingCalendarRange(now = Date.now()) {const start = Math.floor(now / 1000); return {start, end: start + 7 * 86400};}
const object = (value: unknown): Record<string, unknown> | null => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
const invalid = () => new ApiError('飞书返回内容不完整，请刷新后重试。', 422);
export function officialFeishuUrl(value: string): boolean {
  try {const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && !url.port && (url.hostname === 'feishu.cn' || url.hostname.endsWith('.feishu.cn'));} catch {return false;}
}
export function cloudState(value: unknown): CloudState {
  const data = object(value);
  if (!data || data.provider !== 'feishu' || !['not_configured', 'configured', 'authorizing', 'authorization_expired', 'connected', 'expired'].includes(String(data.state)) || typeof data.configured !== 'boolean' || typeof data.revocation_pending !== 'boolean' || !(data.revision === null || typeof data.revision === 'string') || !Array.isArray(data.capabilities) || data.capabilities.length !== 2) throw invalid();
  for (const key of ['app_id', 'account_name', 'account_id', 'error']) if (!(data[key] === null || typeof data[key] === 'string')) throw invalid();
  if (!(data.checked_at === null || (typeof data.checked_at === 'number' && Number.isFinite(data.checked_at)))) throw invalid();
  const seen = new Set();
  for (const item of data.capabilities) {const capability = object(item); if (!capability || !['documents', 'calendar'].includes(String(capability.id)) || seen.has(capability.id) || typeof capability.label !== 'string' || typeof capability.requested !== 'boolean' || typeof capability.authorized !== 'boolean' || !Array.isArray(capability.scopes) || !capability.scopes.every(scope => typeof scope === 'string')) throw invalid(); seen.add(capability.id);}
  if (data.authorization !== null) {const auth = object(data.authorization); if (!auth || typeof auth.id !== 'string' || !/^[a-f0-9]{32}$/.test(auth.id) || typeof auth.url !== 'string' || !officialFeishuUrl(auth.url) || typeof auth.user_code !== 'string' || typeof auth.expires_at !== 'number' || !Number.isFinite(auth.expires_at) || typeof auth.interval !== 'number' || auth.interval < 1 || auth.interval > 120) throw invalid();}
  return data as CloudState;
}
function page<T>(value: unknown, id: string, name?: string): CloudPage<T> {
  const data = object(value);
  if (!data || !Array.isArray(data.items) || typeof data.has_more !== 'boolean' || !(data.next_page_token === undefined || data.next_page_token === null || typeof data.next_page_token === 'string')) throw invalid();
  for (const raw of data.items) {
    const item = object(raw); if (!item || typeof item[id] !== 'string' || (name && typeof item[name] !== 'string')) throw invalid();
    for (const key of ['name', 'type', 'url', 'summary', 'summary_alias', 'description', 'status', 'role']) if (item[key] !== undefined && typeof item[key] !== 'string') throw invalid();
    for (const key of ['start_time', 'end_time', 'location']) if (item[key] !== undefined) {const nested = object(item[key]); if (!nested) throw invalid(); for (const field of ['date', 'timestamp', 'timezone', 'name']) if (nested[field] !== undefined && typeof nested[field] !== 'string') throw invalid();}
  }
  if (data.has_more && !data.next_page_token) throw invalid();
  return {items: data.items as T[], has_more: data.has_more, next_page_token: typeof data.next_page_token === 'string' ? data.next_page_token : null};
}
export function cloudDocument(value: unknown): CloudDocument {
  const data = object(value);
  if (!data || typeof data.content !== 'string' || typeof data.document_id !== 'string' || !(data.title === null || typeof data.title === 'string') || !Number.isSafeInteger(data.offset) || !Number.isSafeInteger(data.total_characters) || !(data.next_offset === null || Number.isSafeInteger(data.next_offset))) throw invalid();
  return data as CloudDocument;
}
export function cloudConfigurationError(appId: string, secret: string, features: CloudFeature[]) {return !/^cli_[A-Za-z0-9]{6,80}$/.test(appId) || !/^[A-Za-z0-9_-]{12,160}$/.test(secret) ? '请核对飞书 App ID 与 App Secret。' : !features.length ? '请选择文档或日历。' : null;}
export class CloudAppsApi {
  private auth: WearingApi;
  constructor(private connection: Connection, private fetcher: typeof fetch = fetch) {this.auth = new WearingApi(connection, fetcher);}
  private async request(path: string, method = 'GET', body?: unknown): Promise<unknown> {
    const token = method === 'GET' ? undefined : await this.auth.voiceAuthorization();
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await this.fetcher(new URL('/api/cloud-apps/feishu' + path, connectionEndpoint(this.connection)).toString(), {method, redirect: 'error', signal: controller.signal, headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(token ? {'X-Wearing-Token': token, 'Content-Type': 'application/json'} : {})}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      const data = await response.json();
      if (!response.ok) throw new ApiError(typeof data.detail === 'string' && data.detail.length < 250 ? data.detail : '这次飞书操作没有完成，请重试。', response.status);
      return data;
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('暂时连不上云端应用服务，请检查连接后重试。');}
    finally {clearTimeout(timeout);}
  }
  async list() {return cloudState(await this.request(''));}
  async configure(app_id: string, secret: string, features: CloudFeature[]) {const error = cloudConfigurationError(app_id, secret, features); if (error) throw new ApiError(error, 422); return cloudState(await this.request('', 'PUT', {app_id, secret, features}));}
  async authorize(revision: string) {return cloudState(await this.request('/authorize', 'POST', {revision}));}
  async poll(authorization_id: string) {return cloudState(await this.request('/poll', 'POST', {authorization_id}));}
  async check() {return cloudState(await this.request('/check', 'POST'));}
  async disconnect(revision: string) {return cloudState(await this.request('', 'DELETE', {revision}));}
  async files(folder?: string, next?: string) {return page<CloudFile>(await this.request('/files?' + new URLSearchParams({...folder ? {folder_token: folder} : {}, ...next ? {page_token: next} : {}})), 'token', 'name');}
  async document(document: string, kind = 'docx', offset = 0) {return cloudDocument(await this.request('/document?' + new URLSearchParams({document, kind, offset: String(offset)})));}
  async calendars(next?: string) {return page<CloudCalendar>(await this.request('/calendars?' + new URLSearchParams(next ? {page_token: next} : {})), 'calendar_id');}
  async events(calendar_id: string, start: number, end: number, next?: string) {return page<CloudEvent>(await this.request('/events?' + new URLSearchParams({calendar_id, start_time: String(start), end_time: String(end), ...next ? {page_token: next} : {}})), 'event_id');}
}
