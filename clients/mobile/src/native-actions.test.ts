import assert from 'node:assert/strict';
import test from 'node:test';
import {NativeActionClient} from './native-action-client';
import {NativeActionDriver, NativeDriverError, type ActionCalendar, type ActionLocation} from './native-action-driver';
import {NativeActionRunner} from './native-action-runner';
import {emptyNativePolicy, nativeRequest, validateNativeDispatch, type NativeDevice, type NativeMethod, type NativeOutcome, type NativeRequest} from './native-action-model';
import {ApiError} from './core';

const at = Date.parse('2026-10-08T00:00:00Z'), session = 'c'.repeat(32), phone = 'a'.repeat(32);
const device:NativeDevice = {server_id:'d'.repeat(32),identity_id:'daily',installation_id:phone,name:'合成 iPhone',revision:1,enabled:true,online:true,
  policy:{...emptyNativePolicy(),calendars:[{id:'cal',title:'测试日历',writable:true}],reminders:[{id:'rem',title:'测试提醒',writable:true}],calendar_create:true,reminder_create:true,location:true},capabilities:['calendar.read','reminders.read','location.read','calendar.create','reminders.create'],availability:'foreground_only'};
function request(method:NativeMethod = 'location.read', params:Record<string,unknown> = {}):NativeRequest {
  const id='native_'+'b'.repeat(32);
  return {id,identity_id:'daily',installation_id:phone,task_id:'task',run_id:'run',fingerprint:'e'.repeat(64),state:'queued',result:null,reviewed:false,
    command:{protocol_version:'1',command_id:id,scope:{tenant_id:device.server_id,identity_id:'daily'},task_id:'task',resource_id:phone,connector_id:phone,connection_id:session,pairing_generation:1,policy_revision:1,lease_epoch:1,method,params,created_at:new Date(at).toISOString(),expires_at:new Date(at+55000).toISOString()}};
}
const create = () => request('reminders.create',{calendar_id:'rem',title:'仅合成测试',notes:'',due:null,all_day:false});
function memory() {
  const rows=new Map<string,unknown>();
  return {rows,async get<T>(key:string):Promise<T | null>{return (structuredClone(rows.get(key)) || null) as T | null;},async put<T>(key:string,v:T){rows.set(key,structuredClone(v));}};
}
function client() {
  let claims=0;const outcomes:NativeOutcome[]=[];
  return {get claims(){return claims;},outcomes,async claim(r:NativeRequest,approve:boolean){claims++;return {...r,state:approve?'executing':'cancelled'};},async finish(r:NativeRequest,o:NativeOutcome){outcomes.push(o);return {...r,state:o.status,result:o};}};
}
function deferred<T>() {let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>resolve=r);return {promise,resolve};}

test('full local scope/policy/deadline guard prevents mismatched native dispatch',()=>{
  const r=create(); validateNativeDispatch(r,device,session,at);
  assert.throws(()=>validateNativeDispatch(r,{...device,server_id:'f'.repeat(32)},session,at));
  assert.throws(()=>validateNativeDispatch(r,{...device,revision:2},session,at));
  assert.throws(()=>validateNativeDispatch(r,device,'f'.repeat(32),at));
  assert.throws(()=>validateNativeDispatch(r,device,session,at+56000));
  assert.throws(()=>validateNativeDispatch({...r,command:{...r.command,params:{...r.command.params,attendees:['outside']}}},device,session,at));
  assert.throws(()=>nativeRequest(r,'other',phone));
  assert.throws(()=>validateNativeDispatch(create(),{...device,policy:{...device.policy,reminders:[]}},session,at));
});
test('no confirmation or inactive foreground produces zero native writes',async()=>{
  const s=memory(),c=client();let calls=0;
  const r=new NativeActionRunner(s,'one',c,{execute:async()=>{calls++;return {}; }},()=>true,()=>at);
  assert.equal((await r.run(create(),device,session,false))?.state,'cancelled');
  const inactive=new NativeActionRunner(s,'one',c,{execute:async()=>{calls++;return {}; }},()=>false,()=>at);
  assert.equal(await inactive.run(create(),device,session,true),null);
  assert.equal(calls,0);assert.equal(c.claims,1);
});
test('admission must be durable before actual OS write',async()=>{
  const s=memory(),c=client();let calls=0;
  const runner=new NativeActionRunner({...s,put:async(key,value)=>{if ((value as {phase?:string})?.phase==='admitted') throw new Error('disk');await s.put(key,value);}},'one',c,{execute:async()=>{calls++;return {};}},()=>true,()=>at);
  await assert.rejects(runner.run(create(),device,session,true),/disk/);assert.equal(calls,0);
  const recovered=new NativeActionRunner(s,'one',c,{execute:async()=>{calls++;return {};}},()=>true,()=>at);
  await recovered.recover();assert.equal(c.outcomes[0].status,'unknown');assert.equal(calls,0);
});
test('process death after admission is recovered without repeating create',async()=>{
  const s=memory(),c=client();let calls=0;
  const runner=new NativeActionRunner(s,'one',c,{execute:async()=>{calls++;return {};}},()=>true,()=>at);
  await s.put(runner.key,{request:create(),phase:'admitted'});
  await runner.recover();assert.equal(calls,0);assert.equal(c.claims,0);assert.equal(c.outcomes[0].status,'unknown');assert.equal(await s.get(runner.key),null);
});
test('lost result acknowledgement resends original receipt only',async()=>{
  const s=memory(),c=client();let calls=0, fail=true;
  const network={...c,finish:async(r:NativeRequest,o:NativeOutcome)=>{c.outcomes.push(o);if(fail) throw new ApiError('offline');return {...r,state:o.status,result:o};}};
  const runner=new NativeActionRunner(s,'one',network,{execute:async()=>{calls++;return {id:'original'};}},()=>true,()=>at);
  await assert.rejects(runner.run(create(),device,session,true),/offline/);
  fail=false;await runner.recover();assert.equal(calls,1);assert.equal(c.outcomes.length,2);assert.deepEqual(c.outcomes[0],c.outcomes[1]);
});
test('old identity write receipt is kept on original journal; new identity stays untouched',async()=>{
  const s=memory(),c=client(),gate=deferred<Record<string,unknown>>();let active=true;
  const runner=new NativeActionRunner(s,'old-tenant|daily',c,{execute:()=>gate.promise},()=>active,()=>at);
  const run=runner.run(create(),device,session,true);
  await new Promise(r=>setTimeout(r,0));active=false;
  await s.put('native-actions-journal:v1:new-tenant|daily',{marker:'new identity'});
  gate.resolve({id:'old-native-record'});await run;
  assert.deepEqual(c.outcomes[0].data,{id:'old-native-record'});
  assert.deepEqual(await s.get('native-actions-journal:v1:new-tenant|daily'),{marker:'new identity'});
});
test('late read after inactive foreground never uploads data',async()=>{
  const s=memory(),c=client(),gate=deferred<Record<string,unknown>>();let active=true;
  const runner=new NativeActionRunner(s,'one',c,{execute:()=>gate.promise},()=>active,()=>at);
  const run=runner.run(request(),device,session,true);await new Promise(r=>setTimeout(r,0));active=false;gate.resolve({latitude:30,longitude:120});await run;
  assert.equal(c.outcomes[0].status,'cancelled');assert.deepEqual(c.outcomes[0].data,{});
});
test('native exception after write does not claim failure/no side effect',async()=>{
  const s=memory(),c=client();const runner=new NativeActionRunner(s,'one',c,{execute:async()=>{throw new Error('OS committed but bridge failed');}},()=>true,()=>at);
  await runner.run(create(),device,session,true);assert.equal(c.outcomes[0].status,'unknown');assert.deepEqual(c.outcomes[0].data,{});
});
function calendar(overrides:Record<string,unknown>={}):ActionCalendar {
  return {getCalendarPermissionsAsync:async()=>({granted:true}),getRemindersPermissionsAsync:async()=>({granted:true}),requestCalendarPermissionsAsync:async()=>{throw new Error('unexpected dialog');},requestRemindersPermissionsAsync:async()=>{throw new Error('unexpected dialog');},getCalendarsAsync:async(kind:string)=>[{id:kind==='event'?'cal':'rem',title:'合成',allowsModifications:true}],...overrides} as unknown as ActionCalendar;
}
test('native driver reads only explicitly selected calendar ids and bounded output',async()=>{
  let ids:string[]=[];
  const api=calendar({getEventsAsync:async(selected:string[])=>{ids=selected;return [{id:'one',calendarId:'cal',title:'合成日程',notes:'a'.repeat(1100),startDate:'2026-10-08T00:00:00Z',endDate:'2026-10-08T01:00:00Z',allDay:false},{id:'outside',calendarId:'private',title:'must not return'}];}});
  const driver=new NativeActionDriver(api,null,()=>true,()=>at);
  const result=await driver.execute(request('calendar.read',{calendar_ids:['cal'],start:'2026-10-08T00:00:00Z',end:'2026-10-09T00:00:00Z',limit:100}),device);
  assert.deepEqual(ids,['cal']);assert.equal((result.items as {notes:string}[]).length,1);assert.equal((result.items as {notes:string}[])[0].notes.length,1000);
});
test('revoked native permission stops dispatch without asking for more permission',async()=>{
  let writes=0;const driver=new NativeActionDriver(calendar({getRemindersPermissionsAsync:async()=>({granted:false}),createReminderAsync:async()=>{writes++;return 'x';}}),null,()=>true,()=>at);
  await assert.rejects(driver.execute(create(),device),(e:unknown)=>e instanceof NativeDriverError && e.code==='permission');assert.equal(writes,0);
});
test('native reminder success requires exact OS readback and marker',async()=>{
  const r=create();let saved:Record<string,unknown>={},writes=0;
  const api=calendar({createReminderAsync:async(id:string,v:Record<string,unknown>)=>{writes++;saved={...v,id:'created',calendarId:id};return 'created';},getReminderAsync:async()=>saved});
  const driver=new NativeActionDriver(api,null,()=>true,()=>at);
  const value=await driver.execute(r,device);assert.equal(value.id,'created');assert.equal(value.marker,'pajio://native/'+r.id);assert.equal(writes,1);
  const wrong=new NativeActionDriver(calendar({createReminderAsync:async()=> 'x',getReminderAsync:async()=>({...saved,title:'changed'})}),null,()=>true,()=>at);
  await assert.rejects(wrong.execute(r,device),(e:unknown)=>e instanceof NativeDriverError && e.code==='readback');
});
test('location is one-shot, checks freshness and revocation after native response',async()=>{
  let granted=true,calls=0;
  const location={getForegroundPermissionsAsync:async()=>({granted}),hasServicesEnabledAsync:async()=>true,getCurrentPositionAsync:async()=>{calls++;granted=false;return {timestamp:at,coords:{latitude:30,longitude:120,accuracy:25}};}} as unknown as ActionLocation;
  const driver=new NativeActionDriver(null,location,()=>true,()=>at);
  await assert.rejects(driver.execute(request(),device),(e:unknown)=>e instanceof NativeDriverError && e.code==='permission');assert.equal(calls,1);
});
test('client sends fixed identity and tenant headers, no secret in device listing',async()=>{
  const calls:{url:string;init:RequestInit}[]=[];
  const connection={endpoint:'https://example.test/',identity:'work',session:{accessToken:'t'.repeat(64),credentialId:'s'.repeat(32),expiresAt:'2099-01-01T00:00:00Z',tenantId:'tenant-one',userId:'user_'+'a'.repeat(32)}};
  const c=new NativeActionClient(connection,{installation_id:phone,secret:'b'.repeat(64)},async(url,init)=>{calls.push({url:String(url),init:init!});return new Response(JSON.stringify({items:[{...device,identity_id:'work'}]}),{status:200});});
  assert.equal((await c.device())?.identity_id,'work');
  const headers=calls[0].init.headers as Record<string,string>;assert.equal(headers['X-Wearing-Identity'],'work');assert.equal(headers['X-Pajio-Expected-Tenant'],'tenant-one');assert.equal(calls[0].init.body,undefined);
});

test('mismatched finish acknowledgement keeps durable receipt and never repeats OS write',async()=>{
  const s=memory(),c=client();let writes=0,wrong=true;
  const transport={...c,finish:async(r:NativeRequest,o:NativeOutcome)=>({...r,run_id:wrong?'different-run':r.run_id,state:o.status,result:o})};
  const runner=new NativeActionRunner(s,'one',transport,{execute:async()=>{writes++;return {id:'created'};}},()=>true,()=>at);
  await assert.rejects(runner.run(create(),device,session,true));
  assert.equal((await s.get<{phase:string}>(runner.key))?.phase,'receipt');
  wrong=false;await runner.recover();assert.equal(writes,1);assert.equal(await s.get(runner.key),null);
});
test('HTTP client rejects altered policy, dispatch and receipt acknowledgements',async()=>{
  const connection={endpoint:'https://example.test/',identity:'daily'};
  let response:unknown=device;
  const c=new NativeActionClient(connection,{installation_id:phone,secret:'b'.repeat(64)},async(url)=>new Response(JSON.stringify(String(url).endsWith('/api/bootstrap')?{token:'csrf',identities:[{id:'daily'}]}:response),{status:200}));
  response={...device,revision:2,policy:{...device.policy,location:false}};
  await assert.rejects(c.configure(1,true,device.policy));
  response={...device,connection_id:session,capabilities:['location.read']};
  await assert.rejects(c.connect(device,session,device.capabilities));
  response={...create(),state:'executing',run_id:'wrong-run'};
  await assert.rejects(c.claim(create(),true));
  response={...create(),state:'succeeded',result:{status:'succeeded',code:'ok',data:{id:'wrong-record'}}};
  await assert.rejects(c.finish(create(),{status:'succeeded',code:'ok',data:{id:'original'}}));
});
test('offline or removed capability cannot execute even when policy still permits it',()=>{
  assert.throws(()=>validateNativeDispatch(create(),{...device,online:false},session,at));
  assert.throws(()=>validateNativeDispatch(create(),{...device,capabilities:['location.read']},session,at));
});
