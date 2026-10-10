import {ApiError, type Connection, type Store, connectionEndpoint, connectionHeaders, scopeOf} from './core';
import {accountWorkAllowed} from './account-work';
import {safeWorkspacePath, type WorkspaceFile} from './personal-hub';

export const DEVICE_FILE_LIMIT = 20 * 1024 * 1024;
export type DeviceFile = {file_id: string; name: string; size: number; sha256: string};
export type TransferDirection = 'to_device' | 'from_device' | 'list';
export type DeviceTransferRequest = {request_id: string; direction: TransferDirection; source?: DeviceFile};
export type DeviceTransfer = DeviceTransferRequest & {resource_id: string; state: 'queued' | 'executing' | 'completed' | 'failed' | 'unknown';
  bytes_completed: number; files?: DeviceFile[]; truncated?: boolean; workspace_file?: WorkspaceFile; error?: string};
export type DeviceFilesCapability = {supported: boolean; available: boolean; reason: string | null; max_bytes: number; inbox_label: string; outbox_label: string};
export type DeviceTransferStore = Pick<Store, 'get' | 'put'> & {
  clearIfSame: (key: string, expected: DeviceTransferRequest, active: () => boolean) => Promise<boolean>;
};
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const id = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v);
const resourceId = (v: unknown): v is string => typeof v === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(v);
const code = (v: unknown): v is string => typeof v === 'string' && /^[a-z][a-z0-9_]{0,95}$/.test(v);
const integer = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 0;
const invalid = () => new ApiError('文件回执不完整，请重新核对原请求。', 0);
export function parseDeviceFile(v: unknown): DeviceFile {
  if (!object(v) || !id(v.file_id) || typeof v.name !== 'string' || !v.name || v.name.trim() !== v.name || v.name.normalize('NFC') !== v.name ||
    new TextEncoder().encode(v.name).length > 180 || v.name.startsWith('.') || /[\\/\u0000-\u001f\u007f]/.test(v.name) ||
    !integer(v.size) || !v.size || v.size > DEVICE_FILE_LIMIT ||
    typeof v.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(v.sha256)) throw invalid();
  return {file_id: v.file_id, name: v.name, size: v.size, sha256: v.sha256};
}
export function parseTransferRequest(v: unknown): DeviceTransferRequest {
  if (!object(v) || !id(v.request_id) || !['to_device', 'from_device', 'list'].includes(String(v.direction))) throw invalid();
  if (v.direction === 'list') {if (v.source !== undefined) throw invalid(); return {request_id: v.request_id, direction: 'list'};}
  return {request_id: v.request_id, direction: v.direction as TransferDirection, source: parseDeviceFile(v.source)};
}
function sameFile(a: DeviceFile | undefined, b: DeviceFile | undefined) {
  return a?.file_id === b?.file_id && a?.name === b?.name && a?.size === b?.size && a?.sha256 === b?.sha256;
}
export function parseDeviceTransfer(v: unknown, resource: string, expected?: DeviceTransferRequest): DeviceTransfer {
  const request = parseTransferRequest(v);
  if (!object(v) || !resourceId(resource) || v.resource_id !== resource || !['queued', 'executing', 'completed', 'failed', 'unknown'].includes(String(v.state)) ||
    !integer(v.bytes_completed) || v.bytes_completed > (request.source?.size ?? 0) ||
    (v.error !== undefined && !code(v.error)) ||
    (expected && (request.request_id !== expected.request_id || request.direction !== expected.direction || !sameFile(request.source, expected.source)))) throw invalid();
  const result: DeviceTransfer = {...request, resource_id: resource, state: v.state as DeviceTransfer['state'], bytes_completed: v.bytes_completed,
    ...(code(v.error) ? {error: v.error} : {})};
  if (v.state === 'completed' && request.direction !== 'list' && v.bytes_completed !== request.source?.size) throw invalid();
  if (v.files !== undefined || v.state === 'completed' && request.direction === 'list') {
    if (request.direction !== 'list' || !Array.isArray(v.files) || v.files.length > 1000 || typeof v.truncated !== 'boolean') throw invalid();
    const files = v.files.map(parseDeviceFile);
    if (new Set(files.map(file => file.file_id)).size !== files.length) throw invalid();
    result.files = files; result.truncated = v.truncated;
  }
  if (v.workspace_file !== undefined || v.state === 'completed' && request.direction === 'from_device') {
    const file = v.workspace_file;
    if (request.direction !== 'from_device' || !object(file) || !safeWorkspacePath(file.path) || !integer(file.size) || file.size !== request.source?.size ||
      typeof file.modified !== 'number' || !Number.isFinite(file.modified) || file.modified < 0) throw invalid();
    result.workspace_file = {path: file.path, size: file.size, modified: file.modified};
  }
  return result;
}
export function parseDeviceFilesCapability(v: unknown): DeviceFilesCapability {
  if (!object(v) || typeof v.supported !== 'boolean' || typeof v.available !== 'boolean' || v.available && !v.supported ||
    !(v.reason === null || code(v.reason)) || !integer(v.max_bytes) || !v.max_bytes || v.max_bytes > DEVICE_FILE_LIMIT ||
    v.inbox_label !== 'Pajio/Inbox' || v.outbox_label !== 'Pajio/Outbox') throw invalid();
  return {supported: v.supported, available: v.available, reason: v.reason, max_bytes: v.max_bytes,
    inbox_label: v.inbox_label, outbox_label: v.outbox_label};
}
const reasons: Record<string, string> = {
  device_private_or_paused: '设备正在私密接管或暂停中。明确交还后，再传递文件。',
  resource_paused_or_syncing: '设备正在暂停或同步状态，请确认交还并等待设备就绪。',
  files_permission_required: '这台设备尚未开通文件传递权限。',
  resource_busy: '设备正在处理其他操作，请稍后再试。',
  connector_offline: '设备暂时离线，连接恢复后再试。',
  previous_action_needs_review: '设备上有一步结果需要核对，请先返回设备页查看。',
  transfer_request_changed: '原请求与当前选择不一致，请核对原回执。',
  source_changed: '源文件已有变化，请重新读取并选择。',
  source_not_found: '源文件已移动或不存在，请重新读取。',
  file_too_large: '每份文件最多 20 MB。',
};
export function deviceFileReason(reason?: string | null) {return reason && reasons[reason] || '文件传递暂不可用，请重新检查设备状态。';}
export function transferLabel(item: DeviceTransfer): string {
  if (item.state === 'completed') return item.direction === 'list' ? '结果目录已读取' : item.direction === 'to_device' ? '已送达设备收件箱' : '已取回工作区';
  return {queued: '已排队，等待设备', executing: '设备正在传递', failed: '传递未完成', unknown: '结果待核对，请勿重复发送'}[item.state];
}
export const transferTerminal = (item: DeviceTransfer) => item.state === 'completed' || item.state === 'failed';

/** File bytes never pass through this client. Credentials and immutable scope remain native. */
export class DeviceFilesApi {
  readonly connection: Connection;
  private token = '';
  private readonly base: string;
  constructor(connection: Connection, readonly resource: string, private fetcher: typeof fetch = fetch) {
    if (!resourceId(resource)) throw invalid();
    this.connection = {...connection, session: connection.session && {...connection.session}, development: connection.development && {...connection.development}};
    this.base = `/api/devices/${encodeURIComponent(resource)}/files`;
  }
  private async request(path: string, body?: unknown, active = () => true): Promise<unknown> {
    if (!accountWorkAllowed(this.connection) || !active()) throw new ApiError('当前页面或账号已变化，本次未发送。', 403);
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)), {method: body === undefined ? 'GET' : 'POST',
        redirect: 'error', signal: controller.signal, headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity,
          ...(body === undefined ? {} : {'X-Wearing-Token': this.token, 'Content-Type': 'application/json'})},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      const data: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        const reason = object(data) && code(data.detail) ? data.detail : undefined;
        throw new ApiError(response.status === 401 ? '登录已到期，请重新登录。' : response.status === 404 ? '尚未找到这份回执，请稍后再次核对。'
          : response.status >= 500 ? '服务回执尚未确认，请核对原请求。' : deviceFileReason(reason), response.status);
      }
      if (!object(data)) throw invalid();
      return data;
    } catch (cause) {
      if (cause instanceof ApiError) throw cause;
      throw new ApiError(body === undefined ? '暂时无法读取文件状态，请检查连接后重试。' : '尚未收到传递回执，请核对原请求，不要重复发送。');
    } finally {clearTimeout(timer);}
  }
  private async mutation(path: string, body: unknown, active: () => boolean) {
    if (!this.token) {
      const v = await this.request('/api/bootstrap', undefined, active);
      if (!object(v) || v.version !== '0.2.0' || typeof v.token !== 'string' || !v.token || !Array.isArray(v.identities) ||
        !v.identities.some(i => object(i) && i.id === this.connection.identity)) throw invalid();
      this.token = v.token;
    }
    // Never retry POST, including an expired CSRF response; a new explicit action can refresh it.
    try {return await this.request(path, body, active);} catch (cause) {if (cause instanceof ApiError && cause.status === 403) this.token = ''; throw cause;}
  }
  async capability() {return parseDeviceFilesCapability(await this.request(this.base));}
  async source(path: string, active = () => true) {
    if (!safeWorkspacePath(path)) throw new ApiError('文件路径无效，请重新选择。', 422);
    return parseDeviceFile(await this.mutation(this.base + '/workspace-source', {path}, active));
  }
  async create(input: DeviceTransferRequest, active = () => true) {
    const request = parseTransferRequest(input);
    return parseDeviceTransfer(await this.mutation(this.base + '/transfers', request, active), this.resource, request);
  }
  async status(input: DeviceTransferRequest) {
    const request = parseTransferRequest(input);
    return parseDeviceTransfer(await this.request(this.base + '/transfers/' + request.request_id), this.resource, request);
  }
  async history(): Promise<DeviceTransfer[]> {
    const v = await this.request(this.base + '/transfers');
    if (!object(v) || !Array.isArray(v.transfers) || v.transfers.length > 50) throw invalid();
    const rows = v.transfers.map(row => parseDeviceTransfer(row, this.resource));
    if (new Set(rows.map(row => row.request_id)).size !== rows.length) throw invalid();
    return rows;
  }
}

/** Persist intent before the only POST. Restarts and unknown results can only read its receipt. */
export class DeviceTransferJournal {
  readonly key: string;
  private busy = false;
  constructor(private store: DeviceTransferStore, private api: DeviceFilesApi) {
    this.key = `device-file-transfer:v1:${scopeOf(api.connection)}|${api.resource}`;
  }
  async pending() {
    const value = await this.store.get<unknown>(this.key);
    if (value === null) return null;
    if (!object(value) || value.schema !== 1) throw new ApiError('待核对请求未完整读取，请重新打开此页；暂不发起新传递。', 422);
    return parseTransferRequest(value.request);
  }
  private writable(active: () => boolean) {return active() && accountWorkAllowed(this.api.connection);}
  private async settle(receipt: DeviceTransfer, active: () => boolean) {
    if (transferTerminal(receipt) && this.writable(active)) await this.store.clearIfSame(this.key, parseTransferRequest(receipt), () => this.writable(active));
    return receipt;
  }
  async create(input: DeviceTransferRequest, active = () => true) {
    if (this.busy) throw new ApiError('正在核对文件传递，请稍候。', 409);
    this.busy = true;
    try {
      if (await this.pending()) throw new ApiError('请先核对上次传递结果。', 409);
      const request = parseTransferRequest(input);
      if (!this.writable(active)) throw new ApiError('当前页面或账号已变化，本次未发送。', 403);
      await this.store.put(this.key, {schema: 1, request});
      if (!this.writable(active)) throw new ApiError('当前页面或账号已变化，请回到此页核对原请求。', 403);
      // Any HTTP error may have come from a gateway after enqueueing. Preserve the original ID.
      return await this.settle(await this.api.create(request, active), active);
    } finally {this.busy = false;}
  }
  async check(active = () => true) {
    if (this.busy) throw new ApiError('正在核对文件传递，请稍候。', 409);
    this.busy = true;
    try {
      const request = await this.pending();
      if (!this.writable(active)) throw new ApiError('当前页面或账号已变化，请重新打开后核对。', 403);
      return request ? await this.settle(await this.api.status(request), active) : null;
    }
    finally {this.busy = false;}
  }
  /** Explicit local acknowledgement only: never calls a cancellation or resubmission endpoint. */
  async stopWaiting(expected: DeviceTransferRequest, confirmed: boolean, active = () => true) {
    if (!confirmed) throw new ApiError('请先确认：停止本机等待不会取消设备上的传递。', 422);
    if (this.busy) throw new ApiError('正在核对文件传递，请稍候。', 409);
    this.busy = true;
    try {
      const request = parseTransferRequest(expected), current = await this.pending();
      if (!current || JSON.stringify(current) !== JSON.stringify(request)) throw new ApiError('待核对请求已变化，请重新读取。', 409);
      if (!this.writable(active)) throw new ApiError('当前页面或账号已变化，请重新打开后核对。', 403);
      if (!await this.store.clearIfSame(this.key, request, () => this.writable(active))) throw new ApiError('等待记录未清除，请重新核对原请求。', 409);
      if (await this.pending() !== null) throw new ApiError('等待记录未清除，请重新核对原请求。', 409);
      if (!this.writable(active)) throw new ApiError('当前页面或账号已变化。', 403);
    } finally {this.busy = false;}
  }
}
