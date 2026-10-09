export const SHARE_LIMITS = {files: 4, fileBytes: 15 * 1024 * 1024, totalBytes: 30 * 1024 * 1024, text: 12000, pending: 8} as const;
export const SHARE_MIMES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/heic', 'image/webp', 'application/pdf', 'text/plain', 'text/markdown', 'application/zip', 'application/x-zip-compressed']);
export const SHARE_ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
export type ShareFile = {path: string; name: string; mime: string; size: number};
export type ShareManifest = {version: 1; id: string; createdAt: string; text: string; files: ShareFile[]};
export type IntakeFile = ShareFile & {id: string; uri: string};
export type ShareAction = 'capture' | 'draft' | 'bookmark';
export type ShareEntry = Omit<ShareManifest, 'files'> & {files: IntakeFile[]; state: 'pending' | 'bound' | 'completed' | 'cancelled'; scope?: string; action?: ShareAction | 'chat-import'};
export type ShareSubmission = {requestId: string; scope: string; text: string; files: IntakeFile[]};
export type ShareReceipt = {requestId: string; scope: string};
export type ShareHandler = (submission: ShareSubmission) => Promise<ShareReceipt>;
export type ShareQueueIO = {
  read(): Promise<ShareEntry[]>;
  write(entries: ShareEntry[]): Promise<void>;
  stage(manifest: ShareManifest, sources: string[]): Promise<IntakeFile[]>;
  discard(id: string): Promise<void>;
};

export function parseShareManifest(raw: unknown): ShareManifest {
  if (!raw || typeof raw !== 'object') throw new Error('分享内容格式不正确。');
  const m = raw as Partial<ShareManifest>;
  if (m.version !== 1 || typeof m.id !== 'string' || !SHARE_ID.test(m.id) || typeof m.createdAt !== 'string' || !Number.isFinite(Date.parse(m.createdAt))) throw new Error('分享记录不完整，请重新分享。');
  if (typeof m.text !== 'string' || m.text.length > SHARE_LIMITS.text || m.text.includes('\0')) throw new Error('分享文字最多 12000 字，且不能包含空字符。');
  if (!Array.isArray(m.files) || m.files.length > SHARE_LIMITS.files) throw new Error('一次最多分享 4 个文件。');
  let total = 0;
  const paths = new Set<string>();
  const files = m.files.map(file => {
    if (!file || typeof file !== 'object' || typeof file.path !== 'string' || !/^[0-3]\.(jpg|jpeg|png|gif|heic|webp|pdf|txt|md|zip)$/.test(file.path) || paths.has(file.path)) throw new Error('分享文件路径无效，请重新分享。');
    paths.add(file.path);
    if (typeof file.name !== 'string' || !file.name.trim() || file.name.length > 160 || /[\x00-\x1f/\\]/.test(file.name)) throw new Error('分享文件名无效。');
    if (!SHARE_MIMES.has(file.mime)) throw new Error('这种文件格式暂不支持。');
    if (!Number.isSafeInteger(file.size) || file.size <= 0 || file.size > SHARE_LIMITS.fileBytes) throw new Error('每个分享文件最多 15 MB，且不能为空。');
    total += file.size;
    return {path: file.path, name: file.name, mime: file.mime, size: file.size};
  });
  if (total > SHARE_LIMITS.totalBytes) throw new Error('每次分享文件总计最多 30 MB。');
  if (!m.text.trim() && !files.length) throw new Error('分享里没有可导入的内容。');
  return {version: 1, id: m.id, createdAt: m.createdAt, text: m.text, files};
}

export function shareWebUrl(value: string) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) throw new Error('仅支持没有登录凭据的网页链接。');
  return url.href;
}

export class ShareIntakeQueue {
  private tail: Promise<unknown> = Promise.resolve();
  constructor(private io: ShareQueueIO) {}
  private serial<T>(fn: () => Promise<T>): Promise<T> {
    const next = this.tail.then(fn, fn);
    this.tail = next.catch(() => {});
    return next;
  }
  list(scope: string) {
    return this.serial(async () => (await this.io.read()).filter(item => (item.state === 'pending' || item.state === 'bound') && (!item.scope || item.scope === scope)));
  }
  received(id: string) {return this.serial(async () => (await this.io.read()).some(item => item.id === id));}
  ingest(raw: unknown, sources: string[]) {
    return this.serial(async () => {
      const manifest = parseShareManifest(raw);
      const entries = await this.io.read();
      const previous = entries.find(item => item.id === manifest.id);
      // A retry can never resurrect a dismissed/imported request, or replace it.
      if (previous) return previous;
      if (entries.filter(item => item.state === 'pending' || item.state === 'bound').length >= SHARE_LIMITS.pending) throw new Error('待处理分享已满，请先处理已有的 8 份分享。');
      if (sources.length !== manifest.files.length) throw new Error('分享附件不完整，请重新分享。');
      const files = await this.io.stage(manifest, sources);
      if (files.length !== manifest.files.length || files.some((file, i) => file.size !== manifest.files[i].size)) throw new Error('分享文件没有完整保存在手机。');
      const entry: ShareEntry = {...manifest, files, state: 'pending'};
      // Completed tombstones prevent interrupted intake from resurrecting data.
      await this.io.write([...entries, entry]);
      return entry;
    });
  }
  claimChatImport(id: string, scope: string) {
    return this.serial(async () => {
      if (!scope) throw new Error('请先选择身份。');
      const entries = await this.io.read(), index = entries.findIndex(item => item.id === id), entry = entries[index];
      if (!entry || !['pending','bound'].includes(entry.state) || entry.scope && entry.scope !== scope || entry.action && entry.action !== 'chat-import') throw new Error('这份分享已在其他身份处理或已完成。');
      entries[index] = {...entry, scope, action: 'chat-import'}; await this.io.write(entries); return entries[index];
    });
  }
  beginChatImport(id: string, scope: string) {
    return this.serial(async () => {
      const entries = await this.io.read(), index = entries.findIndex(item => item.id === id), entry = entries[index];
      if (!entry || entry.scope !== scope || entry.action !== 'chat-import' || !['pending','bound'].includes(entry.state)) throw new Error('这份分享已改变，请回到分享收件箱核对。');
      entries[index] = {...entry, state: 'bound'}; await this.io.write(entries);
    });
  }
  completeChatImport(id: string, scope: string) {
    return this.serial(async () => {
      const entries = await this.io.read(), index = entries.findIndex(item => item.id === id), entry = entries[index];
      if (!entry || entry.scope !== scope || !['pending','bound','completed'].includes(entry.state)) throw new Error('分享归属无法核对，请回到原身份重试。');
      entries[index] = {...entry, state:'completed', text:'', files:[]}; await this.io.write(entries); await this.io.discard(id);
    });
  }
  submit(id: string, scope: string, action: ShareAction, handler: ShareHandler) {
    return this.serial(async () => {
      if (!scope) throw new Error('请先选择要使用的身份。');
      const entries = await this.io.read(), index = entries.findIndex(item => item.id === id);
      const entry = entries[index];
      if (!entry || entry.state === 'cancelled') throw new Error('这份分享已取消或不存在。');
      if ((entry.scope && entry.scope !== scope) || (entry.action && entry.action !== action)) throw new Error('这份分享已经选择了身份和用途，请在原身份确认处理结果。');
      if (entry.files.some(file => file.mime === 'application/zip' || file.mime === 'application/x-zip-compressed' || /\.zip$/i.test(file.path))) throw new Error('聊天 ZIP 请通过选定聊天导入，先预览消息再确认。');
      if (entry.state === 'completed') return {requestId: id, scope};
      if (!['capture', 'draft', 'bookmark'].includes(action)) throw new Error('请选择一种有效用途。');
      if (action !== 'capture' && entry.files.length) throw new Error('有附件的分享请导入记录，再交给 Pajio 使用。');
      const bound: ShareEntry = {...entry, scope, action, state: 'bound'};
      entries[index] = bound;
      await this.io.write(entries);
      // Bound state survives crashes. A retry uses the exact same request ID,
      // account/identity and action. The receiving draft writer must be idempotent.
      const receipt = await handler({requestId: id, scope, text: bound.text, files: bound.files});
      if (receipt?.requestId !== id || receipt.scope !== scope) throw new Error('尚未确认保存结果，请在当前身份重试核对。');
      entries[index] = {...bound, state: 'completed', text: '', files: []};
      await this.io.write(entries);
      await this.io.discard(id).catch(() => {});
      return receipt;
    });
  }
  cancel(id: string) {
    return this.serial(async () => {
      const entries = await this.io.read(), index = entries.findIndex(item => item.id === id);
      const entry = entries[index];
      if (!entry || entry.state === 'cancelled') return;
      if (entry.state !== 'pending') throw new Error('这份分享的保存结果尚需核对，请先在原身份重试。');
      entries[index] = {...entry, state: 'cancelled', text: '', files: []};
      await this.io.write(entries);
      await this.io.discard(id);
    });
  }
}
