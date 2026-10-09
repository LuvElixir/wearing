import test from 'node:test';
import assert from 'node:assert/strict';
import {civilPickerResult,civilPickerValue,setSeriesAllDay,shownSeriesEnd,storedSeriesEnd,civilDateLabel} from './series-date-fields';
import {seriesTemplate,type SeriesTemplate} from './calendar-series-model';
const base:SeriesTemplate={title:'合成会议',content:'原备注',timezone:'America/New_York',all_day:false,start_local:'2026-03-07T09:00',end_local:'2026-03-07T10:00'};

test('one day and multi-day all-day display include the last day without adding an extra day',()=>{
  const all=setSeriesAllDay(base,true);assert.equal(shownSeriesEnd(all),'2026-03-07');assert.equal(all.end_local,'2026-03-08');seriesTemplate(all);
  const changed={...all,end_local:storedSeriesEnd('2026-03-10',true)};assert.equal(changed.end_local,'2026-03-11');assert.equal(shownSeriesEnd(changed),'2026-03-10');
  const timed=setSeriesAllDay(changed,false);assert.equal(timed.end_local,'2026-03-10T10:00');assert.equal(timed.timezone,base.timezone);assert.equal(timed.content,base.content);
});
test('midnight timed end does not invent a further all-day date, including year rollover',()=>{
  const overnight={...base,start_local:'2026-12-31T22:00',end_local:'2027-01-01T00:00'};
  assert.equal(setSeriesAllDay(overnight,true).end_local,'2027-01-01');
  assert.equal(shownSeriesEnd(setSeriesAllDay({...overnight,end_local:'2027-01-01T00:01'},true)),'2027-01-01');
});
test('native picker transports civil fields without converting them using the phone timezone',()=>{
  const picked=civilPickerValue('2026-03-08T02:30');assert.equal(picked.toISOString(),'2026-03-08T02:30:00.000Z');
  assert.equal(civilPickerResult('2026-03-07T09:00',picked,'date',false),'2026-03-08T09:00');
  assert.equal(civilPickerResult('2026-03-07T09:00',picked,'time',false),'2026-03-07T02:30');
  assert.equal(civilPickerResult('2026-03-07',picked,'date',true),'2026-03-08');
});
test('restored unfinished inputs cannot crash picker and selecting a date repairs only the date field',()=>{
  assert.equal(Number.isNaN(civilPickerValue('2026-02-30T88:00').getTime()),false);
  assert.equal(civilPickerResult('',new Date('2026-10-08T12:00Z'),'date',false),'2026-10-08T09:00');
  assert.throws(()=>civilPickerResult('bad',new Date(),'time',false));assert.throws(()=>civilPickerResult('2026-10-08',new Date('2101-01-01T12:00Z'),'date',true));
  assert.match(civilDateLabel('2026-10-08'),/2026/);assert.equal(civilDateLabel('bad'),'选择日期');
});
