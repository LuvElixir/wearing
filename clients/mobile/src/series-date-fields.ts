import {validCivil,type SeriesTemplate} from './calendar-series-model';

// Recurrence fields are civil dates / wall clocks, not instants. UTC is only the
// native picker's neutral display zone; the series keeps its own IANA timezone.
export function civilPickerValue(value:string):Date {
  const day=value.slice(0,10),time=/T(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)?value.slice(11,16):'12:00';
  return validCivil(day)?new Date(day+'T'+time+':00Z'):new Date('2026-01-01T12:00:00Z');
}
export function civilPickerResult(previous:string,selected:Date,part:'date'|'time',allDay:boolean):string {
  if(!Number.isFinite(selected.getTime()))throw new Error('请选择有效日期。');
  const text=selected.toISOString(),day=part==='date'?text.slice(0,10):previous.slice(0,10);
  if(!validCivil(day))throw new Error('日期需在 1970 至 2100 年之间。');
  return allDay?day:day+'T'+(part==='time'?text.slice(11,16):/T(?:[01]\d|2[0-3]):[0-5]\d$/.test(previous)?previous.slice(11,16):'09:00');
}
export function shiftCivil(day:string,days:number):string {
  if(!validCivil(day))return day;
  const date=new Date(day+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+days);return date.toISOString().slice(0,10);
}
export function shownSeriesEnd(template:SeriesTemplate):string {
  return template.all_day?shiftCivil(template.end_local,-1):template.end_local;
}
export function storedSeriesEnd(displayValue:string,allDay:boolean):string {
  return allDay?shiftCivil(displayValue,1):displayValue;
}
export function setSeriesAllDay(template:SeriesTemplate,all_day:boolean):SeriesTemplate {
  if(template.all_day===all_day)return template;
  const start=template.start_local.slice(0,10),end=template.end_local.slice(0,10);
  if(all_day){
    // A timed end at midnight already excludes that new day; other times include it.
    const exclusive=template.end_local.slice(11)==='00:00'&&end>start?end:shiftCivil(end,1);
    return {...template,all_day,start_local:start,end_local:exclusive>start?exclusive:shiftCivil(start,1)};
  }
  const last=shiftCivil(end,-1);
  return {...template,all_day,start_local:start+'T09:00',end_local:(last>=start?last:start)+'T10:00'};
}
export function civilDateLabel(value:string):string {
  return validCivil(value.slice(0,10))?new Date(value.slice(0,10)+'T12:00:00Z').toLocaleDateString('zh-CN',{timeZone:'UTC',year:'numeric',month:'long',day:'numeric',weekday:'short'}):'选择日期';
}
