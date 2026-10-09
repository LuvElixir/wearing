import type {Media, Store} from './core';

/** Private on-device journal; no token, EXIF, base64 or remote URL is persisted. */
export const PICKER_RECOVERY_KEY = 'picker-recovery:v1';
export type PickedPhoto = {uri: string; name: string; mime: string; width: number; height: number};
export type PickerIntent = {id: string; scope: string; draftId: string; asset: PickedPhoto | null};
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
function photo(value: unknown): PickedPhoto {
  const a = value as Partial<PickedPhoto> | null;
  if (!a || typeof a.uri !== 'string' || !/^(file|content):\/\//.test(a.uri) || a.uri.length > 4096 || typeof a.name !== 'string' || !a.name || a.name.length > 240 || typeof a.mime !== 'string' || !/^image\/[a-z0-9.+-]+$/i.test(a.mime) || !Number.isSafeInteger(a.width) || a.width! < 1 || !Number.isSafeInteger(a.height) || a.height! < 1) throw Error('选图结果不完整，请重新选择。');
  return {uri:a.uri,name:a.name,mime:a.mime,width:a.width!,height:a.height!};
}
function rows(value: unknown): PickerIntent[] {
  if (value === null) return [];
  if (!Array.isArray(value) || value.length > 8) throw Error('上次选图记录暂时无法读取。');
  const ids = new Set<string>(); let waiting = 0;
  return value.map(raw => {
    if (!raw || !uuid.test(raw.id) || ids.has(raw.id) || typeof raw.scope !== 'string' || raw.scope.length > 2048 || typeof raw.draftId !== 'string' || !uuid.test(raw.draftId) || !(raw.asset === null || typeof raw.asset === 'object')) throw Error('上次选图记录暂时无法核对。');
    ids.add(raw.id); if (raw.asset === null && ++waiting > 1) throw Error('上次选图记录暂时无法核对。');
    return {id:raw.id,scope:raw.scope,draftId:raw.draftId,asset:raw.asset === null ? null : photo(raw.asset)};
  });
}
function resultPhoto(value: unknown): PickedPhoto | null {
  const result = value as {canceled?:unknown; assets?:unknown; code?:unknown} | null;
  if (result?.canceled === true) return null;
  if (!result || result.code || result.canceled !== false || !Array.isArray(result.assets) || result.assets.length !== 1) throw Error('系统没有返回完整图片，请重新选择。');
  const a = result.assets[0];
  return photo({uri:a?.uri,name:a?.fileName || '随手拍.jpg',mime:a?.mimeType || 'image/jpeg',width:a?.width,height:a?.height});
}

/** Callers hold the capture lock. The queue also prevents Strict Mode/refresh overlap. */
export class PickerRecovery {
  private tail: Promise<unknown> = Promise.resolve();
  constructor(private store: Store, private id: () => string) {}
  private serial<T>(operation: () => Promise<T>): Promise<T> {
    const run = this.tail.then(operation); this.tail = run.catch(() => {}); return run;
  }
  private async collect(getPending: () => Promise<unknown>) {
    const entries = rows(await this.store.get(PICKER_RECOVERY_KEY));
    const waiting = entries.find(item => item.asset === null);
    const pending = await getPending();
    // The OS does not attach an account or operation id. Without our pre-launch
    // proof, never attach its result to whichever account happens to be open.
    if (pending === null || !waiting) return entries;
    const asset = resultPhoto(pending);
    const next = asset ? entries.map(item => item.id === waiting.id ? {...item,asset} : item) : entries.filter(item => item.id !== waiting.id);
    await this.store.put(PICKER_RECOVERY_KEY,next); return next;
  }
  collectPending(getPending: () => Promise<unknown>) {return this.serial(() => this.collect(getPending));}
  begin(scope: string, draftId: string, getPending: () => Promise<unknown>, isCurrent: () => boolean) {
    return this.serial(async () => {
      const entries = (await this.collect(getPending)).filter(item => item.asset !== null);
      if (!isCurrent()) throw Error('账户已切换，没有打开选图。');
      if (entries.length >= 8) throw Error('有多份照片尚未恢复，请先回到原账户的草稿。');
      const intent = {id:this.id(),scope,draftId,asset:null};
      rows([...entries,intent]);
      await this.store.put(PICKER_RECOVERY_KEY,[...entries,intent]);
      if (!isCurrent()) throw Error('账户已切换，没有打开选图。');
      return intent;
    });
  }
  accept(intent: PickerIntent, result: unknown) {
    return this.serial(async () => {
      const entries = rows(await this.store.get(PICKER_RECOVERY_KEY));
      const original = entries.find(item => item.id === intent.id && item.scope === intent.scope && item.draftId === intent.draftId && item.asset === null);
      if (!original) throw Error('这次选图已经结束，没有加入其他草稿。');
      const asset = resultPhoto(result);
      await this.store.put(PICKER_RECOVERY_KEY,asset ? entries.map(item => item.id === intent.id ? {...item,asset} : item) : entries.filter(item => item.id !== intent.id));
    });
  }
  apply<T extends {id:string;media:Media[]}>(scope: string, draft: T, isCurrent: () => boolean, save: (asset: PickedPhoto,id: string) => Promise<Media>) {
    return this.serial(async () => {
      let entries = rows(await this.store.get(PICKER_RECOVERY_KEY)), next = draft;
      for (const intent of entries.filter(item => item.scope === scope && item.draftId === draft.id && item.asset)) {
        if (!isCurrent()) throw Error('账户已切换，照片仍保留在原身份。');
        const existing = next.media.find(media => media.id === intent.id);
        if (!existing && next.media.length >= 4) throw Error('一次最多放四份原件，上次照片仍保留在本机。');
        const media = existing || await save(intent.asset!,intent.id);
        if (media.id !== intent.id || !Number.isFinite(media.size) || media.size <= 0 || media.size > 15*1024*1024) throw Error('照片没有完整保存，请重新打开草稿。');
        if (!isCurrent()) throw Error('账户已切换，照片仍保留在原身份。');
        next = existing ? next : {...next,media:[...next.media,media]};
        entries = entries.filter(item => item.id !== intent.id);
        // A restart sees either the original journal, or the completed draft.
        await this.store.batch([[`draft:${scope}`,next],[PICKER_RECOVERY_KEY,entries]]);
      }
      return next;
    });
  }
}
