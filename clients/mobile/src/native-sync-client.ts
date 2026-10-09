import {ApiError, connectionEndpoint, connectionHeaders, type Connection} from './core';
import {syncReceipt, syncSettings, type SyncBatch, type SyncSettings, type SyncState} from './native-sync-model';
import {calendarSourceIndex} from './calendar-sources';

export class NativeSyncClient {
  private token = '';
  constructor(private connection: Connection, readonly installation: string, private fetcher: typeof fetch, private active: () => boolean, private signal?: AbortSignal) {}
  private async request(path: string, body?: unknown, retry = true): Promise<unknown> {
    if (!this.active()) throw new Error('同步已停止。');
    if (body && !this.token) await this.bootstrap();
    if (!this.active()) throw new Error('同步已停止。');
    const controller = new AbortController(), cancel = () => controller.abort(), timer = setTimeout(cancel, 15000);
    this.signal?.addEventListener('abort', cancel);
    if (this.signal?.aborted) cancel();
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {method: body ? 'POST' : 'GET', signal: controller.signal, redirect: 'error',
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity':this.connection.identity, ...(body ? {'Content-Type':'application/json','X-Wearing-Token':this.token} : {})}, ...(body ? {body:JSON.stringify(body)} : {})});
      if (!this.active()) throw new Error('同步已停止。');
      if (response.status === 403 && body && retry) {await this.bootstrap(); return this.request(path, body, false);}
      const data = await response.json();
      if (!this.active()) throw new Error('同步已停止。');
      if (!response.ok) throw new ApiError(typeof data?.detail === 'string' ? data.detail : '同步未完成，请稍后重试。', response.status);
      return data;
    } finally {clearTimeout(timer); this.signal?.removeEventListener('abort', cancel);}
  }
  private async bootstrap() {
    const v = await this.request('/api/bootstrap') as {token?: string; identities?: {id:string}[]};
    if (!v?.token || !v.identities?.some(i => i.id === this.connection.identity)) throw new Error('同步连接无法核对当前身份。');
    this.token = v.token;
  }
  async state(): Promise<SyncState> {
    const v = await this.request('/api/native-sync/state', {installation:this.installation}) as SyncState;
    const settings = syncSettings(v);
    if (!Array.isArray(v.records) || !v.records.every(r => r && /^life_[a-f0-9]{32}$/.test(r.record_id) && ['event','reminder'].includes(r.source_kind) && typeof r.source_id === 'string' && ['synced','conflict','unseen'].includes(r.state) && Number.isFinite(Date.parse(r.observed_at)))) throw new Error('同步来源状态不完整。');
    return {...settings, records:v.records};
  }
  async configure(value: SyncSettings & {request_id:string}) {
    const result = syncSettings(await this.request('/api/native-sync/configure', {...value, installation:this.installation}));
    if (result.revision !== value.revision + 1 || result.enabled !== value.enabled || JSON.stringify(result.sources) !== JSON.stringify(value.sources)) throw new Error('来源选择回执不匹配。');
    return result;
  }
  async upload(value: SyncBatch) {return syncReceipt(await this.request('/api/native-sync/upload', {...value, installation:this.installation}), value);}
  async index() {return calendarSourceIndex(await this.request('/api/native-sync/index', {}));}
}
