import {ApiError, Connection, connectionEndpoint, connectionHeaders} from './core';

export type RemoteAsset = {id: string; mime: string; name: string};
export type OriginalSource = {uri: string; headers: Record<string, string>};
export const REMOTE_ORIGINAL_LIMIT = 15 * 1024 * 1024;
const mime = (value: string) => value.split(';', 1)[0].trim().toLowerCase();

export function remoteOriginalKind(asset: RemoteAsset): 'image' | 'audio' | 'file' {
  const type = mime(asset.mime);
  if (['image/jpeg', 'image/png', 'image/webp'].includes(type)) return 'image';
  if (['audio/wav', 'audio/x-wav', 'audio/webm', 'audio/ogg', 'audio/mpeg', 'audio/mp4', 'audio/m4a', 'audio/aac', 'audio/x-m4a'].includes(type)) return 'audio';
  return 'file';
}

export function remoteOriginalSource(connection: Connection, asset: RemoteAsset): OriginalSource {
  if (!/^asset_[A-Za-z0-9_-]{1,100}$/.test(asset.id)) throw new ApiError('原件标识无效，请刷新记录。', 422);
  return {uri: new URL('/api/life/assets/' + encodeURIComponent(asset.id), connectionEndpoint(connection)).toString(),
    headers: {...connectionHeaders(connection), 'X-Wearing-Identity': connection.identity}};
}

export function audioOriginalState(status: {error?: string | null; playbackState: string; isLoaded: boolean; isBuffering: boolean; playing: boolean}, localError = '') {
  if (localError || status.error || status.playbackState === 'error') return 'error';
  if (!status.isLoaded || status.isBuffering) return 'loading';
  return status.playing ? 'playing' : 'ready';
}

/** Bounded download used by explicit export, never by opening a record. */
export async function downloadRemoteOriginal(connection: Connection, asset: RemoteAsset, fetcher: typeof fetch = fetch): Promise<Uint8Array> {
  const source = remoteOriginalSource(connection, asset);
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetcher(source.uri, {headers: source.headers, signal: controller.signal, redirect: 'error'});
    if (!response.ok) throw new ApiError(response.status === 401 ? '连接已到期，请重新连接后打开原件。' : response.status === 404 ? '原件已不存在，请刷新记录。' : '暂时无法读取原件，请检查连接后重试。', response.status);
    const length = response.headers.get('content-length');
    if (length && (!Number.isSafeInteger(Number(length)) || Number(length) < 0 || Number(length) > REMOTE_ORIGINAL_LIMIT)) throw new ApiError('原件超过 15 MB，请在电脑上打开。', 413);
    const responseMime = mime(response.headers.get('content-type') || '');
    if (responseMime && responseMime !== 'application/octet-stream' && responseMime !== mime(asset.mime)) throw new ApiError('原件格式与记录不一致，请刷新记录后重试。', 422);
    // Bound streamed bytes even when Content-Length is absent or inaccurate.
    if (response.body?.getReader) {
      const reader = response.body.getReader(), chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (true) {
          const next = await reader.read();
          if (next.done) break;
          size += next.value.byteLength;
          if (size > REMOTE_ORIGINAL_LIMIT) {controller.abort(); throw new ApiError('原件超过 15 MB，请在电脑上打开。', 413);}
          chunks.push(next.value);
        }
      } finally {reader.releaseLock();}
      const bytes = new Uint8Array(size);
      let position = 0;
      for (const chunk of chunks) {bytes.set(chunk, position); position += chunk.byteLength;}
      return bytes;
    }
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > REMOTE_ORIGINAL_LIMIT) throw new ApiError('原件超过 15 MB，请在电脑上打开。', 413);
    return bytes;
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
    throw new ApiError('这次没能读到原件，请检查连接后重试。');
  } finally {clearTimeout(timer);}
}
