import {test} from 'node:test';
import assert from 'node:assert/strict';
import {type Connection,type Store,scopeOf,ApiError} from './core';
import {autoRequest,autoSettings,autoPendingKey,BriefAutomationClient,saveAutomation,type AutoSettings,type AutoRequest,type AutoReceipt} from './briefing-automation';
import {accountCleanupPlan,fenceFor,fencedWrite} from './account-cleanup-model';
const connection:Connection={endpoint:'https://pajio.example/',identity:'daily',session:{userId:'user_'+'a'.repeat(32),tenantId:'test-team',credentialId:'b'.repeat(32),accessToken:'s'.repeat(64),expiresAt:'2030-01-01T00:00:00Z'}};
const command:AutoRequest={revision:0,request_key:'auto-settings-request-01',enabled:true,local_time:'08:00',timezone:'Asia/Shanghai',grace_minutes:120,preferences_revision:0};
const receipt:AutoReceipt={...command,schema:1,identity_id:'daily',revision:1,updated_at:'2026-10-08T00:00:00Z',next_run:'2026-10-09T00:00:00Z'};
const state:AutoSettings={...receipt,preferences_revision:0,schedule_status:'active',reason:'',needs_resave:false,receipts:[],execution:'service_required',quiet_hours:'notification_delivery_only'};
function storage(){const map=new Map<string,unknown>();const store:Pick<Store,'get'|'put'>={get:async<T>(key:string)=>(structuredClone(map.get(key))??null)as T|null,put:async(key,value)=>{map.set(key,structuredClone(value));}};return{map,store};}
function fetcher(post:(init:RequestInit)=>unknown):typeof fetch{return(async(url:unknown,init:RequestInit)=>String(url).endsWith('/api/bootstrap')?Response.json({token:'csrf',identities:[{id:'daily'}]}):init.method==='POST'?Response.json(await post(init)):Response.json(state))as typeof fetch;}

test('automation rejects forged fields bad times zones grace and revisions',()=>{
 assert.equal(autoRequest(command).timezone,'Asia/Shanghai');
 for(const patch of [{owner_scope:'forged'},{enabled:1},{local_time:'25:00'},{timezone:'no/zone'},{grace_minutes:0},{grace_minutes:361},{revision:true},{preferences_revision:-1}])assert.throws(()=>autoRequest({...command,...patch}));
});
test('settings pins identity receipt limit valid local date and actual briefing state',()=>{
 assert.equal(autoSettings(state,'daily'),state);
 const day={local_date:'2026-10-08',timezone:'Asia/Shanghai',revision:1,due_at:receipt.updated_at,state:'requested',briefing_id:'brief_test',task_id:'task',created_at:receipt.updated_at,briefing:{id:'brief_test',date:'2026-10-08',timezone:'Asia/Shanghai',version:1,state:'not_started',task_id:'task'}};
 assert.equal(autoSettings({...state,receipts:[day]},'daily').receipts[0].briefing?.state,'not_started');
 for(const value of [{...state,identity_id:'other'},{...state,receipts:Array(8).fill(day)},{...state,receipts:[{...day,local_date:'2026-02-30'}]},{...state,receipts:[{...day,briefing:{...day.briefing,state:'imagined_success'}}]}])assert.throws(()=>autoSettings(value,'daily'));
});
test('durable save precedes POST and lost response reuses identical request after restart',async()=>{
 const s=storage();let posts=0;const client=new BriefAutomationClient(connection,fetcher(init=>{posts++;assert.deepEqual(s.map.get(autoPendingKey(connection)),JSON.parse(String(init.body)));if(posts===1)throw new Error('lost');return receipt;}),()=>true);
 await assert.rejects(saveAutomation(s.store,client,()=>true,command),/lost/);const saved=await saveAutomation(s.store,client,()=>true);assert.equal(saved.revision,1);assert.equal(posts,2);assert.equal(s.map.get(autoPendingKey(connection)),null);
});
test('disk failure prevents POST and different pending intent cannot replace original',async()=>{
 const s=storage();let posts=0;const client=new BriefAutomationClient(connection,fetcher(()=>{posts++;return receipt;}),()=>true);
 await assert.rejects(saveAutomation({...s.store,put:async()=>{throw new Error('disk');}},client,()=>true,command));assert.equal(posts,0);
 s.map.set(autoPendingKey(connection),command);await assert.rejects(saveAutomation(s.store,client,()=>true,{...command,request_key:'another-request-value'}));assert.equal(posts,0);
});
test('cloud request pins tenant identity auth CSRF and rejects redirects',async()=>{
 const seen:RequestInit[]=[];const client=new BriefAutomationClient(connection,(async(url:unknown,init:RequestInit)=>{seen.push(init);return String(url).endsWith('/api/bootstrap')?Response.json({token:'csrf',identities:[{id:'daily'}]}):Response.json(receipt);})as typeof fetch,()=>true);await client.save(command);
 for(const init of seen){const h=init.headers as Record<string,string>;assert.equal(h.Authorization,'Bearer '+connection.session!.accessToken);assert.equal(h['X-Pajio-Expected-Tenant'],'test-team');assert.equal(h['X-Wearing-Identity'],'daily');assert.equal(init.redirect,'error');}assert.equal((seen[1].headers as Record<string,string>)['X-Wearing-Token'],'csrf');
});
test('foreign or mismatched acknowledgement never clears pending request',async()=>{
 for(const patch of [{identity_id:'foreign'},{revision:5},{request_key:'other'},{local_time:'09:00'}]){const s=storage(),client=new BriefAutomationClient(connection,fetcher(()=>({...receipt,...patch})),()=>true);await assert.rejects(saveAutomation(s.store,client,()=>true,command));assert.deepEqual(s.map.get(autoPendingKey(connection)),command);}
});
test('account switch and ignored transport abort cannot accept late state',async()=>{
 let active=true;const s=storage(),client=new BriefAutomationClient(connection,fetcher(()=>{active=false;return receipt;}),()=>active);await assert.rejects(saveAutomation(s.store,client,()=>active,command));assert.deepEqual(s.map.get(autoPendingKey(connection)),command);
 const abort=new AbortController(),late=new BriefAutomationClient(connection,(async()=>({ok:true,json:async()=>{abort.abort();return state;}}))as typeof fetch,()=>true,abort.signal);await assert.rejects(late.load(),/停止/);
});
test('server conflict remains a definite retry decision and preserves request',async()=>{
 const s=storage(),client=new BriefAutomationClient(connection,(async(url:unknown)=>String(url).endsWith('/api/bootstrap')?Response.json({token:'csrf',identities:[{id:'daily'}]}):Response.json({detail:'new revision'},{status:409}))as typeof fetch,()=>true);
 await assert.rejects(saveAutomation(s.store,client,()=>true,command),(e:unknown)=>e instanceof ApiError&&e.status===409);assert.deepEqual(s.map.get(autoPendingKey(connection)),command);
});
test('automatic briefing intent follows exact account deletion fence and cannot clear another account',()=>{
 const other={...connection,session:{...connection.session!,userId:'user_'+'c'.repeat(32)}},ownKey=autoPendingKey(connection),otherKey=autoPendingKey(other);assert.notEqual(scopeOf(connection),scopeOf(other));assert.equal(fencedWrite(ownKey,command,[fenceFor(connection)]),true);assert.deepEqual(accountCleanupPlan(connection,[{key:ownKey,value:command},{key:otherKey,value:command}]).remove,[ownKey]);
});
