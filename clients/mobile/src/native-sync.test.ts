import {test} from 'node:test';
import assert from 'node:assert/strict';
import type {Event,Reminder} from 'expo-calendar/legacy';
import {chooseNativeSync,runNativeSync,SyncPermissionLost,type SyncRemote} from './native-sync-engine';
import {eventSnapshot,reminderSnapshot,syncKey,syncReceipt,type SyncLocal,type SyncSnapshot,type SyncReceipt,type SyncBatch} from './native-sync-model';
import {NativeSyncClient} from './native-sync-client';
import type {Store} from './core';
const source={kind:'event' as const,id:'cal',title:'合成日历'},start=new Date('2026-10-01T00:00:00Z'),end=new Date('2026-11-01T00:00:00Z');
const event=(patch:Partial<Event>={}):Event=>({id:'event',calendarId:'cal',title:'合成会议',allDay:false,startDate:'2026-10-08T01:00:00Z',endDate:'2026-10-08T02:00:00Z',timeZone:'Asia/Shanghai',...patch});
const snapshot=()=>eventSnapshot(source,[event()],start,end,'Asia/Shanghai');
function env(){
  const rows=new Map<string,unknown>();let counter=0,active=true,reads=0,writes=0,changed=0;
  const store:Pick<Store,'get'|'put'>={get:async<T>(key:string)=>(structuredClone(rows.get(key))??null) as T|null,put:async(key,value)=>{rows.set(key,structuredClone(value));}};
  const nonce=()=> (++counter).toString(16).padStart(32,'0');
  const remote:SyncRemote={state:async()=>({revision:0,enabled:false,sources:[]}),configure:async v=>({...v,revision:v.revision+1}),upload:async v=>{writes++;return receipt(v);}};
  const run=()=>runNativeSync({store,scope:'synthetic',nonce,active:()=>active,remote:()=>remote,allowed:async()=>{},read:async()=>{reads++;return snapshot();},changed:()=>{changed++;}});
  return {store,nonce,remote,run,state:()=>store.get<SyncLocal>(syncKey('synthetic')),disable:()=>{active=false;},counts:()=>({reads,writes,changed}),choose:(enabled=true)=>chooseNativeSync(store,'synthetic',{enabled,sources:[source]},nonce)};
}
const receipt=(v:SyncBatch):SyncReceipt=>({request_id:v.request_id,revision:v.revision,observed_at:v.observed_at,record_ids:['life_'+'a'.repeat(32)],created:1,updated:0,unchanged:0,conflicts:0,unseen:0,truncated:v.snapshots.filter(s=>!s.complete).length});

test('recurrence occurrence key survives moving an instance and preserves a distinct second occurrence',()=>{
  const one=event({originalStartDate:'2026-10-08T01:00:00Z'}),two=event({originalStartDate:'2026-10-09T01:00:00Z',startDate:'2026-10-09T01:00:00Z',endDate:'2026-10-09T02:00:00Z'});
  const initial=eventSnapshot(source,[one,two],start,end,'Asia/Shanghai');
  const moved=eventSnapshot(source,[{...one,startDate:'2026-10-08T03:00:00Z',endDate:'2026-10-08T04:00:00Z'},two],start,end,'Asia/Shanghai');
  assert.deepEqual(moved.items.map(i=>i.occurrence_id),initial.items.map(i=>i.occurrence_id));assert.notEqual(initial.items[0].occurrence_id,initial.items[1].occurrence_id);
});
test('all-day events use local dates and unknown reminder times never become artificial due timestamps',()=>{
  const all=eventSnapshot(source,[event({allDay:true,startDate:'2026-10-07T16:00:00Z',endDate:'2026-10-08T16:00:00Z'})],start,end,'Asia/Shanghai');
  assert.equal(all.items[0].record.start_at,'2026-10-08');assert.equal(all.items[0].record.end_at,'2026-10-09');
  const reminder=reminderSnapshot({kind:'reminder',id:'rem',title:'提醒'},[{id:'r',calendarId:'rem',title:'全天未知',completed:false,dueDate:'2026-10-07T16:00:00Z'} as Reminder],'Asia/Shanghai');
  assert.equal(reminder.items[0].record.due_at,null);assert.match(reminder.items[0].record.content,/2026-10-08/);
});
test('foreign rows excluded and oversized native lists are explicitly incomplete',()=>{
  const rows=Array.from({length:501},(_,i)=>event({id:'e'+i}));
  const value=eventSnapshot(source,[...rows,event({id:'foreign',calendarId:'private'})],start,end,'Asia/Shanghai');
  assert.equal(value.items.length,500);assert.equal(value.complete,false);assert.ok(value.items.every(i=>i.external_id!=='foreign'));
});
test('opt-in required and successful sync has a durable batch before upload',async()=>{
  const e=env();await e.run();assert.deepEqual(e.counts(),{reads:0,writes:0,changed:0});
  await e.choose();e.remote.upload=async batch=>{assert.deepEqual((await e.state())?.pending,batch);return receipt(batch);};
  await e.run();assert.equal((await e.state())?.pending,null);assert.equal(e.counts().changed,1);
});
test('lost upload response replays exact saved batch before another native read',async()=>{
  const e=env();await e.choose();let first:SyncBatch|null=null;
  e.remote.upload=async batch=>{first=batch;throw new Error('offline');};
  await assert.rejects(e.run,/offline/);assert.deepEqual((await e.state())?.pending,first);
  let count=0;e.remote.upload=async batch=>{if(!count++)assert.deepEqual(batch,first);return receipt(batch);};
  await e.run();assert.equal((await e.state())?.pending,null);assert.equal(count,2);
});
test('disable during native read drops the late snapshot before upload',async()=>{
  const e=env();await e.choose();let resolve!:(v:SyncSnapshot)=>void;
  const read=new Promise<SyncSnapshot>(r=>{resolve=r;});
  const running=runNativeSync({store:e.store,scope:'synthetic',nonce:e.nonce,active:()=>true,remote:()=>e.remote,allowed:async()=>{},read:async()=>read,changed:()=>{}});
  await new Promise(r=>setTimeout(r,10));await e.choose(false);resolve(snapshot());await running;
  assert.equal(e.counts().writes,0);assert.equal((await e.state())?.desired.enabled,false);
});
test('permission revocation drops queued data and disables local collection',async()=>{
  const e=env();await e.choose();e.remote.upload=async()=>{throw new Error('offline');};await assert.rejects(e.run);
  await assert.rejects(()=>runNativeSync({store:e.store,scope:'synthetic',nonce:e.nonce,active:()=>true,remote:()=>e.remote,allowed:async()=>{throw new SyncPermissionLost('revoked');},read:async()=>snapshot(),changed:()=>{}}),/revoked/);
  assert.equal((await e.state())?.desired.enabled,false);assert.equal((await e.state())?.pending,null);
});
test('backgrounding before server config response prevents native reads',async()=>{
  const e=env();await e.choose();e.remote.configure=async v=>{e.disable();return {...v,revision:v.revision+1};};
  await e.run();assert.equal(e.counts().reads,0);assert.equal(e.counts().writes,0);
});
test('local journal failure prevents all native uploads',async()=>{
  const e=env();await e.choose();const original=e.store.put;
  e.store.put=async(k,v)=>{if((v as SyncLocal)?.pending)throw new Error('disk');return original(k,v);};
  await assert.rejects(e.run,/disk/);assert.equal(e.counts().writes,0);
});

test('corrupt pending source cannot bypass selection and upload on recovery',async()=>{
  const e=env();await e.choose();e.remote.upload=async()=>{throw new Error('offline');};await assert.rejects(e.run);
  const local=(await e.state())!;local.pending!.snapshots[0].source={...source,id:'private-unselected'};
  await e.store.put(syncKey('synthetic'),local);
  await assert.rejects(e.run,/队列无法核对/);assert.equal(e.counts().writes,0);
});
test('receipt counts and source truncation must match the saved batch',()=>{
  const batch={request_id:'a'.repeat(32),revision:1,observed_at:'2026-10-08T01:00:00Z',snapshots:[snapshot()]};
  assert.deepEqual(syncReceipt(receipt(batch),batch),receipt(batch));
  assert.throws(()=>syncReceipt({...receipt(batch),created:0},batch),/回执不完整/);
  assert.throws(()=>syncReceipt({...receipt(batch),truncated:1},batch),/回执不完整/);
  assert.throws(()=>syncReceipt({...receipt(batch),request_id:'b'.repeat(32)},batch),/回执不完整/);
});
test('cloud client pins trusted account tenant and identity on bootstrap and upload',async()=>{
  const calls:{url:string;init:RequestInit}[]=[];
  const connection={endpoint:'https://synthetic.example/',identity:'daily',session:{accessToken:'a'.repeat(64),credentialId:'b'.repeat(32),userId:'user_'+'c'.repeat(32),tenantId:'synthetic',expiresAt:'2099-01-01T00:00:00Z'}};
  const batch={request_id:'a'.repeat(32),revision:1,observed_at:'2026-10-08T01:00:00Z',snapshots:[snapshot()]};
  const fetcher=(async(url,init)=>{calls.push({url:String(url),init:init!});return new Response(JSON.stringify(String(url).endsWith('/api/bootstrap')?{token:'csrf',identities:[{id:'daily'}]}:receipt(batch)),{status:200});}) as typeof fetch;
  const client=new NativeSyncClient(connection,'f'.repeat(32),fetcher,()=>true);
  await client.upload(batch);assert.equal(calls.length,2);
  for(const call of calls){const headers=call.init.headers as Record<string,string>;assert.equal(headers.Authorization,'Bearer '+'a'.repeat(64));assert.equal(headers['X-Pajio-Expected-Tenant'],'synthetic');assert.equal(headers['X-Wearing-Identity'],'daily');assert.equal(call.init.redirect,'error');}
  assert.equal((calls[1].init.headers as Record<string,string>)['X-Wearing-Token'],'csrf');assert.equal(JSON.parse(calls[1].init.body as string).installation,'f'.repeat(32));
});
test('stopped client rejects a late response body and does not retry with old credentials',async()=>{
  let active=true,calls=0;
  const fetcher=(async()=>{calls++;return {ok:true,status:200,json:async()=>{active=false;return {token:'csrf',identities:[{id:'daily'}]};}};}) as typeof fetch;
  const client=new NativeSyncClient({endpoint:'http://localhost/',identity:'daily'},'a'.repeat(32),fetcher,()=>active);
  await assert.rejects(()=>client.state(),/同步已停止/);assert.equal(calls,1);
});

test('native sync settings and queued notes are fenced and cleaned only for their account',async()=>{
  const {accountCleanupPlan,fenceFor,fencedWrite}=await import('./account-cleanup-model');
  const {scopeOf}=await import('./core');
  const connection={endpoint:'https://synthetic.example/',identity:'daily',session:{accessToken:'a'.repeat(64),credentialId:'b'.repeat(32),userId:'user_'+'c'.repeat(32),tenantId:'synthetic',expiresAt:'2099-01-01T00:00:00Z'}};
  const another={...connection,session:{...connection.session,userId:'user_'+'d'.repeat(32)}};
  const own=syncKey(scopeOf(connection)),other=syncKey(scopeOf(another));
  assert.equal(fencedWrite(own,{pending:'private notes'},[fenceFor(connection)]),true);
  assert.equal(fencedWrite(other,{pending:'other notes'},[fenceFor(connection)]),false);
  assert.deepEqual(accountCleanupPlan(connection,[{key:own,value:{installation:'a'.repeat(32)}},{key:other,value:{installation:'b'.repeat(32)}}]).remove,[own]);
});
