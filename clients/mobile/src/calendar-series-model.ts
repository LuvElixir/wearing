import type {RecordItem} from './core';
import {dateKey,type CalendarDate} from './calendar';
import {moveDay} from './calendar-view-model';

export type SeriesTemplate={title:string;content:string;timezone:string;all_day:boolean;start_local:string;end_local:string};
export type SeriesRule={frequency:'daily'|'weekly'|'monthly'|'yearly';interval:number;weekdays:number[];count:number|null;until:string|null};
export type SeriesDraft={template:SeriesTemplate;rule:SeriesRule};
export type Series={id:string;identity_id:string;revision:number;body:SeriesDraft;deleted_at:string|null;created_at:string;updated_at:string;selected?:SeriesOccurrence|null;exceptions:{occurrence_key:string;revision:number;cancelled:boolean;title:string|null}[]};
export type SeriesOccurrence=RecordItem&{identity_id:string;recurrence:{series_id:string;occurrence_key:string;series_revision:number;exception_revision:number|null}};
export type SeriesQuery={start:string;end:string;timezone:string;checked_at:string;limit:1000;truncated:boolean;items:SeriesOccurrence[]};
export type SeriesMutation={action:'create'|'update'|'archive'|'restore'|'override'|'cancel'|'reset';request_key:string;series_id?:string;revision?:number;draft?:SeriesDraft;template?:SeriesTemplate;occurrence_key?:string};
export const seriesStorageKey=(scope:string)=>'calendar-series:v1:'+scope;
export const seriesDraftKey=(scope:string,target:string)=>'calendar-series-draft:v1:'+scope+':'+target;
export const seriesPendingKey=(scope:string,target:string)=>'calendar-series-pending:v1:'+scope+':'+target;
const fail=()=>{throw new Error('重复日程内容无法核对，原输入仍保留。');};
export const validCivil=(value:unknown):value is string=>{if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;const d=new Date(value+'T12:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===value&&d.getUTCFullYear()>=1970&&d.getUTCFullYear()<=2100;};
const positive=(value:unknown)=>typeof value==='number'&&Number.isSafeInteger(value)&&value>0;
export type SeriesEdit={draft:SeriesDraft;mode:'series'|'once';baseRevision:number|null};
export function seriesEdit(value:unknown):SeriesEdit {
  const v=value as SeriesEdit,t=v?.draft?.template,r=v?.draft?.rule;
  if(!v||!['series','once'].includes(v.mode)||v.baseRevision!==null&&!positive(v.baseRevision)||!t||!r||typeof t.all_day!=='boolean'||['title','content','timezone','start_local','end_local'].some(k=>typeof t[k as keyof SeriesTemplate]!=='string')||t.title.length>200||t.content.length>12000||t.timezone.length>80||t.start_local.length>40||t.end_local.length>40||!['daily','weekly','monthly','yearly'].includes(r.frequency)||!Number.isFinite(r.interval)||r.count!==null&&!Number.isFinite(r.count)||r.until!==null&&typeof r.until!=='string'||!Array.isArray(r.weekdays)||r.weekdays.some(d=>!Number.isInteger(d)||d<0||d>6))return fail();return v;
}
export function seriesTemplate(value:unknown):SeriesTemplate {
  const t=value as SeriesTemplate;
  if(!t||typeof t.title!=='string'||!t.title.trim()||t.title.length>200||typeof t.content!=='string'||t.content.length>12000||typeof t.timezone!=='string'||typeof t.all_day!=='boolean')return fail();
  try{new Intl.DateTimeFormat('en',{timeZone:t.timezone});}catch{return fail();}
  for(const v of [t.start_local,t.end_local])if(typeof v!=='string'||(t.all_day?!validCivil(v):!/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d$/.test(v)||!validCivil(v.slice(0,10))))return fail();
  const a=Date.parse(t.start_local+(t.all_day?'T00:00Z':'Z')),b=Date.parse(t.end_local+(t.all_day?'T00:00Z':'Z'));
  if(!(b>a)||b-a>31*86400000)return fail();return t;
}
export function seriesDraft(value:unknown):SeriesDraft {
  const v=value as SeriesDraft;if(!v)return fail();seriesTemplate(v.template);const r=v.rule;
  if(!r||!['daily','weekly','monthly','yearly'].includes(r.frequency)||!positive(r.interval)||r.interval>365||!Array.isArray(r.weekdays)||r.weekdays.length>7||new Set(r.weekdays).size!==r.weekdays.length||r.weekdays.some(d=>!Number.isInteger(d)||d<0||d>6)||r.frequency!=='weekly'&&r.weekdays.length||r.count!==null&&(!positive(r.count)||r.count>1000)||r.until!==null&&!validCivil(r.until)||r.count!==null&&r.until!==null)return fail();return v;
}
export function seriesRow(value:unknown,identity:string):Series {
  const v=value as Series;if(!v||!/^series_[a-f0-9]{32}$/.test(v.id)||v.identity_id!==identity||!positive(v.revision)||v.deleted_at!==null&&!Number.isFinite(Date.parse(v.deleted_at))||!Number.isFinite(Date.parse(v.updated_at))||!Number.isFinite(Date.parse(v.created_at))||!Array.isArray(v.exceptions)||v.exceptions.length>200)return fail();seriesDraft(v.body);
  const keys=new Set<string>();for(const e of v.exceptions){if(!e||!validCivil(e.occurrence_key)||keys.has(e.occurrence_key)||!positive(e.revision)||typeof e.cancelled!=='boolean'||e.title!==null&&typeof e.title!=='string')return fail();keys.add(e.occurrence_key);}return v;
}
export function seriesQuery(value:unknown,identity:string,start:string,end:string,zone:string):SeriesQuery {
  const v=value as SeriesQuery;if(!v||v.start!==start||v.end!==end||v.timezone!==zone||v.limit!==1000||typeof v.truncated!=='boolean'||!Number.isFinite(Date.parse(v.checked_at))||!Array.isArray(v.items)||v.items.length>1000)return fail();
  const ids=new Set<string>();for(const row of v.items){const m=row?.recurrence;if(!row||row.identity_id!==identity||row.kind!=='event'||row.deleted_at!==null||!m||!/^series_[a-f0-9]{32}$/.test(m.series_id)||!validCivil(m.occurrence_key)||row.id!=='recurrence_'+m.series_id.slice(7)+'_'+m.occurrence_key.replaceAll('-','')||ids.has(row.id)||!positive(row.revision)||row.revision!==m.series_revision||m.exception_revision!==null&&!positive(m.exception_revision)||typeof row.title!=='string'||typeof row.content!=='string'||typeof row.all_day!=='boolean')return fail();
    if(typeof row.timezone!=='string'||!row.timezone)return fail();
    try{new Intl.DateTimeFormat('en',{timeZone:row.timezone});}catch{return fail();}
    if(row.all_day?(!validCivil(row.start_at)||!validCivil(row.end_at)||row.end_at<=row.start_at):(!Number.isFinite(Date.parse(row.start_at||''))||!(Date.parse(row.end_at||'')>Date.parse(row.start_at||''))))return fail();ids.add(row.id);
  }return v;
}
export function seriesMutation(value:unknown):SeriesMutation {
  const v=value as SeriesMutation;if(!v||typeof v.request_key!=='string'||!v.request_key||v.request_key.length>120)return fail();
  const allowed:Record<string,string[]>={create:['draft'],update:['series_id','revision','draft'],archive:['series_id','revision'],restore:['series_id','revision'],override:['series_id','revision','occurrence_key','template'],cancel:['series_id','revision','occurrence_key'],reset:['series_id','revision','occurrence_key']};
  const fields=allowed[v.action];if(!fields||Object.keys(v).some(k=>!['action','request_key',...fields].includes(k))||fields.some(k=>!(k in v)))return fail();
  if(v.action!=='create'&&(!/^series_[a-f0-9]{32}$/.test(v.series_id||'')||!positive(v.revision)))return fail();
  if(['create','update'].includes(v.action))seriesDraft(v.draft);if(v.action==='override')seriesTemplate(v.template);if(['override','cancel','reset'].includes(v.action)&&!validCivil(v.occurrence_key))return fail();return v;
}
export function isSeriesOccurrence(record:RecordItem):record is SeriesOccurrence{return !!(record as SeriesOccurrence).recurrence&&record.id.startsWith('recurrence_');}
export const seriesWindow=(anchor:CalendarDate)=>({start:dateKey(moveDay(anchor,-40)),end:dateKey(moveDay(anchor,70))});
export function ruleLabel(rule:SeriesRule){const units={daily:'天',weekly:'周',monthly:'月',yearly:'年'};return `每 ${rule.interval} ${units[rule.frequency]}${rule.frequency==='weekly'&&rule.weekdays.length?' · '+rule.weekdays.map(d=>'周'+'一二三四五六日'[d]).join('、'):''}${rule.count?' · 共 '+rule.count+' 次':rule.until?' · 至 '+rule.until:' · 持续重复'}`;}
export function localText(date:Date,allDay=false){const day=`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;return allDay?day:day+`T${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`;}
export function occurrenceTemplate(row:SeriesOccurrence):SeriesTemplate {
  const convert=(v:string)=>{if(row.all_day)return v;const values=new Intl.DateTimeFormat('en-CA',{timeZone:row.timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(v));const part=(name:string)=>values.find(p=>p.type===name)?.value;return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`;};
  return {title:row.title,content:row.content,timezone:row.timezone,all_day:!!row.all_day,start_local:convert(row.start_at!),end_local:convert(row.end_at!)};
}
