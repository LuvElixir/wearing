import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError,type Connection} from './core';
import {ConversationSourcesClient,adoptSourcePage,excludeConversation,mergeSourcePages,pendingSource,sourcePage,sourcePendingKey,sourceReceipt,sourceReceiptKey,sourceRequest,type SourcePage,type SourceReceipt,type SourceRequest} from './conversation-sources';
import {accountCleanupPlan,fencedWrite,type AccountFence} from './account-cleanup-model';
const identity='daily',scope='https://fixture.invalid/|user_'+'a'.repeat(32)+'|tenant_a|daily';
const connection:Connection={endpoint:'https://fixture.invalid/',identity,session:{userId:'user_'+'a'.repeat(32),tenantId:'tenant_a',credentialId:'c'.repeat(32),accessToken:'s'.repeat(64),expiresAt:new Date(Date.now()+3_600_000).toISOString()}};
const request:SourceRequest={source_id:'source_'+'a'.repeat(64),source_revision:'b'.repeat(64),revision:0,request_key:'exclude-fixture-0001'};
const result:SourceReceipt={...request,identity_id:identity,revision:1,excluded:true,excluded_at:'2026-10-10T12:00:00Z',continuation_reset:true,history_retained:true};
const page:SourcePage={identity_id:identity,revision:0,snapshot:'c'.repeat(64),next_offset:null,items:[{source_id:request.source_id,source_revision:request.source_revision,source_task_id:'d'.repeat(32),title:'Synthetic conversation',started_at:result.excluded_at,updated_at:result.excluded_at,message_count:3,excluded:false,excluded_at:null}]};
class Memory {data=new Map<string,unknown>();fences:AccountFence[]=[];fail=false;async get<T>(key:string):Promise<T|null>{return structuredClone(this.data.get(key)??null) as T|null;}async put(key:string,value:unknown){await this.batch([[key,value]]);}async batch(values:[string,unknown][]){if(this.fail||values.some(([key,value])=>fencedWrite(key,value,this.fences)))throw Error('disk or fence');for(const [key,value]of values)this.data.set(key,structuredClone(value));}}
const read=(store:Memory)=>store.get(sourcePendingKey(scope));
const json=(v:unknown,status=200)=>new Response(JSON.stringify(v),{status});
const bootstrap={token:'fixture-csrf',identities:[{id:identity}]};
function client(replies:(()=>Response|Promise<Response>)[],c=connection){const calls:{url:string;body:unknown;headers:Headers}[]=[];const api=new ConversationSourcesClient(c,(async(url,options)=>{calls.push({url:String(url),body:options?.body?JSON.parse(String(options.body)):null,headers:new Headers(options?.headers)});return replies.shift()!();}) as typeof fetch);return{api,calls};}

test('request closes fields and receipt binds exact identity, source, revision and recovery key',()=>{
  assert.deepEqual(sourceRequest(request),request);assert.deepEqual(sourceReceipt(result,identity,request),result);assert.deepEqual(sourcePage(page,identity),page);
  for(const patch of [{owner_scope:'forged'},{source_id:'../other'},{source_revision:'short'},{revision:-1},{request_key:'short'}])assert.throws(()=>sourceRequest({...request,...patch}));
  for(const patch of [{identity_id:'other'},{source_revision:'a'.repeat(64)},{source_id:'source_'+'b'.repeat(64)},{revision:0},{history_retained:false},{continuation_reset:false},{request_key:'another-key'}])assert.throws(()=>sourceReceipt({...result,...patch},identity,request),(e:unknown)=>e instanceof ApiError&&e.status===0);
  assert.throws(()=>sourcePage({...page,items:[...page.items,...page.items]},identity));assert.throws(()=>sourcePage({...page,identity_id:'other'},identity));
});
test('pagination preserves exact snapshot, shows more than ten and rejects drift',()=>{
  const first={...page,items:Array.from({length:20},(_,i)=>({...page.items[0],source_id:'source_'+i.toString(16).padStart(64,'0')})),next_offset:20};
  const next={...page,items:[{...page.items[0],source_id:'source_'+'f'.repeat(64)}]};
  assert.equal(mergeSourcePages(first,next,20).items.length,21);
  for(const patch of [{snapshot:'d'.repeat(64)},{identity_id:'other'},{revision:2},{items:[first.items[0]]}])assert.throws(()=>mergeSourcePages(first,{...next,...patch},20));
});
test('unknown response survives cold start, cannot rebase and retries same key',async()=>{
  const store=new Memory(),calls:SourceRequest[]=[];
  await assert.rejects(excludeConversation(store,scope,{exclude:async r=>{calls.push(r);throw new ApiError('lost');}},request,()=>true));
  assert.equal(pendingSource(await read(store))?.phase,'pending');await assert.rejects(adoptSourcePage(store,scope,page));
  await assert.rejects(excludeConversation(store,scope,{exclude:async()=>result},{...request,request_key:'new-key-00000000'},()=>true));
  await excludeConversation(store,scope,{exclude:async r=>{calls.push(r);return result;}},undefined,()=>true);
  assert.deepEqual(calls,[request,request]);assert.equal(await read(store),null);assert.deepEqual(await store.get(sourceReceiptKey(scope)),result);
});
test('invalid receipt or local transaction loss keeps recoverable request',async()=>{
  const store=new Memory(),h=client([()=>json(bootstrap),()=>json({...result,request_key:'wrong'})]);
  await assert.rejects(excludeConversation(store,scope,h.api,request,()=>true));assert.equal(pendingSource(await read(store))?.phase,'pending');
  const batch=store.batch.bind(store);let fail=true;store.batch=async values=>{if(fail&&values.some(([key])=>key===sourceReceiptKey(scope))){fail=false;throw Error('local commit lost');}await batch(values);};
  await assert.rejects(excludeConversation(store,scope,{exclude:async()=>result},undefined,()=>true));assert.equal(pendingSource(await read(store))?.request.request_key,request.request_key);
  await excludeConversation(store,scope,{exclude:async()=>result},undefined,()=>true);assert.equal(await read(store),null);
});
test('proven CAS rejection requires reread and a new explicit confirmation',async()=>{
  const store=new Memory();await store.put(sourcePendingKey(scope+'other'),{fixture:'another identity'});
  await assert.rejects(excludeConversation(store,scope,{exclude:async()=>{throw new ApiError('changed',409);}},request,()=>true));
  assert.equal(pendingSource(await read(store))?.phase,'rejected');await assert.rejects(excludeConversation(store,scope,{exclude:async()=>result},undefined,()=>true));
  await adoptSourcePage(store,scope,page);assert.equal(await read(store),null);assert.deepEqual(await store.get(sourcePendingKey(scope+'other')),{fixture:'another identity'});
});
test('write-before-send plus account switch and deletion fence prevent late recreation',async()=>{
  const store=new Memory();store.fail=true;let calls=0;await assert.rejects(excludeConversation(store,scope,{exclude:async()=>{calls++;return result;}},request,()=>true));assert.equal(calls,0);store.fail=false;
  let current=true;await assert.rejects(excludeConversation(store,scope,{exclude:async()=>{current=false;store.fences=[{address:'https://fixture.invalid/',userId:connection.session!.userId}];const plan=accountCleanupPlan(connection,[...store.data].map(([key,value])=>({key,value})));assert.ok(plan.remove.includes(sourcePendingKey(scope)));store.data.delete(sourcePendingKey(scope));return result;}},request,()=>current));
  assert.equal(await read(store),null);assert.equal(await store.get(sourceReceiptKey(scope)),null);
});
test('transport freezes credentials; model payload supplies no owner or destination',async()=>{
  const c=structuredClone(connection),h=client([()=>json(bootstrap),()=>json(result)],c);c.identity='other';c.session!.accessToken='changed';await h.api.exclude(request);
  assert.equal(h.calls[1].headers.get('authorization'),'Bearer '+'s'.repeat(64));assert.equal(h.calls[1].headers.get('X-Wearing-Identity'),identity);assert.equal(h.calls[1].url,'https://fixture.invalid/api/conversation-sources/exclude');assert.deepEqual(h.calls[1].body,request);
});
