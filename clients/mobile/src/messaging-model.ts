import {ApiError, Connection, connectionEndpoint, connectionHeaders, WearingApi} from './core';

export type MessagingProvider = 'telegram' | 'feishu';
export type MessagingChannel = {provider: MessagingProvider; name: string; configured: boolean; enabled: boolean; state: 'not_configured' | 'configured' | 'connecting' | 'listening' | 'error'; allowed_users: string[]; can_enable: boolean; uncertain_replies: number; revision: string | null; error: string | null; checked_at: string | null; bot_id?: string};
export type MessagingSnapshot = {channels: MessagingChannel[]};
export type MessagingConfiguration = {secret: string; allowed_users: string[]; app_id?: string};
const object = (value: unknown): Record<string, unknown> | null => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
export function messagingSnapshot(value: unknown): MessagingSnapshot {
  const data = object(value), bad = () => new ApiError('渠道状态不完整，请刷新后再试。', 422);
  if (!data || !Array.isArray(data.channels) || data.channels.length !== 2) throw bad();
  const channels = data.channels.map(item => {
    const channel = object(item);
    if (!channel || !['telegram', 'feishu'].includes(String(channel.provider)) || typeof channel.name !== 'string' || !['configured', 'enabled', 'can_enable'].every(key => typeof channel[key] === 'boolean') ||
      !['not_configured', 'configured', 'connecting', 'listening', 'error'].includes(String(channel.state)) || !Array.isArray(channel.allowed_users) || !channel.allowed_users.every(user => typeof user === 'string') ||
      !Number.isSafeInteger(channel.uncertain_replies) || (channel.uncertain_replies as number) < 0 || !(channel.revision === null || (typeof channel.revision === 'string' && /^[a-f0-9]{32}$/.test(channel.revision))) || !(channel.error === null || typeof channel.error === 'string') || !(channel.checked_at === null || typeof channel.checked_at === 'string')) throw bad();
    return channel as MessagingChannel;
  });
  if (new Set(channels.map(channel => channel.provider)).size !== 2) throw bad();
  return {channels};
}
export function allowedMessagingUsers(raw: string): string[] {return [...new Set(raw.split(/[\s,，;；]+/).map(item => item.trim()).filter(Boolean))];}
export function messagingConfigurationError(provider: MessagingProvider, configuration: MessagingConfiguration): string | null {
  const {secret, allowed_users: users, app_id: id} = configuration;
  if (!users.length || users.length > 20) return '请填写 1–20 个个人用户 ID。';
  if (provider === 'telegram' && (!/^[0-9]{5,20}:[A-Za-z0-9_-]{20,120}$/.test(secret) || users.some(user => !/^[1-9][0-9]{0,19}$/.test(user)))) return '请核对 Bot Token 和 Telegram 数字用户 ID。';
  if (provider === 'feishu' && (!/^cli_[A-Za-z0-9]{6,80}$/.test(id || '') || !/^[A-Za-z0-9_-]{12,160}$/.test(secret) || users.some(user => !/^ou_[A-Za-z0-9_-]{6,100}$/.test(user)))) return '请核对飞书 App ID、App Secret 和个人 Open ID。';
  return null;
}

export class MessagingApi {
  private authorization: WearingApi;
  constructor(private connection: Connection, private fetcher: typeof fetch = fetch) {this.authorization = new WearingApi(connection, fetcher);}
  private async request(path: string, method = 'GET', body?: unknown) {
    const token = method === 'GET' ? undefined : await this.authorization.voiceAuthorization();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {method, redirect: 'error', signal: controller.signal,
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(token ? {'X-Wearing-Token': token, 'Content-Type': 'application/json'} : {})},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      const data = await response.json();
      if (!response.ok) throw new ApiError(response.status === 401 ? '连接已到期，请重新连接。' : typeof data.detail === 'string' && data.detail.length < 200 ? data.detail : '这次操作没有完成，请稍后重试。', response.status);
      return messagingSnapshot(data);
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('暂时连不上渠道服务，请检查连接后重试。');}
    finally {clearTimeout(timer);}
  }
  list() {return this.request('/api/messaging');}
  configure(provider: MessagingProvider, configuration: MessagingConfiguration) {const error = messagingConfigurationError(provider, configuration); if (error) throw new ApiError(error, 422); return this.request('/api/messaging/' + provider, 'PUT', configuration);}
  enabled(channel: MessagingChannel, enabled: boolean) {return this.request('/api/messaging/' + channel.provider, 'PATCH', {revision: channel.revision, enabled});}
  disconnect(channel: MessagingChannel) {return this.request('/api/messaging/' + channel.provider, 'DELETE', {revision: channel.revision});}
}
