import assert from 'node:assert/strict';
import test from 'node:test';
import {DecisionClient, decisionSnapshot, PendingDecision} from './pending-decisions';

const connection={endpoint:'https://pajio.example',identity:'daily'};
const row:PendingDecision={id:'decision_'+'a'.repeat(32),identity_id:'daily',task_id:'b'.repeat(32),revision:2,state:'needs_recheck',can_resume:true,recovery_task_id:null,card:{title:'确认测试记录',action:'修改记录标题',impact:'只更新测试记录'}};
test('decisions are identity-bound and malformed or duplicated proposals never become buttons',()=>{
  assert.deepEqual(decisionSnapshot({items:[row]},'daily'),[row]);
  for(const bad of [{...row,identity_id:'other'},{...row,revision:0},{...row,state:'approved'},{...row,recovery_task_id:'../unsafe'}, {...row,card:{title:'incomplete'}}]) assert.throws(()=>decisionSnapshot({items:[bad]},'daily'));
  assert.throws(()=>decisionSnapshot({items:[row,row]},'daily'));
});
test('a lost response and a remounted screen reuse the saved recovery request key',async()=>{
  const saved=new Map<string,unknown>(), keys:string[]=[];let networkLost=true, ids=0;
  const store={get:async<T>(key:string)=>saved.get(key) as T||null,put:async(key:string,value:unknown)=>{saved.set(key,value);}};
  const fetcher=(async(url:unknown,init:RequestInit)=>{
    assert.equal((init.headers as Record<string,string>)['X-Wearing-Identity'],'daily');
    if(String(url).endsWith('/api/bootstrap'))return Response.json({version:'0.2.0',deployment:'local',token:'private-csrf',identities:[{id:'daily',name:'日常'}]});
    assert.equal((init.headers as Record<string,string>)['X-Wearing-Token'],'private-csrf');
    assert.equal(init.redirect,'error');keys.push(JSON.parse(init.body as string).request_key);
    if(networkLost){networkLost=false;throw new Error('response lost');}
    return Response.json({task:{id:'c'.repeat(32)},authorized:false,delivery:'submitted',created:false});
  }) as typeof fetch;
  const create=()=>new DecisionClient(connection,store,()=>{ids++;return 'resume-request-0001';},fetcher);
  await assert.rejects(create().resume(row),/同一次请求/);
  assert.equal((await create().resume(row)).taskId,'c'.repeat(32));
  assert.deepEqual(keys,['resume-request-0001','resume-request-0001']);assert.equal(ids,1);
});
test('local persistence failure prevents starting a recovery',async()=>{
  let calls=0;
  const api=new DecisionClient(connection,{get:async()=>null,put:async()=>{throw new Error('disk full');}},()=> 'resume-request-0002',(async()=>{calls++;return Response.json({});}) as typeof fetch);
  await assert.rejects(api.resume(row),/disk full/);assert.equal(calls,0);
  await assert.rejects(api.resume({...row,identity_id:'other'}));assert.equal(calls,0);
});
test('the resume receipt must explicitly be unauthorized and name a real task',async()=>{
  for(const receipt of [{task:{id:'c'.repeat(32)},authorized:true,delivery:'submitted'},{task:{id:'c'.repeat(32)},delivery:'submitted'},{task:{id:'x'},authorized:false,delivery:'submitted'}]){
    const fetcher=(async(url:unknown)=>Response.json(String(url).endsWith('/api/bootstrap')?{version:'0.2.0',deployment:'local',token:'t',identities:[{id:'daily'}]}:receipt)) as typeof fetch;
    await assert.rejects(new DecisionClient(connection,{get:async()=>null,put:async()=>{}},()=> 'resume-request-0003',fetcher).resume(row));
  }
});
