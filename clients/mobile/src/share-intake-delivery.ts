import {ApiError, Connection, makeDraft, Outbox, Pending, scopeOf, Store} from './core';
import {safeWorkspacePath, WorkspaceFile} from './personal-hub';
import {ImportRequest, uploadWorkspace} from './workspace-import';
import {parseShareManifest, SHARE_ID, ShareReceipt, ShareSubmission} from './share-intake-model';

type DeliveryState = {version: 1; requestId: string; scope: string; signature: string; createdAt: string; uploaded: WorkspaceFile[]; state: 'uploading' | 'completed'};
export type ShareCaptureDependencies = {
  store: Store;
  outbox: Pick<Outbox, 'enqueue'>;
  readFile: (uri: string) => Promise<Blob>;
  fetcher?: typeof fetch;
  isCurrent?: () => boolean;
  upload?: typeof uploadWorkspace;
};
export const shareDeliveryKey = (scope: string, id: string) => `share-delivery:v1:${scope}:${id}`;
const queues = new WeakMap<Store, Map<string, Promise<unknown>>>();
function exclusive<T>(store: Store, key: string, work: () => Promise<T>): Promise<T> {
  let locks = queues.get(store); if (!locks) {locks = new Map(); queues.set(store, locks);}
  const result = (locks.get(key) || Promise.resolve()).catch(() => {}).then(work), settled = result.catch(() => {});
  locks.set(key, settled);
  void settled.then(() => {if (locks!.get(key) === settled) locks!.delete(key);});
  return result;
}

function plan(submission: ShareSubmission) {
  if (submission.files.some(file => /\.zip$/i.test(file.path) || ['application/zip','application/x-zip-compressed'].includes(file.mime))) throw new ApiError('聊天 ZIP 必须先预览选定消息，不能直接作为普通记录上传。', 422);
  if (!SHARE_ID.test(submission.requestId)) throw new ApiError('分享编号无效，请重新分享。', 422);
  parseShareManifest({version: 1, id: submission.requestId, createdAt: '2000-01-01T00:00:00Z', text: submission.text, files: submission.files});
  const requests: ImportRequest[] = submission.files.map((file, index) => {
    const name = file.name.normalize('NFC').trim();
    if (name.startsWith('.') || new TextEncoder().encode(name).length > 180) throw new ApiError('分享文件名太长或以点开头，请改名后重新分享。', 422);
    if (!file.uri.startsWith('file://')) throw new ApiError('分享文件还没有完整保存在手机。', 422);
    return {id: `share-${submission.requestId}-file-${index}`, name, mediaId: file.id, size: file.size};
  });
  const paths = requests.map(request => `imports/${request.id}/${request.name}`);
  // The complete note length is checked BEFORE any upload. Never trim the user's
  // 12k text to make room for generated attachment references.
  const text = noteText(submission.text, paths);
  makeDraft(text, 'note');
  return {requests, paths, text};
}
function noteText(text: string, paths: string[]) {
  return [text, paths.length ? '分享文件（已导入文件夹）：\n' + paths.map(value => `- ${value}`).join('\n') : ''].filter(Boolean).join('\n\n');
}
function validFile(file: WorkspaceFile, request: ImportRequest, expectedPath: string) {
  return !!file && file.path === expectedPath && safeWorkspacePath(file.path) && file.size === request.size && Number.isFinite(file.modified);
}

/** Explicit-click receiver. All files use the workspace binary upload API,
 * including images/PDFs; the capture outbox receives a text-only note. */
export function createShareCaptureHandler(connection: Connection, dependencies: ShareCaptureDependencies) {
  const scope = scopeOf(connection), {store, outbox} = dependencies;
  return (submission: ShareSubmission): Promise<ShareReceipt> => {
    if (submission.scope !== scope) return Promise.reject(new ApiError('身份已切换，请回到原身份处理这份分享。', 409));
    const key = shareDeliveryKey(scope, submission.requestId);
    return exclusive(store, key, async () => {
      const prepared = plan(submission);
      const signature = JSON.stringify({text: submission.text, files: prepared.requests.map(({id, name, size}) => ({id, name, size})), types: submission.files.map(file => file.mime)});
      const stored = await store.get<DeliveryState>(key);
      if (stored && (stored.version !== 1 || stored.requestId !== submission.requestId || stored.scope !== scope || stored.signature !== signature)) throw new ApiError('同一分享编号的内容发生变化，请重新分享。', 409);
      if (stored?.state === 'completed') return {requestId: submission.requestId, scope};
      const state: DeliveryState = stored || {version: 1, requestId: submission.requestId, scope, signature, createdAt: new Date().toISOString(), uploaded: [], state: 'uploading'};
      if (!Array.isArray(state.uploaded) || state.uploaded.length > prepared.requests.length || state.uploaded.some((file, i) => !validFile(file, prepared.requests[i], prepared.paths[i]))) throw new ApiError('分享导入回执不完整，请在原身份核对文件夹。', 422);
      const ensureCurrent = () => {if (dependencies.isCurrent && !dependencies.isCurrent()) throw new ApiError('身份或连接已切换，已导入的文件保留在原身份，请回到原身份重试。', 409);};
      ensureCurrent(); await store.put(key, state);
      for (let index = state.uploaded.length; index < prepared.requests.length; index++) {
        ensureCurrent();
        const blob = await dependencies.readFile(submission.files[index].uri);
        if (blob.size !== prepared.requests[index].size) throw new ApiError('本机分享文件已发生变化，请重新分享。', 409);
        ensureCurrent();
        const receipt = await (dependencies.upload || uploadWorkspace)(connection, prepared.requests[index], blob, dependencies.fetcher);
        if (!validFile(receipt, prepared.requests[index], prepared.paths[index])) throw new ApiError('没有收到完整文件导入回执，请重试核对同一份文件。', 422);
        // A late receipt still belongs to the original scope. Save it, then stop
        // before the next file / note when identity changes during the request.
        state.uploaded.push(receipt); await store.put(key, state);
      }
      ensureCurrent();
      const draft = makeDraft(noteText(submission.text, state.uploaded.map(file => file.path)), 'note');
      const entry: Pending = {id: `share-${submission.requestId}`, scope, draft, media: [], uploaded: [], organize: false, state: 'pending', attempts: 0, nextAt: 0, createdAt: state.createdAt};
      const completed: DeliveryState = {...state, state: 'completed'};
      // Outbox commits both in one Store.batch transaction. Therefore a flush
      // can never remove the outbox item before the durable intake receipt exists.
      await outbox.enqueue(entry, [key, completed]);
      const committed = await store.get<DeliveryState>(key);
      if (committed?.state !== 'completed' || committed.signature !== signature) throw new ApiError('尚未确认记录已加入同步队列，请重试核对。');
      return {requestId: submission.requestId, scope};
    });
  };
}
