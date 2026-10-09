import {ApiError, Connection, connectionEndpoint, connectionHeaders, WearingApi} from './core';
import {safeWorkspacePath, WorkspaceFile} from './personal-hub';
export type ImportRequest = {id: string; name: string; mediaId: string; size: number};
export const IMPORT_LIMIT = 20 * 1024 * 1024;
export function importReceipt(value: unknown, request: ImportRequest): WorkspaceFile {
  const data = value as {request_key?: unknown; sha256?: unknown; file?: WorkspaceFile} | null, file = data?.file;
  if (data?.request_key !== request.id || typeof data.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(data.sha256) || !file || !safeWorkspacePath(file.path) || file.path !== `imports/${request.id}/${request.name.normalize('NFC').trim()}` || file.size !== request.size || !Number.isFinite(file.modified)) throw new ApiError('尚未取得完整导入回执，请重试核对。', 422);
  return file;
}
export async function uploadWorkspace(connection: Connection, request: ImportRequest, blob: Blob, fetcher: typeof fetch = fetch): Promise<WorkspaceFile> {
  if (blob.size !== request.size || request.size <= 0 || request.size > IMPORT_LIMIT) throw new ApiError('请选择非空且不超过 20 MB 的文件。', 413);
  const api = new WearingApi(connection, fetcher), token = await api.voiceAuthorization();
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetcher(new URL('/api/workspace/import?' + new URLSearchParams({name: request.name, request_key: request.id}), connectionEndpoint(connection)).toString(), {method: 'POST', body: blob, redirect: 'error', signal: controller.signal,
      headers: {...connectionHeaders(connection), 'X-Wearing-Identity': connection.identity, 'X-Wearing-Token': token, 'Content-Type': 'application/octet-stream'}});
    const data = await response.json();
    if (!response.ok) throw new ApiError(typeof data?.detail === 'string' ? data.detail : '文件暂时没有导入成功，请重试。', response.status);
    return importReceipt(data, request);
  } catch (error) {if (error instanceof ApiError) throw error; throw new ApiError('尚未确认导入结果，原件已保留。重试会核对同一份文件。');}
  finally {clearTimeout(timer);}
}
