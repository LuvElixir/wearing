import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {NativeActionDriver,type ActionCalendar} from './native-action-driver';
import {NativeActionRunner} from './native-action-runner';
import {emptyNativePolicy,type NativeDevice,type NativeMethod,type NativeRequest,type NativeOutcome} from './native-action-model';

const at=Date.parse('2026-10-08T00:00:00Z'),phone='a'.repeat(32),session='c'.repeat(32);
const device:NativeDevice={server_id:'d'.repeat(32),identity_id:'daily',installation_id:phone,name:'synthetic',revision:1,enabled:true,online:true,availability:'foreground_only',policy:{...emptyNativePolicy(),calendars:[{id:'cal',title:'Synthetic',writable:true}],reminders:[{id:'rem',title:'Synthetic',writable:true}],calendar_edit:true,reminder_edit:true},capabilities:['calendar.read','calendar.update','calendar.delete','reminders.read','reminders.update','reminders.delete']};
let serial=0;
function request(method:NativeMethod,params:Record<string,unknown>):NativeRequest {
  const id='native_'+(++serial).toString(16).padStart(32,'0');
  return {id,identity_id:'daily',installation_id:phone,task_id:'task',run_id:'run',fingerprint:'e'.repeat(64),state:'queued',result:null,reviewed:false,command:{protocol_version:'1',command_id:id,scope:{tenant_id:device.server_id,identity_id:'daily'},task_id:'task',resource_id:phone,connector_id:phone,connection_id:session,pairing_generation:1,policy_revision:1,lease_epoch:1,method,params,created_at:new Date(at).toISOString(),expires_at:new Date(at+55000).toISOString()}};
}
const event=()=>({id:'original',calendarId:'cal',title:'合成会议',notes:'原备注',location:'原地点',startDate:'2026-10-08T01:00:00Z',endDate:'2026-10-08T02:00:00Z',allDay:false,availability:'busy',isDetached:false});
function adapter(overrides:Record<string,unknown>):ActionCalendar{return {getCalendarPermissionsAsync:async()=>({granted:true}),getRemindersPermissionsAsync:async()=>({granted:true}),getCalendarsAsync:async(kind:string)=>[{id:kind==='event'?'cal':'rem',title:'Synthetic',allowsModifications:true}],...overrides} as unknown as ActionCalendar;}
const hash=async(value:string)=>createHash('sha256').update(value).digest('hex');
async function readTarget(driver:NativeActionDriver,reminder=false){const r=request(reminder?'reminders.read':'calendar.read',reminder?{calendar_ids:['rem'],completed:true,limit:100}:{calendar_ids:['cal'],start:'2026-10-08T00:00:00Z',end:'2026-10-09T00:00:00Z',limit:100});const data=await driver.execute(r,device);return {record_ref:r.id+':0',calendar_id:reminder?'rem':'cal',target:(data.items as Record<string,unknown>[])[0]};}
function runner(driver:NativeActionDriver){const values=new Map<string,unknown>(),outcomes:NativeOutcome[]=[];const store={async get<T>(k:string){return (values.get(k)||null) as T|null;},async put<T>(k:string,v:T){values.set(k,structuredClone(v));}};const client={async claim(r:NativeRequest,yes:boolean){return {...r,state:yes?'executing':'cancelled'};},async finish(r:NativeRequest,o:NativeOutcome){outcomes.push(o);return {...r,state:o.status,result:o};}};return {store,outcomes,client,value:new NativeActionRunner(store,'synthetic-review',client,driver,()=>true,()=>at)};}

test('SDK57 omitted alarms on ordinary event can still be safely edited without inventing an alarm',async()=>{
  const raw=event();let calls=0;
  const driver=new NativeActionDriver(adapter({getEventsAsync:async()=>[raw],getEventAsync:async()=>raw,updateEventAsync:async(_id:string,patch:Record<string,unknown>)=>{calls++;Object.assign(raw,patch);return raw.id;}}),null,()=>true,()=>at,hash);
  const p=await readTarget(driver);assert.equal((p.target.snapshot as {mutable:boolean}).mutable,true);
  const flow=runner(driver),result=await flow.value.run(request('calendar.update',{...p,patch:{title:'修改'}}),device,session,true);
  assert.equal(result?.state,'succeeded');assert.equal(calls,1);assert.deepEqual((raw as Record<string,unknown>).alarms,[]);
});

test('SDK57 coord versus coords geofence alarm cannot be silently lost while editing a title',async()=>{
  const raw={...event(),alarms:[{relativeOffset:0,structuredLocation:{title:'办公室',radius:100,proximity:'enter',coord:{latitude:30,longitude:120}}}]};let calls=0;
  const driver=new NativeActionDriver(adapter({getEventsAsync:async()=>[raw],getEventAsync:async()=>raw,updateEventAsync:async(_id:string,patch:Record<string,unknown>)=>{calls++;Object.assign(raw,patch);return raw.id;}}),null,()=>true,()=>at,hash);
  const p=await readTarget(driver);
  // The limited contract rejects alarms that cannot round-trip before any OS mutation.
  assert.equal((p.target.snapshot as {mutable:boolean}).mutable,false);
  const forged={...p,target:{...p.target,snapshot:{...(p.target.snapshot as object),mutable:true}}};
  const flow=runner(driver),result=await flow.value.run(request('calendar.update',{...forged,patch:{title:'修改'}}),device,session,true);
  assert.equal(result?.state,'cancelled');assert.equal(result?.result?.code,'unsupported');assert.equal(calls,0);
});

test('reminder title update preserves SDK omitted allDay and omits dates and recurrence from native patch',async()=>{
  const raw={id:'rem-original',calendarId:'rem',title:'合成提醒',notes:'原备注',location:'原地点',dueDate:'2026-10-08T00:00:00Z',completed:false};let savedPatch:Record<string,unknown>|null=null;
  const driver=new NativeActionDriver(adapter({getRemindersAsync:async()=>[raw],getReminderAsync:async()=>raw,updateReminderAsync:async(_id:string,patch:Record<string,unknown>)=>{savedPatch=patch;Object.assign(raw,patch);return raw.id;}}),null,()=>true,()=>at,hash);
  const p=await readTarget(driver,true),flow=runner(driver);assert.equal(p.target.all_day,null);
  const result=await flow.value.run(request('reminders.update',{...p,patch:{title:'修改提醒'}}),device,session,true);
  assert.equal(result?.state,'succeeded');assert.deepEqual(savedPatch,{title:'修改提醒',notes:'原备注',location:'原地点'});assert.equal((result?.result?.data.record as Record<string,unknown>).all_day,null);
});

test('system edit after phone approval is rejected by fresh snapshot before native mutation',async()=>{
  let raw={...event(),alarms:[]},calls=0;
  const driver=new NativeActionDriver(adapter({getEventsAsync:async()=>[raw],getEventAsync:async()=>raw,updateEventAsync:async()=>{calls++;return raw.id;}}),null,()=>true,()=>at,hash);
  const p=await readTarget(driver);raw={...raw,location:'另一客户端修改'};
  const flow=runner(driver);const result=await flow.value.run(request('calendar.update',{...p,patch:{title:'修改'}}),device,session,true);
  assert.equal(result?.state,'cancelled');assert.equal(result?.result?.code,'conflict');assert.equal(calls,0);
});

test('deletion succeeds only on exact scoped absence; lost readback remains unknown without another OS call',async()=>{
  const raw={...event(),alarms:[],recurrenceRule:{frequency:'weekly',interval:1}};let calls=0,listFailed=false,options:unknown;
  const driver=new NativeActionDriver(adapter({getEventsAsync:async()=>{if(listFailed)throw new Error('bridge lost');return [raw];},getEventAsync:async()=>raw,deleteEventAsync:async(_id:string,value:unknown)=>{calls++;options=value;listFailed=true;}}),null,()=>true,()=>at,hash);
  const p=await readTarget(driver),flow=runner(driver),result=await flow.value.run(request('calendar.delete',p),device,session,true);
  assert.equal(result?.state,'unknown');assert.deepEqual(options,{instanceStartDate:'2026-10-08T01:00:00.000Z',futureEvents:false});assert.equal(calls,1);
  await flow.value.recover();assert.equal(calls,1);
});
