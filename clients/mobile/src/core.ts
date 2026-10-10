import {commitRecordReceipt} from './record-sync';
import {isBookmarkUrl} from './bookmark-url';
import {memoryHistoryId, validMemoryHistory, type MemoryHistory} from './memory-history';
import {developmentConnectionsEnabled} from './development-access';
/** Canonical records remain on the service; creations and edits have separate durable queues. */
export type Kind = 'note' | 'task' | 'event';
export type Draft = {kind: Kind; title: string; content: string; timezone: string; start_at?: string; end_at?: string; all_day?: boolean; due_at?: string | null; url?: string | null};
export type RecordItem = Draft & {id: string; revision: number; completed?: boolean; deleted_at?: string | null; updated_at: string; capture?: {id?: string; state: string; original_text: string; assets: {id: string; name: string; mime: string}[]}};
export type DevelopmentConnection = {accessToken: string; expiresAt: string};
export type NativeSession = {accessToken?: string; expiresAt: string; userId: string; tenantId: string; credentialId: string};
export type Connection = {endpoint: string; identity: string; development?: DevelopmentConnection; session?: NativeSession};
export type ActivityBucket = 'attention' | 'active' | 'waiting' | 'results';
export type ActivityItem = {task_id: string; goal_id: string | null; source: 'goal' | 'schedule' | 'conversation' | 'task'; bucket: ActivityBucket; status: string; label: string; title: string; summary: string; version: string; updated_at: string; unread: boolean};
export type ActivitySnapshot = {checked_at: string; total: number; unread: number; counts: Record<ActivityBucket, number>; has_more: boolean; items: ActivityItem[];
  filtered_total?: number; next_cursor?: string | null; revision?: string; changed_since?: boolean | null};
export type ActivityQuery = {limit?: number; cursor?: string; bucket?: ActivityBucket; since?: string};
export type ActivityReceipt = Pick<ActivityItem, 'task_id' | 'version'>;
export type Media = {id: string; name: string; mime: string; size: number};
export type Pending = {id: string; scope: string; draft: Draft; media: Media[]; uploaded: string[]; organize: boolean; state: 'pending' | 'sending' | 'attention'; attempts: number; nextAt: number; error?: string; createdAt: string};
export type Store = {get<T>(key: string): Promise<T | null>; put(key: string, value: unknown): Promise<void>; batch(values: [string, unknown][]): Promise<void>; blob(id: string): Promise<Blob>};
export type Transport = {upload(media: Media, blob: Blob, key: string): Promise<string>; create(entry: Pending): Promise<RecordItem>};
export class ApiError extends Error { constructor(message: string, public status = 0) {super(message);} }

export function endpoint(raw: string): string {
  let url: URL; try {url = new URL(raw.trim());} catch {throw new Error('请填写完整的 Pajio 地址。');}
  const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  if (!url.hostname || (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('请使用本机 HTTP 或私人 HTTPS 根地址，不要在地址里放账号或密钥。');
  return url.origin + '/';
}
function privateIPv4(host: string) {
  if (!/^\d{1,3}(?:\.\d{1,3}){3}$/.test(host)) return false;
  const parts = host.split('.').map(Number);
  return parts.every(part => part <= 255) && (parts[0] === 10 || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) || (parts[0] === 192 && parts[1] === 168));
}
/** LAN HTTP is an explicit, expiring development capability, never a normal URL. */
export function connectionEndpoint(connection: Connection, allowExpired = false): string {
  if (connection.session) {
    const address = endpoint(connection.endpoint), session = connection.session;
    if (connection.development || !address.startsWith('https://') || !/^user_[a-f0-9]{32}$/.test(session.userId) || !/^[A-Za-z0-9_-]{1,128}$/.test(session.tenantId) || !/^[A-Za-z0-9_-]{32,64}$/.test(session.credentialId) || !Number.isFinite(Date.parse(session.expiresAt)) || (session.accessToken !== undefined && !/^[A-Za-z0-9_-]{64}$/.test(session.accessToken))) throw new ApiError('登录信息不完整，请重新登录。', 401);
    if (!allowExpired && (!session.accessToken || Date.parse(session.expiresAt) <= Date.now())) throw new ApiError('登录已过期，请重新登录。本机草稿仍会保留。', 401);
    return address;
  }
  if (!connection.development) return endpoint(connection.endpoint);
  if (!developmentConnectionsEnabled()) throw new ApiError('短期 LAN 配对仅供已启用开发连接的开发版验收使用。', 403);
  let url: URL;
  try {url = new URL(connection.endpoint.trim());} catch {throw new ApiError('配对地址不完整，请重新打开配对链接。', 422);}
  if (url.protocol !== 'http:' || !privateIPv4(url.hostname) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new ApiError('开发配对需要同一可信 Wi-Fi 内的私人 IPv4 根地址。', 422);
  const {accessToken, expiresAt} = connection.development;
  if (typeof accessToken !== 'string' || !/^[A-Za-z0-9_-]{32,512}$/.test(accessToken) || typeof expiresAt !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(expiresAt) || !Number.isFinite(Date.parse(expiresAt))) throw new ApiError('配对凭据不完整，请重新打开配对链接。', 422);
  const remaining = Date.parse(expiresAt) - Date.now();
  if (remaining > 4 * 60 * 60 * 1000 + 60000) throw new ApiError('配对有效期过长，请重新生成短期链接。', 422);
  if (!allowExpired && remaining <= 0) throw new ApiError('短期配对已过期，请在电脑上重新生成链接；本机草稿仍会保留。', 401);
  return url.origin + '/';
}
export function connectionHeaders(connection: Connection): Record<string, string> {
  connectionEndpoint(connection);
  const access = connection.session?.accessToken || connection.development?.accessToken;
  return access ? {Authorization: 'Bearer ' + access, ...(connection.session ? {'X-Pajio-Expected-Tenant':connection.session.tenantId} : {})} : {};
}
export function pairingConnection(params: Record<string, string | string[] | undefined>): Connection {
  const {endpoint: address, identity, accessToken, expiresAt} = params;
  if (typeof address !== 'string' || typeof identity !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(identity) || typeof accessToken !== 'string' || typeof expiresAt !== 'string') throw new ApiError('配对链接不完整，请重新扫码。', 422);
  const connection: Connection = {endpoint: address, identity, development: {accessToken, expiresAt}};
  return {...connection, endpoint: connectionEndpoint(connection)};
}
export const scopeOf = (c: Connection) => `${connectionEndpoint(c, true)}|${c.session ? `${c.session.userId}|${c.session.tenantId}|` : ''}${c.identity}`;
export const boxKey = (scope: string) => `outbox:${scope}`;

const activityId = (value: unknown): value is string => typeof value === 'string' && /^[-a-zA-Z0-9_]{1,64}$/.test(value);
const activityVersion = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const activityDate = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));
const activityCount = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;

/** Reject partial or incompatible snapshots so an offline view can retain its last verified data. */
export function activitySnapshot(value: unknown, continuation = false): ActivitySnapshot {
  const data = value as ActivitySnapshot | null;
  const invalid = () => {throw new ApiError('进展暂时无法读取，上次查看的内容仍会保留。', 422);};
  if (!data || !activityDate(data.checked_at) || !activityCount(data.total) || !activityCount(data.unread) || data.unread > data.total || !data.counts || typeof data.has_more !== 'boolean' || !Array.isArray(data.items)) return invalid();
  // Older services predate the waiting bucket. Missing counts mean zero, never a
  // guessed reassignment of work from another bucket; malformed present values fail.
  const counts = {...data.counts, waiting: data.counts.waiting === undefined ? 0 : data.counts.waiting};
  const buckets: ActivityBucket[] = ['attention', 'active', 'waiting', 'results'];
  if (buckets.some(bucket => !activityCount(counts[bucket])) || buckets.reduce((sum, bucket) => sum + counts[bucket], 0) !== data.total || data.items.length > data.total || data.unread > counts.results) return invalid();
  const ids = new Set<string>();
  for (const item of data.items) {
    if (!item || !activityId(item.task_id) || ids.has(item.task_id) || !(item.goal_id === null || activityId(item.goal_id)) || !['goal', 'schedule', 'conversation', 'task'].includes(item.source) || !buckets.includes(item.bucket) || !activityVersion(item.version) || !activityDate(item.updated_at) || typeof item.unread !== 'boolean' || (item.unread && item.bucket !== 'results') || !['status', 'label', 'title', 'summary'].every(key => typeof item[key as keyof ActivityItem] === 'string')) return invalid();
    ids.add(item.task_id);
  }
  const paginated = ['filtered_total', 'next_cursor', 'revision', 'changed_since'].some(key => Object.hasOwn(data, key));
  if (paginated && (!activityCount(data.filtered_total) || data.filtered_total > data.total || data.items.length > data.filtered_total ||
    !activityVersion(data.revision) || !(data.changed_since === null || typeof data.changed_since === 'boolean') ||
    !(data.next_cursor === null || (typeof data.next_cursor === 'string' && data.next_cursor.length > 0 && data.next_cursor.length <= 8192)) ||
    data.has_more !== (data.next_cursor !== null))) return invalid();
  if (paginated && !continuation && !data.has_more && data.items.length !== data.filtered_total) return invalid();
  if (buckets.some(bucket => data.items.filter(item => item.bucket === bucket).length > counts[bucket]) || data.items.filter(item => item.unread).length > data.unread || (!paginated && !data.has_more && (data.items.length !== data.total || data.items.filter(item => item.unread).length !== data.unread))) return invalid();
  return {...data, counts};
}

export function activitySummary(snapshot: ActivitySnapshot): string {
  const {counts} = snapshot;
  if (counts.attention) return `${counts.attention} 件事等你处理`;
  if (snapshot.unread) return `${snapshot.unread} 份新结果`;
  if (counts.active) return `${counts.active} 件事正在推进${counts.waiting ? ` · ${counts.waiting} 件已排队` : ''}`;
  if (counts.waiting) return `${counts.waiting} 件事已排队`;
  return snapshot.total ? '最近交给我的事' : '交代过的事，从这里回看';
}

export function makeDraft(text: string, kind: Kind, start?: Date, end?: Date): Draft {
  const content = text.trim();
  if (!content || content.length > 12000) throw new Error('请写一点内容，最多 12000 字。');
  const draft: Draft = {kind, title: content.split('\n')[0].slice(0, 200), content, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'};
  if (kind === 'event') {
    if (!start || !end || !Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end <= start) throw new Error('结束时间需要晚于开始时间。');
    draft.start_at = start.toISOString(); draft.end_at = end.toISOString();
  }
  return draft;
}

export class Outbox {
  private serial: Promise<unknown> = Promise.resolve();
  constructor(private store: Store, private changed: () => void = () => {}) {}
  private exclusive<T>(work: () => Promise<T>): Promise<T> {
    const result = this.serial.then(work, work); this.serial = result.catch(() => {}); return result;
  }
  async items(scope: string): Promise<Pending[]> {return (await this.store.get<Pending[]>(boxKey(scope))) || [];}
  private async write(scope: string, entries: Pending[]) {await this.store.put(boxKey(scope), entries); this.changed();}
  enqueue(entry: Pending, clearDraft?: [string, unknown]) {return this.exclusive(async () => {
    if (entry.media.length > 4 || entry.media.some(m => m.size > 15 * 1024 * 1024 || m.size <= 0)) throw new Error('最多四份原件，每份不超过 15 MB。');
    const items = await this.items(entry.scope);
    if (items.length >= 100) throw new Error('手机里已经存了 100 条待同步记录，先同步一些，再继续记。');
    const prior = items.find(item => item.id === entry.id);
    if (prior && JSON.stringify([prior.draft, prior.media]) !== JSON.stringify([entry.draft, entry.media])) throw new Error('此前的输入已经保存在待同步记录中，请先同步，再另外记下新的修改。');
    if (!prior) {
      await this.store.batch([[boxKey(entry.scope), [...items, entry]], ...(clearDraft ? [clearDraft] : [])]); this.changed();
    }
  });}
  retry(scope: string, id: string) {return this.exclusive(async () => {
    const items = await this.items(scope); const item = items.find(x => x.id === id);
    if (item) {item.state = 'pending'; item.attempts = 0; item.nextAt = 0; delete item.error; await this.write(scope, items);}
  });}
  flush(scope: string, transport: Transport, isCurrent: () => boolean, now = Date.now()) {
    return this.exclusive(async () => {
      const entries = await this.items(scope);
      let sent = 0;
      for (const entry of [...entries]) {
        if (!isCurrent()) break;
        if (entry.scope !== scope) throw new Error('待同步记录的身份不一致，已停止同步。');
        if (entry.state === 'attention' || entry.nextAt > now) continue;
        entry.state = 'sending'; entry.attempts += 1;
        await this.write(scope, entries);
        try {
          for (let index = entry.uploaded.length; index < entry.media.length; index++) {
            if (!isCurrent()) {entry.state = 'pending'; await this.write(scope, entries); return sent;}
            const media = entry.media[index];
            const asset = await transport.upload(media, await this.store.blob(media.id), `${entry.id}-asset-${index}`);
            entry.uploaded.push(asset); await this.write(scope, entries);
          }
          if (!isCurrent()) {entry.state = 'pending'; await this.write(scope, entries); break;}
          const record = await transport.create(entry);
          // Keep the receipt until the canonical snapshot catches up; never lose a saved record between requests.
          await commitRecordReceipt(this.store, scope, record);
          entries.splice(entries.findIndex(x => x.id === entry.id), 1); await this.write(scope, entries); sent++;
        } catch (error) {
          const permanent = error instanceof ApiError && [400, 401, 403, 404, 409, 413, 422].includes(error.status);
          entry.state = permanent || entry.attempts >= 6 ? 'attention' : 'pending';
          entry.error = error instanceof Error ? error.message : '暂时没同步上，原件仍在手机里。';
          entry.nextAt = now + Math.min(300000, 5000 * 2 ** (entry.attempts - 1));
          await this.write(scope, entries);
          // A disconnected service needs one attempt, not one request per queued item.
          break;
        }
      }
      return sent;
    });
  }
}

export type MemorySnapshot = {available: boolean; message?: string; observed_at?: string; identity_id: string;
  targets?: Record<'user' | 'memory', {enabled: boolean; entries: string[]; revision?: string; settings_revision?: string; used_chars?: number; limit_chars?: number; history?: MemoryHistory}>};
export type MemoryChange = {target:'user'|'memory'; revision:string; action:'add'|'replace'|'remove'|'clear'|'set_enabled'; index?:number; content?:string; enabled?:boolean; settings_revision?:string} | {target:'user'|'memory'; revision:string; action:'undo'; history_id:string};
function completeMemorySnapshot(data: unknown, identity: string, mutation = false): data is MemorySnapshot {
  if (!data || typeof data !== 'object') return false;
  const snapshot = data as MemorySnapshot;
  if (snapshot.identity_id !== identity || typeof snapshot.available !== 'boolean' || (mutation && !snapshot.available)) return false;
  return !snapshot.available || ['user', 'memory'].every(key => {
    const page = snapshot.targets?.[key as 'user' | 'memory'];
    return !!page && typeof page.enabled === 'boolean' && Array.isArray(page.entries) && page.entries.every(entry => typeof entry === 'string') && (!mutation || typeof page.revision === 'string' && /^[a-f0-9]{64}$/.test(page.revision)) && (page.history === undefined || validMemoryHistory(page.history, page));
  });
}
export type OngoingItem = {id: string; title: string; status: string; detail: string};

export class WearingApi implements Transport {
  private token = '';
  constructor(readonly connection: Connection, private fetcher: typeof fetch = fetch) {}
  private async request(path: string, method = 'GET', body?: string | Blob, mime = 'application/json', refresh = true, timeoutMs = 20000): Promise<any> {
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const call = this.fetcher;
      const base = connectionEndpoint(this.connection);
      const response = await call(new URL(path, base).toString(), {method, body, signal: controller.signal, redirect: 'error', headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(method !== 'GET' ? {'X-Wearing-Token': this.token, 'Content-Type': mime} : {})}});
      if (response.status === 403 && method !== 'GET' && refresh) {await this.bootstrap(); return this.request(path, method, body, mime, false, timeoutMs);}
      const data = await response.json().catch(() => {throw new ApiError('这个地址没有返回 Pajio 数据，请检查连接。', response.status);});
      if (!response.ok) throw new ApiError(typeof data.detail === 'string' ? data.detail : '这次请求没有完成，请检查连接后重试。', response.status);
      return data;
    } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('暂时连不上 Pajio，请检查连接后重试。');}
    finally {clearTimeout(timeout);}
  }
  async bootstrap(): Promise<{identities: {id: string; name: string}[]}> {
    const data = await this.request('/api/bootstrap');
    if (data.version !== '0.2.0' || !['local', 'cloud'].includes(data.deployment) || typeof data.token !== 'string' || !Array.isArray(data.identities)) throw new ApiError('这个地址不是兼容的 Pajio 服务。', 422);
    if (!data.identities.some((i: {id: string}) => i.id === this.connection.identity)) throw new ApiError('这份连接里没有所选身份，请重新选择。', 404);
    this.token = data.token; return data;
  }
  async changeMemory(change: MemoryChange): Promise<MemorySnapshot> {
    if (change.action === 'undo' && (!memoryHistoryId(change.history_id) || !/^[a-f0-9]{64}$/.test(change.revision))) throw new ApiError('这条修改记录暂时不能撤销，请刷新后重新选择。', 422);
    await this.bootstrap();
    const data = await this.request('/api/memory', 'PATCH', JSON.stringify(change), 'application/json', false);
    if (!completeMemorySnapshot(data, this.connection.identity, true)) throw new ApiError('记忆回执不完整，请刷新核对后再操作。', 422);
    return data;
  }
  async voiceAuthorization(): Promise<string> {await this.bootstrap(); return this.token;}
  async snapshot(): Promise<{items: RecordItem[]; version: number}> {
    const data = await this.request('/api/life?include_deleted=true');
    if (!Array.isArray(data.items) || !Number.isSafeInteger(data.version) || data.version < 0 || new Set(data.items.map((item: RecordItem) => item?.id)).size !== data.items.length) throw new ApiError('记录暂时无法读取，手机里原有内容仍在。', 422);
    for (const item of data.items) this.recordResponse(item, item?.id);
    return data;
  }
  async activity(options: ActivityQuery = {}): Promise<ActivitySnapshot> {
    const query = new URLSearchParams();
    if (options.limit !== undefined) {
      if (!Number.isInteger(options.limit) || options.limit < 1 || options.limit > 100) throw new ApiError('任务页大小无效，请重新打开。', 422);
      query.set('limit', String(options.limit));
    }
    if (options.cursor !== undefined) {
      if (typeof options.cursor !== 'string' || !options.cursor || options.cursor.length > 8192) throw new ApiError('任务页凭据无效，请刷新。', 422);
      query.set('cursor', options.cursor);
    }
    if (options.bucket !== undefined) {
      if (!['attention', 'active', 'waiting', 'results'].includes(options.bucket)) throw new ApiError('任务分类无效，请重新打开。', 422);
      query.set('bucket', options.bucket);
    }
    if (options.since !== undefined) {
      if (!activityVersion(options.since)) throw new ApiError('进展版本无效，请刷新。', 422);
      query.set('since', options.since);
    }
    const snapshot = activitySnapshot(await this.request('/api/activity' + (query.size ? '?' + query.toString() : '')), !!options.cursor);
    if (options.bucket && snapshot.items.some(item => item.bucket !== options.bucket)) throw new ApiError('没有收到当前分类的任务，请刷新。', 422);
    return snapshot;
  }
  async memory(): Promise<MemorySnapshot> {
    const data = await this.request('/api/memory');
    if (!completeMemorySnapshot(data, this.connection.identity)) {
      throw new ApiError('没有收到当前身份的完整记忆，请稍后刷新。', 422);
    }
    return data;
  }
  async ongoing(kind: 'goals' | 'schedules'): Promise<OngoingItem[]> {
    const data = await this.request('/api/' + kind);
    const items = kind === 'goals' ? data : data.items;
    if (!Array.isArray(items) || items.some(item => !item || typeof item.id !== 'string' || typeof item.status !== 'string' || typeof (kind === 'goals' ? item.objective : item.schedule?.title) !== 'string')) throw new ApiError('暂时没有读到完整安排，请稍后重试。', 422);
    return items.map(item => ({id: item.id, title: kind === 'goals' ? item.objective : item.schedule.title, status: item.status,
      detail: kind === 'goals' ? item.next_step || item.reason || '' : item.next_run ? '下次 ' + new Date(item.next_run).toLocaleString('zh-CN') : item.schedule.kind === 'life_change' ? '有相关变化时留意' : ''}));
  }
  async activitySeen(items: ActivityReceipt[]): Promise<ActivitySnapshot> {
    if (!Array.isArray(items) || !items.length || items.length > 100 || items.some(item => !item || !activityId(item.task_id) || !activityVersion(item.version)) || new Set(items.map(item => item.task_id)).size !== items.length) throw new ApiError('没有完整的进展版本，已读状态没有修改。', 422);
    if (!this.token) await this.bootstrap();
    // Send only the exact versions that were read, never a status or execution command.
    return activitySnapshot(await this.request('/api/activity/seen', 'POST', JSON.stringify({items: items.map(({task_id, version}) => ({task_id, version}))})));
  }
  async upload(media: Media, blob: Blob, key: string) {
    if (!this.token) await this.bootstrap();
    const params = new URLSearchParams({name: media.name, request_key: key});
    const data = await this.request('/api/life/assets?' + params, 'POST', blob, media.mime);
    if (!/^asset_[a-f0-9]{32}$/.test(data.id)) throw new ApiError('没有收到原件保存回执，可以重试。', 422);
    return data.id as string;
  }
  async transcribe(asset: string): Promise<{asset_id: string; text: string}> {
    if (!this.token) await this.bootstrap();
    const data = await this.request('/api/life/assets/' + encodeURIComponent(asset) + '/transcribe', 'POST', '{}', 'application/json', true, 150000);
    if (data.asset_id !== asset || typeof data.text !== 'string' || !data.text.trim() || data.text.length > 12000) throw new ApiError('没有收到完整的语音文字，录音仍然保留。', 422);
    return data;
  }
  async create(entry: Pending): Promise<RecordItem> {
    if (!this.token) await this.bootstrap();
    const record = entry.media.length ? (await this.request('/api/captures', 'POST', JSON.stringify({record: entry.draft, asset_ids: entry.uploaded, request_key: entry.id, organize: entry.organize}))).record : await this.request('/api/life', 'POST', JSON.stringify({record: entry.draft, request_key: entry.id}));
    if (entry.draft.url != null) return this.recordResponse(record, record?.id);
    if (!record?.id || !Number.isInteger(record.revision)) throw new ApiError('没有收到记录回执，可以重试。', 422);
    return record;
  }
  async record(id: string): Promise<RecordItem> {
    return this.recordResponse(await this.request('/api/life/' + encodeURIComponent(id)), id);
  }
  private recordResponse(value: unknown, id: string): RecordItem {
    const record = value as RecordItem;
    if (record?.url != null && (record.kind !== 'note' || !isBookmarkUrl(record.url))) throw new ApiError('收藏链接回执不完整，请读取最新版本核对。', 422);
    if (!record || typeof record.id !== 'string' || !record.id || record.id !== id || !Number.isSafeInteger(record.revision) || record.revision < 1 || !['note', 'task', 'event'].includes(record.kind) || typeof record.content !== 'string' || typeof record.title !== 'string' || !Number.isFinite(Date.parse(record.updated_at))) throw new ApiError('未收到完整的记录回执，请读取最新版本核对。', 422);
    if (record.kind === 'event' && (!Number.isFinite(Date.parse(record.start_at || '')) || !Number.isFinite(Date.parse(record.end_at || '')))) throw new ApiError('日程时间不完整，请读取最新版本核对。', 422);
    if (record.capture && (!Array.isArray(record.capture.assets) || typeof record.capture.original_text !== 'string' || record.capture.assets.some(asset => !asset || typeof asset.id !== 'string' || typeof asset.mime !== 'string' || typeof asset.name !== 'string'))) throw new ApiError('原件信息不完整，请读取最新版本核对。', 422);
    return record;
  }
  async update(record: RecordItem, patch: Partial<RecordItem>, action: 'edit' | 'archive' | 'restore' = 'edit', requestKey?: string): Promise<RecordItem> {
    if (!this.token) await this.bootstrap();
    return this.recordResponse(await this.request('/api/life/' + encodeURIComponent(record.id), 'PATCH', JSON.stringify({revision: record.revision, patch, action, ...(requestKey ? {request_key: requestKey} : {})})), record.id);
  }
  async retryCapture(record: RecordItem): Promise<RecordItem> {
    if (!record.capture?.id) throw new ApiError('这条记录没有可重试的整理任务。', 422);
    if (!this.token) await this.bootstrap();
    const data = await this.request('/api/captures/' + encodeURIComponent(record.capture.id) + '/retry', 'POST', '{}');
    return this.recordResponse(data?.record, record.id);
  }
}
