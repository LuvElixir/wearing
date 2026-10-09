import {ApiError, Connection, connectionEndpoint, connectionHeaders, MemorySnapshot} from './core';

export type WorkspaceFile = {path: string; size: number; modified: number};
export type WorkspaceSnapshot = {files: WorkspaceFile[]; truncated: boolean};
export type WorkspacePage = WorkspaceSnapshot & {complete: boolean; scan_id: string; page_cursor: string; next_cursor: string | null; directory: string; query: string; scanned: number; phase: 'complete' | 'checking' | 'scanning'};
export type WorkspaceQuery = {directory?: string; query?: string; cursor?: string};
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
/** Prepare an editable request only. The original memory is never changed here. */
export function memoryCorrectionDraft(key: 'user' | 'memory', entry?: string): string {
  const section = key === 'user' ? '关于你' : '长期记忆';
  if (!entry?.trim()) return `我想补充「${section}」里的记忆：\n`;
  const limit = 9000;
  const source = entry.length > limit ? entry.slice(0, limit) + '\n[原记忆较长，以上为节选]' : entry;
  return `我想纠正「${section}」里的这条记忆。\n\n原记忆：\n${source}\n\n应改为：\n`;
}
/** A removal is a user-reviewed request, never a pretend local deletion. */
export function memoryRemovalDraft(key: 'user' | 'memory', entry: string): string {
  const section = key === 'user' ? '关于你' : '长期记忆';
  const source = entry.length > 9000 ? entry.slice(0, 9000) + '\n[以上为节选，请先核对完整条目]' : entry;
  return `请从「${section}」里删除下面这条记忆，仅删除这一条，并告诉我实际处理结果：\n\n${source}`;
}
export type HubHelpTopic = 'apps' | 'skills' | 'messaging' | 'devices';
export function hubHelpDraft(topic: HubHelpTopic, device?: HubDevice): string {
  if (topic === 'devices' && device) return `请检查执行设备「${device.name}」（设备标识：${device.id}）的当前连接、可用能力和权限。如果无法读取，请说明缺少哪一步，以及我应该在哪里完成。先检查状态，不要执行设备上的其他操作。`;
  const prompts: Record<HubHelpTopic, string> = {
    apps: '我想连接一个常用应用。请先列出当前确实可接入的应用及授权方式，区分已经连接、需要我授权和暂不支持的情况。不要把已安装的工具当成已经授权的账号。',
    skills: '请查看当前身份实际可用的技能和工具，用名称、能做什么、使用条件整理给我。如果有技能文件，附上它在文件空间里的位置；无法读取的部分请明确说明。先查看，不安装或修改技能。',
    messaging: '我想从常用聊天工具与 Pajio 对话。请检查当前服务支持哪些聊天渠道，说明各自如何连接、需要我完成哪些授权。未提供的连接入口请明确说明，先不要发送任何外部消息。',
    devices: '我想连接一台执行设备。请先检查当前服务可支持的电脑和手机类型，以及实际接入方式，告诉我下一步在哪台设备上做什么。',
  };
  return prompts[topic];
}
export function workspaceFileDraft(path: string): string {
  if (!safeWorkspacePath(path)) throw invalid();
  return `请读取当前身份文件空间里的「${path}」，概括内容并告诉我值得关注的地方。若文件不存在或无法读取，请直接说明。`;
}
export function workspaceSearch(files: WorkspaceFile[], directory: string, query: string): WorkspaceEntry[] {
  if (directory && !safeWorkspacePath(directory)) return [];
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return workspaceEntries(files, directory);
  const prefix = directory ? directory + '/' : '';
  return files.filter(file => file.path.startsWith(prefix) && file.path.toLocaleLowerCase().includes(needle))
    .sort((a, b) => a.path.localeCompare(b.path))
    .map(file => ({kind: 'file', name: file.path.slice(prefix.length), path: file.path, count: 1, file}));
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
const validCursor = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{43}$/.test(value);
export function workspacePage(value: unknown, request: WorkspaceQuery = {}): WorkspacePage {
  const data = object(value), snapshot = workspaceSnapshot(value);
  const directory = request.directory || '', query = (request.query || '').trim();
  if (!data || data.directory !== directory || data.query !== query || typeof data.scan_id !== 'string' || !/^[a-f0-9]{32}$/.test(data.scan_id) ||
    !validCursor(data.page_cursor) || (request.cursor !== undefined && data.page_cursor !== request.cursor) ||
    typeof data.complete !== 'boolean' || data.complete === snapshot.truncated ||
    (data.complete ? data.next_cursor !== null || data.phase !== 'complete' : !validCursor(data.next_cursor) || !['checking', 'scanning'].includes(String(data.phase))) ||
    typeof data.scanned !== 'number' || !Number.isSafeInteger(data.scanned) || data.scanned < snapshot.files.length ||
    snapshot.files.some(file => directory && !file.path.startsWith(directory + '/'))) throw invalid();
  return {...snapshot, complete: data.complete, scan_id: data.scan_id, page_cursor: data.page_cursor, next_cursor: data.next_cursor as string | null,
    directory, query, scanned: data.scanned, phase: data.phase as WorkspacePage['phase']};
}
export function mergeWorkspacePages(previous: WorkspacePage, next: WorkspacePage): WorkspacePage {
  if (!previous.next_cursor || next.page_cursor !== previous.next_cursor || next.scan_id !== previous.scan_id || next.directory !== previous.directory || next.query !== previous.query || next.scanned < previous.scanned) throw invalid();
  const seen = new Set(previous.files.map(file => file.path));
  if (next.files.some(file => seen.has(file.path))) throw invalid();
  return {...next, files: [...previous.files, ...next.files]};
}
export function workspaceProgress(page: WorkspacePage): string {
  return page.complete ? `已找到 ${page.files.length} 份文件` : `已检查 ${page.scanned} 项，找到 ${page.files.length} 份文件；还没有查完。`;
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
export const WORKSPACE_ORIGINAL_LIMIT = 20 * 1024 * 1024;
export function workspaceMimeType(path: string): string {
  const extension = path.split('.').pop()?.toLowerCase() || '';
  const types: Record<string, string> = {pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif', txt: 'text/plain', md: 'text/plain', markdown: 'text/plain', csv: 'text/csv', json: 'application/json', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', mp3: 'audio/mpeg', mp4: 'video/mp4'};
  return types[extension] || 'application/octet-stream';
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
  private connection: Connection;
  constructor(connection: Connection, private fetcher: typeof fetch = fetch) {
    this.connection = {...connection, session: connection.session && {...connection.session}, development: connection.development && {...connection.development}};
  }
  private async read<T>(path: string, consume: (response: Response) => Promise<T>, signal?: AbortSignal): Promise<T> {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    const cancel = () => controller.abort();
    signal?.addEventListener('abort', cancel);
    if (signal?.aborted) controller.abort();
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {
        headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity},
        signal: controller.signal, redirect: 'error',
      });
      if (!response.ok) throw new ApiError(response.status === 401 ? '连接已到期，请重新连接后查看。' : response.status === 404 ? '文件已移动或不存在，请刷新列表。' : response.status === 403 ? '当前身份没有读取权限，请检查连接与身份。' : response.status === 409 ? '文件列表已变化或过期，请重新读取。' : response.status === 413 ? '文件夹层级或数量较多，请缩小查找范围后重试。' : '暂时无法读取，请稍后再试。', response.status);
      // Keep timeout and credentials boundary active until the body has finished.
      return await consume(response);
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('暂时连不上，请检查连接后重试。');}
    finally {clearTimeout(timer); signal?.removeEventListener('abort', cancel);}
  }
  async workspace(): Promise<WorkspaceSnapshot> {return this.read('/api/workspace', async response => workspaceSnapshot(await response.json()));}
  async workspacePage(request: WorkspaceQuery = {}, signal?: AbortSignal): Promise<WorkspacePage> {
    const directory = request.directory || '', query = (request.query || '').trim();
    if (directory && !safeWorkspacePath(directory) || query.length > 200 || /[\u0000-\u001f]/.test(query) || request.cursor !== undefined && !validCursor(request.cursor)) throw invalid();
    return this.read('/api/workspace/page?' + new URLSearchParams({directory, query, ...(request.cursor ? {cursor: request.cursor} : {})}), async response => workspacePage(await response.json(), request), signal);
  }
  async workspaceMetadata(path: string, signal?: AbortSignal): Promise<WorkspaceFile> {
    if (!safeWorkspacePath(path)) throw invalid();
    return this.read('/api/workspace/metadata?' + new URLSearchParams({path}), async response => {
      const file = workspaceSnapshot({files: [await response.json()], truncated: false}).files[0];
      if (file.path !== path) throw invalid();
      return file;
    }, signal);
  }
  async runtime(): Promise<HubRuntime> {return this.read('/api/runtime', async response => hubRuntime(await response.json()));}
  async identity(): Promise<HubIdentity> {return this.read('/api/identity', async response => hubIdentity(await response.json()));}
  async textFile(file: WorkspaceFile): Promise<string> {
    if (!safeWorkspacePath(file.path) || !textPreviewAllowed(file)) throw new ApiError('这份文件请到文件页打开。', 422);
    return this.read('/api/workspace/file?' + new URLSearchParams({path: file.path}), async response => {
      const length = response.headers.get('content-length');
      if (length && (!Number.isSafeInteger(Number(length)) || Number(length) > 256 * 1024)) throw new ApiError('文件较大，请打开原件查看。', 413);
      const text = await response.text();
      if (text.length > 256 * 1024 || text.includes('\u0000')) throw new ApiError('这份文件无法直接预览，请打开原件查看。', 422);
      return text;
    });
  }
  async original(file: WorkspaceFile): Promise<Uint8Array> {
    if (!safeWorkspacePath(file.path)) throw new ApiError('这份文件路径无效，请刷新列表。', 422);
    if (!Number.isSafeInteger(file.size) || file.size < 0 || file.size > WORKSPACE_ORIGINAL_LIMIT) throw new ApiError('这份文件超过 20 MB，请在电脑上打开。', 413);
    return this.read('/api/workspace/file?' + new URLSearchParams({path: file.path}), async response => {
      const length = response.headers.get('content-length');
      if (length && (!Number.isSafeInteger(Number(length)) || Number(length) < 0 || Number(length) > WORKSPACE_ORIGINAL_LIMIT)) throw new ApiError('这份文件超过 20 MB，请在电脑上打开。', 413);
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.byteLength > WORKSPACE_ORIGINAL_LIMIT) throw new ApiError('这份文件超过 20 MB，请在电脑上打开。', 413);
      return bytes;
    });
  }
}
