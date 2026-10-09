import {ApiError, Connection, Store, connectionEndpoint, connectionHeaders, scopeOf} from './core';

export const sourceIds = ['event', 'task', 'note', 'files', 'feishu'] as const;
export type BriefSourceId = typeof sourceIds[number];
export type PreferenceValues = {interests: string[]; priorities: string; sources: BriefSourceId[]; max_items: number};
export type BriefPreferences = PreferenceValues & {schema: 1; identity_id: string; revision: number; updated_at: string | null};
export type PreferenceRequest = PreferenceValues & {revision: number; request_key: string};
export type SourceAvailability = {id: BriefSourceId; label: string; state: 'available' | 'empty' | 'failed' | 'authorized' | 'not_connected' | 'unavailable'; count: number | null; observed_at: string; truncated: boolean; selected: boolean};
export type BriefSettings = {preferences: BriefPreferences; available_sources: SourceAvailability[]};
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const revision = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const instant = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value));
const key = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{16,120}$/.test(value);
const bad = () => new ApiError('简报设置回执不完整，请重新读取。', 422);
export function preferenceValues(value: unknown): PreferenceValues {
  if (!object(value) || !Array.isArray(value.interests) || value.interests.length > 8 || value.interests.some(v => typeof v !== 'string' || !v.trim() || v.length > 60) || new Set(value.interests).size !== value.interests.length || typeof value.priorities !== 'string' || value.priorities.length > 1000 || !Array.isArray(value.sources) || !value.sources.length || value.sources.some(v => !sourceIds.includes(v as BriefSourceId)) || new Set(value.sources).size !== value.sources.length || !Number.isInteger(value.max_items) || (value.max_items as number) < 1 || (value.max_items as number) > 3) throw bad();
  const interests = value.interests.map(v => (v as string).trim());
  if (new Set(interests).size !== interests.length) throw bad();
  return {interests, priorities: value.priorities.trim(), sources: sourceIds.filter(id => (value.sources as unknown[]).includes(id)), max_items: value.max_items as number};
}
export function parsePreferences(value: unknown, identity: string): BriefPreferences {
  if (!object(value) || value.schema !== 1 || value.identity_id !== identity || !revision(value.revision) || !(value.updated_at === null || instant(value.updated_at))) throw bad();
  return {...preferenceValues(value), schema: 1, identity_id: identity, revision: value.revision, updated_at: value.updated_at as string | null};
}
export function preferenceRequest(value: unknown): PreferenceRequest {
  if (!object(value) || !revision(value.revision) || !key(value.request_key)) throw bad();
  return {...preferenceValues(value), revision: value.revision, request_key: value.request_key};
}
export function parseSettings(value: unknown, identity: string): BriefSettings {
  if (!object(value) || !Array.isArray(value.available_sources)) throw bad();
  const preferences = parsePreferences(value.preferences, identity);
  const sources = value.available_sources;
  if (sources.length !== sourceIds.length || new Set(sources.map(row => object(row) && row.id)).size !== sourceIds.length) throw bad();
  for (const row of sources) {
    if (!object(row) || !sourceIds.includes(row.id as BriefSourceId) || typeof row.label !== 'string' || !['available', 'empty', 'failed', 'authorized', 'not_connected', 'unavailable'].includes(String(row.state)) || !(row.count === null || revision(row.count)) || !instant(row.observed_at) || typeof row.truncated !== 'boolean' || row.selected !== preferences.sources.includes(row.id as BriefSourceId)) throw bad();
  }
  return {preferences, available_sources: sources as SourceAvailability[]};
}
export function sourceAvailabilityLabel(source: Pick<SourceAvailability, 'state' | 'count' | 'truncated'>) {
  return source.state === 'authorized' ? '已授权，生成时才读取' : source.state === 'not_connected' ? '尚未授权或授权已失效' : source.state === 'unavailable' ? '服务未接入连接状态' : source.state === 'failed' ? '读取失败，其他来源仍可整理' : source.state === 'empty' ? '暂无已保存资料' : `${source.count} 项${source.truncated ? ' · 部分列表' : ''}`;
}
export class BriefPreferenceApi {
  private token = '';
  readonly connection: Connection;
  constructor(connection: Connection, private fetcher: typeof fetch = fetch) {this.connection = {...connection, ...(connection.session ? {session: {...connection.session}} : {}), ...(connection.development ? {development: {...connection.development}} : {})};}
  private async request(path: string, body?: PreferenceRequest, retry = true): Promise<unknown> {
    const timer = new AbortController(), timeout = setTimeout(() => timer.abort(), 15000);
    try {
      const result = await this.fetcher(new URL(path, connectionEndpoint(this.connection)), {method: body ? 'POST' : 'GET', signal: timer.signal, redirect: 'error', headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(body ? {'Content-Type': 'application/json', 'X-Wearing-Token': this.token} : {})}, ...(body ? {body: JSON.stringify(body)} : {})});
      if (body && result.status === 403 && retry) {await this.bootstrap(); return this.request(path, body, false);}
      if (!result.ok) throw new ApiError(result.status === 409 ? '简报偏好已在别处修改，输入已保留。请读取最新设置后核对。' : '暂时无法读写简报偏好，请稍后重试。', result.status);
      return await result.json();
    } catch (cause) {if (cause instanceof ApiError) throw cause; throw new ApiError(body ? '保存结果尚未确认，原请求已保留。' : '简报偏好暂时无法读取。', 0);}
    finally {clearTimeout(timeout);}
  }
  private async bootstrap() {
    const data = await this.request('/api/bootstrap');
    if (!object(data) || typeof data.token !== 'string' || !data.token || !Array.isArray(data.identities) || !data.identities.some(row => object(row) && row.id === this.connection.identity)) throw bad();
    this.token = data.token;
  }
  async load() {return parseSettings(await this.request('/api/briefings/preferences'), this.connection.identity);}
  async save(input: PreferenceRequest) {
    const body = preferenceRequest(input);
    if (!this.token) await this.bootstrap();
    const data = await this.request('/api/briefings/preferences', body);
    try {
      const saved = parsePreferences(data, this.connection.identity);
      if (!object(data) || data.request_key !== body.request_key || saved.revision !== body.revision + 1 || JSON.stringify(preferenceValues(saved)) !== JSON.stringify(preferenceValues(body))) throw bad();
      return saved;
    } catch {throw new ApiError('保存回执尚未核对，请取回同一次保存结果。', 0);}
  }
}
/** A saved request survives reload and must be resolved or explicitly abandoned after a definite conflict. */
export class PreferenceChanges {
  readonly key: string;
  private busy = false;
  constructor(private store: Pick<Store, 'get' | 'put'>, readonly api: BriefPreferenceApi) {this.key = `briefing-preference-request:${scopeOf(api.connection)}`;}
  async pending() {const value = await this.store.get(this.key); return value === null ? null : preferenceRequest(value);}
  async save(input?: PreferenceRequest) {
    if (this.busy) throw new ApiError('正在核对这次保存，请稍候。', 409);
    this.busy = true;
    try {
      const old = await this.pending(), body = old || (input && preferenceRequest(input));
      if (!body) throw bad();
      if (old && input && JSON.stringify(preferenceRequest(input)) !== JSON.stringify(old)) throw new ApiError('请先取回上次保存回执。', 409);
      await this.store.put(this.key, body);
      const receipt = await this.api.save(body);
      await this.store.put(this.key, null);
      return receipt;
    } finally {this.busy = false;}
  }
  async discardConflict() {if (this.busy) throw new ApiError('请等待保存结束。', 409); await this.store.put(this.key, null);}
}
