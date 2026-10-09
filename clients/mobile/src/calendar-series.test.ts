import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError,scopeOf,type Connection,type Store} from './core';
import {CalendarSeriesClient,submitSeriesMutation} from './calendar-series-client';
import {occurrenceTemplate,seriesDraft,seriesEdit,seriesMutation,seriesPendingKey,seriesQuery,seriesRow,seriesStorageKey,seriesDraftKey,type Series,type SeriesDraft,type SeriesMutation,type SeriesOccurrence,type SeriesQuery} from './calendar-series-model';
import {accountCleanupPlan,fenceFor,fencedWrite} from './account-cleanup-model';
const draft:SeriesDraft={template:{title:'合成安排',content:'测试内容是数据',timezone:'Asia/Shanghai',all_day:false,start_local:'2026-10-08T09:00',end_local:'2026-10-08T10:00'},rule:{frequency:'weekly',interval:1,weekdays:[],count:null,until:null}};
const row:Series={id:'series_'+'a'.repeat(32),identity_id:'daily',revision:1,body:draft,deleted_at:null,created_at:'2026-10-08T00:00:00Z',updated_at:'2026-10-08T00:00:00Z',exceptions:[]};
const item:SeriesOccurrence={id:'recurrence_'+'a'.repeat(32)+'_20261008',identity_id:'daily',kind:'event',title:'一次安排',content:'内容',timezone:'Asia/Shanghai',all_day:false,start_at:'2026-10-08T01:00:00Z',end_at:'2026-10-08T02:00:00Z',revision:1,updated_at:row.updated_at,deleted_at:null,recurrence:{series_id:row.id,series_revision:1,occurrence_key:'2026-10-08',exception_revision:null}};
const snapshot:SeriesQuery={start:'2026-10-01',end:'2026-11-01',timezone:'Asia/Shanghai',checked_at:row.updated_at,limit:1000,truncated:false,items:[item]};
const command:SeriesMutation={action:'create',draft,request_key:'once'};
const connection:Connection={endpoint:'https://pajio.example/',identity:'daily',session:{userId:'user_'+'a'.repeat(32),tenantId:'team',credentialId:'b'.repeat(32),accessToken:'s'.repeat(64),expiresAt:'2030-01-01T00:00:00Z'}};
function store(){const rows=new Map<string,unknown>();const data:Pick<Store,'get'|'put'>={get:async<T>(key:string)=>(structuredClone(rows.get(key))??null)as T|null,put:async(key,v)=>{rows.set(key,structuredClone(v));}};return {data,rows};}

test('series parser rejects foreign identity, malformed dates, weekdays and unknown operation fields',()=>{
  assert.equal(seriesRow(row,'daily'),row);assert.throws(()=>seriesRow(row,'other'));
  assert.throws(()=>seriesDraft({...draft,template:{...draft.template,start_local:'2026-02-30T09:00'}}));
  assert.throws(()=>seriesDraft({...draft,rule:{...draft.rule,weekdays:[0,0]}}));
  assert.throws(()=>seriesMutation({...command,owner:'forged'}));
  assert.throws(()=>seriesMutation({action:'cancel',request_key:'x',series_id:row.id,revision:1}));
});
test('derived occurrence identity and range must match exactly before replacing cached view',()=>{
  assert.equal(seriesQuery(snapshot,'daily',snapshot.start,snapshot.end,snapshot.timezone),snapshot);
  for(const changed of [{...snapshot,items:[item,item]},{...snapshot,items:[{...item,id:'life_'+'a'.repeat(32)}]},{...snapshot,start:'2026-10-02'},{...snapshot,timezone:'America/New_York'},{...snapshot,items:[{...item,revision:2}]}])assert.throws(()=>seriesQuery(changed,'daily',snapshot.start,snapshot.end,snapshot.timezone));
});
test('editing a saved UTC instance reconstructs its series timezone, not the device clock',()=>{
  assert.equal(occurrenceTemplate(item).start_local,'2026-10-08T09:00');
  assert.equal(occurrenceTemplate({...item,timezone:'America/New_York'}).start_local,'2026-10-07T21:00');
  assert.equal(occurrenceTemplate({...item,all_day:true,start_at:'2026-10-08',end_at:'2026-10-09'}).start_local,'2026-10-08');
});
test('unfinished draft keeps its base revision while malformed stored structures fail closed',()=>{
  assert.equal(seriesEdit({draft:{...draft,template:{...draft.template,title:''}},mode:'series',baseRevision:1}).baseRevision,1);
  assert.throws(()=>seriesEdit({draft:{},mode:'once',baseRevision:1}));assert.throws(()=>seriesEdit({draft,mode:'series',baseRevision:0}));
});
test('durable mutation exists before HTTP, lost receipt replays identical request key after reload',async()=>{
  const s=store();let calls=0;const client={mutate:async(v:SeriesMutation)=>{calls++;assert.deepEqual(s.rows.get(seriesPendingKey('scope','new')),v);if(calls===1)throw new Error('lost response');assert.deepEqual(v,command);return row;}};
  await assert.rejects(submitSeriesMutation(s.data,'scope','new',client,command),/lost response/);
  assert.deepEqual(await submitSeriesMutation(s.data,'scope','new',client),row);assert.equal(s.rows.get(seriesPendingKey('scope','new')),null);assert.equal(calls,2);
});
test('write failure, changed pending command and foreign target do not send a mutation',async()=>{
  const s=store();let calls=0;const client={mutate:async()=>{calls++;return row;}};
  await assert.rejects(submitSeriesMutation({...s.data,put:async()=>{throw new Error('disk');}},'scope','new',client,command));assert.equal(calls,0);
  s.rows.set(seriesPendingKey('scope','new'),command);await assert.rejects(submitSeriesMutation(s.data,'scope','new',client,{...command,request_key:'replacement'}));
  s.rows.set(seriesPendingKey('scope',row.id),{action:'archive',series_id:'series_'+'b'.repeat(32),revision:1,request_key:'bad'});await assert.rejects(submitSeriesMutation(s.data,'scope',row.id,client));assert.equal(calls,0);
});
test('late result after account switch retains journal and cannot clear another session work',async()=>{
  const s=store();let active=true;const client={mutate:async()=>{active=false;return row;}};
  await assert.rejects(submitSeriesMutation(s.data,'scope','new',client,command,()=>active),/停止/);assert.deepEqual(s.rows.get(seriesPendingKey('scope','new')),command);
});
test('aborted client rejects a late body even if the mock transport ignores AbortSignal',async()=>{
  const abort=new AbortController();
  const fetcher=(async(url:unknown)=>String(url).endsWith('/api/bootstrap')?Response.json({token:'csrf',identities:[{id:'daily'}]}):{ok:true,status:200,json:async()=>{abort.abort();return row;}})as typeof fetch;
  await assert.rejects(new CalendarSeriesClient(connection,fetcher,()=>true,abort.signal).get(row.id),/停止/);
});
test('cloud client pins account identity tenant and current revision, rejected response keeps pending journal',async()=>{
  const seen:RequestInit[]=[];const fetcher=(async(url:unknown,init:RequestInit)=>{seen.push(init);return String(url).endsWith('/api/bootstrap')?Response.json({token:'csrf',identities:[{id:'daily'}]}):Response.json({detail:'changed'},{status:409});}) as typeof fetch;
  const s=store(),client=new CalendarSeriesClient(connection,fetcher,()=>true);
  await assert.rejects(submitSeriesMutation(s.data,'scope','new',client,command),(e:unknown)=>e instanceof ApiError&&e.status===409);
  for(const request of seen){const headers=request.headers as Record<string,string>;assert.equal(headers.Authorization,'Bearer '+connection.session!.accessToken);assert.equal(headers['X-Pajio-Expected-Tenant'],'team');assert.equal(headers['X-Wearing-Identity'],'daily');assert.equal(request.redirect,'error');}
  assert.equal((seen[1].headers as Record<string,string>)['X-Wearing-Token'],'csrf');assert.deepEqual(s.rows.get(seriesPendingKey('scope','new')),command);
});
test('latest selected occurrence is validated against series revision rather than trusting stale calendar card',async()=>{
  const fetcher=(async(url:unknown)=>String(url).endsWith('/api/bootstrap')?Response.json({token:'csrf',identities:[{id:'daily'}]}):Response.json({...row,revision:2,selected:item})) as typeof fetch;
  await assert.rejects(new CalendarSeriesClient(connection,fetcher,()=>true).get(row.id,'2026-10-08'),/不匹配/);
});
test('all recurrence caches drafts and retry journals respect exact account fence and cleanup',()=>{
  const scope=scopeOf(connection),other={...connection,session:{...connection.session!,userId:'user_'+'b'.repeat(32)}};
  const keys=[seriesStorageKey(scope)+':calendar',seriesDraftKey(scope,'new'),seriesPendingKey(scope,row.id)];
  assert.deepEqual(accountCleanupPlan(connection,[...keys.map(key=>({key,value:command})),{key:seriesStorageKey(scopeOf(other)),value:snapshot}]).remove,keys);
  for(const key of keys)assert.equal(fencedWrite(key,command,[fenceFor(connection)]),true);
});

test('crash during local draft acknowledgement retains the creation key until the draft is cleared',async()=>{
  const s=store(),key=seriesDraftKey('scope','new');s.rows.set(key,draft);let calls=0;
  const client={mutate:async(v:SeriesMutation)=>{calls++;assert.deepEqual(v,command);return row;}};
  await assert.rejects(submitSeriesMutation(s.data,'scope','new',client,command,()=>true,async()=>{throw new Error('disk after server commit');}),/disk after/);
  assert.deepEqual(s.rows.get(seriesPendingKey('scope','new')),command);
  const receipt=await submitSeriesMutation(s.data,'scope','new',client,undefined,()=>true,async()=>{await s.data.put(key,null);});
  assert.equal(receipt.id,row.id);assert.equal(s.rows.get(key),null);assert.equal(s.rows.get(seriesPendingKey('scope','new')),null);assert.equal(calls,2);
});
