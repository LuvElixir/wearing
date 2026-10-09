import {ApiError, connectionEndpoint, connectionHeaders, type Connection, type Store} from './core';
import {withRecordDraft} from './record-editor';

type Dict = Record<string, unknown>;
const object = (v: unknown): v is Dict => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string';
const hex = (v: unknown, length: number): v is string => text(v) && new RegExp(`^[a-f0-9]{${length}}$`).test(v);
const id = (v: unknown): v is string => text(v) && /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/.test(v);
export const validProjectId = (v: unknown): v is string => text(v) && /^[a-fA-F0-9]{8}-(?:[a-fA-F0-9]{4}-){3}[a-fA-F0-9]{12}$/.test(v);
type NotificationEnvelope = {v: 1; server_id: string; event_key: string; identity_id: string};
export type NotificationTarget = NotificationEnvelope & ({type: 'pajio.task'; task_id: string} | {type: 'pajio.record'; record_id: string});
export type ResolvedNotification = {type:'task'; taskId:string;identityId:string;kind:'result'|'approval'} | {type:'record';recordId:string;identityId:string;kind:'record_reminder';seriesId:string|null;occurrenceKey:string|null};
export function notificationTarget(value: unknown): NotificationTarget | null {
  if (!object(value) || value.v !== 1 || !hex(value.server_id, 32) || !hex(value.event_key, 64) || !id(value.identity_id)) return null;
  const common = {v:1 as const,server_id:value.server_id,event_key:value.event_key,identity_id:value.identity_id};
  if (value.type === 'pajio.task' && id(value.task_id)) return {...common,type:'pajio.task',task_id:value.task_id};
  if (value.type === 'pajio.record' && text(value.record_id) && /^(?:life_[a-f0-9]{32}|recurrence_[a-f0-9]{32}_\d{8})$/.test(value.record_id)) return {...common,type:'pajio.record',record_id:value.record_id};
  return null;
}
export type NotificationStatus = {identity_id: string; installation_id: string; server_id: string; configured: boolean; project_id: string | null;
  enabled: boolean; reason: string | null; provider_status: string; provider_error: string | null; counts: Record<string, number>};
export type QuietHours = {identity_id: string; installation_id: string; revision: number; enabled: boolean; start_minute: number; end_minute: number; timezone: string};
export const quietTime = (minutes: number) => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
export function quietMinute(value: string): number {
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value.trim())) throw new ApiError('请按 22:00 这样的格式填写时间。', 422);
  const [hour, minute] = value.trim().split(':').map(Number); return hour * 60 + minute;
}
export function quietReceipt(value: unknown, identity: string, installation: string): QuietHours {
  const v = value as QuietHours;
  if (!v || v.identity_id !== identity || v.installation_id !== installation || !Number.isSafeInteger(v.revision) || v.revision < 0 || typeof v.enabled !== 'boolean' ||
      ![v.start_minute, v.end_minute].every(n => Number.isSafeInteger(n) && n >= 0 && n < 1440) || v.start_minute === v.end_minute || typeof v.timezone !== 'string' || !v.timezone || v.timezone.length > 80) throw new ApiError('安静时段回执无法核对，请重新读取。', 422);
  return {identity_id: v.identity_id, installation_id: v.installation_id, revision: v.revision, enabled: v.enabled, start_minute: v.start_minute, end_minute: v.end_minute, timezone: v.timezone};
}
const malformed = () => new ApiError('通知回执不完整，请重新检查状态。', 422);
const states = ['unverified', 'pending', 'sending', 'ticket', 'provider_accepted', 'failed', 'unknown', 'cancelled', 'awaiting_registration'];
export function providerMessage(status: NotificationStatus): string {
  if (!status.configured) return '服务端尚未配置推送。';
  if (status.reason === 'DeviceNotRegistered') return '手机的通知凭据已失效，请重新开启通知。';
  if (status.reason === 'expired' || status.provider_status === 'awaiting_registration') return '通知登记已到期。重新登录并开启通知后，仍有效的通知与提醒可继续发送。';
  if (!status.enabled) return '这台手机尚未接收当前身份的通知与提醒。';
  if (status.provider_error === 'InvalidCredentials' || status.provider_error === 'MismatchSenderId') return '推送凭据需要修复，暂时无法发送通知。';
  if (status.provider_status === 'provider_accepted') return '最近一条已交给系统推送服务，实际提醒仍受手机通知设置影响。';
  if (status.provider_status === 'ticket') return '最近一条已交给推送服务，等待系统回执。';
  if (status.provider_status === 'unknown') return '最近一条送达情况暂不明确。任务结果仍保留在 App 内。';
  if (status.provider_status === 'failed') return '最近一条未能发出。任务结果仍保留在 App 内。';
  return '已登记。新的结果、确认和已开启的日程待办提醒会尝试通知你，首次送达尚未验证。';
}
export function notificationInstallation(store: Pick<Store, 'get' | 'put'>, randomId: () => string): Promise<string> {
  const key = 'notification-installation:v1';
  return withRecordDraft(key, async () => {
    const saved = await store.get<string>(key);
    if (saved && /^[a-zA-Z0-9_-]{16,100}$/.test(saved)) return saved;
    const value = randomId();
    if (!/^[a-zA-Z0-9_-]{16,100}$/.test(value)) throw new Error('手机通知标识未能生成，请重试。');
    await store.put(key, value); return value;
  });
}

/** A fixed identity snapshot. A notification never supplies a URL or credentials. */
export class NotificationClient {
  private token = '';
  private readonly connection: Connection;
  constructor(connection: Connection, readonly installation: string, private readonly fetcher: typeof fetch = fetch) {
    this.connection = {...connection, ...(connection.development ? {development: {...connection.development}} : {}), ...(connection.session ? {session: {...connection.session}} : {})};
  }
  private async request(path: string, body?: unknown, retry = true): Promise<unknown> {
    const mutation = body !== undefined;
    if (mutation && !this.token) await this.bootstrap();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {method: mutation ? 'POST' : 'GET', redirect: 'error', signal: controller.signal,
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity,
          ...(mutation ? {'Content-Type': 'application/json', 'X-Wearing-Token': this.token} : {})}, ...(mutation ? {body: JSON.stringify(body)} : {})});
      if (response.status === 403 && mutation && retry) {await this.bootstrap(); return this.request(path, body, false);}
      const value: unknown = await response.json().catch(() => {throw malformed();});
      if (!response.ok) throw new ApiError(object(value) && text(value.detail) ? value.detail : '通知操作未完成，请检查连接后再试。', response.status);
      return value;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError('没有收到通知服务的回执，请重新检查状态。');
    } finally {clearTimeout(timer);}
  }
  private async bootstrap() {
    const v = await this.request('/api/bootstrap');
    if (!object(v) || v.version !== '0.2.0' || !text(v.token) || !v.token || !Array.isArray(v.identities) || !v.identities.some(i => object(i) && i.id === this.connection.identity)) throw malformed();
    this.token = v.token;
  }
  private parse(v: unknown): NotificationStatus {
    if (!object(v) || v.identity_id !== this.connection.identity || v.installation_id !== this.installation || !hex(v.server_id, 32) || typeof v.configured !== 'boolean' ||
      typeof v.enabled !== 'boolean' || (v.project_id !== null && !validProjectId(v.project_id)) || !states.includes(String(v.provider_status)) ||
      (v.reason !== null && !text(v.reason)) || (v.provider_error !== null && !text(v.provider_error)) || !object(v.counts) ||
      Object.entries(v.counts).some(([k, n]) => !states.includes(k) || !Number.isSafeInteger(n) || (n as number) < 0)) throw malformed();
    return v as NotificationStatus;
  }
  async quietHours() {
    return quietReceipt(await this.request('/api/notifications/preferences?installation_id=' + encodeURIComponent(this.installation)), this.connection.identity, this.installation);
  }
  async saveQuietHours(value: QuietHours) {
    const p = quietReceipt(value, this.connection.identity, this.installation);
    const result = quietReceipt(await this.request('/api/notifications/preferences', {installation_id: this.installation, revision: p.revision, enabled: p.enabled, start_minute: p.start_minute, end_minute: p.end_minute, timezone: p.timezone}), this.connection.identity, this.installation);
    if (result.revision !== p.revision + 1 || result.enabled !== p.enabled || result.start_minute !== p.start_minute || result.end_minute !== p.end_minute || result.timezone !== p.timezone) throw malformed();
    return result;
  }
  async status() {return this.parse(await this.request('/api/notifications/status?installation_id=' + encodeURIComponent(this.installation)));}
  async register(token: string, projectId: string, platform: 'ios' | 'android') {
    if (!validProjectId(projectId) || !/^(?:Expo|Exponent)PushToken\[[A-Za-z0-9_-]{10,200}\]$/.test(token)) throw malformed();
    const receipt = this.parse(await this.request('/api/notifications/register', {installation_id: this.installation, expo_push_token: token, project_id: projectId, platform}));
    if (!receipt.enabled || !receipt.configured || receipt.project_id !== projectId) throw malformed();
    return receipt;
  }
  async disable() {
    const receipt = this.parse(await this.request('/api/notifications/disable', {installation_id: this.installation}));
    if (receipt.enabled) throw malformed(); return receipt;
  }
  async disableInstallation() {
    const receipt = this.parse(await this.request('/api/notifications/disable-installation', {installation_id: this.installation}));
    if (receipt.enabled) throw malformed(); return receipt;
  }
  async resolve(target: NotificationTarget):Promise<ResolvedNotification> {
    if (target.identity_id !== this.connection.identity) throw new ApiError('请先切换到这条通知对应的身份。', 409);
    const v = await this.request('/api/notifications/resolve?event_key=' + encodeURIComponent(target.event_key));
    if (!object(v) || v.server_id !== target.server_id || v.event_key !== target.event_key || v.identity_id !== target.identity_id) throw malformed();
    if (target.type === 'pajio.record') {
      if (v.kind !== 'record_reminder' || v.record_id !== target.record_id) throw malformed();
      const recurring = target.record_id.startsWith('recurrence_');
      if (recurring ? !text(v.series_id) || v.series_id !== 'series_' + target.record_id.slice(11,43) || !text(v.occurrence_key) || !/^\d{4}-\d{2}-\d{2}$/.test(v.occurrence_key) || v.occurrence_key.replaceAll('-','') !== target.record_id.slice(-8) : v.series_id !== null || v.occurrence_key !== null) throw malformed();
      return {type:'record',recordId:target.record_id,identityId:target.identity_id,kind:'record_reminder',seriesId:v.series_id as string|null,occurrenceKey:v.occurrence_key as string|null};
    }
    if (v.task_id !== target.task_id || !['result', 'approval'].includes(String(v.kind))) throw malformed();
    return {type:'task',taskId: target.task_id, identityId: target.identity_id, kind: v.kind as 'result' | 'approval'};
  }
}
