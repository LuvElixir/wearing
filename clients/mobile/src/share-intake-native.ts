import {Directory, File, FileMode, Paths} from 'expo-file-system';
import * as Crypto from 'expo-crypto';
import * as Sharing from 'expo-sharing';
import {Platform} from 'react-native';
import {storage} from './storage';
import {IntakeFile, parseShareManifest, SHARE_ID, SHARE_LIMITS, SHARE_MIMES, ShareEntry, ShareIntakeQueue, ShareManifest, shareWebUrl} from './share-intake-model';

export const SHARE_APP_GROUP = 'group.io.luckyloading.wearing.mobile.share';
const INDEX = 'share-intake:v1', JOURNAL = 'share-intake:android-journal:v1';
const root = () => new Directory(Paths.document, 'share-intake');
const mimeExtension: Record<string, string> = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif', 'image/heic': 'heic', 'image/webp': 'webp', 'application/pdf': 'pdf', 'text/plain': 'txt', 'text/markdown': 'md', 'application/zip': 'zip', 'application/x-zip-compressed': 'zip'};
let intakeTail: Promise<unknown> = Promise.resolve();

// Never use getResolvedSharedPayloadsAsync: it can fetch shared URLs before the
// user has chosen an identity or consented to an action.
async function copyBounded(uri: string, destination: File, expected?: number) {
  const input = new File(uri).open(FileMode.ReadOnly);
  let output: ReturnType<File['open']> | null = null;
  let size = 0;
  try {
    destination.create({overwrite: true}); output = destination.open(FileMode.WriteOnly);
    while (true) {
      const bytes = input.readBytes(64 * 1024);
      if (!bytes.length) break;
      size += bytes.length;
      if (size > SHARE_LIMITS.fileBytes || (expected !== undefined && size > expected)) throw new Error('文件超过 15 MB，或分享文件已发生变化。');
      output.writeBytes(bytes);
      // Yield between bounded blocks; no 15 MB synchronous read on the UI thread.
      await new Promise<void>(resolve => setTimeout(resolve, 0));
    }
    if (!size || (expected !== undefined && expected !== size)) throw new Error('分享文件不完整，请重新分享。');
    return size;
  } finally {input.close(); output?.close();}
}

async function stage(manifest: ShareManifest, sources: string[]): Promise<IntakeFile[]> {
  root().create({idempotent: true, intermediates: true});
  const staging = new Directory(root(), `.${manifest.id}`), destination = new Directory(root(), manifest.id);
  if (staging.exists) staging.delete();
  staging.create();
  try {
    for (let index = 0; index < manifest.files.length; index++) {
      await copyBounded(sources[index], new File(staging, manifest.files[index].path), manifest.files[index].size);
    }
    // A crash between move and index write is recovered with this same id.
    if (destination.exists) destination.delete();
    staging.move(destination);
    return manifest.files.map((file, index) => ({...file, id: `share-${manifest.id}-${index}`, uri: new File(destination, file.path).uri}));
  } catch (error) {if (staging.exists) staging.delete(); throw error;}
}

export const shareIntakeQueue = new ShareIntakeQueue({
  async read() {
    const entries = await storage.get<ShareEntry[]>(INDEX) || [];
    // iOS can change the container prefix during an app update.
    return entries.map(entry => ({...entry, files: entry.files.map(file => ({...file, uri: new File(root(), entry.id, file.path).uri}))}));
  },
  async write(entries) {await storage.put(INDEX, entries);},
  stage,
  async discard(id) {if (!SHARE_ID.test(id)) throw new Error('无效分享编号。'); const folder = new Directory(root(), id); if (folder.exists) folder.delete();},
});

async function receiveIOS() {
  const container = Paths.appleSharedContainers[SHARE_APP_GROUP];
  // The older native build can run the JS update; it just has no share target.
  if (!container) return;
  const inbox = new Directory(container, 'pajio-share-inbox');
  if (!inbox.exists) return;
  const folders = inbox.list().filter((entry): entry is Directory => entry instanceof Directory && SHARE_ID.test(entry.name)).sort((a, b) => a.name.localeCompare(b.name));
  for (const folder of folders) {
    const file = new File(folder, 'manifest.json');
    if (!file.exists || file.size > 96 * 1024) throw new Error('有一份分享未能读取，请重新分享或清除无法读取的副本。');
    const manifest = parseShareManifest(JSON.parse(await file.text()));
    if (manifest.id !== folder.name) throw new Error('分享编号不匹配。');
    await shareIntakeQueue.ingest(manifest, manifest.files.map(item => new File(folder, item.path).uri));
    folder.delete(); // Only after the private copy and durable index exist.
  }
}

async function fingerprint(payloads: Sharing.SharePayload[]) {
  return Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, JSON.stringify(payloads));
}
type AndroidJournal = {fingerprint: string; id: string; createdAt: string; cleared: boolean};
async function receiveAndroid() {
  const payloads = Sharing.getSharedPayloads();
  if (!payloads.length) return;
  if (payloads.length > 5) throw new Error('一次最多分享 4 个文件和一段文字。');
  const signature = await fingerprint(payloads);
  const previous = await storage.get<AndroidJournal>(JOURNAL);
  const journal: AndroidJournal = previous && !previous.cleared && previous.fingerprint === signature ? previous : {fingerprint: signature, id: Crypto.randomUUID(), createdAt: new Date().toISOString(), cleared: false};
  await storage.put(JOURNAL, journal);
  if (await shareIntakeQueue.received(journal.id)) {
    if (await fingerprint(Sharing.getSharedPayloads()) === signature) Sharing.clearSharedPayloads();
    await storage.put(JOURNAL, {...journal, cleared: true});
    return;
  }
  const temporary = new Directory(Paths.cache, `pajio-share-${journal.id}`);
  temporary.create({idempotent: true, intermediates: true});
  try {
    const texts: string[] = [], files: ShareManifest['files'] = [], sources: string[] = [];
    let total = 0;
    for (const payload of payloads) {
      if (typeof payload.value !== 'string') throw new Error('分享内容不完整。');
      const providerFile = payload.value.startsWith('content://');
      if (!providerFile && (payload.shareType === 'text' || payload.shareType === 'url')) {
        if (payload.value.length > SHARE_LIMITS.text) throw new Error('分享文字最多 12000 字。');
        texts.push(payload.shareType === 'url' ? shareWebUrl(payload.value) : payload.value);
      } else {
        const mime = payload.mimeType?.toLowerCase() || '';
        // Only grant-bearing provider URIs; never open an arbitrary file:// path
        // supplied by another app, including paths inside Pajio's sandbox.
        if (!payload.value.startsWith('content://') || !SHARE_MIMES.has(mime) || files.length >= 4) throw new Error('支持最多 4 个图片、PDF、文字或聊天 ZIP 文件，请重新选择。');
        const path = `${files.length}.${mimeExtension[mime]}`, destination = new File(temporary, path);
        const size = await copyBounded(payload.value, destination);
        total += size;
        if (total > SHARE_LIMITS.totalBytes) throw new Error('每次分享文件总计最多 30 MB。');
        files.push({path, name: `分享文件 ${files.length + 1}.${mimeExtension[mime]}`, mime, size}); sources.push(destination.uri);
      }
    }
    await shareIntakeQueue.ingest({version: 1, id: journal.id, createdAt: journal.createdAt, text: texts.join('\n\n'), files}, sources);
    // A newer incoming intent must not be cleared by an older slow file copy.
    if (await fingerprint(Sharing.getSharedPayloads()) === signature) Sharing.clearSharedPayloads();
    await storage.put(JOURNAL, {...journal, cleared: true});
  } finally {if (temporary.exists) temporary.delete();}
}

export function receiveSharedIntake(): Promise<void> {
  const receive = async () => {if (Platform.OS === 'ios') await receiveIOS(); else if (Platform.OS === 'android') await receiveAndroid();};
  const next = intakeTail.then(receive, receive); intakeTail = next.catch(() => {}); return next;
}

export function shareIntakeAvailable() {
  return Platform.OS === 'android' || (Platform.OS === 'ios' && !!Paths.appleSharedContainers[SHARE_APP_GROUP]);
}
