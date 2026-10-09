import {Platform} from 'react-native';
import {requireOptionalNativeModule} from 'expo';
import {Directory, File, Paths} from 'expo-file-system';
import * as Crypto from 'expo-crypto';
import {ApiError} from './core';
import {PersonalHubApi, WorkspaceFile, workspaceMimeType} from './personal-hub';
import {exportWorkspaceOriginal} from './workspace-export';

/** Export only the selected original. Auth headers are never shared with another app. */
export async function shareWorkspaceFile(api: PersonalHubApi, selected: WorkspaceFile, stillActive: () => boolean): Promise<void> {
  return shareOriginalBytes(() => api.original(selected), selected.path.split('/').pop()!, workspaceMimeType(selected.path), stillActive);
}

/** Share only local bytes. Remote URLs and authentication never enter the sheet. */
export async function shareOriginalBytes(original: () => Promise<Uint8Array>, name: string, mimeType: string, stillActive: () => boolean): Promise<void> {
  if (Platform.OS === 'web' || !requireOptionalNativeModule('ExpoSharing')) throw new Error('当前安装版尚未提供原件分享，请更新 App 后再试。');
  // Probe first so an older installed binary still opens the rest of the app.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const Sharing = require('expo-sharing') as typeof import('expo-sharing');
  try {
    await exportWorkspaceOriginal({original}, {path: name, size: 0, modified: 0}, {
      available: async () => Platform.OS !== 'web' && await Sharing.isAvailableAsync(),
      active: stillActive,
      write: (bytes, name) => {
        const temporary = new Directory(Paths.cache, 'pajio-file-' + Crypto.randomUUID());
        const remove = () => {try {if (temporary.exists) temporary.delete();} catch { /* OS cache cleanup remains a fallback. */ }};
        try {
          temporary.create();
          const file = new File(temporary, name);
          file.create(); file.write(bytes);
          return {uri: file.uri, remove};
        } catch (cause) {remove(); throw cause;}
      },
      share: uri => Sharing.shareAsync(uri, {mimeType, dialogTitle: name}),
    });
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
    throw new Error('这次没能打开原件，请重试。原文件没有改变。');
  }
}
