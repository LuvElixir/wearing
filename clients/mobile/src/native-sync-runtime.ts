import {Platform} from 'react-native';
import {requireOptionalNativeModule} from 'expo';
import * as Crypto from 'expo-crypto';
import type * as Calendar from 'expo-calendar/legacy';
import {type Connection, scopeOf} from './core';
import {storage} from './storage';
import {serviceFetch} from './transport';
import {boundedNativeRead} from './nativeConnectionsModel';
import {chooseNativeSync, runNativeSync, SyncPermissionLost} from './native-sync-engine';
import {eventSnapshot, reminderSnapshot, syncWindow, type SyncSource} from './native-sync-model';
import {NativeSyncClient} from './native-sync-client';

type Signal = {scope:string;run:boolean};
const listeners = new Set<(signal:Signal)=>void>();
const versions = new Map<string,number>();
const changing = new Set<string>();
export const nativeSyncNonce = () => Crypto.randomUUID().replaceAll('-','');
export const nativeSyncVersion = (scope:string) => versions.get(scope) || 0;
export function requestNativeSync(scope:string, run = true) {
  versions.set(scope,nativeSyncVersion(scope)+1);
  for (const listener of listeners) listener({scope,run});
}
export function observeNativeSync(listener:(signal:Signal)=>void) {listeners.add(listener); return () => {listeners.delete(listener);};}
function calendarApi(): typeof Calendar | null {
  if (Platform.OS === 'web' || !requireOptionalNativeModule('ExpoCalendar')) return null;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('expo-calendar/legacy') as typeof Calendar;
}
async function permitted(api:typeof Calendar,kind:SyncSource['kind'], ask:boolean) {
  if (kind === 'reminder' && Platform.OS !== 'ios') throw new SyncPermissionLost('Apple 提醒事项只在 iPhone 上提供。');
  const get = kind === 'event' ? api.getCalendarPermissionsAsync : api.getRemindersPermissionsAsync;
  const request = kind === 'event' ? api.requestCalendarPermissionsAsync : api.requestRemindersPermissionsAsync;
  let permission = await get();
  if (!permission.granted && ask && permission.canAskAgain) permission = await request();
  if (!permission.granted) throw new SyncPermissionLost('系统权限已关闭，同步已停止。重新允许后，请再次选择并启用同步。');
}
export async function discoverNativeSyncSources(kind:SyncSource['kind']):Promise<SyncSource[]> {
  const api = calendarApi();
  if (!api) throw new Error('当前安装版没有系统日历能力。');
  await permitted(api,kind,true);
  const rows = await boundedNativeRead(api.getCalendarsAsync(kind),'来源列表读取超时。');
  await permitted(api,kind,false);
  return rows.map(row=>({kind,id:row.id,title:(row.title || '未命名列表').slice(0,200)}));
}
export async function saveNativeSyncChoice(connection:Connection,desired:{enabled:boolean;sources:SyncSource[]}) {
  const scope = scopeOf(connection);
  changing.add(scope);
  requestNativeSync(scope,false); // Invalidate late OS and HTTP responses before awaiting local storage.
  const value = await chooseNativeSync(storage,scope,desired,nativeSyncNonce);
  // A failed local write keeps collection suspended until the user successfully saves again.
  changing.delete(scope);
  requestNativeSync(scope); return value;
}
export async function performNativeSync(connection:Connection,active:()=>boolean,signal:AbortSignal,changed:()=>void) {
  const api = calendarApi();
  if (!api) return;
  const scope = scopeOf(connection), version = nativeSyncVersion(scope);
  const current = () => active() && !signal.aborted && !changing.has(scope) && nativeSyncVersion(scope) === version;
  const allowed = async (sources:SyncSource[]) => {
    for (const kind of ['event','reminder'] as const) {
      const selected = sources.filter(s=>s.kind===kind);
      if (!selected.length) continue;
      await permitted(api,kind,false);
      if (!current()) throw new Error('同步已停止。');
      const lists = await boundedNativeRead(api.getCalendarsAsync(kind),'来源列表读取超时。');
      if (selected.some(s=>!lists.some(v=>v.id===s.id))) throw new Error('所选来源暂时不可用，保留已同步记录。请重新选择来源后继续。');
    }
  };
  await runNativeSync({store:storage,scope,active:current,nonce:nativeSyncNonce,changed,allowed,
    remote:value=>new NativeSyncClient(connection,value.installation,serviceFetch,current,signal),
    read:async source=>{
      await allowed([source]);
      if (!current()) throw new Error('同步已停止。');
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';
      if (source.kind === 'event') {
        const window = syncWindow();
        const rows = await boundedNativeRead(api.getEventsAsync([source.id],window.start,window.end),'日历同步读取超时。');
        return eventSnapshot(source,rows,window.start,window.end,timezone);
      }
      const rows = await boundedNativeRead(api.getRemindersAsync([source.id],null,null,null),'提醒事项同步读取超时。');
      return reminderSnapshot(source,rows,timezone);
    }});
}
