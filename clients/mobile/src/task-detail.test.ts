import test from 'node:test';
import assert from 'node:assert/strict';
import {taskDetail, TaskDetailApi} from './task-detail';
import {stopDeletedAccountWork} from './account-work';
import type {Connection} from './core';

const taskId = 'a'.repeat(32), otherId = 'b'.repeat(32), stamp = '2026-10-08T10:00:00Z';
const task = (changes = {}) => ({id:taskId,identity_id:'daily',title:'整理一份资料',prompt:'仅整理测试资料',output:'',status:'running',run_id:'run_test',created_at:stamp,updated_at:stamp,events:[],artifacts:[],...changes});
const connection: Connection = {endpoint:'http://127.0.0.1:8891/',identity:'daily'};
const response = (v:unknown, status = 200) => new Response(JSON.stringify(v), {status,headers:{'Content-Type':'application/json'}});
const snapshot = () => taskDetail(task(),taskId,'daily');
test('task detail validates identity and strips technical events and unknown fields', () => {
  const result = taskDetail(task({error:'private traceback',events:[{kind:'failed',created_at:stamp,message:'secret traceback'}, {kind:'provider_debug',created_at:stamp,message:'API key'}],artifacts:[{id:'art_abc',task_id:taskId,title:'资料简报',html:'private'}]}),taskId,'daily');
  assert.deepEqual(result.events,[{label:'执行未完成',at:stamp}]);
  assert.deepEqual(result.artifacts,[{id:'art_abc',title:'资料简报'}]);
  assert.equal('error' in result,false);
  assert.throws(()=>taskDetail(task(),otherId,'daily'));
  assert.throws(()=>taskDetail(task(),taskId,'work'));
  assert.throws(()=>taskDetail(task({artifacts:[{id:'art_abc',task_id:otherId,title:'串任务'}]}),taskId,'daily'));
});
test('known execution limit is explained without exposing raw errors or unknown failure text',()=>{
  const result=taskDetail(task({status:'failed',failure_code:'execution_limit',error:'private debug trace'}),taskId,'daily');
  assert.match(result.failureReason!,/执行上限/);assert.equal('error' in result,false);
  assert.equal(taskDetail(task({status:'failed',failure_code:'private debug trace',error:'request_confirmation payload'}),taskId,'daily').failureReason,null);
  assert.equal(taskDetail(task({status:'running',failure_code:'execution_limit'}),taskId,'daily').failureReason,null);
});
test('queue cancellation needs authoritative receipt and stopping never offers another stop', () => {
  assert.equal(taskDetail(task({status:'draft'}),taskId,'daily').queued,false);
  assert.equal(taskDetail(task({status:'draft',queued:true}),taskId,'daily').queued,true);
  assert.equal(taskDetail(task({status:'running',queued:true}),taskId,'daily').queued,false);
  for (const status of ['stopping','verified','failed','future_status']) assert.equal(taskDetail(task({status}),taskId,'daily').canStop,false);
  assert.equal(taskDetail(task({status:'completed_unverified'}),taskId,'daily').label,'结果已返回');
});
test('saved drafts expose retry and withdrawal only with fresh authoritative capabilities', () => {
  const draft={status:'draft',run_id:null,can_cancel:true,can_retry:true,blocked_reason:'执行端暂时离线。',message_kind:'confirmation_recovery'};
  const result=taskDetail(task(draft),taskId,'daily');
  assert.equal(result.canCancel,true);assert.equal(result.canRetry,true);assert.equal(result.recovery,true);assert.equal(result.blockedReason,'执行端暂时离线。');
  assert.equal(taskDetail(task({status:'draft',run_id:null}),taskId,'daily').canCancel,false);
  assert.equal(taskDetail(task({...draft,status:'running'}),taskId,'daily').canCancel,false);
  assert.equal(taskDetail(task({...draft,run_id:'unexpected-run'}),taskId,'daily').canRetry,false);
  assert.equal(taskDetail(task({...draft,queued:true}),taskId,'daily').canRetry,false);
  assert.throws(()=>taskDetail(task({...draft,can_cancel:'true'}),taskId,'daily'));
});
test('saved recovery retry retains task id and reads real status without changing user text',async()=>{
  const calls:string[]=[];let began=false;
  const draft=task({status:'draft',run_id:null,can_retry:true,can_cancel:true,title:'重新核对：合成提案',prompt:'重新核对：合成提案',message_kind:'confirmation_recovery'});
  const api=new TaskDetailApi(connection,async(input,init)=>{const path=new URL(String(input)).pathname;calls.push(path);if(path.endsWith('/bootstrap'))return response({token:'csrf',identities:[{id:'daily'}]});if(path.endsWith('/start')){assert.equal(init?.method,'POST');assert.deepEqual(JSON.parse(String(init?.body)),{});began=true;}return response(began?{...draft,status:'running',run_id:'new-run',can_retry:false,can_cancel:false}:draft);});
  const result=await api.control(taskDetail(draft,taskId,'daily'),'start');
  assert.equal(result.status,'running');assert.equal(result.id,taskId);assert.equal(result.prompt,draft.prompt);
  assert.equal(calls.filter(path=>path.endsWith('/start')).length,1);assert.equal(calls.at(-1),'/api/tasks/'+taskId);
});
test('saved withdrawal and start are refused when fresh read shows prior admission',async()=>{
  const draft=taskDetail(task({status:'draft',run_id:null,can_retry:true,can_cancel:true}),taskId,'daily');
  for(const action of ['start','cancel-message'] as const){let posts=0;const api=new TaskDetailApi(connection,async(_input,init)=>{if(init?.method==='POST')posts++;return response(task({status:'starting',run_id:null,can_retry:false,can_cancel:false}));});await assert.rejects(api.control(draft,action),/已有变化/);assert.equal(posts,0);}
});
test('lost saved withdrawal acknowledgement does not start or retry a request',async()=>{
  let posts=0;
  const draft=task({status:'draft',run_id:null,can_retry:true,can_cancel:true});
  const api=new TaskDetailApi(connection,async(input,init)=>{if(String(input).endsWith('/bootstrap'))return response({token:'csrf',identities:[{id:'daily'}]});if(init?.method==='POST'){posts++;throw new Error('unknown receipt');}return response(posts?{...draft,status:'stopped',queue_state:'cancelled',can_retry:false,can_cancel:false}:draft);});
  await assert.rejects(api.control(taskDetail(draft,taskId,'daily'),'cancel-message'),/尚未确认/);
  assert.equal((await api.read(taskId)).label,'已撤回');assert.equal(posts,1);
});
test('stop checks latest run before any control request', async () => {
  const paths:string[]=[]; const api = new TaskDetailApi(connection, async input => {paths.push(new URL(String(input)).pathname);return response(task({run_id:'new_run'}));});
  await assert.rejects(api.control(snapshot(),'stop'),/已有变化/);
  assert.deepEqual(paths,['/api/tasks/'+taskId]);
});
test('lost stop response is never automatically repeated or reported stopped', async () => {
  const calls:{path:string;method:string}[]=[];
  const api = new TaskDetailApi(connection, async (input,init) => {const path=new URL(String(input)).pathname;calls.push({path,method:init?.method||'GET'});if(path.endsWith('/stop'))throw new Error('response lost');return response(path.endsWith('/bootstrap')?{token:'csrf',identities:[{id:'daily'}]}:task());});
  await assert.rejects(api.control(snapshot(),'stop'),/尚未确认/);
  assert.equal(calls.filter(call=>call.method==='POST').length,1);
  assert.equal((await api.read(taskId)).status,'running');
  assert.equal(calls.filter(call=>call.method==='POST').length,1);
});
test('confirmed control reads original task and preserves stopping as distinct from stopped', async () => {
  const calls:string[]=[];let stopped=false;
  const api = new TaskDetailApi(connection, async (input,init) => {const path=new URL(String(input)).pathname;calls.push(path);if(path.endsWith('/bootstrap'))return response({token:'csrf',identities:[{id:'daily'}]});if(init?.method==='POST'){assert.equal(new Headers(init.headers).get('X-Wearing-Token'),'csrf');stopped=true;}return response(task({status:stopped?'stopping':'running'}));});
  const result=await api.control(snapshot(),'stop');assert.equal(result.status,'stopping');assert.equal(result.canStop,false);assert.equal(calls.at(-1),'/api/tasks/'+taskId);
});
test('switching account during bootstrap prevents a late control', async () => {
  let current=true,posts=0;
  const api = new TaskDetailApi(connection,async (input,init)=>{if(init?.method==='POST')posts++;if(String(input).endsWith('/api/bootstrap')){current=false;return response({token:'csrf',identities:[{id:'daily'}]});}return response(task());},()=>current);
  await assert.rejects(api.control(snapshot(),'stop'),/已切换/);assert.equal(posts,0);
});
test('close aborts in-flight reads and prevents future network calls', async () => {
  let signal:AbortSignal|null|undefined,calls=0,release!:(value:Response)=>void;
  const api=new TaskDetailApi(connection, async (_input,init)=>{calls++;signal=init?.signal;return new Promise<Response>(resolve=>{release=resolve;});});
  const reading=api.read(taskId);api.close();assert.equal(signal?.aborted,true);release(response(task()));await assert.rejects(reading,/已切换/);await assert.rejects(api.read(taskId));assert.equal(calls,1);
});
test('cloud headers use captured account and a deletion freeze prevents later reads',async()=>{
  const c:Connection={endpoint:'https://test.pajio.example/',identity:'daily',session:{userId:'user_'+'c'.repeat(32),tenantId:'tenant_task_detail',credentialId:'d'.repeat(32),accessToken:'p'.repeat(64),expiresAt:'2099-01-01T00:00:00Z'}};
  let calls=0;const api=new TaskDetailApi(c,async(_input,init)=>{calls++;assert.equal(new Headers(init?.headers).get('Authorization'),'Bearer '+'p'.repeat(64));assert.equal(new Headers(init?.headers).get('X-Pajio-Expected-Tenant'),'tenant_task_detail');return response(task());});
  c.session!.accessToken='q'.repeat(64);await api.read(taskId);await stopDeletedAccountWork(api.connection);await assert.rejects(api.read(taskId));assert.equal(calls,1);
});
test('reopening the same panel cannot accept a late read from its previous activation', async () => {
  let release!:(value:Response)=>void, calls=0;
  const api = new TaskDetailApi(connection, async () => ++calls === 1 ? new Promise<Response>(resolve => {release=resolve;}) : response(task({output:'new activation'})));
  const oldRead=api.read(taskId); api.close(); api.activate();
  const current=await api.read(taskId); assert.equal(current.output,'new activation');
  release(response(task({output:'old activation'}))); await assert.rejects(oldRead,/已重新打开/);
});
test('seen uses only the rendered receipt and never fetches a replacement version', async () => {
  const version='f'.repeat(64), paths:string[]=[];
  const api=new TaskDetailApi(connection, async(input,init)=>{
    const path=new URL(String(input)).pathname;paths.push(path);
    if(path.endsWith('/bootstrap'))return response({token:'csrf',identities:[{id:'daily'}]});
    assert.deepEqual(JSON.parse(String(init?.body)),{items:[{task_id:taskId,version}]});
    return response({items:[],unread:1});
  });
  assert.equal(await api.seen(snapshot()),false);assert.equal(paths.length,0);
  const rendered=taskDetail(task({status:'completed_unverified',activity_receipt:{task_id:taskId,version}}),taskId,'daily');
  assert.equal(await api.seen(rendered),true);
  assert.deepEqual(paths,['/api/bootstrap','/api/activity/seen']);
  assert.throws(()=>taskDetail(task({activity_receipt:{task_id:otherId,version}}),taskId,'daily'));
});
