import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {AIConsentClient,AIConsentError,AIConsentGate,AI_PRIVACY_URL,aiConsentSnapshot,needsAIConsent,type AIConsentSnapshot} from './ai-consent-client';
import {Outbox,scopeOf,type Connection,type Pending,type RecordItem,type Store,type Transport} from './core';
import {PUBLIC_PAJIO_ENDPOINT} from './connection-default';

const connection=():Connection=>({endpoint:PUBLIC_PAJIO_ENDPOINT,identity:'daily',session:{accessToken:'t'.repeat(64),expiresAt:new Date(Date.now()+3_600_000).toISOString(),userId:'user_'+'a'.repeat(32),tenantId:'synthetic_consent_only',credentialId:'c'.repeat(32)}});
const requestId='1'.repeat(32);
const snapshot=(state:AIConsentSnapshot['state']='not_granted',revision=state==='not_granted'?0:1):AIConsentSnapshot=>({required:true,provider:{id:'deepseek',name:'DeepSeek',origin:'https://api.deepseek.com',privacy_url:AI_PRIVACY_URL},policy_version:'2026-10-10',disclosure:{title:'AI 服务与数据授权',purpose:'为你处理主动交付的任务。',data_categories:['任务正文','为完成任务选择的上下文'],withdrawal:'撤回后停止新的 AI 处理。'},accepted:state==='accepted',state,revision,updated_at:revision?1791600000.125:null});
const receipt=(state:AIConsentSnapshot['state']='accepted',action:'accept'|'revoke'='accept',revision=1)=>({...snapshot(state,revision),receipt:{request_id:requestId,action,revision,recorded_at:1791600000.125}});
const bootstrap=()=>({version:'0.2.0',token:'synthetic-csrf',identities:[{id:'daily'}]});
const signal=()=>new AbortController().signal;
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(r=>{resolve=r;});return {promise,resolve};}

test('real server Unix-second fractions are accepted; revision remains an integer',()=>{
  const view=aiConsentSnapshot(snapshot('accepted'));
  assert.equal(view.updated_at,1791600000.125);assert.equal(view.accepted,true);
  for(const updated_at of [0,-1,Infinity,NaN,'1791600000.125'])assert.throws(()=>aiConsentSnapshot({...snapshot('accepted'),updated_at}),AIConsentError);
  for(const revision of [-1,1.25,Infinity,'1'])assert.throws(()=>aiConsentSnapshot({...snapshot('accepted'),revision}),AIConsentError);
});

test('partial, contradictory and different-provider responses cannot manufacture consent',()=>{
  const yes=snapshot('accepted');
  const invalid:unknown[]=[null,{},true,{accepted:true},{...yes,required:false},{...yes,provider:{...yes.provider,id:'other'}},{...yes,provider:{...yes.provider,origin:'https://other.example'}},{...yes,provider:{...yes.provider,privacy_url:'javascript:alert(1)'}},{...yes,state:'revoked'},{...yes,accepted:'true'},{...yes,revision:0},{...yes,updated_at:null},{...yes,disclosure:{...yes.disclosure,data_categories:[]}},{...yes,disclosure:{...yes.disclosure,data_categories:['x'.repeat(501)]}}];
  for(const value of invalid)assert.throws(()=>aiConsentSnapshot(value),AIConsentError);
  const source=snapshot('accepted'),copy=aiConsentSnapshot(source);source.disclosure.data_categories[0]='changed elsewhere';
  assert.notEqual(copy.disclosure.data_categories[0],source.disclosure.data_categories[0]);
});

test('policy change not_granted with an existing revision is not inferred as accepted',()=>{
  const value=aiConsentSnapshot({...snapshot('not_granted',4),policy_version:'next-policy'});
  assert.equal(value.accepted,false);assert.equal(value.revision,4);
});

test('gate defaults closed and separates exact account, identity and activation objects',()=>{
  const a=connection(),b={...connection(),session:{...connection().session!,tenantId:'other_tenant'}},identity={...a,identity:'work'},sameCredentials={...a};
  const gate=new AIConsentGate();assert.equal(gate.allows(a),false);gate.activate(a);
  assert.equal(gate.allows(a),false);assert.equal(gate.observe(a,snapshot('accepted')),true);assert.equal(gate.allows(a),true);
  for(const other of [b,identity,sameCredentials])assert.equal(gate.allows(other),false);
  gate.activate(b);assert.equal(gate.observe(a,snapshot('accepted')),false);assert.equal(gate.allows(a),false);assert.equal(gate.allows(b),false);
  gate.observe(b,snapshot('accepted'));gate.activate(b);assert.equal(gate.allows(b),false);
  gate.activate(null);assert.equal(gate.observe(b,snapshot('accepted')),false);assert.equal(gate.allows(b),false);
});

test('background, withdrawal and account deletion invalidation immediately close the gate',()=>{
  const a=connection(),other=connection(),gate=new AIConsentGate();gate.activate(a);gate.observe(a,snapshot('accepted'));
  gate.invalidate(other);assert.equal(gate.allows(a),true);
  gate.invalidate(a);assert.equal(gate.allows(a),false);
  gate.observe(a,snapshot('accepted'));gate.observe(a,snapshot('revoked',2));assert.equal(gate.allows(a),false);
  assert.equal(needsAIConsent(a),true);assert.equal(needsAIConsent({endpoint:'http://127.0.0.1:8878/',identity:'daily'}),false);
});

test('read is only the authenticated fixed-path GET, without bootstrap, body, cookie or token URL',async()=>{
  const a=connection(),calls:{url:string;init?:RequestInit}[]=[];
  const client=new AIConsentClient(a,async(url,init)=>{calls.push({url:String(url),init});return Response.json(snapshot());});
  assert.equal((await client.read(signal())).accepted,false);assert.equal(calls.length,1);
  assert.equal(calls[0].url,PUBLIC_PAJIO_ENDPOINT+'api/ai-consent');assert.equal(calls[0].init?.method,'GET');assert.equal(calls[0].init?.body,undefined);
  assert.deepEqual(calls[0].init?.headers,{Authorization:'Bearer '+a.session!.accessToken,'X-Pajio-Expected-Tenant':a.session!.tenantId,'X-Wearing-Identity':'daily'});
  assert.equal(calls[0].init?.credentials,'omit');assert.equal(calls[0].init?.redirect,'error');assert.equal(calls[0].init?.cache,'no-store');
  assert.equal(calls[0].url.includes(a.session!.accessToken!),false);
});

test('explicit accept uses current bootstrap CSRF and one revision-bound POST with fractional receipt',async()=>{
  const calls:{url:string;init?:RequestInit}[]=[];
  const client=new AIConsentClient(connection(),async(url,init)=>{calls.push({url:String(url),init});return Response.json(calls.length===1?bootstrap():receipt());});
  const result=await client.change('accept',snapshot(),requestId,signal());assert.equal(result.accepted,true);
  assert.deepEqual(calls.map(c=>[new URL(c.url).pathname,c.init?.method]),[['/api/bootstrap','GET'],['/api/ai-consent','POST']]);
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)),{action:'accept',policy_version:'2026-10-10',expected_revision:0,request_id:requestId});
  assert.equal((calls[1].init?.headers as Record<string,string>)['X-Wearing-Token'],'synthetic-csrf');
  assert.equal(calls[1].init?.credentials,'omit');assert.equal(calls[1].init?.redirect,'error');
});

test('explicit withdrawal uses accept revision and respects the current revoked state',async()=>{
  let calls=0;const client=new AIConsentClient(connection(),async()=>Response.json(++calls===1?bootstrap():receipt('revoked','revoke',2)));
  const result=await client.change('revoke',snapshot('accepted'),requestId,signal());assert.equal(result.state,'revoked');assert.equal(result.accepted,false);assert.equal(calls,2);
});

test('historical accepted receipt cannot override a newer server withdrawal',async()=>{
  let calls=0;const response={...snapshot('revoked',2),receipt:receipt().receipt};
  const client=new AIConsentClient(connection(),async()=>Response.json(++calls===1?bootstrap():response));
  const result=await client.change('accept',snapshot(),requestId,signal());assert.equal(result.accepted,false);assert.equal(result.revision,2);
});

test('wrong request, action, receipt revision or timestamp never yields an accepted result',async()=>{
  const wrong=[{request_id:'2'.repeat(32)},{action:'revoke'},{revision:0},{revision:2},{revision:1.5},{recorded_at:0},{recorded_at:'today'}];
  for(const fields of wrong){let calls=0;const value=receipt();Object.assign(value.receipt,fields);const client=new AIConsentClient(connection(),async()=>Response.json(++calls===1?bootstrap():value));await assert.rejects(client.change('accept',snapshot(),requestId,signal()),AIConsentError);assert.equal(calls,2);}
});

test('bootstrap without the selected identity cannot dispatch a consent POST',async()=>{
  let calls=0;const client=new AIConsentClient(connection(),async()=>{calls++;return Response.json({...bootstrap(),identities:[{id:'other'}]});});
  await assert.rejects(client.change('accept',snapshot(),requestId,signal()),AIConsentError);assert.equal(calls,1);
  for(const invalid of ['', 'x'.repeat(32),'1'.repeat(31)])await assert.rejects(client.change('accept',snapshot(),invalid,signal()),AIConsentError);
  assert.equal(calls,1);
});

test('401/403/409/503 and network errors expose fixed copy, never response secrets',async()=>{
  for(const [status,code]of [[401,'expired'],[403,'unavailable'],[409,'changed'],[503,'unconfirmed']]as const){
    const client=new AIConsentClient(connection(),async()=>new Response('synthetic-private-detail',{status}));
    await assert.rejects(client.read(signal()),e=>e instanceof AIConsentError&&e.code===code&&!e.message.includes('private-detail'));
  }
  const broken=new AIConsentClient(connection(),async()=>{throw Error('synthetic-credential');});
  await assert.rejects(broken.read(signal()),e=>e instanceof AIConsentError&&!e.message.includes('credential'));
});

test('uncertain or rejected POST is never replayed or retried with a refreshed CSRF token',async()=>{
  for(const failure of [403,409,503,'network'] as const){
    const calls:string[]=[];const client=new AIConsentClient(connection(),async(url,init)=>{calls.push(String(init?.method));if(calls.length===1)return Response.json(bootstrap());if(failure==='network')throw Error('synthetic lost response');return new Response('private response',{status:failure});});
    await assert.rejects(client.change('accept',snapshot(),requestId,signal()),AIConsentError);assert.deepEqual(calls,['GET','POST']);
  }
});

test('abort before dispatch or during bootstrap cannot submit a decision',async()=>{
  const controller=new AbortController(),waiting=deferred<Response>();let calls=0;
  const client=new AIConsentClient(connection(),async()=>{calls++;return waiting.promise;});
  const pending=client.change('accept',snapshot(),requestId,controller.signal);controller.abort();waiting.resolve(Response.json(bootstrap()));
  await assert.rejects(pending,AIConsentError);assert.equal(calls,1);
  await assert.rejects(client.read(controller.signal),AIConsentError);assert.equal(calls,1);
});

test('late accepted POST or GET cannot reopen a background/disposed request',async()=>{
  for(const post of [false,true]){
    const controller=new AbortController(),waiting=deferred<Response>();let calls=0;
    const client=new AIConsentClient(connection(),async()=>{calls++;if(post&&calls===1)return Response.json(bootstrap());return waiting.promise;});
    const operation=post?client.change('accept',snapshot(),requestId,controller.signal):client.read(controller.signal);
    await new Promise<void>(resolve=>setImmediate(resolve));controller.abort();waiting.resolve(Response.json(post?receipt():snapshot('accepted')));
    await assert.rejects(operation,AIConsentError);assert.equal(calls,post?2:1);
  }
});

test('aborting while the response body is arriving cannot publish accepted state',async()=>{
  const controller=new AbortController(),body=deferred<string>();
  const client=new AIConsentClient(connection(),async()=>({ok:true,status:200,text:()=>body.promise}) as Response);
  const pending=client.read(controller.signal);await new Promise<void>(resolve=>setImmediate(resolve));
  controller.abort();body.resolve(JSON.stringify(snapshot('accepted')));
  await assert.rejects(pending,AIConsentError);
});

test('expired native session is rejected before any authenticated request',async()=>{
  const a=connection();a.session!.expiresAt=new Date(Date.now()-1000).toISOString();let calls=0;
  const client=new AIConsentClient(a,async()=>{calls++;return Response.json(snapshot('accepted'));});
  await assert.rejects(client.read(signal()),e=>e instanceof AIConsentError&&e.code==='expired');assert.equal(calls,0);
});

test('oversized or malformed success bodies do not become consent',async()=>{
  for(const body of ['{not-json',JSON.stringify({...snapshot('accepted'),unused:'x'.repeat(17000)})]){
    const client=new AIConsentClient(connection(),async()=>new Response(body));
    await assert.rejects(client.read(signal()),AIConsentError);
  }
});

class MemoryStore implements Store{
  values=new Map<string,unknown>();
  async get<T>(key:string){return this.values.has(key)?structuredClone(this.values.get(key)) as T:null;}
  async put(key:string,value:unknown){this.values.set(key,structuredClone(value));}
  async batch(values:[string,unknown][]){for(const [key,value]of values)await this.put(key,value);}
  async blob(){return new Blob(['fixture']);}
}
const entry=(scope:string,id:string):Pending=>({scope,id,draft:{kind:'note',title:'synthetic',content:'synthetic consent queue',timezone:'Asia/Shanghai'},media:[],uploaded:[],organize:true,state:'pending',attempts:0,nextAt:0,createdAt:new Date().toISOString()});

test('real outbox keeps pending originals without consent and stops the next dispatch on withdrawal',async()=>{
  const a=connection(),gate=new AIConsentGate(),store=new MemoryStore(),outbox=new Outbox(store),scope=scopeOf(a),first=entry(scope,'first'),second=entry(scope,'second');
  await outbox.enqueue(first);await outbox.enqueue(second);gate.activate(a);
  const calls:string[]=[];const transport:Transport={upload:async()=>{throw Error('unexpected upload');},create:async row=>{calls.push(row.id);gate.invalidate(a);return {...row.draft,id:row.id,revision:1,updated_at:new Date().toISOString()} as RecordItem;}};
  assert.equal(await outbox.flush(scope,transport,()=>gate.allows(a)),0);assert.deepEqual(calls,[]);assert.equal((await outbox.items(scope)).length,2);
  gate.observe(a,snapshot('accepted'));assert.equal(await outbox.flush(scope,transport,()=>gate.allows(a)),1);assert.deepEqual(calls,['first']);assert.deepEqual((await outbox.items(scope)).map(x=>x.id),['second']);
});

test('Mobile checks consent before sync and mounts, while data, deletion and account exits stay reachable',()=>{
  const mobile=readFileSync(new URL('./Mobile.tsx',import.meta.url),'utf8'),panel=readFileSync(new URL('./AIConsentPanel.tsx',import.meta.url),'utf8');
  const sync=mobile.slice(mobile.indexOf('async function synchronize'),mobile.indexOf('async function activateConnection'));
  assert.ok(sync.indexOf('aiConsent.allows(connection)')>=0&&sync.indexOf('aiConsent.allows(connection)')<sync.indexOf('api.bootstrap()'));
  assert.match(sync,/outbox\.flush\([^;]+aiConsent\.allows\(connection\)/);
  const render=mobile.slice(mobile.indexOf("if (deletionFrozen && screen !== 'connection')"));
  for(const name of ['NativeRemoteDevicePanel','OnboardingPanel','NativeActionSession','RetainedConversation'])assert.ok(render.indexOf('<AIConsentPanel')<render.indexOf('<'+name));
  assert.match(render,/!\['connection','account-deletion','account-data'\]\.includes\(screen\)/);
  assert.match(mobile,/screen === 'account-data'[\s\S]*?<NativeDataPanel/);
  assert.match(panel,/onPress=\{onData\}/);assert.match(panel,/onPress=\{onDelete\}/);assert.match(panel,/\{account\}/);
});
