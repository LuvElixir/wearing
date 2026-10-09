import {dateKey,eventOccursOn,localDateTime,type CalendarDate} from './calendar';
import type {RecordItem} from './core';
export type CalendarView='month'|'week'|'agenda';
export type CalendarViewPreferences={version:1;view:CalendarView;source:string};
export const calendarViewKey=(scope:string)=>'calendar-view:v1:'+scope;
export function calendarViewPreferences(value:unknown):CalendarViewPreferences {
  const v=value as CalendarViewPreferences;
  if(!v||v.version!==1||!['month','week','agenda'].includes(v.view)||typeof v.source!=='string'||!(['all','other'].includes(v.source)||/^[a-f0-9]{64}$/.test(v.source)))return {version:1,view:'month',source:'all'};
  return v;
}
/** Civil arithmetic is deliberately UTC based; never add 24 hours to a local midnight. */
export function moveDay(date:CalendarDate,days:number):CalendarDate {
  const d=new Date(0);d.setUTCFullYear(date.year,date.month-1,date.day+days);d.setUTCHours(12,0,0,0);
  return {year:d.getUTCFullYear(),month:d.getUTCMonth()+1,day:d.getUTCDate()};
}
export function weekDays(date:CalendarDate):CalendarDate[] {
  const d=new Date(0);d.setUTCFullYear(date.year,date.month-1,date.day);d.setUTCHours(12,0,0,0);
  const start=moveDay(date,-((d.getUTCDay()+6)%7));return Array.from({length:7},(_,i)=>moveDay(start,i));
}
export function calendarDays(view:CalendarView,selected:CalendarDate):CalendarDate[] {
  return view==='week'?weekDays(selected):view==='agenda'?Array.from({length:30},(_,i)=>moveDay(selected,i)):[selected];
}
export function eventsForDay(events:RecordItem[],day:CalendarDate):RecordItem[] {
  return events.filter(r=>r.kind==='event'&&!r.deleted_at&&eventOccursOn(r,day)).sort((a,b)=>{
    const aa=/^\d{4}-\d{2}-\d{2}$/.test(a.start_at||''),bb=/^\d{4}-\d{2}-\d{2}$/.test(b.start_at||'');
    return Number(bb)-Number(aa)||(aa?0:Date.parse(a.start_at!)-Date.parse(b.start_at!))||a.title.localeCompare(b.title,'zh-CN')||a.id.localeCompare(b.id);
  });
}
export function eventDayTime(event:RecordItem,day:CalendarDate):string {
  if(!eventOccursOn(event,day))return '时间需核对';
  if(/^\d{4}-\d{2}-\d{2}$/.test(event.start_at||''))return '全天';
  const start=new Date(event.start_at!),end=new Date(event.end_at!),midnight=localDateTime(day),next=localDateTime(moveDay(day,1));
  const time=(d:Date)=>d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false});
  return `${start<midnight?'此前开始':time(start)} – ${end>next?'延续至次日':end.getTime()===next.getTime()?'24:00':time(end)}`;
}
export function dayTitle(date:CalendarDate,today?:CalendarDate|null) {
  const day=localDateTime(date,12).toLocaleDateString('zh-CN',{weekday:'short'});
  return `${date.month} 月 ${date.day} 日 · ${day}${today&&dateKey(today)===dateKey(date)?' · 今天':''}`;
}
export function calendarGroups(events:RecordItem[],days:CalendarDate[],limit:number) {
  let left=limit,total=0;const unique=new Set<string>();
  const groups=days.map(day=>{
    const items=eventsForDay(events,day);total+=items.length;for(const item of items)unique.add(item.id);
    const shown=items.slice(0,Math.max(0,left));left-=shown.length;return {day,items:shown,total:items.length};
  });
  return {groups,total,unique:unique.size,shown:Math.min(limit,total)};
}
