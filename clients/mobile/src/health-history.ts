import {ApiError, type Connection, type Store, connectionEndpoint, connectionHeaders, scopeOf} from './core';
import {taskPhases} from './diagnostics-client';
export const components = ['runtime','engine','devices','task','collector'] as const;
export const statuses = ['ok','fault','review','waiting','inactive','ended','unknown','not_configured'] as const;
export const codes = ['observed','runtime_unavailable','runtime_error','engine_unavailable','engine_timeout','device_source_unavailable','device_disconnected','device_review','run_failed','engine_connection_lost','run_state_unknown','stop_unconfirmed','progress_check','collection_failed'] as const;
export const kinds = ['condition_started','condition_changed','condition_cleared','condition_ended','state_changed'] as const;
export const categories = ['chat','voice','sync','files','notifications','devices','performance','other'] as const;
export type HealthCategory = typeof categories[number];
const bad = () => new ApiError('运行历史回执无法核对，请重新读取。',422);
const object = (v:unknown):Record<string,unknown> => {if(!v||typeof v!=='object'||Array.isArray(v))throw bad();return v as Record<string,unknown>;};
const option = <T extends string>(v:unknown,items:readonly T[]):T => {if(typeof v!=='string'||!items.includes(v as T))throw bad();return v as T;};
const integer = (v:unknown,max=Number.MAX_SAFE_INTEGER):number => {if(!Number.isSafeInteger(v)||(v as number)<0||(v as number)>max)throw bad();return v as number;};
const positive = (v:unknown) => {const n=integer(v);if(!n)throw bad();return n;};
const boolean = (v:unknown) => {if(typeof v!=='boolean')throw bad();return v;};
const instant = (v:unknown):string => {if(typeof v!=='string'||!/^\d{4}-\d\d-\d\dT/.test(v)||!Number.isFinite(Date.parse(v)))throw bad();return new Date(v).toISOString();};
const nullable = <T>(v:unknown,parse:(v:unknown)=>T):T|null => v===null?null:parse(v);
const list = (v:unknown,max:number):unknown[] => {if(!Array.isArray(v)||v.length>max)throw bad();return v;};
const reference = (v:unknown):string => {if(typeof v!=='string'||!/^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|run_[a-f0-9]{32}|ref_[a-f0-9]{16})$/.test(v))throw bad();return v;};
const reportId = (v:unknown):string => {if(typeof v!=='string'||!/^[a-f0-9]{32}$/.test(v))throw bad();return v;};
function signal(v:unknown){const r=object(v);return {component:option(r.component,components),status:option(r.status,statuses),code:option(r.code,codes),task_id:nullable(r.task_id,reference),run_id:nullable(r.run_id,reference),attempt:nullable(r.attempt,n=>integer(n,100000)),phase:nullable(r.phase,p=>option(p,taskPhases)),last_state_event_at:nullable(r.last_state_event_at,instant)};}
/** Export only a closed projection; unknown logs, addresses and content never pass through. */
export function healthHistory(v:unknown){
  const r=object(v),c=object(r.coverage);
  if(r.schema!==1||r.scope!=='current_identity'||c.mode!=='point_in_time_samples'||c.continuous_uptime_proven!==false)throw bad();
  const samples=list(r.samples,288).map(v=>{const s=object(v);return {id:positive(s.id),observed_at:instant(s.observed_at),source:option(s.source,['manual','scheduled','unknown'] as const),deployment:option(s.deployment,['local','cloud','synthetic','unknown'] as const),observations:list(s.observations,34).map(signal)};});
  const events=list(r.events,500).map(v=>{const e=object(v);return {id:positive(e.id),sample_id:positive(e.sample_id),observed_at:instant(e.observed_at),kind:option(e.kind,kinds),component:option(e.component,components),task_id:nullable(e.task_id,reference),status:option(e.status,statuses),code:option(e.code,codes),previous_status:nullable(e.previous_status,s=>option(s,statuses)),previous_code:nullable(e.previous_code,s=>option(s,codes)),condition_started_at:nullable(e.condition_started_at,instant)};});
  if(new Set(samples.map(s=>s.id)).size!==samples.length||new Set(events.map(e=>e.id)).size!==events.length)throw bad();
  return {schema:1 as const,scope:'current_identity' as const,read_at:instant(r.read_at),sampler_running:r.sampler_running===undefined?null:boolean(r.sampler_running),coverage:{retention_seconds:positive(c.retention_seconds),sample_interval_seconds:positive(c.sample_interval_seconds),latest_observed_at:nullable(c.latest_observed_at,instant),earliest_retained_at:nullable(c.earliest_retained_at,instant),seconds_since_observation:nullable(c.seconds_since_observation,integer),freshness:option(c.freshness,['never_observed','stale','recent'] as const),continuous_uptime_proven:false as const,mode:'point_in_time_samples' as const},samples,events,samples_truncated:boolean(r.samples_truncated),events_truncated:boolean(r.events_truncated),next_before_sample:nullable(r.next_before_sample,positive),next_before_event:nullable(r.next_before_event,positive)};
}
export type HealthHistory = ReturnType<typeof healthHistory>;
export function healthExport(v:unknown,category:HealthCategory){const r=object(v),id=reportId(r.id);if(r.schema!==1||r.category!==category||r.transmission!=='not_sent'||typeof r.sha256!=='string'||!/^[a-f0-9]{64}$/.test(r.sha256)||r.filename!==`pajio-diagnostics-${id}.json`)throw bad();return {schema:1 as const,id,category,created_at:instant(r.created_at),expires_at:instant(r.expires_at),sha256:r.sha256,bytes:integer(r.bytes,1048576),filename:r.filename,transmission:'not_sent' as const};}
export type HealthExport = ReturnType<typeof healthExport>;
export function healthExportContents(v:unknown,metadata:HealthExport){const r=object(v);if(r.schema!==1||r.report_id!==metadata.id||r.category!==metadata.category||r.transmission!=='not_sent'||instant(r.created_at)!==metadata.created_at||instant(r.expires_at)!==metadata.expires_at)throw bad();return {schema:1,report_id:metadata.id,category:metadata.category,created_at:metadata.created_at,expires_at:metadata.expires_at,transmission:'not_sent',contents:healthHistory(r.contents)};}
export class HealthHistoryApi {
  private token='';
  private enabled=true;
  setActive(value:boolean){this.enabled=value;}
  readonly connection:Connection;
  constructor(connection:Connection,private digest:(bytes:Uint8Array)=>Promise<string>,private fetcher:typeof fetch=fetch,private active:()=>boolean=()=>true){this.connection={...connection,...(connection.session?{session:{...connection.session}}:{}),...(connection.development?{development:{...connection.development}}:{})};}
  private async request(path:string,body?:object,raw=false,retry=true):Promise<unknown>{
    if(!this.enabled||!this.active())throw new ApiError('账户或页面已切换，请重新打开。',409);
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),25000);
    try{const response=await this.fetcher(new URL(path,connectionEndpoint(this.connection)),{method:body?'POST':'GET',signal:controller.signal,redirect:'error',headers:{...connectionHeaders(this.connection),'X-Wearing-Identity':this.connection.identity,...(body?{'Content-Type':'application/json','X-Wearing-Token':this.token}:{})},...(body?{body:JSON.stringify(body)}:{})});
      if(body&&response.status===403&&retry){await this.bootstrap();return this.request(path,body,raw,false);}
      if(!response.ok)throw new ApiError(response.status===404?'运行历史尚未接入或报告已过期。':response.status===429?'今日诊断文件已达上限，请使用已生成的文件。':'运行历史暂时无法读取，请重试。',response.status);
      if(!response.headers.get('Content-Type')?.includes('application/json'))throw bad();
      const length=Number(response.headers.get('Content-Length')||0);if(length>1048576)throw bad();
      const bytes=new Uint8Array(await response.arrayBuffer());if(bytes.byteLength>1048576)throw bad();
      return raw?{bytes,sha256:response.headers.get('X-Content-SHA256')}:JSON.parse(new TextDecoder().decode(bytes));
    }catch(error){if(error instanceof ApiError)throw error;throw new ApiError(body?'请求结果尚未确认，请重试取回同一次结果。':'运行历史连接中断，请重试。',0);}finally{clearTimeout(timeout);}
  }
  private async bootstrap(){const r=object(await this.request('/api/bootstrap'));if(typeof r.token!=='string'||!r.token||!Array.isArray(r.identities)||!r.identities.some(v=>object(v).id===this.connection.identity))throw bad();this.token=r.token;}
  async load(beforeEvent?:number){return healthHistory(await this.request('/api/diagnostics/history?sample_limit=48&event_limit=50'+(beforeEvent?`&before_event=${positive(beforeEvent)}`:'')));}
  async sample(){if(!this.token)await this.bootstrap();const r=object(await this.request('/api/diagnostics/sample',{}));if(r.schema!==1||typeof r.sampled!=='boolean')throw bad();return this.load();}
  async create(requestKey:string,category:HealthCategory){if(!/^[A-Za-z0-9_-]{16,80}$/.test(requestKey)||!categories.includes(category))throw bad();if(!this.token)await this.bootstrap();return healthExport(await this.request('/api/diagnostics/exports',{request_key:requestKey,category}),category);}
  async contents(metadata:HealthExport){const raw=await this.request(`/api/diagnostics/exports/${reportId(metadata.id)}/file`,undefined,true) as {bytes:Uint8Array;sha256:string|null};if(raw.bytes.byteLength!==metadata.bytes||raw.sha256!==metadata.sha256||await this.digest(raw.bytes)!==metadata.sha256)throw bad();return healthExportContents(JSON.parse(new TextDecoder().decode(raw.bytes)),metadata);}
}
/** Persist a stable key before exporting; loss of the response never makes another report. */
export class HealthExportRequest {
  readonly key:string;
  private busy=false;
  constructor(private storage:Pick<Store,'get'|'put'>,private api:HealthHistoryApi){this.key=`health-export-request:${scopeOf(api.connection)}`;}
  async pending(){const v=await this.storage.get(this.key);if(v===null)return null;const r=object(v);if(typeof r.request_key!=='string'||!/^[A-Za-z0-9_-]{16,80}$/.test(r.request_key))throw bad();return {request_key:r.request_key,category:option(r.category,categories)};}
  async run(id:string,category:HealthCategory){if(this.busy)throw new ApiError('正在生成诊断文件，请稍候。',409);this.busy=true;try{const prior=await this.pending();const body=prior||{request_key:id,category};await this.storage.put(this.key,body);return await this.api.create(body.request_key,body.category);}finally{this.busy=false;}}
  async reset(){if(this.busy)throw new ApiError('请等待这次请求结束。',409);await this.storage.put(this.key,null);}
}
export const componentLabels:Record<typeof components[number],string>={runtime:'运行环境',engine:'执行引擎',devices:'执行设备',task:'任务',collector:'状态采集'};
export const statusLabels:Record<typeof statuses[number],string>={ok:'本次检查正常',fault:'发现异常',review:'需要核对',waiting:'等待处理',inactive:'未运行',ended:'本次状态已结束',unknown:'尚未确认',not_configured:'尚未配置'};
export const eventLabels:Record<typeof kinds[number],string>={condition_started:'发现问题',condition_changed:'问题有变化',condition_cleared:'本次检查已恢复',condition_ended:'观察已结束',state_changed:'状态变化'};
