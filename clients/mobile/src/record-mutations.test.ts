import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError, type RecordItem} from './core';
import {RecordMutations, mutationKey, projectRecordMutations, type MutationTransport} from './record-mutations';
import {commitRecordReceipt, commitRecordSnapshot, localRecords} from './record-sync';
import {recordEdit, withRecordDraft} from './record-editor';
const clone=<T>(v:T):T=>JSON.parse(JSON.stringify(v));
class Memory {
  data=new Map<string,unknown>();fail=false;
  async get<T>(key:string):Promise<T|null>{const value=this.data.get(key);return value===undefined?null:clone(value) as T;}
  async put(key:string,value:unknown){await this.batch([[key,value]]);}
  async batch(values:[string,unknown][]){if(this.fail)throw Error('synthetic full disk');for(const[key,value]of values)this.data.set(key,clone(value));}
}
const record=(patch:Partial<RecordItem>={}):RecordItem=>({id:'life_synthetic',kind:'note',title:'原文',content:'原文',timezone:'Asia/Shanghai',revision:1,updated_at:'2026-10-08T01:00:00Z',...patch});
const scope='https://synthetic.invalid/|tenant-one|daily',other='https://synthetic.invalid/|tenant-two|daily';
const make=(store:Memory)=>{let key=0;return new RecordMutations(store,()=>`synthetic-request-${++key}`);};
function deferred<T>(){let resolve!:(v:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes;});return{promise,resolve};}
const unusedRead=async()=>{throw Error('unexpected read');};

test('offline edits of note, event and completion persist across reopening, isolated by identity',async()=>{
  const store=new Memory(),queue=make(store),note=record(),task=record({id:'life_task',kind:'task',completed:false}),event=record({id:'life_event',kind:'event',all_day:true,start_at:'2026-10-08',end_at:'2026-10-09'});
  await queue.enqueue(scope,note,{title:'本机修改',content:'本机修改'});await queue.enqueue(scope,task,{completed:true});await queue.enqueue(scope,event,{start_at:'2026-10-08T01:00:00Z',end_at:'2026-10-08T02:00:00Z',all_day:false});
  const reopened=make(store),rows=await reopened.items(scope);assert.equal(rows.length,3);assert.deepEqual(await reopened.items(other),[]);
  const projected=projectRecordMutations([note,task,event],rows);assert.equal(projected.find(r=>r.id===task.id)?.completed,true);assert.equal(projected.find(r=>r.id===event.id)?.all_day,false);
  let calls=0;await reopened.flush(scope,{update:async()=>{calls++;throw new ApiError('离线',0);},record:unusedRead},()=>true,100);
  assert.equal(calls,1);assert.equal((await reopened.items(scope))[0].base.revision,1);assert.equal((await reopened.items(scope))[0].state,'pending');
  assert.equal(await reopened.flush(other,{update:async()=>{throw Error('cross identity send');},record:unusedRead},()=>true),0);
});
test('response loss replays exact durable key/revision/patch without auto-advancing the base',async()=>{
  const store=new Memory(),queue=make(store);await queue.enqueue(scope,record(),{content:'修改'});let saved:RecordItem|null=null;const calls:unknown[][]=[];
  const transport:MutationTransport={update:async(base,patch,_action,key)=>{calls.push([key,base.revision,patch]);if(!saved){saved=record({...patch,revision:2});throw new ApiError('回执丢失',0);}return saved;},record:unusedRead};
  await queue.flush(scope,transport,()=>true,100);const reopened=new RecordMutations(store,()=>{throw Error('must reuse persisted attempt key');});await reopened.flush(scope,transport,()=>true,10000);
  assert.deepEqual(calls[0],calls[1]);assert.equal(calls[0][1],1);assert.deepEqual(await reopened.items(scope),[]);assert.equal((await localRecords(store,scope))[0].revision,2);
});
test('new input during an older request survives its success and next uses the acknowledged revision',async()=>{
  const store=new Memory(),queue=make(store),gate=deferred<RecordItem>(),entered=deferred<void>();await queue.enqueue(scope,record(),{content:'第一稿'});
  const first=queue.flush(scope,{update:async()=>{entered.resolve();return gate.promise;},record:unusedRead},()=>true);await entered.promise;await queue.enqueue(scope,record(),{content:'第二稿'});gate.resolve(record({content:'第一稿',revision:2}));await first;
  const row=(await queue.items(scope))[0];assert.equal(row.patch.content,'第二稿');assert.equal(row.base.revision,2);assert.equal(row.attempt,undefined);
  await queue.flush(scope,{update:async(base,patch,_a,key)=>{assert.equal(base.revision,2);assert.equal(patch.content,'第二稿');assert.equal(key,'synthetic-request-2');return record({...patch,revision:3});},record:unusedRead},()=>true);
  assert.deepEqual(await queue.items(scope),[]);assert.equal((await localRecords(store,scope))[0].content,'第二稿');
});
test('new edits after response loss retry the old frozen attempt before sending the newer generation',async()=>{
  const store=new Memory(),queue=make(store);await queue.enqueue(scope,record(),{content:'先保存'});await queue.flush(scope,{update:async()=>{throw new ApiError('失网');},record:unusedRead},()=>true,100);await queue.enqueue(scope,record(),{content:'后来继续编辑'});
  await queue.flush(scope,{update:async(base,patch,_a,key)=>{assert.equal(base.revision,1);assert.equal(patch.content,'先保存');assert.equal(key,'synthetic-request-1');return record({content:'先保存',revision:2});},record:unusedRead},()=>true,10000);
  const pending=(await queue.items(scope))[0];assert.equal(pending.patch.content,'后来继续编辑');assert.equal(pending.base.revision,2);assert.equal(pending.attempt,undefined);
});
test('409 preserves both copies after reopening; writes resume only after explicit generation-fenced resolution',async()=>{
  const store=new Memory(),queue=make(store),server=record({revision:4,content:'他处新内容'});await queue.enqueue(scope,record(),{content:'本机输入'});await queue.flush(scope,{update:async()=>{throw new ApiError('版本冲突',409);},record:async()=>server},()=>true);
  const reopened=make(store),row=(await reopened.items(scope))[0];assert.equal(row.patch.content,'本机输入');assert.equal(row.latest?.content,'他处新内容');assert.equal(row.state,'conflict');assert.equal((await localRecords(store,scope))[0].revision,4);
  assert.equal(await reopened.flush(scope,{update:async()=>{throw Error('must not auto overwrite');},record:unusedRead},()=>true),0);await assert.rejects(reopened.resolve(scope,row.id,row.generation+1,server,true),/状态已有变化/);await assert.rejects(reopened.enqueue(scope,server,{content:'不可静默替换冲突'}),/版本冲突/);
  await reopened.resolve(scope,row.id,row.generation,server,true,{content:'核对后的本机内容'});await reopened.flush(scope,{update:async(base,patch)=>{assert.equal(base.revision,4);assert.equal(patch.content,'核对后的本机内容');return record({...patch,revision:5});},record:unusedRead},()=>true);assert.equal((await localRecords(store,scope))[0].revision,5);
});
test('adopting server data removes only this identity edit and cannot revive a deleted record',async()=>{
  const store=new Memory(),queue=make(store),deleted=record({revision:2,deleted_at:'2026-10-08T02:00:00Z'});await queue.enqueue(scope,record(),{content:'保留'});await queue.enqueue(other,record(),{content:'另一身份'});await queue.inspect(scope,record().id,deleted);
  await assert.rejects(queue.resolve(scope,record().id,1,deleted,true),/已移除/);await queue.resolve(scope,record().id,1,deleted,false);assert.deepEqual(await queue.items(scope),[]);assert.equal((await queue.items(other))[0].patch.content,'另一身份');assert.equal((await localRecords(store,scope))[0].deleted_at,deleted.deleted_at);
});
test('a late reply writes only the original identity and stops further queued records after switching',async()=>{
  const store=new Memory(),queue=make(store),gate=deferred<RecordItem>(),entered=deferred<void>();let active=true,calls=0;await queue.enqueue(scope,record(),{content:'旧身份'});await queue.enqueue(scope,record({id:'life_two'}),{content:'第二条'});
  const work=queue.flush(scope,{update:async()=>{calls++;entered.resolve();return gate.promise;},record:unusedRead},()=>active);await entered.promise;active=false;gate.resolve(record({revision:2,content:'旧身份'}));await work;assert.equal(calls,1);assert.equal((await queue.items(scope)).length,1);assert.deepEqual(await localRecords(store,other),[]);
});
test('failed durable attempt writes prevent network access and do not claim synchronization',async()=>{
  const store=new Memory(),queue=make(store);await queue.enqueue(scope,record(),{content:'保存'});store.fail=true;await assert.rejects(queue.flush(scope,{update:async()=>{throw Error('should not send');},record:unusedRead},()=>true),/full disk/);store.fail=false;assert.equal((await queue.items(scope))[0].state,'pending');assert.equal((await queue.items(scope))[0].attempt,undefined);
});
test('malformed persisted queues fail closed without clearing the original values',async()=>{
  const store=new Memory(),queue=make(store),raw=[{version:99,scope,content:'原始输入'}];await store.put(mutationKey(scope),raw);await assert.rejects(queue.items(scope),/原输入已保留/);assert.deepEqual(await store.get(mutationKey(scope)),raw);
});
test('saving an older draft cannot erase keystrokes already persisted by a newer editor',async()=>{
  const store=new Memory(),queue=make(store),key='synthetic-draft',submitted=recordEdit(record()),newer={...submitted,text:'重开后的新输入'};await withRecordDraft(key,()=>store.put(key,newer));await queue.enqueue(scope,record(),{content:submitted.text},{key,value:submitted});assert.deepEqual(await store.get(key),newer);await queue.enqueue(scope,record(),{content:newer.text},{key,value:newer});assert.equal(await store.get(key),null);
});
test('late snapshots cannot replace newer revisions or prematurely discard a receipt',async()=>{
  const store=new Memory(),v1=record(),v2=record({revision:2,content:'修改回执'}),v3=record({revision:3,content:'之后的内容'});await commitRecordSnapshot(store,scope,{version:1,items:[v1]});await commitRecordReceipt(store,scope,v2);await commitRecordSnapshot(store,scope,{version:1,items:[v1]});assert.equal((await localRecords(store,scope))[0].revision,2);assert.equal((await store.get<RecordItem[]>(`receipts:${scope}`))?.length,1);
  await commitRecordSnapshot(store,scope,{version:3,items:[v3]});await commitRecordReceipt(store,scope,v2);await commitRecordSnapshot(store,scope,{version:2,items:[v2]});assert.equal((await localRecords(store,scope))[0].content,'之后的内容');assert.equal(await store.get(`snapshot-version:${scope}`),3);await commitRecordSnapshot(store,scope,{version:3,items:[v3]});assert.deepEqual(await store.get(`receipts:${scope}`),[]);
});
test('concurrent flush callers share one attempt rather than sending twice',async()=>{
  const store=new Memory(),queue=make(store),gate=deferred<RecordItem>();let calls=0;await queue.enqueue(scope,record(),{content:'一次'});const api={update:async()=>{calls++;return gate.promise;},record:unusedRead};const first=queue.flush(scope,api,()=>true),second=make(store).flush(scope,api,()=>true);assert.equal(first,second);gate.resolve(record({revision:2,content:'一次'}));await Promise.all([first,second]);assert.equal(calls,1);
});

test('a process restart with a durable sending attempt recovers the exact request and its original base',async()=>{
  const oldStore=new Memory(),oldQueue=make(oldStore),entered=deferred<void>(),gate=deferred<RecordItem>();
  await oldQueue.enqueue(scope,record(),{content:'退出前的修改'});
  const flight=oldQueue.flush(scope,{update:async()=>{entered.resolve();return gate.promise;},record:unusedRead},()=>true);
  await entered.promise;
  const durable=await oldStore.get(mutationKey(scope));
  const restartedStore=new Memory();await restartedStore.put(mutationKey(scope),durable);
  const reopened=new RecordMutations(restartedStore,()=>{throw Error('restart must not create a new request key');});
  assert.equal((await reopened.items(scope))[0].state,'sending');
  await reopened.flush(scope,{update:async(base,patch,_a,key)=>{assert.equal(base.revision,1);assert.equal(patch.content,'退出前的修改');assert.equal(key,'synthetic-request-1');return record({...patch,revision:2});},record:unusedRead},()=>true);
  assert.deepEqual(await reopened.items(scope),[]);
  gate.resolve(record({content:'退出前的修改',revision:2}));await flight;
});
test('losing the local receipt transaction after a server commit replays the same request, not a fresh overwrite',async()=>{
  const store=new Memory(),queue=make(store);await queue.enqueue(scope,record(),{content:'服务器已接收'});
  const batch=store.batch.bind(store);let failReceipt=true;
  store.batch=async values=>{if(failReceipt&&values.some(([key])=>key===`receipts:${scope}`)){failReceipt=false;throw Error('synthetic receipt transaction failed');}await batch(values);};
  const keys:string[]=[],receipt=record({content:'服务器已接收',revision:2});
  const api:MutationTransport={update:async(base,_patch,_a,key)=>{keys.push(key);assert.equal(base.revision,1);return receipt;},record:unusedRead};
  await queue.flush(scope,api,()=>true,100);assert.equal((await queue.items(scope))[0].base.revision,1);assert.deepEqual(await localRecords(store,scope),[]);
  await queue.flush(scope,api,()=>true,10000);assert.deepEqual(keys,['synthetic-request-1','synthetic-request-1']);assert.deepEqual(await queue.items(scope),[]);assert.equal((await localRecords(store,scope))[0].revision,2);
});
