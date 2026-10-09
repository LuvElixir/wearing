import {ApiError, Connection, Store, connectionEndpoint, connectionHeaders, scopeOf} from './core';
import {safeWorkspacePath} from './personal-hub';

export const TEXT_LIMIT = 64 * 1024;
export type TextDocument = {identity_id: string; path: string; text: string; size: number; sha256: string; revision: string; modified: number; save_mode: 'copy' | 'replace'; editable: boolean; blocked_reason: string | null; history: {id: string; created_at: string}[]};
export type TextRequest = {path: string; text: string; base_revision: string; base_sha256: string; request_key: string};
export type TextReceipt = Omit<TextDocument, 'text' | 'editable' | 'blocked_reason' | 'history'> & {source_path: string; request_key: string; recovery_id: string; saved_at: string};
export type RecoveryText = {identity_id: string; path: string; id: string; created_at: string; text: string; sha256: string; size: number};
export type TextDraft = {schema: 1; base: TextDocument; text: string; pending: TextRequest | null};
type Digest = (text: string) => Promise<string>;
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const requestKey = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{16,80}$/.test(value);
const date = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));
const invalid = () => new ApiError('文档回执不完整，请重新读取；草稿会保留。', 422);
export const textSize = (text: string) => new TextEncoder().encode(text).byteLength;
export function editableDocument(path: string, size = 0): boolean {
  const reserved = ['skills', 'skill', 'scripts', 'bin', 'node_modules', 'config', 'credentials', 'secrets', 'keys', 'hermes', 'runtime'];
  const names = ['agents.md', 'agent.md', 'skill.md', 'soul.md', 'user.md', 'memory.md', 'identity.md', 'credentials.txt', 'secrets.txt', 'passwords.txt', 'tokens.txt'];
  return safeWorkspacePath(path) && /\.(md|markdown|txt)$/i.test(path) && !path.split('/').some(part => part.startsWith('.') || reserved.includes(part.toLowerCase())) && !names.includes(path.split('/').pop()!.toLowerCase()) && size <= TEXT_LIMIT;
}
function validText(value: unknown): value is string {return typeof value === 'string' && textSize(value) <= TEXT_LIMIT && !Array.from(value).some(c => c.codePointAt(0)! >= 0xd800 && c.codePointAt(0)! <= 0xdfff) && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value) && !/-----BEGIN (?:[A-Z ]* )?PRIVATE KEY-----/.test(value);}
export function parseDocument(value: unknown, identity: string, path: string): TextDocument {
  if (!object(value) || value.identity_id !== identity || value.path !== path || !editableDocument(path) || !validText(value.text) || value.size !== textSize(value.text) || !hash(value.sha256) || !hash(value.revision) || typeof value.modified !== 'number' || !Number.isFinite(value.modified) || value.modified < 0 || value.save_mode !== (path.startsWith('imports/') ? 'copy' : 'replace') || typeof value.editable !== 'boolean' || (value.editable ? value.blocked_reason !== null : typeof value.blocked_reason !== 'string') || !Array.isArray(value.history) || value.history.length > 20 || value.history.some(item => !object(item) || !requestKey(item.id) || !date(item.created_at))) throw invalid();
  return value as TextDocument;
}
export function parseTextRequest(value: unknown): TextRequest {
  if (!object(value) || typeof value.path !== 'string' || !editableDocument(value.path) || !validText(value.text) || !hash(value.base_revision) || !hash(value.base_sha256) || !requestKey(value.request_key)) throw invalid();
  return {path: value.path, text: value.text, base_revision: value.base_revision, base_sha256: value.base_sha256, request_key: value.request_key};
}
export function parseTextDraft(value: unknown, identity: string, path: string): TextDraft {
  if (!object(value) || value.schema !== 1 || !validText(value.text)) throw invalid();
  const base = parseDocument(value.base, identity, path), pending = value.pending === null ? null : parseTextRequest(value.pending);
  if (pending && (pending.path !== path || pending.base_revision !== base.revision || pending.base_sha256 !== base.sha256 || pending.text !== value.text)) throw invalid();
  return {schema: 1, base, text: value.text, pending};
}
function expectedPath(body: TextRequest) {return body.path.startsWith('imports/') ? `documents/${body.request_key}/${body.path.split('/').pop()}` : body.path;}

export class WorkspaceTextApi {
  private token = '';
  readonly connection: Connection;
  constructor(connection: Connection, private digest: Digest, private fetcher: typeof fetch = fetch) {this.connection = {...connection, ...(connection.session ? {session: {...connection.session}} : {}), ...(connection.development ? {development: {...connection.development}} : {})};}
  private async request(path: string, body?: TextRequest, retry = true): Promise<unknown> {
    const timer = new AbortController(), timeout = setTimeout(() => timer.abort(), 20000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)), {method: body ? 'POST' : 'GET', redirect: 'error', signal: timer.signal, headers: {...connectionHeaders(this.connection), 'X-Wearing-Identity': this.connection.identity, ...(body ? {'Content-Type': 'application/json', 'X-Wearing-Token': this.token} : {})}, ...(body ? {body: JSON.stringify(body)} : {})});
      if (body && response.status === 403 && retry) {await this.bootstrap(); return this.request(path, body, false);}
      if (!response.ok) throw new ApiError(response.status === 409 ? '文档已有更新，草稿已保留。请读取最新版并比较。' : response.status === 423 ? '当前身份的任务还在执行。草稿保留，完成或停止后再保存。' : response.status === 403 ? '这份文档不开放编辑，请检查类型和权限。' : response.status === 413 ? '直接编辑支持不超过 64 KB 的文字。' : response.status === 404 ? '文档已移动或不存在，请刷新文件夹。' : '读写文档暂时失败，请重试核对原请求。', response.status);
      return await response.json();
    } catch (cause) {if (cause instanceof ApiError) throw cause; throw new ApiError(body ? '保存结果尚未确认，请取回原保存回执。' : '文档暂时无法读取。', 0);}
    finally {clearTimeout(timeout);}
  }
  private async bootstrap() {
    const value = await this.request('/api/bootstrap');
    if (!object(value) || typeof value.token !== 'string' || !value.token || !Array.isArray(value.identities) || !value.identities.some(row => object(row) && row.id === this.connection.identity)) throw invalid();
    this.token = value.token;
  }
  async load(path: string): Promise<TextDocument> {
    if (!editableDocument(path)) throw invalid();
    const result = parseDocument(await this.request('/api/workspace/text?' + new URLSearchParams({path})), this.connection.identity, path);
    if (await this.digest(result.text) !== result.sha256) throw invalid();
    return result;
  }
  async recovery(path: string, version: string): Promise<RecoveryText> {
    if (!editableDocument(path) || !requestKey(version)) throw invalid();
    const result = await this.request('/api/workspace/text/recovery?' + new URLSearchParams({path, version}));
    if (!object(result) || result.identity_id !== this.connection.identity || result.path !== path || result.id !== version || !date(result.created_at) || !validText(result.text) || result.size !== textSize(result.text) || result.sha256 !== await this.digest(result.text)) throw invalid();
    return result as RecoveryText;
  }
  async save(input: TextRequest): Promise<TextReceipt> {
    const body = parseTextRequest(input);
    if (!this.token) await this.bootstrap();
    const result = await this.request('/api/workspace/text', body);
    if (!object(result) || result.identity_id !== this.connection.identity || result.source_path !== body.path || result.path !== expectedPath(body) || result.request_key !== body.request_key || result.recovery_id !== body.request_key || result.sha256 !== await this.digest(body.text) || !hash(result.revision) || result.size !== textSize(body.text) || !date(result.saved_at) || typeof result.modified !== 'number' || !Number.isFinite(result.modified) || result.modified < 0 || result.save_mode !== (body.path.startsWith('imports/') ? 'copy' : 'replace')) throw new ApiError('保存回执尚未核对，原请求保留。请重试核对。', 0);
    return result as TextReceipt;
  }
}

/** Every keystroke is queued to scoped storage; saving drains that queue first. */
export class WorkspaceTextDrafts {
  readonly key: string;
  private tail: Promise<unknown> = Promise.resolve();
  private busy = false;
  constructor(private store: Pick<Store, 'get' | 'put'>, readonly api: WorkspaceTextApi, readonly path: string) {this.key = `workspace-text-draft:${scopeOf(api.connection)}|${encodeURIComponent(path)}`;}
  private enqueue<T>(work: () => Promise<T>): Promise<T> {const next = this.tail.then(work, work); this.tail = next.catch(() => {}); return next;}
  async get() {await this.tail; const value = await this.store.get(this.key); return value === null ? null : parseTextDraft(value, this.api.connection.identity, this.path);}
  async update(base: TextDocument, text: string) {
    if (this.busy) return Promise.reject(new ApiError('正在保存，请稍候。', 409));
    const draft = parseTextDraft({schema: 1, base, text, pending: null}, this.api.connection.identity, this.path);
    return this.enqueue(async () => {
      const old = await this.store.get(this.key);
      if (old && parseTextDraft(old, this.api.connection.identity, this.path).pending) throw new ApiError('请先取回上次保存回执。', 409);
      await this.store.put(this.key, draft); return draft;
    });
  }
  async save(base: TextDocument, text: string, key: string) {
    if (this.busy) throw new ApiError('正在保存，请稍候。', 409);
    this.busy = true;
    try {
      const old = await this.get();
      const pending = old?.pending || parseTextRequest({path: this.path, text, base_revision: base.revision, base_sha256: base.sha256, request_key: key});
      if (old?.pending && text !== old.text) throw new ApiError('请先取回上次保存回执，原草稿已保留。', 409);
      const draft: TextDraft = {schema: 1, base: old?.pending ? old.base : base, text: pending.text, pending};
      await this.store.put(this.key, draft);
      const receipt = await this.api.save(pending);
      await this.store.put(this.key, null);
      return receipt;
    } finally {this.busy = false;}
  }
  /** Only used after a definite 409 and an explicit user comparison/rebase action. */
  async rebase(latest: TextDocument, text: string) {
    if (this.busy) throw new ApiError('请等待保存结束。', 409);
    return this.enqueue(async () => {const draft = parseTextDraft({schema: 1, base: latest, text, pending: null}, this.api.connection.identity, this.path); await this.store.put(this.key, draft); return draft;});
  }
}

export function comparisonSummary(original: string, draft: string) {
  if (original === draft) return '两份文字相同。';
  const before = original.split('\n'), after = draft.split('\n');
  const first = before.findIndex((line, index) => after[index] !== line);
  return `最新版 ${before.length} 行，草稿 ${after.length} 行；从第 ${(first < 0 ? before.length : first) + 1} 行开始不同。请逐项核对后保存。`;
}
