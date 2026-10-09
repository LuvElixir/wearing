import * as Crypto from 'expo-crypto';
import {Directory, File, FileMode, Paths} from 'expo-file-system';
import {type Connection, scopeOf} from './core';
import {fenceFor, keyScope, ownedScope} from './account-cleanup-model';
import {withNativeState} from './storage';
import {upsertState} from './account-cleanup-state';
import {CHAT_IMPORT_LIMITS, parseChatImport} from './chat-import-parser';
import type {ChatImportDraft, ChatImportPending} from './chat-import-client';
import type {ShareEntry} from './share-intake-model';
const stopped = new WeakSet<Connection>();
export const chatImportWorkAllowed = (connection: Connection) => !stopped.has(connection);
export async function readChatImportFile(uri: string, name: string, active: () => boolean): Promise<ChatImportDraft> {
  const source = new File(uri);
  if (source.size > CHAT_IMPORT_LIMITS.fileBytes) throw new Error('聊天文件最多 15 MB，请减少所选消息。');
  const handle = source.open(FileMode.ReadOnly), chunks: Uint8Array[] = []; let total = 0;
  try {
    while (true) {
      if (!active()) throw new Error('身份已切换，已停止读取聊天。');
      const chunk = handle.readBytes(64 * 1024); if (!chunk.length) break;
      total += chunk.length; if (total > CHAT_IMPORT_LIMITS.fileBytes) throw new Error('聊天文件超过 15 MB。');
      chunks.push(chunk); await new Promise<void>(resolve => setTimeout(resolve, 0));
    }
  } finally {handle.close();}
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.length;}
  const preview = await parseChatImport(bytes, name, active);
  const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, bytes);
  if (!active()) throw new Error('身份已切换，已停止读取聊天。');
  return {version: 1, key: Crypto.randomUUID(), sourceHash: Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join(''), preview, selfAuthor: null};
}
/** Only a DocumentPicker-owned cache copy; never remove a provider's original. */
export function discardChatPickerCopy(uri: string) {
  const cache = Paths.cache.uri.replace(/\/$/, '') + '/';
  if (uri.startsWith(cache) && !uri.slice(cache.length).includes('..')) {const file = new File(uri); if (file.exists) file.delete();}
}
/** Logout removes private preview/body copies, while a body-free request key
 * remains to query an unknown result after signing back into the same identity. */
export async function clearChatImportPrivateDrafts(connection: Connection) {
  stopped.add(connection);
  await withNativeState(async db => {
    const snapshot = await db.getFirstAsync<{rows: string}>("SELECT json_group_array(json_object('key',key,'value',value)) AS rows FROM local_state");
    const rows = JSON.parse(snapshot?.rows || '[]') as {key: string; value: string}[];
    const belongs = (key: string) => connection.session ? ownedScope(keyScope(key), fenceFor(connection)) : key.endsWith(scopeOf(connection));
    const shares = new Set<string>();
    for (const row of rows) {
      if (!belongs(row.key)) continue;
      if (row.key.startsWith('chat-import-draft:v1:')) {
        const value = JSON.parse(row.value) as ChatImportDraft | null; if (value?.shareId) shares.add(value.shareId);
        await upsertState(db, row.key, null);
      } else if (row.key.startsWith('chat-import-pending:v1:')) {
        const value = JSON.parse(row.value) as ChatImportPending | null;
        if (value?.shareId) shares.add(value.shareId);
        if (value) await upsertState(db, row.key, {version: 1, key: value.key, request: null});
      }
    }
    const shareRow = rows.find(row => row.key === 'share-intake:v1');
    if (shareRow) {
      const entries = JSON.parse(shareRow.value) as ShareEntry[];
      for (let index = 0; index < entries.length; index++) {
        const entry = entries[index];
        // A claimed share can fail parsing before a draft exists. Include it
        // directly, and keep its inventory until deletion succeeds so retry
        // after a full disk / locked file never loses the cleanup reference.
        const owned = typeof entry.scope === 'string' && (connection.session ? ownedScope(entry.scope, fenceFor(connection)) : entry.scope === scopeOf(connection));
        if (!owned || entry.action !== 'chat-import' && !shares.has(entry.id)) continue;
        if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(entry.id)) throw new Error('聊天分享清理编号无法核对，请重试。');
        const folder = new Directory(Paths.document, 'share-intake', entry.id);
        if (folder.exists) folder.delete();
        entries[index] = {...entry, state: 'cancelled', text: '', files: []};
        await upsertState(db, shareRow.key, entries);
      }
    }
  });
}
