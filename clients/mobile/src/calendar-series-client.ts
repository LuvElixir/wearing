import {ApiError,connectionEndpoint,connectionHeaders,type Connection,type Store} from './core';
import {seriesMutation,seriesPendingKey,seriesQuery,seriesRow,type SeriesMutation} from './calendar-series-model';
export class CalendarSeriesClient {
  constructor(readonly connection:Connection,private fetcher:typeof fetch,private active:()=>boolean,private signal?:AbortSignal){}
  private async call(body?:unknown):Promise<unknown>{
    if(!this.active()||this.signal?.aborted)throw new Error('当前日历连接已停止。');
    const controller=new AbortController(),cancel=()=>controller.abort(),timer=setTimeout(cancel,15000);this.signal?.addEventListener('abort',cancel);if(this.signal?.aborted)cancel();
    try{
      const base=connectionEndpoint(this.connection),headers={...connectionHeaders(this.connection),'X-Wearing-Identity':this.connection.identity};
      let token='';if(body){const boot=await this.call() as {token?:string;identities?:{id:string}[]};if(!boot.token||!boot.identities?.some(i=>i.id===this.connection.identity))throw new Error('无法核对当前日历身份。');token=boot.token;}
      if(!this.active()||this.signal?.aborted)throw new Error('当前日历连接已停止。');
      const response=await this.fetcher(new URL(body?'/api/calendar-series':'/api/bootstrap',base).toString(),{method:body?'POST':'GET',redirect:'error',signal:controller.signal,headers:{...headers,...(body?{'Content-Type':'application/json','X-Wearing-Token':token}:{})},...(body?{body:JSON.stringify(body)}:{})});
      const data=await response.json();if(!this.active()||this.signal?.aborted)throw new Error('当前日历连接已停止。');
      if(!response.ok)throw new ApiError(typeof data?.detail==='string'?data.detail:'日历请求未完成，原输入已保留。',response.status);return data;
    }finally{clearTimeout(timer);this.signal?.removeEventListener('abort',cancel);}
  }
  async get(id:string,occurrence_key?:string){const row=seriesRow(await this.call({action:'get',series_id:id,...(occurrence_key?{occurrence_key}:{})}),this.connection.identity);if(row.id!==id)throw new Error('系列回执不匹配。');if(occurrence_key&&row.selected){seriesQuery({start:'selected',end:'selected',timezone:'selected',checked_at:row.updated_at,limit:1000,truncated:false,items:[row.selected]},this.connection.identity,'selected','selected','selected');if(row.selected.recurrence.occurrence_key!==occurrence_key||row.selected.recurrence.series_id!==row.id||row.selected.revision!==row.revision)throw new Error('该次日程回执不匹配。');}else if(occurrence_key&&row.selected!==null)throw new Error('该次日程状态不完整。');return row;}
  async list(after?:string){const v=await this.call({action:'list',include_deleted:true,...(after?{after}:{})}) as {items:unknown[];next:string|null};if(!v||!Array.isArray(v.items)||v.items.length>50||v.next!==null&&!/^series_[a-f0-9]{32}$/.test(v.next))throw new Error('系列列表无法核对。');return{items:v.items.map(row=>seriesRow(row,this.connection.identity)),next:v.next};}
  async query(start:string,end:string,timezone:string){return seriesQuery(await this.call({action:'query',start,end,timezone}),this.connection.identity,start,end,timezone);}
  async mutate(command:SeriesMutation){const input=seriesMutation(command),row=seriesRow(await this.call(input),this.connection.identity);if(input.series_id&&row.id!==input.series_id||row.revision!==(input.action==='create'?1:input.revision!+1))throw new Error('系列保存回执不匹配，请用原编号再次核对。');return row;}
}
/** Durable intent always precedes HTTP; retries reuse identical command and request key. */
const queues=new Map<string,Promise<unknown>>();
export async function submitSeriesMutation(store:Pick<Store,'get'|'put'>,scope:string,target:string,client:Pick<CalendarSeriesClient,'mutate'>,command?:SeriesMutation,active=()=>true,completeLocalSave?:()=>Promise<void>){
  const key=seriesPendingKey(scope,target);
  const operation=async()=>{
  const saved=await store.get<unknown>(key);if(!active())throw new Error('日历保存已停止。');
  const pending=saved?seriesMutation(saved):command?seriesMutation(command):null;if(!pending)throw new Error('没有待核对的修改。');
  if(target!=='new'&&pending.series_id!==target)throw new Error('本机修改不属于当前系列。');
  if(saved&&command&&JSON.stringify(saved)!==JSON.stringify(command))throw new Error('先核对上一次保存，再发起新的修改。');
  if(!saved)await store.put(key,pending);if(!active())throw new Error('日历保存已停止。');
  const result=await client.mutate(pending);if(!active())throw new Error('日历保存已停止。');
  // Clear the recoverable draft before its idempotency journal, so a crash cannot
  // resurrect the same completed creation as a new intent.
  if(completeLocalSave)await completeLocalSave();if(!active())throw new Error('日历保存已停止。');
  await store.put(key,null);return result;
  };
  const result=(queues.get(key)||Promise.resolve()).catch(()=>{}).then(operation);queues.set(key,result);
  try{return await result;}finally{if(queues.get(key)===result)queues.delete(key);}
}
