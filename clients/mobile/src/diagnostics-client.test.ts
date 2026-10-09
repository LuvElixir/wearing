import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError, Connection} from './core';
import {DiagnosticSnapshot, DiagnosticsClient, clearDiagnosticErrors, diagnosticBytes, diagnosticFindings, diagnosticSnapshot, makeDiagnosticReport, observeDiagnosticError, recentDiagnosticErrors, shareDiagnosticReport} from './diagnostics-client';
const now = Date.parse('2026-10-08T00:00:00Z'), stamp = new Date(now).toISOString();
const connection: Connection = {endpoint: 'https://private-host.invalid', identity: 'daily', session: {accessToken:'s'.repeat(64), expiresAt: new Date(Date.now()+3600000).toISOString(), userId:'user_'+'a'.repeat(32), tenantId:'private-tenant', credentialId:'b'.repeat(32)}};
const canary = 'PRIVATE token /Users/person/document.txt https://private.invalid';
const local = {app_version:'0.2.0', native_build:'3', platform:'ios', os_version:'27.0', network:{type:'WIFI',isConnected:true,isInternetReachable:true,ip:canary}};
function snapshot(): DiagnosticSnapshot {
  return {schema:1,report_id:'a'.repeat(32),identity_id:'daily',captured_at:stamp,
    service:{state:'reachable',version:'0.2.0',deployment:'cloud'},
    runtime:{state:'observed',observed_at:stamp,phase:'running',installed:true,running:true,error_present:false,connectors:{files:{phase:'ready',active:true,error_present:false},phone:{phase:'idle',active:false,error_present:false},computer:{phase:'idle',active:false,error_present:false}}},
    engine_probe:{state:'reachable',observed_at:stamp},devices:{state:'not_observed',observed_at:null,truncated:false,items:[]},
    tasks:{limit:30,long_phase_seconds:900,truncated:false,items:[{task_id:'c'.repeat(32),run_id:'d'.repeat(32),phase:'running',attempt:1,created_at:stamp,record_updated_at:stamp,last_state_event_at:stamp,seconds_without_state_change:900,needs_progress_check:true,error_category:null}]}};
}
const response = (value: unknown, status=200) => new Response(JSON.stringify(value),{status});

test('projection and serialized report drop raw scope, tokens, logs, text and paths at every level', () => {
  const input = {...snapshot(), secret:canary, runtime:{...snapshot().runtime,url:canary,error:canary}, tasks:{...snapshot().tasks,items:[{...snapshot().tasks.items[0],title:canary,prompt:canary,output:canary,error:canary}]}};
  const parsed = diagnosticSnapshot(input,'daily');
  const report = makeDiagnosticReport(connection, {...local, app_version:canary, os_version:canary}, parsed, 'task',[],now);
  const text = new TextDecoder().decode(diagnosticBytes(report));
  for (const secret of ['PRIVATE','/Users/','private-host','private-tenant',connection.session!.accessToken!,connection.session!.userId,connection.session!.credentialId,'identity_id']) assert.equal(text.includes(secret),false);
  assert.equal(report.app.manifest_version,null); assert.equal(report.app.os_version,null);
  assert.equal(report.server?.tasks.items[0].task_id,'c'.repeat(32));
  assert.equal(report.connection.mode,'cloud_session'); assert.equal(report.network.type,'WIFI');
});
test('wrong identity, leaked ID shapes, unknown enums and nonfinite timings fail closed', () => {
  assert.throws(() => diagnosticSnapshot(snapshot(),'other'),ApiError);
  for (const patch of [{task_id:canary},{run_id:canary},{phase:canary},{seconds_without_state_change:Infinity},{error_category:canary},{record_updated_at:canary}]) {
    assert.throws(() => diagnosticSnapshot({...snapshot(),tasks:{...snapshot().tasks,items:[{...snapshot().tasks.items[0],...patch}]}},'daily'),ApiError);
  }
  assert.throws(() => makeDiagnosticReport({...connection,identity:'other'},local,snapshot(),'general',[],now),ApiError);
});
test('GET uses fixed credentials and identity headers, never body or query credentials', async () => {
  let request: {url:string;init:RequestInit}|undefined;
  const mutable = {...connection, session:{...connection.session!}};
  const api = new DiagnosticsClient(mutable,(async (input,init) => {request={url:String(input),init:init!};return response(snapshot());}) as typeof fetch);
  mutable.identity='other'; mutable.session.accessToken='changed';
  assert.equal((await api.snapshot()).identity_id,'daily'); assert.ok(request);
  assert.equal(request.url,'https://private-host.invalid/api/diagnostics'); assert.equal(request.init.method,'GET');
  const headers = new Headers(request.init.headers); assert.equal(headers.get('Authorization'),'Bearer '+'s'.repeat(64)); assert.equal(headers.get('X-Wearing-Identity'),'daily');
  assert.equal(request.init.redirect,'error'); assert.equal(request.init.body,undefined);
});
test('server error body and malformed receipt never become diagnostics or user-visible text', async () => {
  const fail = new DiagnosticsClient(connection,(async () => response({detail:canary},503)) as typeof fetch);
  await assert.rejects(fail.snapshot(),(error:unknown)=>error instanceof ApiError && error.status===503 && !error.message.includes('PRIVATE'));
  const malformed = new DiagnosticsClient(connection,(async () => new Response('secret non-json')) as typeof fetch);
  await assert.rejects(malformed.snapshot(),(error:unknown)=>error instanceof ApiError && error.status===422);
});
test('aborted or switched request cannot produce a usable snapshot even when transport completes', async () => {
  const controller = new AbortController(); let networkSignal: AbortSignal | null | undefined;
  const api = new DiagnosticsClient(connection,(async (_,init) => {networkSignal=init?.signal; controller.abort(); return response(snapshot());}) as typeof fetch);
  await assert.rejects(api.snapshot(controller.signal),(error:unknown)=>error instanceof ApiError && error.status===408);
  assert.equal(networkSignal?.aborted,true);
});
test('history is scope-isolated, bounded, expires, and stores categories without exception bodies', () => {
  clearDiagnosticErrors(connection);
  for(let n=0;n<12;n++) observeDiagnosticError(connection,'sync',new Error('SQLite database is locked '+canary),now+n);
  const rows=recentDiagnosticErrors(connection,now+100); assert.equal(rows.length,8); assert.equal(rows[0].category,'storage_busy'); assert.equal(JSON.stringify(rows).includes('PRIVATE'),false);
  assert.deepEqual(recentDiagnosticErrors({...connection,identity:'other'},now+100),[]);
  assert.deepEqual(recentDiagnosticErrors(connection,now+86400100),[]);
  clearDiagnosticErrors(connection); assert.deepEqual(recentDiagnosticErrors(connection,now+100),[]);
});
test('expired login and offline service still allow an accurate local report without remote state', () => {
  const c={...connection,session:{...connection.session!,expiresAt:new Date(now-1000).toISOString()}};
  const report=makeDiagnosticReport(c,{...local,network:{type:'NONE',isConnected:false,isInternetReachable:false}},null,'connection',[],now);
  assert.equal(report.connection.authorization,'expired'); assert.equal(report.server,null); assert.equal(report.network.connected,false);
  assert.match(diagnosticFindings(null)[0],/未取得服务诊断/);
});
test('findings distinguish uncertain runs, stale phase evidence, engine reachability and device leases', () => {
  const data=snapshot(); data.engine_probe.state='unavailable'; data.tasks.items.push({...data.tasks.items[0],phase:'connection_lost',needs_progress_check:false});
  data.devices={state:'observed',observed_at:stamp,truncated:false,items:[{kind:'computer',connected:false,online:false,paused:false,control_pending:false,needs_review:true,last_seen_at:stamp}]};
  const findings=diagnosticFindings(data).join('\n');
  assert.match(findings,/服务可达.*没有确认执行引擎/); assert.match(findings,/不等于任务已卡死/); assert.match(findings,/租约已失效/); assert.match(findings,/未核对的旧动作/);
});
test('user-controlled share has no network submission, cancels on scope disposal, and retries exact same bytes', async () => {
  const report=makeDiagnosticReport(connection,local,snapshot(),'general',[],now), sent:Uint8Array[]=[];
  assert.equal(await shareDiagnosticReport(report,()=>false,async()=>{assert.fail('must not share stale scope');}),false);
  await assert.rejects(shareDiagnosticReport(report,()=>true,async bytes=>{sent.push(bytes);throw new Error('share failed');}));
  assert.equal(await shareDiagnosticReport(report,()=>true,async bytes=>{sent.push(bytes);}),true);
  assert.deepEqual(sent[0],sent[1]);
});
