import {test} from 'node:test';
import assert from 'node:assert/strict';
import {NotificationClient, quietMinute, quietTime, quietReceipt, type QuietHours} from './notification-client';
const connection = {endpoint:'https://quiet.invalid',identity:'daily'}, install = 'synthetic-quiet-001';
const policy: QuietHours = {identity_id:'daily',installation_id:install,revision:0,enabled:false,start_minute:1320,end_minute:480,timezone:'Asia/Shanghai'};
const response = (data:unknown,status=200) => new Response(JSON.stringify(data),{status});
test('quiet times validate before submission and preserve midnight', () => {
  assert.equal(quietMinute('00:00'),0); assert.equal(quietMinute('23:59'),1439); assert.equal(quietTime(480),'08:00');
  for(const value of ['24:00','22:60','9:00','-1:00','22:00 garbage']) assert.throws(()=>quietMinute(value));
  for(const patch of [{identity_id:'other'},{installation_id:'other'},{revision:-1},{start_minute:480},{timezone:''},{enabled:'yes'}]) assert.throws(()=>quietReceipt({...policy,...patch},'daily',install));
});
test('preference read and save bind identity, installation, CSRF and exact next revision', async () => {
  const calls: {path:string; headers:Headers; body:unknown}[] = [];
  const replies = [policy,{version:'0.2.0',token:'synthetic-csrf',identities:[{id:'daily'}]},{...policy,enabled:true,revision:1}];
  const api = new NotificationClient(connection,install,(async(input,init)=>{
    calls.push({path:new URL(String(input)).pathname,headers:new Headers(init?.headers),body:init?.body?JSON.parse(String(init.body)):null});
    return response(replies.shift());
  }) as typeof fetch);
  assert.deepEqual(await api.quietHours(),policy);
  assert.equal((await api.saveQuietHours({...policy,enabled:true})).revision,1);
  assert.equal(calls[2].path,'/api/notifications/preferences');
  assert.equal(calls[2].headers.get('X-Wearing-Identity'),'daily');
  assert.equal(calls[2].headers.get('X-Wearing-Token'),'synthetic-csrf');
  assert.deepEqual(calls[2].body,{installation_id:install,revision:0,enabled:true,start_minute:1320,end_minute:480,timezone:'Asia/Shanghai'});
});
test('unknown save outcome preserves server CAS instead of claiming success or changing revision', async () => {
  let count=0;
  const api=new NotificationClient(connection,install,(async()=>{
    if(++count===1)return response({version:'0.2.0',token:'csrf',identities:[{id:'daily'}]});
    return response({detail:'时段已修改，请重新读取'},409);
  }) as typeof fetch);
  await assert.rejects(api.saveQuietHours(policy),/重新读取/);
  assert.equal(count,2);assert.equal(policy.revision,0);
});
test('mismatched preference receipt never reports saved', async () => {
  let count=0;
  const api=new NotificationClient(connection,install,(async()=>response(++count===1?{version:'0.2.0',token:'csrf',identities:[{id:'daily'}]}:{...policy,revision:1,end_minute:600})) as typeof fetch);
  await assert.rejects(api.saveQuietHours(policy),/回执/);
});
