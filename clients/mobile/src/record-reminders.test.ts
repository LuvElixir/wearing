import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError,type Connection} from './core';
import {RecordReminderClient,adoptReminderRead,pendingReminder,reminderCacheKey,reminderKey,reminderReceipt,reminderRequest,submitReminder,type Reminder,type ReminderRequest} from './record-reminders';
import {NotificationClient,notificationTarget,type NotificationTarget} from './notification-client';
import {recordEdit,recordEditChanged,recordPatch,validRecordEdit} from './record-editor';
import {RecordMutations} from './record-mutations';
import {fencedWrite,type AccountFence} from './account-cleanup-model';
const target='life_'+'a'.repeat(32),identity='daily',scope='https://fixture.invalid/|user_'+'a'.repeat(32)+'|tenant_a|daily';
const connection:Connection={endpoint:'https://fixture.invalid/',identity};
const request:ReminderRequest={revision:0,record_revision:1,enabled:true,advance_minutes:15,request_key:'reminder-request-0001'};
const result:Reminder={identity_id:identity,target_id:target,revision:1,record_revision:1,enabled:true,advance_minutes:15,anchor_at:'2026-10-10T12:00:00Z',fire_at:'2026-10-10T11:45:00Z',status:'scheduled',reason:null,provider_status:null,request_key:request.request_key};
class Memory {data=new Map<string,unknown>();fences:AccountFence[]=[];fail=false;async get<T>(key:string):Promise<T|null>{return structuredClone(this.data.get(key)??null) as T|null;}async put(key:string,value:unknown){await this.batch([[key,value]]);}async batch(values:[string,unknown][]){if(this.fail||values.some(([key,value])=>fencedWrite(key,value,this.fences)))throw Error('disk or fence');for(const [key,value]of values)this.data.set(key,structuredClone(value));}}
const read=(store:Memory)=>store.get(reminderKey(scope,target));
const json=(v:unknown,status=200)=>new Response(JSON.stringify(v),{status});
function client(replies:(()=>Response|Promise<Response>)[],c=connection){const calls:{url:string;body:unknown;headers:Headers}[]=[];const api=new RecordReminderClient(c,(async(url,options)=>{calls.push({url:String(url),body:options?.body?JSON.parse(String(options.body)):null,headers:new Headers(options?.headers)});return replies.shift()!();}) as typeof fetch);return{api,calls};}
const bootstrap={token:'fixture-csrf',identities:[{id:identity}]};

test('request and receipt close fields, bind identity/revision/key and exact reminder time',()=>{
  assert.deepEqual(reminderRequest(request),request);assert.deepEqual(reminderReceipt(result,identity,target,request),result);
  for(const patch of [{enabled:'true'},{advance_minutes:10},{owner_scope:'forged'},{record_revision:0},{request_key:'short'}])assert.throws(()=>reminderRequest({...request,...patch}));
  for(const patch of [{identity_id:'work'},{target_id:'life_'+'b'.repeat(32)},{revision:3},{enabled:false},{request_key:'another-request'},{fire_at:result.anchor_at}])assert.throws(()=>reminderReceipt({...result,...patch},identity,target,request),(e:unknown)=>e instanceof ApiError&&e.status===0);
});
test('unknown saving survives cold start and retries exact request, never GET-rebases',async()=>{
  const store=new Memory(),calls:ReminderRequest[]=[];
  await assert.rejects(submitReminder(store,scope,target,{save:async(_t,r)=>{calls.push(r);throw new ApiError('lost');}},request,()=>true));
  assert.equal(pendingReminder(await read(store))?.phase,'pending');
  await assert.rejects(adoptReminderRead(store,scope,target,result),/结果未知/);
  await assert.rejects(submitReminder(store,scope,target,{save:async()=>result},{...request,request_key:'replacement-request'},()=>true));
  await submitReminder(store,scope,target,{save:async(_t,r)=>{calls.push(r);return result;}},undefined,()=>true);
  assert.deepEqual(calls,[request,request]);assert.equal(await read(store),null);assert.deepEqual(await store.get(reminderCacheKey(scope,target)),result);
});
test('unverified success and local receipt transaction failure preserve original request',async()=>{
  const store=new Memory(),h=client([()=>json(bootstrap),()=>json({...result,request_key:'wrong-key'})]);
  await assert.rejects(submitReminder(store,scope,target,h.api,request,()=>true));assert.equal(pendingReminder(await read(store))?.phase,'pending');
  const batch=store.batch.bind(store);let fail=true;store.batch=async values=>{if(fail&&values.some(([key])=>key===reminderCacheKey(scope,target))){fail=false;throw Error('local commit');}await batch(values);};
  await assert.rejects(submitReminder(store,scope,target,{save:async()=>result},undefined,()=>true));assert.equal(pendingReminder(await read(store))?.request.request_key,request.request_key);
  await submitReminder(store,scope,target,{save:async()=>result},undefined,()=>true);assert.equal(await read(store),null);
});
test('proven conflict allows explicit reread, preserves selected input and other identity',async()=>{
  const store=new Memory();await store.put(reminderKey(scope+'other',target),{fixture:'other'});
  await assert.rejects(submitReminder(store,scope,target,{save:async()=>{throw new ApiError('changed',409);}},request,()=>true));assert.equal(pendingReminder(await read(store))?.phase,'rejected');
  await adoptReminderRead(store,scope,target,{...result,revision:3});assert.equal(await read(store),null);assert.deepEqual(await store.get(reminderKey(scope+'other',target)),{fixture:'other'});assert.equal(request.advance_minutes,15);
});
test('failed persistence sends nothing, account cleanup fences prevent late restoration',async()=>{
  const store=new Memory();store.fail=true;let calls=0;await assert.rejects(submitReminder(store,scope,target,{save:async()=>{calls++;return result;}},request,()=>true));assert.equal(calls,0);store.fail=false;
  let active=true;await assert.rejects(submitReminder(store,scope,target,{save:async()=>{active=false;store.fences=[{address:'https://fixture.invalid/',userId:'user_'+'a'.repeat(32)}];store.data.delete(reminderKey(scope,target));return result;}},request,()=>active));
  assert.equal(await read(store),null);assert.equal(await store.get(reminderCacheKey(scope,target)),null);
});
test('transport freezes account and identity, no owner/URL accepted from payload',async()=>{
  const c:Connection={...connection,session:{userId:'user_'+'a'.repeat(32),tenantId:'tenant_a',credentialId:'c'.repeat(32),accessToken:'s'.repeat(64),expiresAt:'2026-10-10T00:00:00Z'}};
  const h=client([()=>json(bootstrap),()=>json(result)],c);c.identity='other';c.session!.accessToken='later';await h.api.save(target,request);
  assert.equal(h.calls[1].headers.get('authorization'),'Bearer '+'s'.repeat(64));assert.equal(h.calls[1].headers.get('X-Wearing-Identity'),identity);assert.deepEqual(h.calls[1].body,request);
});
test('record taps only navigate authenticated exact record and occurrence resolution',async()=>{
  const base={v:1 as const,type:'pajio.record' as const,identity_id:identity,server_id:'a'.repeat(32),event_key:'b'.repeat(64),record_id:target};
  assert.deepEqual(notificationTarget({...base,url:'https://evil.invalid',body:'injected'}),base);assert.equal(notificationTarget({...base,record_id:'../secret'}),null);
  const resolve=async(t:NotificationTarget,value:unknown)=>new NotificationClient(connection,'fixture-installation',(async()=>json(value)) as typeof fetch).resolve(t);
  assert.deepEqual(await resolve(base,{...base,kind:'record_reminder',series_id:null,occurrence_key:null}),{type:'record',identityId:identity,recordId:target,kind:'record_reminder',seriesId:null,occurrenceKey:null});
  const recurring={...base,record_id:'recurrence_'+'a'.repeat(32)+'_20261010'};
  assert.equal((await resolve(recurring,{...recurring,kind:'record_reminder',series_id:'series_'+'a'.repeat(32),occurrence_key:'2026-10-10'})).type,'record');
  for(const patch of [{identity_id:'other'},{record_id:target},{series_id:'series_'+'b'.repeat(32)},{occurrence_key:'2026-10-11'}])await assert.rejects(resolve(recurring,{...recurring,kind:'record_reminder',series_id:'series_'+'a'.repeat(32),occurrence_key:'2026-10-10',...patch}));
});
test('task deadlines use existing durable record queue, legacy drafts cannot clear dates',async()=>{
  const original={id:target,kind:'task' as const,title:'Task',content:'Task',timezone:'Asia/Shanghai',revision:1,updated_at:'2026-10-08T12:00:00Z',due_at:'2026-10-10T12:00:00Z'};
  const oldDraft={revision:1,text:'old draft',start:'',end:''};assert.equal(validRecordEdit(oldDraft),true);assert.equal(recordPatch(original,oldDraft).due_at,undefined);
  const edit={...recordEdit(original),due:''};assert.equal(recordEditChanged(original,edit),true);assert.equal(recordPatch(original,edit).due_at,null);
  const store=new Memory(),queue=new RecordMutations(store,()=> 'deadline-request-001');await queue.enqueue(scope,original,{due_at:null});
  await queue.flush(scope,{update:async(_b,p,a)=>{assert.equal(a,'edit');assert.deepEqual(p,{due_at:null});return{...original,revision:2,due_at:null};},record:async()=>original},()=>true);assert.deepEqual(await queue.items(scope),[]);
  await assert.rejects(queue.enqueue(scope,{...original,kind:'note'},{due_at:original.due_at}));
});
