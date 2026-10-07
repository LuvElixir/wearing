import {ApiError, Connection, connectionEndpoint, connectionHeaders, MemorySnapshot} from './core';

export type WorkspaceFile = {path: string; size: number; modified: number};
export type WorkspaceSnapshot = {files: WorkspaceFile[]; truncated: boolean};
export type WorkspaceEntry = {kind: 'folder' | 'file'; name: string; path: string; count: number; file?: WorkspaceFile};
export type HubRuntime = {running: boolean; applied: boolean; provider: string | null; modelReady: boolean; files: boolean; computer: boolean; phone: boolean};
export type HubDevice = {id: string; name: string; kind: 'computer' | 'phone'; online: boolean | null};
export type HubIdentity = {devices: HubDevice[]; cloudAccountsConnected: boolean | null};

/** A missing observation is not an empty collection. Keep that distinction in copy and counts. */
export function memoryCollection(data: MemorySnapshot | null, key: 'user' | 'memory', loading: boolean) {
  const target = data?.available ? data.targets?.[key] : undefined;
  return {state: loading ? 'loading' as const : target ? 'available' as const : 'unavailable' as const,
    entries: target && !loading ? target.entries : null,
    countLabel: loading ? '正在读取' : target ? `${target.entries.length} 条记忆` : '未读取'};
}
export function memoryObservationLabel(data: MemorySnapshot | null): string | null {
  if (!data?.available || !data.observed_at) return null;
  const date = new Date(data.observed_at);
  return Number.isFinite(date.getTime()) ? '读取于 ' + date.toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false}) : null;
}
export function deviceCollectionState(profile: HubIdentity | null, loading: boolean): 'loading' | 'unavailable' | 'empty' | 'available' {
  return loading ? 'loading' : profile === null ? 'unavailable' : profile.devices.length ? 'available' : 'empty';
}

const object = (value: unknown): Record<string, unknown> | null => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
const invalid = () => new ApiError('这次没有读到完整内容，请稍后刷新。', 422);
export function safeWorkspacePath(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= 2048 && !value.startsWith('/') && !/[\\\u0000-\u001f]/.test(value) && value.split('/').every(part => !!part && part !== '.' && part !== '..');
}
export function workspaceSnapshot(value: unknown): WorkspaceSnapshot {
  const data = object(value);
  if (!data || !Array.isArray(data.files) || data.files.length > 200 || typeof data.truncated !== 'boolean') throw invalid();
  const seen = new Set<string>();
  const files = data.files.map(value => {
    const file = object(value);
    if (!file || !safeWorkspacePath(file.path) || seen.has(file.path) || typeof file.size !== 'number' || !Number.isSafeInteger(file.size) || file.size < 0 || typeof file.modified !== 'number' || !Number.isFinite(file.modified) || file.modified < 0) throw invalid();
    seen.add(file.path);
    return {path: file.path, size: file.size, modified: file.modified};
  });
  return {files, truncated: data.truncated};
}
export function workspaceEntries(files: WorkspaceFile[], directory = ''): WorkspaceEntry[] {
  if (directory && !safeWorkspacePath(directory)) return [];
  const prefix = directory ? directory + '/' : '';
  const folders = new Map<string, WorkspaceEntry>();
  const leaves: WorkspaceEntry[] = [];
  for (const file of files) {
    if (!file.path.startsWith(prefix)) continue;
    const relative = file.path.slice(prefix.length), split = relative.indexOf('/');
    if (split >= 0) {
      const name = relative.slice(0, split), path = prefix + name;
      const current = folders.get(path);
      if (current) current.count++;
      else folders.set(path, {kind: 'folder', name, path, count: 1});
    } else leaves.push({kind: 'file', name: relative, path: file.path, count: 1, file});
  }
  return [...folders.values()].sort((a, b) => a.name.localeCompare(b.name)).concat(leaves.sort((a, b) => a.name.localeCompare(b.name)));
}
export function textPreviewAllowed(file: WorkspaceFile): boolean {
  return file.size <= 256 * 1024 && /\.(md|markdown|txt|json|csv|tsv|yaml|yml|log)$/i.test(file.path);
}
export function hubRuntime(value: unknown): HubRuntime {
  const data = object(value), product = object(data?.product), model = object(data?.model);
  if (!data || typeof data.running !== 'boolean' || typeof product?.applied !== 'boolean' || !model || typeof model.state !== 'string' ||
    !['files', 'phone', 'computer'].every(key => typeof object(data[key])?.active === 'boolean')) throw invalid();
  return {running: data.running, applied: product.applied,
    provider: typeof model?.provider === 'string' ? model.provider : null, modelReady: model?.state === 'configured',
    files: object(data.files)?.active === true, computer: object(data.computer)?.active === true, phone: object(data.phone)?.active === true};
}
export function hubIdentity(value: unknown): HubIdentity {
  const data = object(value);
  if (!data || !Array.isArray(data.devices)) throw invalid();
  const devices = data.devices.map(value => {
    const device = object(value);
    if (!device || typeof device.id !== 'string' || typeof device.name !== 'string' || !['phone', 'computer'].includes(String(device.kind))) throw invalid();
    return {id: device.id, name: device.name, kind: device.kind as HubDevice['kind'], online: typeof device.online === 'boolean' ? device.online : null};
  });
  return {devices, cloudAccountsConnected: data.accounts === 'connected' ? true : data.accounts === 'not_connected' ? false : null};
}

/** This surface is deliberately read-only. Credentials stay in request headers. */
export class PersonalHubApi {
  constructor(private connection: Connection, private fetcher: typeof fetch = fetch) {}
  private async read(path: string): Promise<Response> {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity},
        signal: controller.signal, redirect: 'error',
      });
      if (!response.ok) throw new ApiError(response.status === 401 ? '连接已到期，请重新连接后查看。' : '暂时无法读取，请稍后再试。', response.status);
      return response;
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('暂时连不上，请检查连接后重试。');}
    finally {clearTimeout(timer);}
  }
  async workspace(): Promise<WorkspaceSnapshot> {return workspaceSnapshot(await (await this.read('/api/workspace')).json());}
  async runtime(): Promise<HubRuntime> {return hubRuntime(await (await this.read('/api/runtime')).json());}
  async identity(): Promise<HubIdentity> {return hubIdentity(await (await this.read('/api/identity')).json());}
  async textFile(file: WorkspaceFile): Promise<string> {
    if (!safeWorkspacePath(file.path) || !textPreviewAllowed(file)) throw new ApiError('这份文件请到文件页打开。', 422);
    const response = await this.read('/api/workspace/file?' + new URLSearchParams({path: file.path}));
    const length = response.headers.get('content-length');
    if (length && (!Number.isSafeInteger(Number(length)) || Number(length) > 256 * 1024)) throw new ApiError('文件较大，请到文件页打开。', 413);
    const text = await response.text();
    if (text.length > 256 * 1024 || text.includes('\u0000')) throw new ApiError('这份文件无法直接预览，请到文件页打开。', 422);
    return text;
  }
}
