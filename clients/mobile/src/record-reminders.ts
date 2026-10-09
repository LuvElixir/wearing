import {ApiError, connectionEndpoint, connectionHeaders, type Connection, type Store} from './core';
import {withRecordDraft} from './record-editor';
export const reminderAdvances = [0, 5, 15, 30, 60, 1440] as const;
export type Reminder = {identity_id:string;target_id:string;revision:number;record_revision:number|null;enabled:boolean;advance_minutes:number;anchor_at:string|null;fire_at:string|null;status:'unavailable'|'disabled'|'expired'|'scheduled'|'due';reason:string|null;provider_status:string|null;request_key?:string};
export type ReminderRequest = {revision:number;record_revision:number;enabled:boolean;advance_minutes:number;request_key:string};
export type PendingReminder = {schema:1;request:ReminderRequest;phase:'pending'|'rejected';error?:string};
const targetId=(v:unknown):v is string=>typeof v==='string'&&/^(?:life_[a-f0-9]{32}|recurrence_[a-f0-9]{32}_\d{8})$/.test(v);
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const natural=(v:unknown):v is number=>Number.isSafeInteger(v)&&(v as number)>=0;
const instant=(v:unknown):v is string=>typeof v==='string'&&Number.isFinite(Date.parse(v));
const bad=(status=422)=>new ApiError('提醒设置回执无法核对，原操作仍保留。',status);
export const reminderKey=(scope:string,target:string)=>`record-reminder-request:${scope}:${target}`;
export const reminderCacheKey=(scope:string,target:string)=>`record-reminder-last:${scope}:${target}`;
export function reminderRequest(v:unknown):ReminderRequest {
  if(!object(v)||Object.keys(v).some(k=>!['revision','record_revision','enabled','advance_minutes','request_key'].includes(k))||!natural(v.revision)||!natural(v.record_revision)||!v.record_revision||typeof v.enabled!=='boolean'||!reminderAdvances.includes(v.advance_minutes as never)||typeof v.request_key!=='string'||!/^[A-Za-z0-9_-]{16,120}$/.test(v.request_key))throw bad();
  return {revision:v.revision,record_revision:v.record_revision,enabled:v.enabled,advance_minutes:v.advance_minutes as number,request_key:v.request_key};
}
export function reminderReceipt(v:unknown,identity:string,target:string,request?:ReminderRequest):Reminder {
  if(!object(v)||!targetId(target)||v.target_id!==target||v.identity_id!==identity||!natural(v.revision)||!(v.record_revision===null||natural(v.record_revision)&&v.record_revision>0)||typeof v.enabled!=='boolean'||!reminderAdvances.includes(v.advance_minutes as never)||!(v.anchor_at===null||instant(v.anchor_at))||!(v.fire_at===null||instant(v.fire_at))||!['unavailable','disabled','expired','scheduled','due'].includes(String(v.status))||!(v.reason===null||['missing','removed','completed','all_day','no_time'].includes(String(v.reason)))||!(v.provider_status===null||['pending','awaiting_registration','sending','ticket','provider_accepted','unknown','failed','cancelled'].includes(String(v.provider_status))))throw bad(request?0:422);
  if(v.anchor_at!==null&&(v.fire_at===null||Date.parse(v.anchor_at as string)-Date.parse(v.fire_at as string)!==(v.advance_minutes as number)*60000))throw bad(request?0:422);
  if(request&&(v.revision!==request.revision+1||v.record_revision!==request.record_revision||v.enabled!==request.enabled||v.advance_minutes!==request.advance_minutes||v.request_key!==request.request_key))throw bad(0);
  return v as Reminder;
}
export function pendingReminder(v:unknown):PendingReminder|null {
  if(v===null)return null;
  if(!object(v)||v.schema!==1||!['pending','rejected'].includes(String(v.phase)))throw bad();
  return {schema:1,request:reminderRequest(v.request),phase:v.phase as PendingReminder['phase'],...(typeof v.error==='string'?{error:v.error}:{})};
}
export function reminderMessage(v:Reminder):string {
  const unavailable:Record<string,string>={missing:'这次日程已取消或记录不可用。',removed:'记录已移除，提醒已停止。',completed:'待办已完成，提醒已停止。',all_day:'全天日程还没有具体时刻，请先设置开始时间。',no_time:'请先为待办设置截止时间，或为日程设置具体开始时间。'};
  if(v.status==='unavailable')return unavailable[v.reason||'no_time'];
  if(!v.enabled)return '未开启这条记录的提醒。';
  if(v.status==='expired')return '提醒时间已过去；过期提醒不会补发。';
  if(v.provider_status==='unknown')return '这次提醒的送达尚未确认，为避免重复打扰不会重新发送。';
  if(v.provider_status==='awaiting_registration')return '提醒等待这台手机重新开启通知；过期后不会补发。';
  if(v.provider_status==='provider_accepted'||v.provider_status==='ticket')return '提醒已交给推送服务，手机是否展示仍受系统设置影响。';
  return `已安排在 ${new Date(v.fire_at!).toLocaleString('zh-CN')} 提醒；遵循通知设置与安静时段。`;
}
export class RecordReminderClient {
  private token=''; readonly connection:Connection;
  constructor(connection:Connection,private fetcher:typeof fetch=fetch,private current:()=>boolean=()=>true,private signal?:AbortSignal){this.connection={...connection,...(connection.session?{session:{...connection.session}}:{}),...(connection.development?{development:{...connection.development}}:{})};}
  private check(){if(!this.current()||this.signal?.aborted)throw new ApiError('当前身份已切换，原操作留在原身份。',0);}
  private async request(path:string,body?:ReminderRequest,retry=true):Promise<unknown>{
    this.check();const timer=new AbortController(),abort=()=>timer.abort(),timeout=setTimeout(abort,20000);this.signal?.addEventListener('abort',abort,{once:true});
    try{const response=await this.fetcher(new URL(path,connectionEndpoint(this.connection)),{method:body?'POST':'GET',redirect:'error',signal:timer.signal,headers:{...connectionHeaders(this.connection),'X-Wearing-Identity':this.connection.identity,...(body?{'Content-Type':'application/json','X-Wearing-Token':this.token}:{})},...(body?{body:JSON.stringify(body)}:{})});this.check();
      if(body&&response.status===403&&retry){await this.bootstrap();return this.request(path,body,false);}
      const value:unknown=await response.json().catch(()=>{throw bad(body?0:422);});
      if(!response.ok)throw new ApiError(object(value)&&typeof value.detail==='string'?value.detail:'提醒操作未完成，请重新读取。',response.status);return value;
    }catch(error){if(error instanceof ApiError)throw error;throw new ApiError('没有收到提醒设置的回执，原操作仍留在本机。',0);}finally{clearTimeout(timeout);this.signal?.removeEventListener('abort',abort);}
  }
  private async bootstrap(){const value=await this.request('/api/bootstrap');if(!object(value)||typeof value.token!=='string'||!value.token||!Array.isArray(value.identities)||!value.identities.some(row=>object(row)&&row.id===this.connection.identity))throw bad(0);this.token=value.token;}
  async get(target:string){if(!targetId(target))throw bad();return reminderReceipt(await this.request('/api/record-reminders/'+target),this.connection.identity,target);}
  async save(target:string,input:ReminderRequest){if(!targetId(target))throw bad();const request=reminderRequest(input);await this.bootstrap();return reminderReceipt(await this.request('/api/record-reminders/'+target,request),this.connection.identity,target,request);}
}
type ReminderStore=Pick<Store,'get'|'put'|'batch'>;
export async function submitReminder(store:ReminderStore,scope:string,target:string,client:Pick<RecordReminderClient,'save'>,input:ReminderRequest|undefined,current:()=>boolean){
  const key=reminderKey(scope,target);return withRecordDraft(key,async()=>{
    if(!current())throw new ApiError('当前身份已切换。',0);
    let waiting=pendingReminder(await store.get(key));
    if(input){const request=reminderRequest(input);if(waiting)throw new ApiError('请先取回上一项提醒操作回执。',409);waiting={schema:1,request,phase:'pending'};await store.put(key,waiting);}
    if(!waiting)throw new ApiError('没有待核对的提醒操作。',422);
    if(waiting.phase==='rejected')throw new ApiError('请先读取最新设置，保留输入后重新核对。',409);
    try{if(!current())throw new ApiError('当前身份已切换。',0);const result=await client.save(target,waiting.request);
      if(!current())throw new ApiError('当前身份已切换，稍后可取回原回执。',0);
      await store.batch([[reminderCacheKey(scope,target),result],[key,null]]);return result;
    }catch(error){const rejected=error instanceof ApiError&&[400,404,409,413,422].includes(error.status);if(current())await store.put(key,{...waiting,phase:rejected?'rejected':'pending',error:error instanceof Error?error.message:'操作尚未确认。'});throw error;}
  });
}
export async function adoptReminderRead(store:ReminderStore,scope:string,target:string,value:Reminder){
  const key=reminderKey(scope,target);return withRecordDraft(key,async()=>{const waiting=pendingReminder(await store.get(key));if(waiting&&waiting.phase!=='rejected')throw new ApiError('操作结果未知，请先取回原回执。',409);await store.batch([[reminderCacheKey(scope,target),value],[key,null]]);});
}
