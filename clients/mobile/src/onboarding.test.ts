import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ApiError,scopeOf,type Connection,type Store} from './core';
import {accountCleanupPlan,fencedWrite,fenceFor} from './account-cleanup-model';
import {OnboardingActivity,OnboardingApi,OnboardingChanges,onboardingDraft} from './onboarding-client';
import {emptyOnboarding,onboardingDraftKey,onboardingPendingKey,onboardingSnapshot,onboardingValues,shouldEnterOnboarding,toggleOnboardingSelection,type OnboardingRequest,type OnboardingSnapshot} from './onboarding-model';

const connection:Connection={endpoint:'https://pajio.example/',identity:'daily'};
const snapshot=(patch:Partial<OnboardingSnapshot>={}):OnboardingSnapshot=>({schema:1,identity_id:'daily',revision:0,status:'draft',step:0,values:emptyOnboarding(),confirmed_at:null,updated_at:null,source:'self_selected',recommend_onboarding:true,...patch});
const command:OnboardingRequest={revision:0,status:'draft',step:2,values:{...emptyOnboarding(),roles:['student']},request_key:'onboarding-command-001'};
const receipt=(body:OnboardingRequest)=>snapshot({...body,revision:body.revision+1,updated_at:'2026-10-09T00:00:00Z',confirmed_at:body.status==='completed'?'2026-10-09T00:00:00Z':null,recommend_onboarding:body.status==='draft'});
function memory(){const rows=new Map<string,unknown>();const store:Pick<Store,'get'|'put'>={get:async<T>(key:string)=>(structuredClone(rows.get(key))??null) as T|null,put:async(key,value)=>{rows.set(key,structuredClone(value));}};return{rows,store};}
test('onboarding gate requires server recommendation and authenticated landing; never hijacks an active route',()=>{
  assert.equal(shouldEnterOnboarding(snapshot(),'conversation',true),true);
  assert.equal(shouldEnterOnboarding(snapshot({recommend_onboarding:false}),'conversation',true),false);
  for(const screen of ['connection','task-detail','account-deletion','capture'])assert.equal(shouldEnterOnboarding(snapshot(),screen,true),false);
  assert.equal(shouldEnterOnboarding(snapshot(),'conversation',false),false);
  assert.equal(shouldEnterOnboarding(snapshot({status:'completed'}),'conversation',true),false);
});
test('unknown, duplicate and over-limit choices cannot become initial context; nullable preferences remain unknown',()=>{
  assert.deepEqual(onboardingValues(emptyOnboarding()),emptyOnboarding());
  for(const values of [{roles:['employed','student','business','caregiver']},{roles:['student','student']},{apps:['gmail']},{interests:['mbti']},{reply_detail:'warm'},{reply_tone:'brief'}])assert.throws(()=>onboardingValues({...emptyOnboarding(),...values}));
  assert.throws(()=>onboardingSnapshot(snapshot(),'foreign'));
  assert.throws(()=>onboardingSnapshot(snapshot({status:'completed',confirmed_at:null}),'daily'));
  assert.throws(()=>onboardingDraft({version:1,revision:-1,step:0,values:emptyOnboarding()}));
  assert.deepEqual(toggleOnboardingSelection(['a','b'],'c',2),['a','b']);
  assert.deepEqual(toggleOnboardingSelection(['a','b'],'a',2),['b']);
});
test('opening onboarding reads only its snapshot, without bootstrap, permissions or mutations',async()=>{
  const calls:string[]=[];
  const api=new OnboardingApi(connection,(async(url,init)=>{calls.push(String(url));assert.equal(init?.method,'GET');assert.equal(init?.redirect,'error');assert.equal(new Headers(init?.headers).get('X-Wearing-Identity'),'daily');return Response.json(snapshot());}) as typeof fetch);
  assert.equal((await api.load()).revision,0);assert.deepEqual(calls,['https://pajio.example/api/onboarding']);
});
test('lost response retains the exact request and a restarted client retries before accepting latest state',async()=>{
  const {store}=memory();let first=true,server=snapshot(),posts=0;
  const fetcher=(async(url,init)=>{
    if(String(url).endsWith('/api/bootstrap'))return Response.json({token:'synthetic',identities:[{id:'daily'}]});
    if(init?.method==='POST'){posts++;const body=JSON.parse(String(init.body));assert.deepEqual(body,command);assert.deepEqual(await store.get(onboardingPendingKey(scopeOf(connection))),command);server=receipt(body);if(first){first=false;throw new Error('lost response');}return Response.json({...server,request_key:body.request_key});}
    return Response.json(server);
  }) as typeof fetch;
  const firstChanges=new OnboardingChanges(store,new OnboardingApi(connection,fetcher));
  await firstChanges.retain({version:1,revision:0,step:1,values:command.values});
  await assert.rejects(()=>firstChanges.save(command),cause=>cause instanceof ApiError&&cause.status===0);
  const restarted=new OnboardingChanges(store,new OnboardingApi(connection,fetcher));
  assert.deepEqual(await restarted.pending(),command);assert.equal((await restarted.save()).revision,1);assert.equal(posts,2);assert.equal(await restarted.pending(),null);assert.equal((await restarted.draft())?.step,2);
});
test('if latest-state verification fails the mutation journal survives an otherwise successful receipt',async()=>{
  const {store}=memory();const api=new OnboardingApi(connection,(async(url,init)=>String(url).endsWith('/api/bootstrap')?Response.json({token:'synthetic',identities:[{id:'daily'}]}):init?.method==='POST'?Response.json({...receipt(command),request_key:command.request_key}):Promise.reject(new Error('read unavailable'))) as typeof fetch);
  const changes=new OnboardingChanges(store,api);await assert.rejects(()=>changes.save(command));assert.deepEqual(await changes.pending(),command);assert.equal(await changes.draft(),null);
});
test('switching identity while bootstrap is in flight prevents the old POST',async()=>{
  let live=true,posts=0;const api=new OnboardingApi(connection,(async(_url,init)=>{if(init?.method==='POST')posts++;live=false;return Response.json({token:'synthetic',identities:[{id:'daily'}]});}) as typeof fetch,()=>live);
  await assert.rejects(()=>api.save(command));assert.equal(posts,0);
});
test('unmounted sessions and frozen accounts cannot write queued choices',async()=>{
  const {store,rows}=memory();const activity=new OnboardingActivity(()=>true),api=new OnboardingApi(connection,fetch,activity.active),changes=new OnboardingChanges(store,api,activity.active);
  activity.stop();await assert.rejects(()=>changes.retain({version:1,revision:0,step:1,values:emptyOnboarding()}));assert.equal(rows.size,0);
  activity.mount();activity.update(()=>false);assert.equal(activity.active(),false);
});
test('initial-choice drafts and requests participate in existing account deletion fences and scoped cleanup',()=>{
  const owned:Connection={...connection,session:{userId:'user_'+'a'.repeat(32),tenantId:'tenant1',credentialId:'c'.repeat(32),expiresAt:'2030-01-01T00:00:00Z'}};
  const other:Connection={...owned,session:{...owned.session!,userId:'user_'+'b'.repeat(32)}};
  const keys=[onboardingDraftKey(scopeOf(owned)),onboardingPendingKey(scopeOf(owned))],retained=onboardingDraftKey(scopeOf(other));
  const plan=accountCleanupPlan(owned,[...keys.map(key=>({key,value:command})),{key:retained,value:command}]);
  assert.deepEqual(plan.remove,keys);assert.equal(plan.remove.includes(retained),false);
  for(const key of keys)assert.equal(fencedWrite(key,command,[fenceFor(owned)]),true);
  assert.equal(fencedWrite(retained,command,[fenceFor(owned)]),false);
});
