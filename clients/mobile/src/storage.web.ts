import {openDB} from 'idb';
import type {Media, Store} from './core';
const database = openDB('wearing-mobile-preview', 1, {upgrade(db) {db.createObjectStore('state'); db.createObjectStore('originals');}});
export const storage: Store = {
  async get<T>(key: string) {return (await (await database).get('state', key)) as T ?? null;},
  async put(key, value) {await (await database).put('state', value, key);},
  async batch(values) {const tx = (await database).transaction('state', 'readwrite'); for (const [key, value] of values) await tx.store.put(value, key); await tx.done;},
  async blob(id) {const value = await (await database).get('originals', id); if (!(value instanceof Blob)) throw new Error('这份本机原件暂时无法读取，请保留记录并检查存储。'); return value;}
};
export async function keepMedia(uri: string, media: Media) {
  const response = await fetch(uri); const blob = await response.blob();
  if (!blob.size) throw new Error('文件为空，请重新选择。');
  await (await database).put('originals', blob, media.id); media.size = blob.size; return media;
}
const urls = new Map<string, string>();
export async function preview(id: string) {if (!urls.has(id)) urls.set(id, URL.createObjectURL(await storage.blob(id))); return urls.get(id)!;}
