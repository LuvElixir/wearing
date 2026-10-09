import {ApiError, connectionEndpoint, connectionHeaders, type Connection} from './core';
import {matchNativeRequest, nativeDevice, nativeOutcome, nativeRequest, object, sameNativeValue, type NativeCredential, type NativeDevice, type NativeMethod, type NativeOutcome, type NativePolicy, type NativeRequest} from './native-action-model';

export class NativeActionClient {
  private token = '';
  readonly connection: Connection;
  constructor(connection: Connection, readonly credential: NativeCredential, private readonly fetcher: typeof fetch = fetch) {this.connection = JSON.parse(JSON.stringify(connection));}
  private async request(path: string, body?: unknown, retry = true): Promise<unknown> {
    if (body && !this.token) await this.bootstrap();
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {method: body ? 'POST' : 'GET', redirect: 'error', signal: controller.signal,
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity':this.connection.identity, ...(body ? {'Content-Type':'application/json', 'X-Wearing-Token':this.token} : {})}, ...(body ? {body:JSON.stringify(body)} : {})});
      if (response.status === 403 && body && retry) {await this.bootstrap(); return this.request(path, body, false);}
      const value: unknown = await response.json();
      if (!response.ok) throw new ApiError(object(value) && typeof value.detail === 'string' ? value.detail : '手机请求未完成，请重新检查连接。', response.status);
      return value;
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('尚未收到手机能力服务的回执，请检查连接。');}
    finally {clearTimeout(timer);}
  }
  private async bootstrap() {
    const v = await this.request('/api/bootstrap');
    if (!object(v) || typeof v.token !== 'string' || !v.token || !Array.isArray(v.identities) || !v.identities.some(i => object(i) && i.id === this.connection.identity)) throw new ApiError('手机连接未能核对当前身份。', 422);
    this.token = v.token;
  }
  private phone(connection?: string) {return {...this.credential, ...(connection ? {connection_id:connection} : {})};}
  private parse(v: unknown) {return nativeRequest(v, this.connection.identity, this.credential.installation_id);}
  async device(): Promise<NativeDevice | null> {
    const v = await this.request('/api/native-actions/devices');
    if (!object(v) || !Array.isArray(v.items)) throw new ApiError('手机设置回执不完整。', 422);
    const all = v.items.map(i => nativeDevice(i, this.connection.identity));
    return all.find(d => d.installation_id === this.credential.installation_id) || null;
  }
  async configure(revision: number, enabled: boolean, policy: NativePolicy) {
    const value = nativeDevice(await this.request('/api/native-actions/configure', {...this.phone(), revision, enabled, policy}), this.connection.identity);
    if (value.installation_id !== this.credential.installation_id || value.revision !== revision + 1 || value.enabled !== enabled || !sameNativeValue(value.policy,policy)) throw new ApiError('手机设置保存回执无法核对。', 422);
    return value;
  }
  async connect(device: NativeDevice, connection: string, capabilities: NativeMethod[]) {
    const v = await this.request('/api/native-actions/connect', {...this.phone(connection), revision:device.revision, capabilities});
    const parsed = nativeDevice(v, this.connection.identity);
    if (!object(v) || v.connection_id !== connection || parsed.installation_id !== device.installation_id || parsed.revision !== device.revision || parsed.server_id !== device.server_id || !parsed.enabled || !parsed.online || !sameNativeValue(parsed.policy,device.policy) || !sameNativeValue([...parsed.capabilities].sort(),[...capabilities].sort())) throw new ApiError('手机前台会话无法核对。', 422);
    return parsed;
  }
  async poll(connection: string): Promise<NativeRequest[]> {
    const v = await this.request('/api/native-actions/poll', this.phone(connection));
    if (!object(v) || !Array.isArray(v.items) || v.items.length > 1) throw new ApiError('手机请求列表无法核对。', 422);
    return v.items.map(i => this.parse(i));
  }
  async claim(r: NativeRequest, approve: boolean) {
    const value = matchNativeRequest(this.parse(await this.request('/api/native-actions/claim', {...this.phone(r.command.connection_id),command_id:r.id,fingerprint:r.fingerprint,approve})),r);
    if (value.state !== (approve ? 'executing' : 'cancelled')) throw new ApiError('手机执行许可与原请求不匹配。',422);
    return value;
  }
  async finish(r: NativeRequest, outcome: NativeOutcome) {
    nativeOutcome(outcome);
    const value = matchNativeRequest(this.parse(await this.request('/api/native-actions/result', {...this.phone(r.command.connection_id),command_id:r.id,fingerprint:r.fingerprint,outcome})),r);
    if (value.state !== outcome.status || !sameNativeValue(value.result,outcome)) throw new ApiError('手机原始回执尚未核对保存，请稍后重试。',422);
    return value;
  }
  async disconnect(connection: string) {await this.request('/api/native-actions/disconnect', this.phone(connection));}
  async history(): Promise<NativeRequest[]> {
    const v = await this.request('/api/native-actions/history', this.phone());
    if (!object(v) || !Array.isArray(v.items) || v.items.length > 30) throw new ApiError('手机请求历史无法核对。', 422);
    return v.items.map(i => this.parse(i));
  }
  async review(r: NativeRequest) {
    const value = matchNativeRequest(this.parse(await this.request('/api/native-actions/review', {...this.phone(), command_id:r.id})),r);
    if (value.state !== 'unknown' || !value.reviewed) throw new ApiError('核对标记尚未保存，请重试。',422);
    return value;
  }
}
