import type {Event, Reminder} from 'expo-calendar/legacy';
import type {Draft} from './core';

export type SyncSource = {kind: 'event' | 'reminder'; id: string; title: string};
export type SyncRecord = Draft & {due_at?: string | null; completed?: boolean; list_name?: string};
export type SyncSnapshot = {source: SyncSource; complete: boolean; window_start: string | null; window_end: string | null;
  items: {external_id: string; occurrence_id: string; record: SyncRecord}[]};
export type SyncSettings = {revision: number; enabled: boolean; sources: SyncSource[]};
export type SyncState = SyncSettings & {records: {record_id: string; source_kind: 'event' | 'reminder'; source_id: string; state: 'synced' | 'conflict' | 'unseen'; observed_at: string}[]};
export type SyncReceipt = {request_id: string; revision: number; observed_at: string; record_ids: string[]; created: number; updated: number; unchanged: number; conflicts: number; unseen: number; truncated: number};
export type SyncBatch = {request_id: string; revision: number; observed_at: string; snapshots: SyncSnapshot[]};
export type SyncLocal = {version: 1; installation: string; choice: string; desired: {enabled: boolean; sources: SyncSource[]};
  configured: string | null; settings: SyncSettings; pendingConfig: (SyncSettings & {request_id: string}) | null; pending: SyncBatch | null; receipt: SyncReceipt | null; error: string};
export const syncKey = (scope: string) => 'native-sync:v1:' + scope;
export const sourceKey = (s: SyncSource) => JSON.stringify([s.kind, s.id]);
const iso = (value: string | Date | undefined) => {
  if (!value || !Number.isFinite(new Date(value).getTime())) throw new Error('系统记录日期不完整，这个来源暂未更新。');
  return new Date(value).toISOString();
};
const localDay = (value: string, zone: string) => {
  const parts = new Intl.DateTimeFormat('en-US', {timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(new Date(value));
  const part = (type: string) => parts.find(p => p.type === type)!.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
};
const zoneOf = (value: string | undefined, fallback: string) => {
  try {if (value) {new Intl.DateTimeFormat('en', {timeZone: value}); return value;}} catch { /* Use the device's verified current zone. */ }
  return fallback;
};
export function syncWindow(stamp = new Date()) {return {start: new Date(stamp.getTime() - 7 * 86400000), end: new Date(stamp.getTime() + 30 * 86400000)};}
export function eventSnapshot(source: SyncSource, rows: Event[], start: Date, end: Date, timezone: string): SyncSnapshot {
  const own = rows.filter(row => row.calendarId === source.id && row.status !== 'canceled');
  const instances = new Map<string,number>();
  for (const row of own) instances.set(row.id,(instances.get(row.id)||0)+1);
  const keys = new Set<string>();
  const items = own.slice(0, 500).map(row => {
    if (!row.id || typeof row.allDay !== 'boolean') throw new Error('系统日程回执不完整，这个来源暂未更新。');
    const begin = iso(row.startDate), finish = iso(row.endDate), zone = zoneOf(row.timeZone, timezone);
    if (finish <= begin) throw new Error('系统日程时间需要核对，这个来源暂未更新。');
    const recurring = row.recurrenceRule || row.originalStartDate || row.isDetached || (instances.get(row.id)||0) > 1;
    const occurrence = recurring ? iso(row.originalStartDate || row.startDate) : '';
    const key = JSON.stringify([row.id, occurrence]);
    if (keys.has(key)) throw new Error('系统返回了重复的日程实例，这个来源暂未更新。');
    keys.add(key);
    return {external_id: row.id, occurrence_id: occurrence, record: {kind: 'event' as const, title: (row.title?.trim() || '未命名日程').slice(0, 200), content: (row.notes || '').slice(0, 3000), timezone: zone,
      all_day: row.allDay, start_at: row.allDay ? localDay(begin, zone) : begin, end_at: row.allDay ? localDay(finish, zone) : finish}};
  });
  return {source, items, complete: own.length <= 500, window_start: start.toISOString(), window_end: end.toISOString()};
}
export function reminderSnapshot(source: SyncSource, rows: Reminder[], timezone: string): SyncSnapshot {
  const own = rows.filter(r => r.calendarId === source.id), seen = new Set<string>();
  const items = own.slice(0, 500).map(row => {
    if (!row.id || seen.has(row.id) || typeof row.completed !== 'boolean') throw new Error('系统提醒事项回执不完整，这个来源暂未更新。');
    seen.add(row.id);
    const due = row.dueDate ? iso(row.dueDate) : null;
    const dateOnly = due && row.allDay !== false;
    return {external_id: row.id, occurrence_id: '', record: {kind: 'task' as const, title: (row.title?.trim() || '未命名提醒').slice(0, 200),
      content: (row.notes || '').slice(0, 3000) + (dateOnly ? `\n系统日期：${localDay(due, timezone)}${row.allDay === true ? '（全天）' : '，具体时间/全天设置请在系统提醒事项核对。'}` : ''),
      timezone, due_at: row.allDay === false ? due : null, completed: row.completed, list_name: source.title.slice(0, 80)}};
  });
  return {source, items, complete: own.length <= 500, window_start: null, window_end: null};
}
export function validSources(value: unknown): value is SyncSource[] {
  return Array.isArray(value) && value.length <= 50 && value.every(v => v && ['event','reminder'].includes(v.kind) && typeof v.id === 'string' && v.id.length > 0 && v.id.length <= 512 && typeof v.title === 'string' && v.title.length > 0 && v.title.length <= 200) && new Set(value.map(sourceKey)).size === value.length;
}
export function syncSettings(value: unknown): SyncSettings {
  const v = value as SyncSettings;
  if (!v || !Number.isSafeInteger(v.revision) || v.revision < 0 || typeof v.enabled !== 'boolean' || !validSources(v.sources) || (v.enabled && !v.sources.length)) throw new Error('同步设置回执不完整。');
  return {revision: v.revision, enabled: v.enabled, sources: v.sources};
}
export function syncReceipt(value: unknown, expected: SyncBatch): SyncReceipt {
  const v = value as SyncReceipt;
  if (!v || v.request_id !== expected.request_id || v.revision !== expected.revision || v.observed_at !== expected.observed_at || !Array.isArray(v.record_ids) || !v.record_ids.every(id => /^life_[a-f0-9]{32}$/.test(id)) ||
    !['created','updated','unchanged','conflicts','unseen','truncated'].every(k => Number.isSafeInteger(v[k as keyof SyncReceipt]) && (v[k as keyof SyncReceipt] as number) >= 0) || new Set(v.record_ids).size !== v.record_ids.length ||
    v.created+v.updated+v.unchanged+v.conflicts !== v.record_ids.length || v.record_ids.length !== expected.snapshots.reduce((sum,s)=>sum+s.items.length,0) || v.truncated!==expected.snapshots.filter(s=>!s.complete).length) throw new Error('同步保存回执不完整，将保留原批次重试。');
  return v;
}

export const syncNonce = (v:unknown): v is string => typeof v==='string' && /^[a-f0-9]{32}$/.test(v);
const stamp = (v:unknown): v is string => typeof v==='string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
/** A disk journal is recovery data, never implicit permission to upload another source. */
export function validSyncBatch(v:SyncBatch, settings:SyncSettings):boolean {
  if(!v || !syncNonce(v.request_id) || v.revision!==settings.revision || !stamp(v.observed_at) || !Array.isArray(v.snapshots) || !v.snapshots.length || v.snapshots.length>50 || v.snapshots.reduce((sum,s)=>sum+(Array.isArray(s?.items)?s.items.length:501),0)>500) return false;
  const sources=new Set<string>();
  return v.snapshots.every(s=>{
    if(!s || !validSources([s.source]) || !settings.sources.some(p=>sourceKey(p)===sourceKey(s.source)) || sources.has(sourceKey(s.source)) || typeof s.complete!=='boolean' || !Array.isArray(s.items) || s.items.length>500) return false;
    sources.add(sourceKey(s.source));
    if(s.source.kind==='event' ? (!stamp(s.window_start)||!stamp(s.window_end)||Date.parse(s.window_end)<=Date.parse(s.window_start)||Date.parse(s.window_end)-Date.parse(s.window_start)>45*86400000) : (s.window_start!==null||s.window_end!==null)) return false;
    const ids=new Set<string>();
    return s.items.every(item=>{
      if(!item || typeof item.external_id!=='string'||!item.external_id||item.external_id.length>512||typeof item.occurrence_id!=='string'||item.occurrence_id.length>512||s.source.kind==='reminder'&&item.occurrence_id!=='')return false;
      const key=JSON.stringify([item.external_id,item.occurrence_id]);if(ids.has(key))return false;ids.add(key);
      const r=item.record;
      if(!r||r.kind!==(s.source.kind==='event'?'event':'task')||typeof r.title!=='string'||!r.title||r.title.length>200||typeof r.content!=='string'||r.content.length>4000||typeof r.timezone!=='string')return false;
      try{new Intl.DateTimeFormat('en',{timeZone:r.timezone});}catch{return false;}
      if(r.kind==='event')return typeof r.all_day==='boolean' && (r.all_day ? typeof r.start_at==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(r.start_at)&&typeof r.end_at==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(r.end_at) : stamp(r.start_at)&&stamp(r.end_at)) && Date.parse(r.end_at!)>Date.parse(r.start_at!);
      return typeof r.completed==='boolean' && (r.due_at===null||stamp(r.due_at)) && typeof r.list_name==='string' && r.list_name.length>0 && r.list_name.length<=80;
    });
  });
}
