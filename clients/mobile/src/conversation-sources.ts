import {ApiError, connectionEndpoint, connectionHeaders, type Connection, type Store} from './core';
import {withRecordDraft} from './record-editor';
export type ConversationSource={source_id:string;source_revision:string;source_task_id:string;title:string;started_at:string;updated_at:string;message_count:number;excluded:boolean;excluded_at:string|null};
export type SourcePage={identity_id:string;revision:number;snapshot:string;items:ConversationSource[];next_offset:number|null};
export type SourceRequest={source_id:string;source_revision:string;revision:number;request_key:string};
export type SourceReceipt=SourceRequest&{identity_id:string;excluded:true;excluded_at:string;continuation_reset:true;history_retained:true};
export type PendingSource={schema:1;request:SourceRequest;phase:'pending'|'rejected';error?:string};
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const natural=(v:unknown):v is number=>Number.isSafeInteger(v)&&(v as number)>=0;
const hash=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const sourceId=(v:unknown):v is string=>typeof v==='string'&&/^source_[a-f0-9]{64}$/.test(v);
const instant=(v:unknown):v is string=>typeof v==='string'&&Number.isFinite(Date.parse(v));
const bad=(status=422)=>new ApiError('对话来源回执无法核对，原操作仍保留。',status);
export const sourcePendingKey=(scope:string)=>`conversation-source-request:${scope}`;
export const sourcePageKey=(scope:string)=>`conversation-source-page:${scope}`;
export const sourceReceiptKey=(scope:string)=>`conversation-source-receipt:${scope}`;
export function sourceRequest(v:unknown):SourceRequest{
  if(!object(v)||Object.keys(v).some(k=>!['source_id','source_revision','revision','request_key'].includes(k))||!sourceId(v.source_id)||!hash(v.source_revision)||!natural(v.revision)||typeof v.request_key!=='string'||!/^[A-Za-z0-9_-]{16,120}$/.test(v.request_key))throw bad();
  return {source_id:v.source_id,source_revision:v.source_revision,revision:v.revision,request_key:v.request_key};
}
export function sourcePage(v:unknown,identity:string):SourcePage{
  if(!object(v)||v.identity_id!==identity||!natural(v.revision)||!hash(v.snapshot)||!Array.isArray(v.items)||v.items.length>50||!(v.next_offset===null||natural(v.next_offset)&&v.next_offset>0))throw bad();
  const ids=new Set<string>();
  for(const row of v.items){if(!object(row)||!sourceId(row.source_id)||ids.has(row.source_id)||!hash(row.source_revision)||typeof row.source_task_id!=='string'||!/^[a-f0-9]{32}$/.test(row.source_task_id)||typeof row.title!=='string'||Array.from(row.title).length>120||!instant(row.started_at)||!instant(row.updated_at)||!natural(row.message_count)||!row.message_count||typeof row.excluded!=='boolean'||!(row.excluded?instant(row.excluded_at):row.excluded_at===null))throw bad();ids.add(row.source_id);}
  return v as SourcePage;
}
export function sourceReceipt(v:unknown,identity:string,request:SourceRequest):SourceReceipt{
  if(!object(v)||v.identity_id!==identity||v.source_id!==request.source_id||v.source_revision!==request.source_revision||v.revision!==request.revision+1||v.request_key!==request.request_key||v.excluded!==true||v.continuation_reset!==true||v.history_retained!==true||!instant(v.excluded_at))throw bad(0);
  return v as SourceReceipt;
}
export function pendingSource(v:unknown):PendingSource|null{
  if(v===null)return null;if(!object(v)||v.schema!==1||!['pending','rejected'].includes(String(v.phase)))throw bad();
  return {schema:1,request:sourceRequest(v.request),phase:v.phase as PendingSource['phase'],...(typeof v.error==='string'?{error:v.error}:{})};
}
export function mergeSourcePages(previous:SourcePage,next:SourcePage,offset:number):SourcePage{
  if(previous.identity_id!==next.identity_id||previous.revision!==next.revision||previous.snapshot!==next.snapshot||previous.next_offset!==offset||previous.items.length!==offset||next.items.some(row=>previous.items.some(old=>old.source_id===row.source_id)))throw new ApiError('对话列表已变化，请从头刷新。',409);
  return {...next,items:[...previous.items,...next.items]};
}
export class ConversationSourcesClient{
  private token='';readonly connection:Connection;
  constructor(connection:Connection,private fetcher:typeof fetch=fetch,private current:()=>boolean=()=>true,private signal?:AbortSignal){this.connection={...connection,...(connection.session?{session:{...connection.session}}:{}),...(connection.development?{development:{...connection.development}}:{})};}
  private check(){if(!this.current()||this.signal?.aborted)throw new ApiError('当前身份已切换，原操作留在原身份。',0);}
  private async request(path:string,body?:SourceRequest,retry=true):Promise<unknown>{
    this.check();const aborter=new AbortController(),abort=()=>aborter.abort(),timeout=setTimeout(abort,20000);this.signal?.addEventListener('abort',abort,{once:true});
    try{const response=await this.fetcher(new URL(path,connectionEndpoint(this.connection)),{method:body?'POST':'GET',redirect:'error',signal:aborter.signal,headers:{...connectionHeaders(this.connection),'X-Wearing-Identity':this.connection.identity,...(body?{'Content-Type':'application/json','X-Wearing-Token':this.token}:{})},...(body?{body:JSON.stringify(body)}:{})});this.check();
      if(body&&response.status===403&&retry){await this.bootstrap();return this.request(path,body,false);}
      const value:unknown=await response.json().catch(()=>{throw bad(body?0:422);});this.check();if(!response.ok)throw new ApiError(object(value)&&typeof value.detail==='string'?value.detail:'对话来源操作未完成。',response.status);return value;
    }catch(error){if(error instanceof ApiError)throw error;throw new ApiError('没有收到来源操作回执，请取回原回执。',0);}finally{clearTimeout(timeout);this.signal?.removeEventListener('abort',abort);}
  }
  private async bootstrap(){const value=await this.request('/api/bootstrap');if(!object(value)||typeof value.token!=='string'||!value.token||!Array.isArray(value.identities)||!value.identities.some(row=>object(row)&&row.id===this.connection.identity))throw bad(0);this.token=value.token;}
  async page(offset=0,snapshot?:string){if(!natural(offset)||snapshot!==undefined&&!hash(snapshot))throw bad();return sourcePage(await this.request(`/api/conversation-sources?offset=${offset}&limit=20${snapshot?`&snapshot=${snapshot}`:''}`),this.connection.identity);}
  async exclude(input:SourceRequest){const request=sourceRequest(input);await this.bootstrap();return sourceReceipt(await this.request('/api/conversation-sources/exclude',request),this.connection.identity,request);}
}
type LocalStore=Pick<Store,'get'|'put'|'batch'>;
export async function excludeConversation(store:LocalStore,scope:string,client:Pick<ConversationSourcesClient,'exclude'>,input:SourceRequest|undefined,current:()=>boolean){
  const key=sourcePendingKey(scope);return withRecordDraft(key,async()=>{
    if(!current())throw new ApiError('当前身份已切换。',0);let pending=pendingSource(await store.get(key));
    if(input){if(pending)throw new ApiError('请先取回上一次来源操作的回执。',409);pending={schema:1,request:sourceRequest(input),phase:'pending'};await store.put(key,pending);}
    if(!pending)throw new ApiError('没有待核对的来源操作。',422);if(pending.phase==='rejected')throw new ApiError('请先重新读取来源范围，再确认。',409);
    try{if(!current())throw new ApiError('当前身份已切换。',0);const result=await client.exclude(pending.request);if(!current())throw new ApiError('当前身份已切换，稍后可取回原回执。',0);
      await store.batch([[sourceReceiptKey(scope),result],[sourcePageKey(scope),null],[key,null]]);return result;
    }catch(error){if(current())await store.put(key,{...pending,phase:error instanceof ApiError&&[400,404,409,413,422].includes(error.status)?'rejected':'pending',error:error instanceof Error?error.message:'操作还未确认。'});throw error;}
  });
}
export async function adoptSourcePage(store:LocalStore,scope:string,page:SourcePage){const key=sourcePendingKey(scope);return withRecordDraft(key,async()=>{const pending=pendingSource(await store.get(key));if(pending?.phase==='pending')throw new ApiError('原操作结果未知，请先取回原回执。',409);await store.batch([[sourcePageKey(scope),page],[key,null]]);});}
