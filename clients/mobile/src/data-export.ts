import {ApiError, Connection, connectionEndpoint, connectionHeaders} from './core';
export const EXPORT_LIMIT = 15 * 1024 * 1024;
export type DataExport = {id: string; identity_id: string; created_at: number; expires_at: number; size: number; sha256: string; counts: Record<string, number>; omitted: {section: string; path?: string; reason: string}[]; workspace_count: number; filename: string};
function object(value: unknown): value is Record<string, unknown> {return !!value && typeof value === 'object' && !Array.isArray(value);}
export function dataExport(value: unknown, identity: string): DataExport {
  const invalid = () => new ApiError('导出内容暂时无法核对，请重新生成。', 422);
  if (!object(value) || !/^[0-9a-f]{32}$/.test(String(value.id)) || value.identity_id !== identity || !/^[0-9a-f]{64}$/.test(String(value.sha256)) || !/^pajio-data-[0-9a-f]{8}\.zip$/.test(String(value.filename)) || typeof value.created_at !== 'number' || !Number.isFinite(value.created_at) || typeof value.expires_at !== 'number' || !Number.isFinite(value.expires_at) || value.expires_at <= value.created_at || !Number.isSafeInteger(value.size) || (value.size as number) <= 0 || (value.size as number) > EXPORT_LIMIT || !object(value.counts) || !Number.isSafeInteger(value.workspace_count) || (value.workspace_count as number) < 0 || !Array.isArray(value.omitted)) throw invalid();
  if (Object.values(value.counts).some(count => !Number.isSafeInteger(count) || (count as number) < 0) || value.omitted.some(row => !object(row) || typeof row.section !== 'string' || typeof row.reason !== 'string' || (row.path !== undefined && typeof row.path !== 'string'))) throw invalid();
  return value as DataExport;
}
export class DataExportApi {
  constructor(readonly connection: Connection, private fetcher: typeof fetch = fetch) {}
  private async call<T>(path: string, consume: (response: Response) => Promise<T>, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {...init, signal: controller.signal, redirect: 'error', headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...init.headers}});
      if (!response.ok) {const error = await response.json().catch(() => null); throw new ApiError(response.status === 401 ? '连接已失效，请重新连接后导出。' : typeof error?.detail === 'string' ? error.detail : '这次导出没有完成，请重试。', response.status);}
      return await consume(response);
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('暂时连不上服务，请检查连接后重试。');}
    finally {clearTimeout(timer);}
  }
  async latest(): Promise<DataExport | null> {
    return this.call('/api/data-exports', async response => {
      const value = await response.json();
      if (!object(value) || !Array.isArray(value.exports) || value.exports.length > 3) throw new ApiError('导出清单暂时无法读取。', 422);
      const rows = value.exports.map(row => dataExport(row, this.connection.identity));
      return rows.sort((a, b) => b.created_at - a.created_at)[0] || null;
    });
  }
  async create(requestKey: string): Promise<DataExport> {
    const bootstrap = await this.call('/api/bootstrap', response => response.json());
    if (bootstrap.version !== '0.2.0' || typeof bootstrap.token !== 'string' || !Array.isArray(bootstrap.identities) || !bootstrap.identities.some((row: {id?: string}) => row.id === this.connection.identity)) throw new ApiError('请重新连接当前身份后导出。', 422);
    return this.call('/api/data-exports', async response => dataExport(await response.json(), this.connection.identity), {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Wearing-Token': bootstrap.token}, body: JSON.stringify({request_key: requestKey})});
  }
  async bytes(item: DataExport): Promise<Uint8Array> {
    dataExport(item, this.connection.identity);
    return this.call('/api/data-exports/' + item.id + '/file', async response => {
      const length = Number(response.headers.get('content-length'));
      if (!Number.isSafeInteger(length) || length !== item.size || length > EXPORT_LIMIT || !response.headers.get('content-type')?.startsWith('application/zip')) throw new ApiError('导出文件大小或格式不一致，请重新生成。', 422);
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.byteLength !== item.size || bytes.byteLength > EXPORT_LIMIT) throw new ApiError('导出文件未完整下载，请重试。', 422);
      return bytes;
    });
  }
}
/** Keep the same receipt after sharing fails; an explicit regenerate uses a new key. */
export async function handoffDataExport(api: DataExportApi, item: DataExport, active: () => boolean, verify: (bytes: Uint8Array) => Promise<string>, share: (bytes: Uint8Array) => Promise<void>): Promise<boolean> {
  const bytes = await api.bytes(item);
  if (!active()) return false;
  if (await verify(bytes) !== item.sha256) throw new ApiError('导出文件校验未通过，请重新生成。', 422);
  if (!active()) return false;
  await share(bytes);
  return active();
}
