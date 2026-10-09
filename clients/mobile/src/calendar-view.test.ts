import {test} from 'node:test';
import assert from 'node:assert/strict';
import {scopeOf,type Connection,type RecordItem} from './core';
import {dateKey} from './calendar';
import {calendarDays,calendarGroups,calendarViewKey,calendarViewPreferences,eventDayTime,eventsForDay,moveDay,weekDays} from './calendar-view-model';
import {calendarSourceIndex,calendarSources,filterCalendarRecords,sourceIndexKey,type CalendarSourceIndex} from './calendar-sources';
import {accountCleanupPlan,fenceFor,fencedWrite} from './account-cleanup-model';
const id=(n:number)=>'life_'+n.toString(16).padStart(32,'0');
const event=(patch:Partial<RecordItem>={}):RecordItem=>({id:id(1),revision:1,updated_at:'2026-10-08T00:00:00Z',kind:'event',title:'会议',content:'',timezone:'Asia/Shanghai',start_at:'2026-10-08T01:00:00Z',end_at:'2026-10-08T02:00:00Z',...patch});
function tz(zone:string,work:()=>void){const old=process.env.TZ;process.env.TZ=zone;try{work();}finally{if(old===undefined)delete process.env.TZ;else process.env.TZ=old;}}
test('week stays Monday-first across years and agenda periods are consecutive without gaps',()=>{
  const selected={year:2026,month:1,day:1};
  assert.deepEqual(weekDays(selected).map(dateKey),['2025-12-29','2025-12-30','2025-12-31','2026-01-01','2026-01-02','2026-01-03','2026-01-04']);
  const first=calendarDays('agenda',selected),next=calendarDays('agenda',moveDay(selected,30));
  assert.equal(first.length,30);assert.equal(dateKey(moveDay(first.at(-1)!,1)),dateKey(next[0]));assert.equal(new Set([...first,...next].map(dateKey)).size,60);
});
test('civil navigation preserves days across DST and leap days in every display timezone',()=>{
  for(const zone of ['Asia/Shanghai','America/New_York','Pacific/Auckland'])tz(zone,()=>{
    assert.equal(dateKey(moveDay({year:2028,month:2,day:28},1)),'2028-02-29');
    assert.equal(dateKey(moveDay({year:2026,month:3,day:8},1)),'2026-03-09');
    assert.equal(dateKey(moveDay({year:2026,month:11,day:1},-1)),'2026-10-31');
  });
});
test('day rows use local overlap, all-day first, and chronological instant order',()=>tz('Asia/Shanghai',()=>{
  const rows=[event({id:id(1),start_at:'2026-10-08T10:00:00+08:00',end_at:'2026-10-08T11:00:00+08:00'}),event({id:id(2),all_day:true,start_at:'2026-10-08',end_at:'2026-10-09'}),event({id:id(3),start_at:'2026-10-08T01:00:00Z',end_at:'2026-10-08T02:00:00Z'}),event({id:id(4),deleted_at:'2026-10-08T00:00:00Z'})];
  assert.deepEqual(eventsForDay(rows,{year:2026,month:10,day:8}).map(r=>r.id),[id(2),id(3),id(1)]);
}));
test('cross-midnight continuation labels never present yesterday start time as today start',()=>tz('Asia/Shanghai',()=>{
  const item=event({start_at:'2026-10-07T23:00:00+08:00',end_at:'2026-10-09T00:00:00+08:00'});
  assert.equal(eventDayTime(item,{year:2026,month:10,day:8}),'此前开始 – 24:00');
  assert.equal(eventDayTime(item,{year:2026,month:10,day:7}),'23:00 – 延续至次日');
  assert.equal(eventDayTime(item,{year:2026,month:10,day:9}),'时间需核对');
}));
test('agenda bound counts date entries separately from unique records and retains exact record objects',()=>{
  const item=event({all_day:true,start_at:'2026-10-08',end_at:'2026-10-11'}),days=calendarDays('agenda',{year:2026,month:10,day:8});
  const page=calendarGroups([item],days,2);assert.equal(page.unique,1);assert.equal(page.total,3);assert.equal(page.shown,2);assert.equal(page.groups[0].items[0],item);assert.equal(page.groups[2].total,1);assert.equal(page.groups[2].items.length,0);
  assert.equal(calendarGroups([item],days,100).shown,3);
});
const index:CalendarSourceIndex={checked_at:'2026-10-08T01:00:00Z',limit:1000,truncated:false,records:[{record_id:id(1),source_key:'a'.repeat(64),title:'工作',kind:'event',state:'synced'},{record_id:id(2),source_key:'b'.repeat(64),title:'工作',kind:'event',state:'conflict'}]};
test('sources use server mapping not titles or user-entered notes, and same-name calendars stay distinct',()=>{
  const records=[event(),event({id:id(2)}),event({id:id(3),content:'来自系统日历「工作」的单向副本。'}),event({id:id(4),kind:'note'})];
  assert.equal(calendarSources(index).length,2);assert.deepEqual(filterCalendarRecords(records,'a'.repeat(64),index).map(r=>r.id),[id(1)]);
  assert.deepEqual(filterCalendarRecords(records,'other',index).map(r=>r.id),[id(3)]);assert.equal(filterCalendarRecords(records,'all',null).length,3);
  assert.equal(filterCalendarRecords(records,'c'.repeat(64),index).length,0);
});
test('invalid or duplicated source mapping cannot overwrite a previous cache',()=>{
  assert.equal(calendarSourceIndex(index),index);
  assert.throws(()=>calendarSourceIndex({...index,records:[...index.records,index.records[0]]}));
  assert.throws(()=>calendarSourceIndex({...index,limit:10000}));
  assert.throws(()=>calendarSourceIndex({...index,records:[{...index.records[0],state:'deleted'}]}));
});
test('view restoration accepts only explicit display settings and preserves a missing source selection',()=>{
  assert.deepEqual(calendarViewPreferences({version:1,view:'week',source:'a'.repeat(64)}),{version:1,view:'week',source:'a'.repeat(64)});
  assert.deepEqual(calendarViewPreferences({version:1,view:'scheduled-agent',source:'all'}),{version:1,view:'month',source:'all'});
});
test('source cache and view preferences honor whole-account deletion without affecting another account',()=>{
  const connection:Connection={endpoint:'https://pajio.example/',identity:'daily',session:{userId:'user_'+'a'.repeat(32),tenantId:'home',credentialId:'d'.repeat(32),expiresAt:'2030-01-01T00:00:00Z'}};
  const other={...connection,session:{...connection.session!,userId:'user_'+'b'.repeat(32)}};
  const keys=[sourceIndexKey(scopeOf(connection)),calendarViewKey(scopeOf(connection))],foreign=sourceIndexKey(scopeOf(other));
  assert.deepEqual(accountCleanupPlan(connection,[...keys.map(key=>({key,value:index})),{key:foreign,value:index}]).remove,keys);
  for(const key of keys)assert.equal(fencedWrite(key,index,[fenceFor(connection)]),true);
  assert.equal(fencedWrite(foreign,index,[fenceFor(connection)]),false);
});
