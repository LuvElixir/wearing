import {PersonalHubApi, WorkspaceFile} from './personal-hub';

export type WorkspaceExportPorts = {
  available: () => Promise<boolean>;
  active: () => boolean;
  write: (bytes: Uint8Array, name: string) => {uri: string; remove: () => void};
  share: (uri: string, file: WorkspaceFile) => Promise<void>;
};

/** Identity/navigation changes cancel the handoff before any external app sees a file. */
export async function exportWorkspaceOriginal(api: Pick<PersonalHubApi, 'original'>, file: WorkspaceFile, ports: WorkspaceExportPorts) {
  if (!await ports.available()) throw new Error('当前设备无法打开分享面板，请在手机 App 中打开原件。');
  if (!ports.active()) return;
  const bytes = await api.original(file);
  if (!ports.active()) return;
  const basename = file.path.split(/[\\/]/).pop()!.replace(/[:*?"<>|\u0000-\u001f]/g, '_').slice(0, 180);
  const name = !basename || basename === '.' || basename === '..' ? '原件' : basename;
  const temporary = ports.write(bytes, name);
  try {
    if (!ports.active()) return;
    await ports.share(temporary.uri, file);
  } finally {temporary.remove();}
}
