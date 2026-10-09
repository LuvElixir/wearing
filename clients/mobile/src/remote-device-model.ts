import {ApiError, Connection, connectionEndpoint, connectionHeaders} from './core';
import {accountWorkAllowed} from './account-work';

type Dict = Record<string, unknown>;
const object = (v: unknown): v is Dict => !!v && typeof v === 'object' && !Array.isArray(v);
const integer = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;
export const deviceIdentifier = (v: unknown): v is string => typeof v === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(v);
const invalid = () => new ApiError('设备接管信息不完整，请重新检查连接。', 422);
export type IceServer = {urls: string[]; username?: string; credential?: string};
export type RemoteAccessState = 'unavailable' | 'agent_ready' | 'handoff_pending' | 'human_private' | 'return_pending' | 'paused';
export type RemoteAccess = {
  resource_id: string; supported: boolean; state: RemoteAccessState; control_generation: number;
  session_id: string | null; epoch: number; gateway_epoch: number | null; device_confirmed: boolean;
  expires_at: number | null;
};
export type RemoteAnswer = {type: 'answer'; sdp: string; gateway_epoch: number};
export type RemoteTransport = {kind: 'webrtc'; session_id: string; epoch: number; gateway_epoch: number; ice_servers: IceServer[]};

function iceServers(value: unknown): IceServer[] {
  if (!Array.isArray(value) || value.length > 8) throw invalid();
  return value.map(item => {
    if (!object(item) || !Array.isArray(item.urls) || !item.urls.length || item.urls.length > 8 ||
      !item.urls.every(u => typeof u === 'string' && /^(stun|stuns|turn|turns):[^\s<>]{1,500}$/.test(u)) ||
      item.username !== undefined && (typeof item.username !== 'string' || item.username.length > 512) ||
      item.credential !== undefined && (typeof item.credential !== 'string' || item.credential.length > 1024)) throw invalid();
    return {urls: item.urls as string[], ...(typeof item.username === 'string' ? {username: item.username} : {}), ...(typeof item.credential === 'string' ? {credential: item.credential} : {})};
  });
}
export function parseRemoteAccess(value: unknown, resource: string): RemoteAccess {
  if (!deviceIdentifier(resource) || !object(value) || typeof value.supported !== 'boolean') throw invalid();
  if (!value.supported) return {resource_id: resource, supported: false, state: 'unavailable', control_generation: 0, session_id: null, epoch: 0, gateway_epoch: null, device_confirmed: false, expires_at: null};
  if (value.resource_id !== resource || !['agent_ready', 'handoff_pending', 'human_private', 'return_pending', 'paused'].includes(String(value.state)) ||
    !integer(value.control_generation) || !integer(value.epoch) || value.session_id !== null && !deviceIdentifier(value.session_id) ||
    value.gateway_epoch !== null && !integer(value.gateway_epoch) || typeof value.device_confirmed !== 'boolean' ||
    value.expires_at !== null && (typeof value.expires_at !== 'number' || !Number.isFinite(value.expires_at) || value.expires_at <= 0)) throw invalid();
  if (['human_private', 'handoff_pending', 'return_pending'].includes(String(value.state)) && (!value.session_id || !value.epoch || !value.expires_at)) throw invalid();
  return {resource_id: resource, supported: true, state: value.state as RemoteAccessState, control_generation: value.control_generation,
    session_id: value.session_id as string | null, epoch: value.epoch, gateway_epoch: value.gateway_epoch as number | null,
    device_confirmed: value.device_confirmed, expires_at: value.expires_at as number | null};
}
export function canStream(access: RemoteAccess, now = Date.now()): boolean {
  return access.supported && access.state === 'human_private' && access.device_confirmed && !!access.session_id && access.epoch > 0 &&
    access.gateway_epoch !== null && access.expires_at !== null && access.expires_at * 1000 > now;
}
export function remoteStatusCopy(access: RemoteAccess | null): string {
  if (!access) return '正在检查设备';
  return {unavailable: '远程接管尚未开放', agent_ready: '尚未接管', handoff_pending: '等待设备确认接管', human_private: '由你接管', return_pending: '等待设备确认交还', paused: '设备保持暂停'}[access.state];
}

/** Never retries a control mutation, SDP offer, or sensitive input automatically. */
export class RemoteDeviceApi {
  private csrf = '';
  private readonly connection: Connection;
  constructor(connection: Connection, private readonly fetcher: typeof fetch = fetch, private usable: () => boolean = () => true) {
    this.connection = {...connection, ...(connection.session ? {session: {...connection.session}} : {}), ...(connection.development ? {development: {...connection.development}} : {})};
  }
  setUsable(usable: () => boolean) {this.usable = usable;}
  private async request(path: string, body?: unknown, closing = false): Promise<unknown> {
    const check = () => {if (!closing && (!this.usable() || !accountWorkAllowed(this.connection))) throw new ApiError('账户或页面已切换，请重新打开设备。', 409);};
    check();
    if (body !== undefined && !this.csrf) {
      const bootstrap = await this.request('/api/bootstrap', undefined, closing);
      if (!object(bootstrap) || typeof bootstrap.token !== 'string' || !bootstrap.token || !Array.isArray(bootstrap.identities) || !bootstrap.identities.some(i => object(i) && i.id === this.connection.identity)) throw invalid();
      this.csrf = bootstrap.token;
    }
    check();
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 20000);
    try {
      const endpoint = connectionEndpoint(this.connection);
      const response = await this.fetcher(new URL(path, endpoint).toString(), {method: body === undefined ? 'GET' : 'POST', signal: abort.signal, redirect: 'error',
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity,
          ...(body === undefined ? {} : {'Content-Type': 'application/json', 'X-Wearing-Token': this.csrf, Origin: new URL(endpoint).origin})},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      const value: unknown = await response.json().catch(() => {throw invalid();});
      if (!response.ok) {
        if (response.status === 403) this.csrf = '';
        throw new ApiError(object(value) && typeof value.detail === 'string' ? value.detail : '设备没有确认这次操作，请检查状态后再试。', response.status);
      }
      return value;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError('设备连接中断。本次操作不会自动重发，请重新连接后查看实际状态。');
    } finally {clearTimeout(timer);}
  }
  private path(resource: string, suffix = ''): string {if (!deviceIdentifier(resource)) throw invalid(); return `/api/devices/access/${resource}${suffix}`;}
  async status(resource: string): Promise<RemoteAccess> {return parseRemoteAccess(await this.request(this.path(resource)), resource);}
  async begin(previous: RemoteAccess, request_id: string): Promise<RemoteAccess> {
    if (!previous.supported || !integer(previous.control_generation) || !/^[a-f0-9]{32}$/.test(request_id)) throw invalid();
    return parseRemoteAccess(await this.request(this.path(previous.resource_id, '/request'), {expected_generation: previous.control_generation, request_id}), previous.resource_id);
  }
  private session(access: RemoteAccess) {if (!deviceIdentifier(access.session_id) || !integer(access.epoch) || !access.epoch) throw invalid(); return {session_id: access.session_id, epoch: access.epoch};}
  async close(access: RemoteAccess): Promise<RemoteAccess> {return parseRemoteAccess(await this.request(this.path(access.resource_id, '/close'), this.session(access), true), access.resource_id);}
  async transport(access: RemoteAccess): Promise<RemoteTransport> {
    if (!canStream(access)) throw invalid();
    const value = await this.request(this.path(access.resource_id, '/transport'));
    if (!object(value) || value.kind !== 'webrtc' || value.session_id !== access.session_id || value.epoch !== access.epoch || value.gateway_epoch !== access.gateway_epoch) throw invalid();
    return {kind: 'webrtc', ...this.session(access), gateway_epoch: access.gateway_epoch!, ice_servers: iceServers(value.ice_servers)};
  }
  async giveBack(access: RemoteAccess, safeScreen: boolean, scopeConfirmed: boolean): Promise<RemoteAccess> {
    if (!canStream(access) || safeScreen !== true || scopeConfirmed !== true) throw new ApiError('请先退出登录验证页面，再确认交还设备。', 409);
    return parseRemoteAccess(await this.request(this.path(access.resource_id, '/return'), {...this.session(access), safe_screen_confirmed: true, scope_confirmed: true}), access.resource_id);
  }
  async offer(access: RemoteAccess, sdp: string): Promise<RemoteAnswer> {
    if (!canStream(access) || typeof sdp !== 'string' || !sdp.startsWith('v=0') || sdp.length > 65536) throw invalid();
    const value = await this.request(this.path(access.resource_id, '/offer'), {...this.session(access), type: 'offer', sdp});
    if (!object(value) || value.type !== 'answer' || typeof value.sdp !== 'string' || !value.sdp.startsWith('v=0') || value.sdp.length > 65536 || value.gateway_epoch !== access.gateway_epoch) throw invalid();
    return {type: 'answer', sdp: value.sdp, gateway_epoch: value.gateway_epoch as number};
  }
}

/** Reject black bars and zero-sized/invalid frames rather than clicking somewhere else. */
export function remotePoint(x: number, y: number, boxWidth: number, boxHeight: number, frameWidth: number, frameHeight: number): {x: number; y: number} | null {
  if (![x, y, boxWidth, boxHeight, frameWidth, frameHeight].every(Number.isFinite) || [boxWidth, boxHeight, frameWidth, frameHeight].some(v => v <= 0)) return null;
  const scale = Math.min(boxWidth / frameWidth, boxHeight / frameHeight), width = frameWidth * scale, height = frameHeight * scale;
  const left = (boxWidth - width) / 2, top = (boxHeight - height) / 2;
  if (x < left || x >= left + width || y < top || y >= top + height) return null;
  return {x: Math.floor((x - left) / scale), y: Math.floor((y - top) / scale)};
}
