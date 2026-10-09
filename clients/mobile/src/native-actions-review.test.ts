/** Realistic SDK 57 legacy reminder receipts, including absent native allDay. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {NativeActionDriver, type ActionCalendar} from './native-action-driver';
import {emptyNativePolicy, type NativeDevice, type NativeRequest} from './native-action-model';

const stamp = Date.parse('2026-10-08T00:00:00Z');
const device:NativeDevice = {server_id:'d'.repeat(32),identity_id:'daily',installation_id:'a'.repeat(32),name:'Synthetic',revision:1,enabled:true,online:true,availability:'foreground_only',capabilities:['reminders.read','reminders.create'],policy:{...emptyNativePolicy(),reminders:[{id:'rem',title:'Synthetic reminders',writable:true}],reminder_create:true}};
function request(write = false, allDay = false):NativeRequest {
  const id = 'native_' + 'b'.repeat(32);
  return {id,identity_id:'daily',installation_id:device.installation_id,task_id:'task',run_id:'run',fingerprint:'e'.repeat(64),state:'executing',result:null,reviewed:false,command:{protocol_version:'1',command_id:id,scope:{tenant_id:device.server_id,identity_id:'daily'},task_id:'task',resource_id:device.installation_id,connector_id:device.installation_id,connection_id:'c'.repeat(32),pairing_generation:1,policy_revision:1,lease_epoch:1,method:write?'reminders.create':'reminders.read',params:write?{calendar_id:'rem',title:'Synthetic reminder',notes:'',due:'2026-10-09T00:00:00Z',all_day:allDay}:{calendar_ids:['rem'],completed:false,limit:100},created_at:new Date(stamp).toISOString(),expires_at:new Date(stamp+55000).toISOString()}};
}
function legacy(overrides:Record<string,unknown> = {}):ActionCalendar {
  return {getRemindersPermissionsAsync:async()=>({granted:true}),getCalendarsAsync:async()=>[{id:'rem',title:'Synthetic reminders',allowsModifications:true}],...overrides} as unknown as ActionCalendar;
}
const saved = {id:'native-reminder',calendarId:'rem',title:'Synthetic reminder',notes:'',dueDate:'2026-10-09T00:00:00Z',completed:false};

test('legacy missing allDay must remain unknown in read receipts',async()=>{
  const driver = new NativeActionDriver(legacy({getRemindersAsync:async()=>[saved]}),null,()=>true,()=>stamp);
  const data = await driver.execute(request(),device);
  assert.equal((data.items as Record<string,unknown>[])[0].all_day,null);
});

test('unsupported all-day reminder is rejected before any OS write',async()=>{
  let writes = 0;
  const driver = new NativeActionDriver(legacy({createReminderAsync:async()=>{writes++;return saved.id;},getReminderAsync:async()=>saved}),null,()=>true,()=>stamp);
  await assert.rejects(driver.execute(request(true,true),device));
  assert.equal(writes,0);
});

test('timed reminder readback cannot fabricate missing all-day evidence',async()=>{
  let writes = 0;
  const r = request(true);
  const driver = new NativeActionDriver(legacy({createReminderAsync:async()=>{writes++;return saved.id;},getReminderAsync:async()=>({...saved,url:'pajio://native/'+r.id})}),null,()=>true,()=>stamp);
  const data = await driver.execute(r,device);
  assert.equal(writes,1);
  assert.equal(data.all_day,null);
  assert.equal(data.id,saved.id);
  assert.equal(data.due,saved.dueDate.replace('Z','.000Z'));
});
