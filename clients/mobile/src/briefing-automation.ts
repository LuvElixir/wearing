import {ApiError,connectionEndpoint,connectionHeaders,scopeOf,type Connection,type Store} from './core';
export type AutoValues={enabled:boolean;local_time:string;timezone:string;grace_minutes:number;preferences_revision:number};
export type AutoRequest=AutoValues&{revision:number;request_key:string};
export type AutoReceipt=AutoValues&{schema:1;identity_id:string;revision:number;request_key:string;updated_at:string;next_run:string|null};
export type DayReceipt={local_date:string;timezone:string;revision:number;due_at:string;state:'requested'|'existing'|'skipped';briefing_id:string|null;task_id:string|null;created_at:string;briefing:{id:string;date:string;timezone:string;version:number;state:string;task_id:string|null}|null};
export type AutoSettings=Omit<AutoReceipt,'request_key'|'preferences_revision'|'updated_at'>&{preferences_revision:number|null;updated_at:string|null;schedule_status:string|null;reason:string;needs_resave:boolean;receipts:DayReceipt[];execution:'service_required';quiet_hours:'notification_delivery_only'};
const fail=()=>new ApiError('自动简报回执无法核对，原设置保留。',422);
const integer=(v:unknown)=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
const stamp=(v:unknown)=>typeof v==='string'&&Number.isFinite(Date.parse(v));
const day=(v:unknown)=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&stamp(v)&&new Date(v).toISOString().slice(0,10)===v;
const zone=(v:unknown)=>{if(typeof v!=='string'||!v||v.length>80)return false;try{new Intl.DateTimeFormat('en',{timeZone:v});return true;}catch{return false;}};
export function autoValues(raw:unknown):AutoValues {const v=raw as AutoValues;if(!v||typeof v.enabled!=='boolean'||typeof v.local_time!=='string'||!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(v.local_time)||!zone(v.timezone)||!integer(v.grace_minutes)||v.grace_minutes<1||v.grace_minutes>360||!integer(v.preferences_revision))throw fail();return {enabled:v.enabled,local_time:v.local_time,timezone:v.timezone,grace_minutes:v.grace_minutes,preferences_revision:v.preferences_revision};}
export function autoRequest(raw:unknown):AutoRequest {const v=raw as AutoRequest;if(!v||!integer(v.revision)||typeof v.request_key!=='string'||!/^[A-Za-z0-9_-]{16,120}$/.test(v.request_key)||Object.keys(v).some(k=>!['enabled','local_time','timezone','grace_minutes','preferences_revision','revision','request_key'].includes(k)))throw fail();return {...autoValues(v),revision:v.revision,request_key:v.request_key};}
export function autoReceipt(raw:unknown,identity:string):AutoReceipt {const v=raw as AutoReceipt;autoValues(v);if(v.schema!==1||v.identity_id!==identity||!integer(v.revision)||v.revision<1||!stamp(v.updated_at)||v.next_run!==null&&!stamp(v.next_run)||typeof v.request_key!=='string')throw fail();return v;}
export function autoSettings(raw:unknown,identity:string):AutoSettings {
 const v=raw as AutoSettings;autoValues({...v,preferences_revision:v?.preferences_revision??0});if(!v||v.schema!==1||v.identity_id!==identity||!integer(v.revision)||v.preferences_revision!==null&&!integer(v.preferences_revision)||v.updated_at!==null&&!stamp(v.updated_at)||v.next_run!==null&&!stamp(v.next_run)||!([null,'active','paused','cancelled','finished'] as unknown[]).includes(v.schedule_status)||typeof v.reason!=='string'||typeof v.needs_resave!=='boolean'||v.execution!=='service_required'||v.quiet_hours!=='notification_delivery_only'||!Array.isArray(v.receipts)||v.receipts.length>7)throw fail();
 const seen=new Set<string>();for(const r of v.receipts){if(!r||!day(r.local_date)||seen.has(r.local_date)||!zone(r.timezone)||!integer(r.revision)||r.revision<1||!stamp(r.due_at)||!stamp(r.created_at)||!['requested','existing','skipped'].includes(r.state)||r.briefing_id!==null&&typeof r.briefing_id!=='string'||r.task_id!==null&&typeof r.task_id!=='string')throw fail();seen.add(r.local_date);if(r.briefing){const b=r.briefing;if(b.id!==r.briefing_id||b.date!==r.local_date||!zone(b.timezone)||!integer(b.version)||b.version<1||!['not_started','queued','needs_attention','running','ready','text_only','failed','stopped'].includes(b.state)||b.task_id!==null&&typeof b.task_id!=='string')throw fail();}else if(r.briefing_id!==null)throw fail();}return v;
}
export const autoPendingKey=(connection:Connection)=>'briefing-automation-request:'+scopeOf(connection);
export class BriefAutomationClient {
 constructor(readonly connection:Connection,private fetcher:typeof fetch,private active:()=>boolean,private signal?:AbortSignal){}
 private async request(body?:AutoRequest):Promise<unknown>{
  if(!this.active()||this.signal?.aborted)throw new ApiError('当前自动简报连接已停止。',0);
  const controller=new AbortController(),abort=()=>controller.abort(),timer=setTimeout(abort,15000);this.signal?.addEventListener('abort',abort);if(this.signal?.aborted)abort();
  const valid=()=>this.active()&&!this.signal?.aborted&&!controller.signal.aborted;
  try{const headers={...connectionHeaders(this.connection),'X-Wearing-Identity':this.connection.identity};let token='';
   if(body){const boot=await this.fetcher(new URL('/api/bootstrap',connectionEndpoint(this.connection)),{signal:controller.signal,redirect:'error',headers});const value=await boot.json();if(!valid()||!boot.ok||typeof value.token!=='string'||!value.token||!value.identities?.some((i:{id?:string})=>i.id===this.connection.identity))throw fail();token=value.token;}
   if(!valid())throw new ApiError('当前自动简报连接已停止。',0);
   const response=await this.fetcher(new URL('/api/briefing-automation',connectionEndpoint(this.connection)),{method:body?'POST':'GET',signal:controller.signal,redirect:'error',headers:{...headers,...(body?{'Content-Type':'application/json','X-Wearing-Token':token}:{})},...(body?{body:JSON.stringify(body)}:{})});const value=await response.json();if(!valid())throw new ApiError('当前自动简报连接已停止。',0);if(!response.ok)throw new ApiError(typeof value.detail==='string'?value.detail:'自动简报设置尚未读取或保存。',response.status);return value;
  }finally{clearTimeout(timer);this.signal?.removeEventListener('abort',abort);}
 }
 async load(){return autoSettings(await this.request(),this.connection.identity);}
 async save(raw:AutoRequest){const body=autoRequest(raw),result=autoReceipt(await this.request(body),this.connection.identity);if(result.request_key!==body.request_key||result.revision!==body.revision+1||['enabled','local_time','timezone','grace_minutes',...(body.enabled?['preferences_revision']:[])].some(k=>result[k as keyof AutoReceipt]!==body[k as keyof AutoRequest]))throw fail();return result;}
}
const locks=new Map<string,Promise<unknown>>();
export async function saveAutomation(store:Pick<Store,'get'|'put'>,client:BriefAutomationClient,active:()=>boolean,input?:AutoRequest){
 const key=autoPendingKey(client.connection);const work=async()=>{const old=await store.get<unknown>(key);if(!active())throw new ApiError('当前设置已停止。',0);const body=old?autoRequest(old):input?autoRequest(input):null;if(!body)throw fail();if(old&&input&&JSON.stringify(body)!==JSON.stringify(autoRequest(input)))throw new ApiError('请先核对上一次保存。',409);if(!old)await store.put(key,body);if(!active())throw new ApiError('当前设置已停止。',0);const receipt=await client.save(body);if(!active())throw new ApiError('当前设置已停止。',0);await store.put(key,null);return receipt;};
 const result=(locks.get(key)||Promise.resolve()).catch(()=>{}).then(work);locks.set(key,result);try{return await result;}finally{if(locks.get(key)===result)locks.delete(key);}
}
