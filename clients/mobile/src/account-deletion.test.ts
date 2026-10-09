import {test} from 'node:test';
import assert from 'node:assert/strict';
import {AccountDeletionClient, deletionPlan, deletionStatus, readRecovery, recoveryFor, reauthURL, type DeletionRecovery} from './account-deletion-client';
import type {Connection} from './core';
const connection = (): Connection => ({endpoint: 'https://pajio.example/', identity: 'daily', session: {userId: 'user_' + 'a'.repeat(32), tenantId: 'home', credentialId: 'd'.repeat(32), accessToken: 's'.repeat(64), expiresAt: new Date(Date.now() + 3600000).toISOString()}});
const plan = () => ({schema: 1, user_id: connection().session!.userId, tenants: [{tenant_id: 'home', classification: 'private', action: 'erase_private'}, {tenant_id: 'team', classification: 'shared', action: 'leave_shared'}], blockers: [], ready: true, revision: 'a'.repeat(64), request_key: 'k'.repeat(43), receipt_token: 'pdr1.' + 'r'.repeat(180), receipt_expires_in: 7776000, reauth_required: false});
const status = () => ({id: 'c'.repeat(32), user_id: plan().user_id, request_key: plan().request_key, plan_revision: plan().revision, state: 'awaiting_operator', code: 'adapter_unconfigured', data_erased: false, tenants: plan().tenants, created_at: 100, updated_at: 100});
const api = (handler: (url: string, init: RequestInit) => Promise<unknown>, target = connection()) => new AccountDeletionClient(target, (async (input, init) => new Response(JSON.stringify(await handler(String(input), init!)), {status: 200})) as typeof fetch);
test('plan and status bind exact user, revision and real scope; false completion fails', () => {
 const c=connection(),p=deletionPlan(plan(),c),r=recoveryFor(c,p); assert.equal(p.tenants[1].action,'leave_shared');
 for(const patch of [{user_id:'other'},{tenants:[]},{revision:'bad'},{blockers:[{tenant_id:'home',code:'unknown'}]},{tenants:[{...plan().tenants[0],classification:'shared'}]}]) assert.throws(()=>deletionPlan({...plan(),...patch},c));
 for(const patch of [{state:'completed'},{data_erased:true},{user_id:'other'},{request_key:'x'.repeat(43)},{created_at:'100'}]) assert.throws(()=>deletionStatus({...status(),...patch},r));
 assert.equal(deletionStatus(status(),r).state,'awaiting_operator');
});
test('recovery contains no business token; dedicated reauth refuses foreign/ordinary routes',()=>{
 const c=connection(),r=recoveryFor(c,deletionPlan(plan(),c));assert.equal(JSON.stringify(r).includes(c.session!.accessToken!),false);assert.deepEqual(readRecovery(r),r);assert.throws(()=>readRecovery({...r,target:c}));
 const url='https://pajio.example/auth/account-deletion/reauth/start?ticket='+'t'.repeat(43);assert.equal(reauthURL({authorize_url:url},c),url);
 for(const value of [url.replace('pajio.example','evil.example'),url.replace('account-deletion/reauth','mobile'),url+'&token=secret',url+'#fragment'])assert.throws(()=>reauthURL({authorize_url:value},c));
});
test('durable limited receipt precedes mutation; persistence failure means zero HTTP',async()=>{
 const events:string[]=[],client=api(async(url,init)=>{events.push('http');assert.ok(url.endsWith('/request'));assert.equal(init.credentials,'omit');assert.equal(init.redirect,'error');assert.equal(JSON.parse(String(init.body)).confirm,'DELETE');return status();});
 await assert.rejects(client.submit(deletionPlan(plan(),connection()),async()=>{throw new Error('keychain locked');}),/keychain locked/);assert.equal(events.length,0);
 const result=await client.submit(deletionPlan(plan(),connection()),async row=>{events.push(row.phase);});assert.deepEqual(events,['prepared','http','submitted']);assert.equal(result.status.state,'awaiting_operator');
});
test('lost response retains original token and key, status uses no business bearer or tenant header',async()=>{
 let saved:DeletionRecovery|null=null,calls=0;const client=api(async()=>{calls++;throw new Error('response lost');});
 await assert.rejects(client.submit(deletionPlan(plan(),connection()),async row=>{saved=row;}));assert.equal(calls,1);assert.equal(saved!.phase,'uncertain');
 const frozen=api(async(url,init)=>{assert.ok(url.endsWith('/status'));assert.equal(init.method,'GET');assert.deepEqual(init.headers,{Authorization:'Bearer '+saved!.token});return status();},saved!.target);
 assert.equal((await frozen.status(saved!)).state,'awaiting_operator');assert.equal(saved!.requestKey,plan().request_key);
});
test('phase persistence failure after admission does not hide freeze or resubmit',async()=>{
 let calls=0;const result=await api(async()=>{calls++;return status();}).submit(deletionPlan(plan(),connection()),async row=>{if(row.phase==='submitted')throw new Error('locked');});assert.equal(calls,1);assert.equal(result.recovery.phase,'submitted');
});
test('foreign recovery is rejected before network',async()=>{
 const other={...connection(),session:{...connection().session!,userId:'user_'+'b'.repeat(32)}};let calls=0;
 await assert.rejects(api(async()=>{calls++;return status();}).status(recoveryFor(other,deletionPlan({...plan(),user_id:other.session.userId},other))));assert.equal(calls,0);
});

test('verified completion requires matching completed, verified and true evidence together',()=>{
 const recovery=recoveryFor(connection(),deletionPlan(plan(),connection()));
 assert.equal(deletionStatus({...status(),state:'completed',code:'verified',data_erased:true},recovery).state,'completed');
 assert.equal(deletionStatus({...status(),state:'waiting',code:'backup_retained'},recovery).state,'waiting');
 for(const patch of [{state:'frozen',code:'verified',data_erased:true},{state:'completed',code:'verified',data_erased:false},{state:'waiting',code:'arbitrary-provider-success'}])assert.throws(()=>deletionStatus({...status(),...patch},recovery));
});

test('startup checks uncertain delivery with receipt only, and never restores business on unknown state',async()=>{
 const {deletionDisposition}=await import('./account-deletion-recovery');
 const r=recoveryFor(connection(),deletionPlan(plan(),connection()));let checks=0;
 const reader={fenced:async()=>false,load:async()=>r,status:async()=>{checks++;return{state:'not_submitted' as const,code:'not_submitted' as const};}};
 assert.equal(await deletionDisposition(connection(),reader),'clear');assert.equal(checks,1);
 assert.equal(await deletionDisposition(connection(),{...reader,status:async()=>{throw new Error('offline');}}),'review');
 assert.equal(await deletionDisposition(connection(),{...reader,status:async()=>deletionStatus(status(),r)}),'review');
 assert.equal(await deletionDisposition(connection(),{...reader,load:async()=>({...r,phase:'submitted'})}),'review');
 assert.equal(await deletionDisposition(connection(),{...reader,fenced:async()=>true}),'review');assert.equal(checks,1);
 assert.equal(await deletionDisposition(connection(),{...reader,load:async()=>null}),'clear');
});
