import {ApiError, connectionEndpoint, connectionHeaders, scopeOf, type Connection, type RecordItem, type Store} from './core';
import {mutationKey} from './record-mutations';
import {recordReceiptWrites, withRecordScope} from './record-sync';

export type TaskList = {id: string; name: string; revision: number; archived_at: string | null; created_at: string; updated_at: string; total: number; open: number};
export type ListTask = RecordItem & {kind: 'task'; identity_id: string; list_name: string; position?: number};
export type ListCatalog = {identity_id: string; revision: number; lists: TaskList[]};
export type ListPage = {identity_id: string; revision: number; list: TaskList; items: ListTask[]; offset: number; next_offset: number | null};
export type ListAction = 'create' | 'rename' | 'archive' | 'restore' | 'add' | 'move' | 'reorder';
export type ListRequest = {action: ListAction; revision: number; request_key: string; list_id?: string; name?: string; title?: string; content?: string; timezone?: string; record_id?: string; record_revision?: number; target_list_id?: string; before_id?: string | null};
export type ListReceipt = {identity_id: string; revision: number; request_key: string; action: ListAction; lists: TaskList[]; record: ListTask | null; changed_records: number};
export type PendingListChange = {schema: 1; request: ListRequest; phase: 'pending' | 'conflict' | 'rejected'; error?: string};
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const integer = (v: unknown, min = 0): v is number => Number.isSafeInteger(v) && (v as number) >= min;
const instant = (v: unknown): v is string => typeof v === 'string' && Number.isFinite(Date.parse(v));
const listId = (v: unknown): v is string => typeof v === 'string' && /^list_[a-f0-9]{32}$/.test(v);
const recordId = (v: unknown): v is string => typeof v === 'string' && /^life_[a-f0-9]{32}$/.test(v);
const text = (v: unknown, max: number, empty = false): v is string => typeof v === 'string' && v.length <= max && (empty || !!v.trim());
const bad = () => new ApiError('清单数据未通过核对，请重新读取。', 422);
function metadata(v: unknown): TaskList {
  if (!object(v) || !listId(v.id) || !text(v.name, 80) || !integer(v.revision, 1) || !(v.archived_at === null || instant(v.archived_at)) || !instant(v.created_at) || !instant(v.updated_at) || !integer(v.total) || !integer(v.open) || v.open > v.total) throw bad();
  return {id: v.id, name: v.name, revision: v.revision, archived_at: v.archived_at as string | null, created_at: v.created_at, updated_at: v.updated_at, total: v.total, open: v.open};
}
function task(v: unknown, identity: string): ListTask {
  if (!object(v) || !recordId(v.id) || v.identity_id !== identity || v.kind !== 'task' || !integer(v.revision, 1) || !text(v.title, 200) || !text(v.content, 12000, true) || !text(v.timezone, 80) || !text(v.list_name, 80) || typeof v.completed !== 'boolean' || v.deleted_at || !instant(v.updated_at)) throw bad();
  return v as ListTask;
}
export function parseCatalog(v: unknown, identity: string): ListCatalog {
  if (!object(v) || v.identity_id !== identity || !integer(v.revision) || !Array.isArray(v.lists) || v.lists.length > 500) throw bad();
  const lists = v.lists.map(metadata);
  if (new Set(lists.map(row => row.id)).size !== lists.length) throw bad();
  return {identity_id: identity, revision: v.revision, lists};
}
export function parseListPage(v: unknown, identity: string, id: string): ListPage {
  if (!object(v) || v.identity_id !== identity || !integer(v.revision) || !integer(v.offset) || !Array.isArray(v.items) || v.items.length > 100 || !(v.next_offset === null || integer(v.next_offset))) throw bad();
  const list = metadata(v.list), items = v.items.map(row => task(row, identity));
  if (list.id !== id || new Set(items.map(row => row.id)).size !== items.length || items.some((row, i) => row.list_name !== list.name || !integer(row.position, 1) || (i > 0 && row.position! <= items[i - 1].position!)) || v.offset + items.length > list.total || (v.next_offset === null ? v.offset + items.length !== list.total : !items.length || v.next_offset !== v.offset + items.length || v.next_offset >= list.total)) throw bad();
  return {identity_id: identity, revision: v.revision, list, items, offset: v.offset, next_offset: v.next_offset as number | null};
}
/** Never concatenate pages from different board versions or silently omit changed rows. */
export function appendListPage(previous: ListPage | null, next: ListPage): ListPage {
  if (!previous) {if (next.offset !== 0) throw bad(); return next;}
  if (previous.identity_id !== next.identity_id || previous.list.id !== next.list.id || previous.revision !== next.revision || previous.next_offset !== next.offset || previous.list.total !== next.list.total || new Set([...previous.items, ...next.items].map(row => row.id)).size !== previous.items.length + next.items.length || (previous.items.length && next.items.length && previous.items.at(-1)!.position! >= next.items[0].position!)) throw bad();
  return {...next, offset: 0, items: [...previous.items, ...next.items]};
}
export function listRequest(v: unknown): ListRequest {
  if (!object(v) || !['create', 'rename', 'archive', 'restore', 'add', 'move', 'reorder'].includes(String(v.action)) || !integer(v.revision) || typeof v.request_key !== 'string' || !/^[A-Za-z0-9_-]{16,120}$/.test(v.request_key)) throw bad();
  const action = v.action as ListAction;
  const required = {create: ['name'], rename: ['list_id', 'name'], archive: ['list_id'], restore: ['list_id'], add: ['list_id', 'title'], move: ['list_id', 'record_id', 'record_revision', 'target_list_id'], reorder: ['list_id', 'record_id', 'record_revision']}[action];
  const allowed = [...required, 'action', 'revision', 'request_key', ...(action === 'add' ? ['content', 'timezone'] : ['move', 'reorder'].includes(action) ? ['before_id'] : [])];
  if (required.some(k => v[k] === undefined || v[k] === null) || Object.keys(v).some(k => !allowed.includes(k))) throw bad();
  const validators: Record<string, (x: unknown) => boolean> = {list_id: listId, target_list_id: listId, record_id: recordId, before_id: x => x === null || recordId(x), record_revision: x => integer(x, 1), name: x => text(x, 80), title: x => text(x, 200), content: x => text(x, 12000, true), timezone: x => text(x, 80)};
  if (Object.keys(v).some(k => validators[k] && !validators[k](v[k]))) throw bad();
  // Closed, deterministic serialization makes retry comparisons independent of object key order.
  return Object.fromEntries(allowed.filter(k => v[k] !== undefined).sort().map(k => [k, typeof v[k] === 'string' ? (v[k] as string).trim() : v[k]])) as ListRequest;
}
export function parseListReceipt(v: unknown, identity: string, request: ListRequest): ListReceipt {
  if (!object(v) || v.identity_id !== identity || v.request_key !== request.request_key || v.action !== request.action || !integer(v.revision, request.revision + 1) || !integer(v.changed_records) || !Array.isArray(v.lists)) throw bad();
  const lists = v.lists.map(metadata), record = v.record === null ? null : task(v.record, identity);
  const expected = request.action === 'move' ? [...new Set([request.list_id, request.target_list_id])] : [request.list_id];
  if (!lists.length || lists.length > 2 || new Set(lists.map(row => row.id)).size !== lists.length || (request.action === 'create' ? lists.length !== 1 || lists[0].name !== request.name : lists.length !== expected.length || expected.some(id => !lists.some(row => row.id === id)))) throw bad();
  if (request.action === 'rename' && lists[0].name !== request.name || request.action === 'archive' && !lists[0].archived_at || request.action === 'restore' && lists[0].archived_at) throw bad();
  if (['add', 'move', 'reorder'].includes(request.action)) {
    const target = lists.find(row => row.id === (request.target_list_id || request.list_id));
    if (!record || !target || record.list_name !== target.name || request.record_id && record.id !== request.record_id || request.record_revision && record.revision < request.record_revision || request.action === 'add' && (record.title !== request.title || record.content !== (request.content || ''))) throw bad();
  } else if (record) throw bad();
  return {identity_id: identity, revision: v.revision, request_key: request.request_key, action: request.action, lists, record, changed_records: v.changed_records};
}
export class TaskListApi {
  private token = '';
  readonly connection: Connection;
  constructor(connection: Connection, private fetcher: typeof fetch = fetch) {this.connection = {...connection, ...(connection.session ? {session: {...connection.session}} : {}), ...(connection.development ? {development: {...connection.development}} : {})};}
  private async request(path: string, body?: ListRequest, retry = true): Promise<unknown> {
    const timer = new AbortController(), timeout = setTimeout(() => timer.abort(), 15000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)), {method: body ? 'POST' : 'GET', redirect: 'error', signal: timer.signal, headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(body ? {'Content-Type': 'application/json', 'X-Wearing-Token': this.token} : {})}, ...(body ? {body: JSON.stringify(body)} : {})});
      if (body && response.status === 403 && retry) {await this.bootstrap(); return this.request(path, body, false);}
      if (!response.ok) throw new ApiError(response.status === 409 ? '清单已有变化，操作内容仍保留。请读取最新内容后核对。' : '清单暂时无法读写，请稍后重试。', response.status);
      return await response.json();
    } catch (cause) {if (cause instanceof ApiError) throw cause; throw new ApiError(body ? '操作结果尚未确认，原请求已留在本机。' : '暂时无法读取清单。', 0);} finally {clearTimeout(timeout);}
  }
  private async bootstrap() {
    const value = await this.request('/api/bootstrap');
    if (!object(value) || !text(value.token, 1024) || !Array.isArray(value.identities) || !value.identities.some(row => object(row) && row.id === this.connection.identity)) throw bad();
    this.token = value.token;
  }
  async catalog() {return parseCatalog(await this.request('/api/task-lists'), this.connection.identity);}
  async page(id: string, offset = 0, revision?: number) {
    if (!listId(id) || !integer(offset) || offset && !integer(revision)) throw bad();
    const result = parseListPage(await this.request(`/api/task-lists/${id}/items?limit=100&offset=${offset}${revision === undefined ? '' : `&revision=${revision}`}`), this.connection.identity, id);
    if (result.offset !== offset || revision !== undefined && result.revision !== revision) throw bad();
    return result;
  }
  async change(input: ListRequest) {
    const body = listRequest(input); if (!this.token) await this.bootstrap();
    const value = await this.request('/api/task-lists/change', body);
    try {return parseListReceipt(value, this.connection.identity, body);} catch {throw new ApiError('回执尚未核对，请取回同一次清单操作。', 0);}
  }
}
type LocalStore = Pick<Store, 'get' | 'put' | 'batch'>;
export class TaskListChanges {
  readonly key: string; readonly scope: string;
  constructor(private store: LocalStore, readonly api: Pick<TaskListApi, 'connection' | 'change'>) {this.scope = scopeOf(api.connection); this.key = `task-list-request:${this.scope}`;}
  async pending(): Promise<PendingListChange | null> {
    const value = await this.store.get<PendingListChange>(this.key);
    if (value === null) return null;
    if (value.schema !== 1 || !['pending', 'conflict', 'rejected'].includes(value.phase)) throw bad();
    return {...value, request: listRequest(value.request)};
  }
  save(input?: ListRequest) {
    // A dedicated queue shared across instances serializes network attempts without blocking record sync.
    return withRecordScope(this.store, `task-lists:${this.scope}`, async () => {
      const old = await this.pending(), request = old?.request || (input && listRequest(input));
      if (!request || old && input && JSON.stringify(listRequest(input)) !== JSON.stringify(old.request)) throw new ApiError('请先处理上一次清单操作。', 409);
      if (old && old.phase !== 'pending') throw new ApiError('上次操作未执行，请读取最新清单，核对后再提交。', 409);
      if (!old) {
        const edits = await this.store.get<unknown[]>(mutationKey(this.scope));
        if (edits && (!Array.isArray(edits) || edits.length)) throw new ApiError('请先同步待办修改或处理版本冲突，再整理清单。', 409);
      }
      await this.store.put(this.key, {schema: 1, request, phase: 'pending'});
      let receipt: ListReceipt;
      try {receipt = await this.api.change(request);}
      catch (cause) {
        if (cause instanceof ApiError && [400, 404, 409, 413, 422].includes(cause.status)) await this.store.put(this.key, {schema: 1, request, phase: cause.status === 409 ? 'conflict' : 'rejected', error: cause.message});
        throw cause;
      }
      await withRecordScope(this.store, this.scope, async () => {
        await this.store.batch([[this.key, null], [`task-list-last-receipt:${this.scope}`, receipt], ...(receipt.record ? await recordReceiptWrites(this.store, this.scope, receipt.record) : [])]);
      });
      return receipt;
    });
  }
  discardRejected() {
    return withRecordScope(this.store, `task-lists:${this.scope}`, async () => {
      const pending = await this.pending();
      if (pending?.phase === 'pending') throw new ApiError('结果尚未确认，请先取回原回执。', 409);
      await this.store.put(this.key, null);
    });
  }
}
export function listActionLabel(request: ListRequest) {
  return {create: `新建清单「${request.name}」`, rename: `改名为「${request.name}」`, archive: '归档清单（保留事项）', restore: '恢复清单', add: `添加「${request.title}」`, move: '移动事项到另一份清单', reorder: '调整事项顺序'}[request.action];
}
