import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {NativeActionDriver, NativeDriverError, type ActionCalendar} from './native-action-driver';
import {NativeActionRunner} from './native-action-runner';
import {emptyNativePolicy, validateNativeDispatch, type NativeDevice, type NativeMethod, type NativeOutcome, type NativeRequest} from './native-action-model';

const at=Date.parse('2026-10-08T00:00:00Z'),session='c'.repeat(32),digest=async(s:string)=>createHash('sha256').update(s).digest('hex');
const device:NativeDevice={server_id:'d'.repeat(32),identity_id:'daily',installation_id:'a'.repeat(32),name:'Synthetic',revision:1,enabled:true,online:true,availability:'foreground_only',
  capabilities:['calendar.read','calendar.update','calendar.delete','reminders.read','reminders.update','reminders.delete'],
  policy:{...emptyNativePolicy(),calendars:[{id:'cal',title:'Calendar fixture',writable:true}],reminders:[{id:'rem',title:'Reminder fixture',writable:true}],calendar_edit:true,reminder_edit:true}};
function req(method:NativeMethod,params:Record<string,unknown>,digit='b'):NativeRequest {
  const id='native_'+digit.repeat(32);
  return {id,identity_id:'daily',installation_id:device.installation_id,task_id:'task',run_id:'run',fingerprint:'e'.repeat(64),state:'queued',result:null,reviewed:false,
    command:{protocol_version:'1',command_id:id,scope:{tenant_id:device.server_id,identity_id:'daily'},task_id:'task',resource_id:device.installation_id,connector_id:device.installation_id,connection_id:session,pairing_generation:1,policy_revision:1,lease_epoch:1,method,params,created_at:new Date(at).toISOString(),expires_at:new Date(at+55000).toISOString()}};
}
function fixture(event=true) {
  let active=true,granted=true,writes=0;
  const original:Record<string,unknown>={id:'native-id',calendarId:event?'cal':'rem',title:'Original',notes:'Keep notes',location:'Keep location',lastModifiedDate:'2026-10-07T00:00:00Z',
    ...(event?{startDate:'2026-10-08T01:00:00Z',endDate:'2026-10-08T02:00:00Z',allDay:false,availability:'busy',alarms:[{relativeOffset:-15}]}:{completed:false,dueDate:'2026-10-09T00:00:00Z',startDate:'2026-10-07T23:00:00Z',alarms:[{relativeOffset:0}]})};
  let current:Record<string,unknown>|null=structuredClone(original);
  const calls:{id:string;details?:Record<string,unknown>;options?:Record<string,unknown>}[]=[];
  const api={getCalendarPermissionsAsync:async()=>({granted}),getRemindersPermissionsAsync:async()=>({granted}),getCalendarsAsync:async()=>[{id:event?'cal':'rem',title:'fixture',allowsModifications:true}],
    getEventsAsync:async()=>current?[structuredClone(current)]:[],getRemindersAsync:async()=>current?[structuredClone(current)]:[],
    getEventAsync:async(id:string,options:Record<string,unknown>)=>{calls.push({id,options});if(!current)throw new Error('missing');return structuredClone(current);},
    getReminderAsync:async()=>{if(!current)throw new Error('missing');return structuredClone(current);},
    updateEventAsync:async(id:string,details:Record<string,unknown>,options:Record<string,unknown>)=>{writes++;calls.push({id,details,options});current={...current,...details,alarms:details.alarms||[],title:details.title,notes:details.notes,location:details.location,allDay:details.allDay,availability:details.availability,lastModifiedDate:'2026-10-08T00:00:01Z'};return id;},
    updateReminderAsync:async(id:string,details:Record<string,unknown>)=>{writes++;calls.push({id,details});current={...current,...details,title:details.title,location:details.location,notes:details.notes,lastModifiedDate:'2026-10-08T00:00:01Z'};return id;},
    deleteEventAsync:async(id:string,options:Record<string,unknown>)=>{writes++;calls.push({id,options});current=null;},deleteReminderAsync:async()=>{writes++;current=null;}} as unknown as ActionCalendar;
  const driver=new NativeActionDriver(api,null,()=>active,()=>at,digest);
  return {api,driver,calls,original,get writes(){return writes;},get current(){return current;},set current(v){current=v;},set active(v:boolean){active=v;},set granted(v:boolean){granted=v;}};
}
async function mutation(f:ReturnType<typeof fixture>,method:NativeMethod,patch?:Record<string,unknown>) {
  const event=method.startsWith('calendar.');
  const read=req(event?'calendar.read':'reminders.read',event?{calendar_ids:['cal'],start:'2026-10-08T00:00:00Z',end:'2026-10-09T00:00:00Z',limit:100}:{calendar_ids:['rem'],completed:true,limit:100});
  const data=await f.driver.execute(read,device),target=(data.items as Record<string,unknown>[])[0];
  return req(method,{record_ref:read.id+':0',target,calendar_id:target.calendar_id,...(patch?{patch}:{})},'f');
}
test('calendar update preserves SDK-reset fields and exact single-instance options',async()=>{
  const f=fixture(),r=await mutation(f,'calendar.update',{title:'New title',start:'2026-10-08T01:15:00+00:00'});
  validateNativeDispatch(r,device,session,at);
  const data=await f.driver.execute(r,device),write=f.calls.find(c=>c.details)!;
  assert.equal(f.writes,1);assert.deepEqual(write.options,{instanceStartDate:'2026-10-08T01:00:00.000Z',futureEvents:false});
  assert.equal(write.details?.location,'Keep location');assert.equal(write.details?.notes,'Keep notes');assert.equal(write.details?.allDay,false);assert.equal(write.details?.availability,'busy');
  assert.deepEqual(write.details?.alarms,[{relativeOffset:-15}]);assert.equal(data.absent,false);assert.equal((data.record as {title:string}).title,'New title');
});
test('reminder title/completion patch leaves unknown allDay, due, start, recurrence and alarms untouched',async()=>{
  const f=fixture(false),r=await mutation(f,'reminders.update',{completed:true});
  const data=await f.driver.execute(r,device),write=f.calls.find(c=>c.details)!;
  assert.deepEqual(write.details,{title:'Original',notes:'Keep notes',location:'Keep location',completed:true});
  assert.equal((data.record as {all_day:null}).all_day,null);assert.equal(f.current?.dueDate,f.original.dueDate);assert.equal(f.writes,1);
});
for (const change of ['notes','calendar','instance','modified'] as const) test('changed '+change+' fails before OS write',async()=>{
  const f=fixture(),r=await mutation(f,'calendar.delete');
  f.current={...f.current,[{notes:'notes',calendar:'calendarId',instance:'startDate',modified:'lastModifiedDate'}[change]]:'different'};
  await assert.rejects(f.driver.execute(r,device),(e:unknown)=>e instanceof NativeDriverError&&e.code==='conflict');assert.equal(f.writes,0);
});
test('recurring reminder and unsupported date patches never receive write authority',async()=>{
  const f=fixture(false);f.current={...f.current,recurrenceRule:{frequency:'daily'}};
  const r=await mutation(f,'reminders.delete');assert.equal(((r.command.params.target as Record<string,unknown>).snapshot as {mutable:boolean}).mutable,false);
  assert.throws(()=>validateNativeDispatch(r,device,session,at));await assert.rejects(f.driver.execute(r,device));assert.equal(f.writes,0);
  const normal=fixture(false),bad=await mutation(normal,'reminders.update',{due:'2026-10-10T00:00:00Z'});assert.throws(()=>validateNativeDispatch(bad,device,session,at));
});
test('revoked write opt-in and untrusted direct ID dispatch are blocked',async()=>{
  const f=fixture(),r=await mutation(f,'calendar.delete');
  assert.throws(()=>validateNativeDispatch(r,{...device,policy:{...device.policy,calendar_edit:false}},session,at));
  assert.throws(()=>validateNativeDispatch(req('calendar.delete',{calendar_id:'cal',id:'native-id'}),device,session,at));
  f.granted=false;await assert.rejects(f.driver.execute(r,device));assert.equal(f.writes,0);
});
test('delete readback requires successful absence query and unknown is never replayed',async()=>{
  const f=fixture(),r=await mutation(f,'calendar.delete');
  f.api.getEventsAsync=async()=>{throw new Error('bridge lost after delete');};
  const rows=new Map<string,unknown>(),store={async get<T>(k:string){return (rows.get(k)||null) as T|null;},async put<T>(k:string,v:T){rows.set(k,structuredClone(v));}};
  const outcomes:NativeOutcome[]=[],client={async claim(r:NativeRequest){return {...r,state:'executing'};},async finish(r:NativeRequest,o:NativeOutcome){outcomes.push(o);throw new Error('network');}};
  const runner=new NativeActionRunner(store,'synthetic-account',client,f.driver,()=>true,()=>at);
  await assert.rejects(runner.run(r,device,session,true));assert.equal(f.writes,1);assert.equal(outcomes[0].status,'unknown');
  const restored=new NativeActionRunner(store,'synthetic-account',{...client,async finish(r,o){outcomes.push(o);return {...r,state:o.status,result:o};}},f.driver,()=>true,()=>at);
  await restored.recover();assert.equal(f.writes,1);assert.deepEqual(outcomes[0],outcomes[1]);
});
test('recurring event delete uses original single instance and verifies remaining instance does not imply failure',async()=>{
  const f=fixture();f.current={...f.current,recurrenceRule:{frequency:'daily'}};
  const r=await mutation(f,'calendar.delete');
  f.api.getEventsAsync=async()=>f.current?[f.current as never]:[{...f.original,startDate:'2026-10-09T01:00:00Z'} as never];
  const data=await f.driver.execute(r,device);assert.equal(data.absent,true);assert.equal(f.writes,1);
  assert.deepEqual(f.calls.at(-1)?.options,{instanceStartDate:'2026-10-08T01:00:00.000Z',futureEvents:false});
});
test('recovery inspection reads current content without executing or changing original state',async()=>{
  const f=fixture(false),r=await mutation(f,'reminders.update',{completed:true});
  r.state='unknown';f.current={...f.current,completed:true};
  const result=await f.driver.inspect(r,device);assert.match(result,/系统记录已有变化/);assert.match(result,/完成：是/);assert.equal(f.writes,0);assert.equal(r.state,'unknown');
});
