import test from 'node:test';
import assert from 'node:assert/strict';
import {ApiError,type Connection,type Store} from './core';
import {OnboardingApi,OnboardingChanges} from './onboarding-client';
import {emptyOnboarding,type OnboardingRequest,type OnboardingSnapshot} from './onboarding-model';

const connection:Connection={endpoint:'http://127.0.0.1:8891/',identity:'daily'};
const command:OnboardingRequest={revision:0,request_key:'independent-request-001',step:1,status:'draft',values:{...emptyOnboarding(),roles:['student']}};
function snapshot(request:OnboardingRequest,revision=request.revision+1):OnboardingSnapshot&{request_key:string}{return {schema:1,identity_id:'daily',revision,status:request.status,step:request.step,values:request.values,source:'self_selected',confirmed_at:request.status==='completed'?'2026-10-09T00:00:00Z':null,updated_at:'2026-10-09T00:00:00Z',recommend_onboarding:request.status==='draft',request_key:request.request_key};}
function setup(fetcher:typeof fetch){
  const rows=new Map<string,unknown>();
  const store:Pick<Store,'get'|'put'>={get:async<T>(key:string)=>(structuredClone(rows.get(key))??null) as T|null,put:async(key,value)=>{rows.set(key,structuredClone(value));}};
  const api=new OnboardingApi(connection,fetcher);
  return {rows,store,api,changes:new OnboardingChanges(store,api)};
}
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status});

test('lost response then another device skips: exact retry conflicts and latest state clears pending',async()=>{
  let posted=0;
  const skipped=snapshot({...command,revision:1,request_key:'independent-skip-002',status:'skipped',step:0,values:emptyOnboarding()});
  const e=setup((async(url,init)=>{
    if(String(url).endsWith('/api/bootstrap'))return response({token:'synthetic',identities:[{id:'daily'}]});
    if(init?.method==='POST'){
      assert.deepEqual(JSON.parse(String(init.body)),command);posted++;
      if(posted===1)throw new TypeError('synthetic lost response');
      return response({detail:'superseded'},409);
    }
    return response(skipped);
  }) as typeof fetch);
  await assert.rejects(()=>e.changes.save(command),(cause:unknown)=>cause instanceof ApiError&&cause.status===0);
  assert.deepEqual(await e.changes.pending(),command);
  await assert.rejects(()=>e.changes.save(),(cause:unknown)=>cause instanceof ApiError&&cause.status===409);
  const latest=await e.api.load();
  await e.changes.resolveConflict(latest);
  assert.equal(await e.changes.pending(),null);
  assert.equal(latest.status,'skipped');
  assert.deepEqual(latest.values,emptyOnboarding());
});

test('mismatched receipt keeps exact request for retry and never checkpoints unverified values',async()=>{
  const receipt=snapshot(command);
  const e=setup((async(url)=>String(url).endsWith('/api/bootstrap')?response({token:'synthetic',identities:[{id:'daily'}]}):response({...receipt,identity_id:'foreign'})) as typeof fetch);
  await assert.rejects(()=>e.changes.save(command),(cause:unknown)=>cause instanceof ApiError&&cause.status===0);
  assert.deepEqual(await e.changes.pending(),command);
  assert.equal(await e.changes.draft(),null);
});

test('known old receipt never rolls a newer completed profile back to an unconfirmed draft',async()=>{
  const old=snapshot(command);
  const latest=snapshot({...command,revision:1,request_key:'independent-newer-002',status:'completed',step:5,values:{...emptyOnboarding(),roles:['caregiver']}});
  const e=setup((async(url,init)=>String(url).endsWith('/api/bootstrap')?response({token:'synthetic',identities:[{id:'daily'}]}):response(init?.method==='POST'?old:latest)) as typeof fetch);
  const saved=await e.changes.save(command);
  assert.equal(saved.revision,latest.revision);
  assert.equal(saved.status,'completed');
  assert.deepEqual(saved.values.roles,['caregiver']);
  assert.equal(await e.changes.draft(),null);
});
