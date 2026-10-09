import type {RecordItem} from './core';
export type CalendarSourceRow={record_id:string;source_key:string;title:string;kind:'event'|'reminder';state:'synced'|'unseen'|'conflict'};
export type CalendarSourceIndex={checked_at:string;limit:1000;truncated:boolean;records:CalendarSourceRow[]};
export type CalendarFilter='all'|'other'|string;
export function calendarSourceIndex(value:unknown):CalendarSourceIndex {
  const v=value as CalendarSourceIndex;
  if(!v||typeof v.checked_at!=='string'||!Number.isFinite(Date.parse(v.checked_at))||v.limit!==1000||typeof v.truncated!=='boolean'||!Array.isArray(v.records)||v.records.length>1000)throw new Error('日历来源暂时无法核对。');
  const seen=new Set<string>();
  for(const r of v.records){
    if(!r||typeof r.record_id!=='string'||!/^life_[a-f0-9]{32}$/.test(r.record_id)||seen.has(r.record_id)||typeof r.source_key!=='string'||!/^[a-f0-9]{64}$/.test(r.source_key)||typeof r.title!=='string'||!r.title||r.title.length>200||!['event','reminder'].includes(r.kind)||!['synced','unseen','conflict'].includes(r.state))throw new Error('日历来源暂时无法核对。');
    seen.add(r.record_id);
  }
  return v;
}
export const sourceIndexKey=(scope:string)=>'calendar-sources:v1:'+scope;
export function calendarSources(index:CalendarSourceIndex|null) {
  const sources=new Map<string,{id:string;title:string}>();
  for(const row of index?.records||[])if(row.kind==='event'&&!sources.has(row.source_key))sources.set(row.source_key,{id:row.source_key,title:row.title});
  return [...sources.values()].sort((a,b)=>a.title.localeCompare(b.title,'zh-CN')||a.id.localeCompare(b.id));
}
export function filterCalendarRecords(records:RecordItem[],filter:CalendarFilter,index:CalendarSourceIndex|null):RecordItem[] {
  const known=new Map((index?.records||[]).map(row=>[row.record_id,row]));
  return records.filter(r=>r.kind==='event'&&!r.deleted_at&&(filter==='all'||(filter==='other'?!known.has(r.id):known.get(r.id)?.source_key===filter)));
}
