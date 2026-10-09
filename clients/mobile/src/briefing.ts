import {ApiError, Connection, connectionEndpoint, connectionHeaders} from './core';
import {validTimezone} from './ongoing-management-forms';
import {parsePreferences, type BriefPreferences} from './briefing-preferences';

export type BriefingState = 'not_started' | 'queued' | 'running' | 'needs_attention' | 'ready' | 'text_only' | 'failed' | 'stopped';
export type BriefingArtifact = {id: string; task_id: string; title: string; summary: string; revision: number; sources: string[]; limitations: string[]; checks: {file: string; render: string; content: string}};
export type BriefingSource = {id: string; label: string; state: 'available' | 'empty' | 'failed' | 'authorized' | 'not_connected' | 'unavailable'; count: number | null; observed_at: string; truncated: boolean};
export type Briefing = {id: string; identity_id: string; date: string; timezone: string; version: number; created_at: string; updated_at: string; state: BriefingState;
  task_id: string | null; task_status: string | null; output: string; error: string; delivery: {queued: boolean; blocked_reason: string | null}; sources: BriefingSource[]; artifacts: BriefingArtifact[]; preferences?: BriefPreferences | null};
export type BriefingRequest = {date: string; timezone: string; request_key: string; base_version: number; preferences_revision?: number};
const object = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);
const id = (value: unknown): value is string => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,64}$/.test(value);
const text = (value: unknown): value is string => typeof value === 'string';
const instant = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));
const integer = (value: unknown, min = 0) => Number.isSafeInteger(value) && (value as number) >= min;
const texts = (value: unknown) => Array.isArray(value) && value.every(text);
const failure = () => new ApiError('简报数据暂时不完整，请刷新后再查看。', 422);
const states = new Set<BriefingState>(['not_started', 'queued', 'running', 'needs_attention', 'ready', 'text_only', 'failed', 'stopped']);
export const briefingStateLabel: Record<BriefingState, string> = {not_started: '尚未开始', queued: '已排队', running: '正在整理', needs_attention: '需要查看进展', ready: '图文已生成', text_only: '文字已返回，图文未交付', failed: '这次没有完成', stopped: '已停止'};
export const briefingInProgress = (item: Briefing) => ['not_started', 'queued', 'running', 'needs_attention'].includes(item.state);
export function validBriefingRequest(value: unknown): value is BriefingRequest {
  if (!object(value) || !text(value.date) || !/^\d{4}-\d{2}-\d{2}$/.test(value.date) || !text(value.timezone) || !validTimezone(value.timezone) ||
    !text(value.request_key) || !/^[A-Za-z0-9_-]{16,120}$/.test(value.request_key) || !integer(value.base_version) || (value.preferences_revision !== undefined && !integer(value.preferences_revision))) return false;
  const stamp = Date.parse(value.date + 'T00:00:00Z');
  return Number.isFinite(stamp) && new Date(stamp).toISOString().slice(0, 10) === value.date;
}
export function parseBriefing(value: unknown, identity: string, date?: string, timezone?: string): Briefing {
  if (!object(value) || !id(value.id) || value.identity_id !== identity || !text(value.date) || !/^\d{4}-\d{2}-\d{2}$/.test(value.date) ||
    (date && value.date !== date) || !text(value.timezone) || !validTimezone(value.timezone) || (timezone && value.timezone !== timezone) ||
    !integer(value.version, 1) || !instant(value.created_at) || !instant(value.updated_at) || !states.has(value.state) ||
    !(value.task_id === null || id(value.task_id)) || !(value.task_status === null || text(value.task_status)) ||
    !text(value.output) || !text(value.error) || !object(value.delivery) || typeof value.delivery.queued !== 'boolean' ||
    !(value.delivery.blocked_reason === null || text(value.delivery.blocked_reason)) || !Array.isArray(value.sources) || !Array.isArray(value.artifacts)) throw failure();
  if ((value.task_id === null && (value.state !== 'not_started' || value.task_status !== null || value.artifacts.length)) || (value.state === 'ready' && !value.artifacts.length)) throw failure();
  for (const source of value.sources) {
    if (!object(source) || !id(source.id) || !text(source.label) || !['available', 'empty', 'failed', 'authorized', 'not_connected', 'unavailable'].includes(source.state) ||
      !(source.count === null || integer(source.count)) || !instant(source.observed_at) || typeof source.truncated !== 'boolean') throw failure();
  }
  for (const artifact of value.artifacts) {
    if (!object(artifact) || !id(artifact.id) || artifact.task_id !== value.task_id || !text(artifact.title) || !text(artifact.summary) ||
      !integer(artifact.revision, 1) || !texts(artifact.sources) || !texts(artifact.limitations) || !object(artifact.checks) ||
      !['file', 'content', 'render'].every(key => text(artifact.checks[key]))) throw failure();
  }
  if (new Set(value.sources.map(source => source.id)).size !== value.sources.length || new Set(value.artifacts.map(artifact => artifact.id)).size !== value.artifacts.length) throw failure();
  if (value.preferences !== undefined && value.preferences !== null) parsePreferences(value.preferences, identity);
  return value as Briefing;
}
export class BriefingApi {
  private token = '';
  private pending = false;
  private readonly connection: Connection;
  constructor(connection: Connection, private readonly fetcher: typeof fetch = fetch) {this.connection = {...connection, ...(connection.session ? {session: {...connection.session}} : {}), ...(connection.development ? {development: {...connection.development}} : {})};}
  private async request(path: string, body?: BriefingRequest, retry = true): Promise<unknown> {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {method: body ? 'POST' : 'GET', signal: controller.signal, redirect: 'error',
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(body ? {'X-Wearing-Token': this.token, 'Content-Type': 'application/json'} : {})},
        ...(body ? {body: JSON.stringify(body)} : {})});
      if (response.status === 403 && body && retry) {await this.bootstrap(); return await this.request(path, body, false);}
      const data = await response.json().catch(() => {throw new ApiError('回执不完整，请重新读取这次简报。', body ? 0 : 422);});
      if (!response.ok) throw new ApiError(object(data) && text(data.detail) ? data.detail : '这次请求没有完成，请刷新后重试。', response.status);
      return data;
    } catch (cause) {
      if (cause instanceof ApiError) throw cause;
      throw new ApiError(body ? '暂时没有取到生成回执。请求已保留，重试会继续读取同一份简报。' : '暂时连不上 Pajio，请检查连接后刷新。');
    } finally {clearTimeout(timeout);}
  }
  private async bootstrap() {
    const data = await this.request('/api/bootstrap');
    if (!object(data) || data.version !== '0.2.0' || !text(data.token) || !data.token || !Array.isArray(data.identities) || !data.identities.some(identity => object(identity) && identity.id === this.connection.identity)) throw failure();
    this.token = data.token;
  }
  async list(date: string, timezone: string): Promise<Briefing[]> {
    if (!validBriefingRequest({date, timezone, request_key: 'readonly-validation', base_version: 0})) throw new ApiError('简报日期或时区不正确。', 422);
    const data = await this.request(`/api/briefings?date=${encodeURIComponent(date)}&timezone=${encodeURIComponent(timezone)}`);
    if (!object(data) || data.identity_id !== this.connection.identity || data.date !== date || data.timezone !== timezone || !Array.isArray(data.items)) throw failure();
    const items = data.items.map(value => parseBriefing(value, this.connection.identity, date, timezone));
    if (new Set(items.map(item => item.id)).size !== items.length || new Set(items.map(item => item.version)).size !== items.length) throw failure();
    return items.sort((a, b) => b.version - a.version);
  }
  async create(body: BriefingRequest): Promise<Briefing> {
    if (!validBriefingRequest(body)) throw new ApiError('简报请求不完整，请重新打开。', 422);
    if (this.pending) throw new ApiError('正在取回这次生成回执，请稍候。', 409);
    this.pending = true;
    try {
      if (!this.token) await this.bootstrap();
      const data = await this.request('/api/briefings', body);
      try {return parseBriefing(data, this.connection.identity, body.date, body.timezone);} catch {throw new ApiError('暂时没有读到当前身份的完整回执，请重试读取原简报。');}
    } finally {this.pending = false;}
  }
}
