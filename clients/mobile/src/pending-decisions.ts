import {ApiError, Connection, connectionEndpoint, connectionHeaders, scopeOf, Store, WearingApi} from './core';

export type PendingDecision = {id: string; identity_id: string; task_id: string; revision: number; state: string;
  recovery_task_id: string | null; can_resume: boolean; card: {title: string; action: string; impact: string}};
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const taskId = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{32}$/.test(v);
const malformed = () => new ApiError('确认事项暂时无法核对，请刷新。', 422);
export function decisionSnapshot(value: unknown, identity: string): PendingDecision[] {
  if (!object(value) || !Array.isArray(value.items)) throw malformed();
  const seen = new Set<string>();
  return value.items.map(row => {
    if (!object(row) || typeof row.id !== 'string' || !/^decision_[a-f0-9]{32}$/.test(row.id) || seen.has(row.id) || row.identity_id !== identity || !taskId(row.task_id) || !Number.isSafeInteger(row.revision) || (row.revision as number) < 1 || typeof row.state !== 'string' || typeof row.can_resume !== 'boolean' || (row.recovery_task_id !== null && !taskId(row.recovery_task_id)) || !object(row.card) || ['title','action','impact'].some(k => typeof (row.card as Record<string,unknown>)[k] !== 'string')) throw malformed();
    if (row.can_resume && row.state !== 'needs_recheck') throw malformed();
    seen.add(row.id);
    return row as PendingDecision;
  });
}
export function decisionLabel(row: PendingDecision): string {
  return ({pending:'等你确认', sending:'正在核对确认结果', unknown:'确认结果待核对', needs_recheck:row.can_resume?'等待重新核对':'等待原任务结束', recovering:'正在重新核对', executing:'正在执行已确认的操作', execution_unknown:'需核对原结果'} as Record<string,string>)[row.state] || '查看记录';
}
export class DecisionClient {
  constructor(private connection: Connection, private store: Pick<Store,'get'|'put'>, private id:()=>string, private fetcher: typeof fetch = fetch) {}
  private async request(path: string, body?: unknown): Promise<unknown> {
    const token = body ? await new WearingApi(this.connection, this.fetcher).voiceAuthorization() : '';
    const controller = new AbortController(), timer = setTimeout(()=>controller.abort(), 20000);
    try {
      const response = await this.fetcher(new URL(path, connectionEndpoint(this.connection)).toString(), {method:body?'POST':'GET', signal:controller.signal, redirect:'error', headers:{...connectionHeaders(this.connection),'X-Wearing-Identity':this.connection.identity,...(body?{'X-Wearing-Token':token,'Content-Type':'application/json'}:{})}, ...(body?{body:JSON.stringify(body)}:{})});
      if (!response.ok) throw new ApiError(response.status===409?'事项状态已有变化，请刷新后重新核对。':response.status===401?'连接已到期，请重新登录。':response.status===404?'当前身份找不到这项确认，请刷新。':'暂时无法处理，请稍后重试。',response.status);
      return await response.json();
    } catch(error) {if(error instanceof ApiError) throw error;throw new ApiError('暂时无法确认处理结果。刷新后可以用同一次请求重试。');}
    finally {clearTimeout(timer);}
  }
  async list() {return decisionSnapshot(await this.request('/api/confirmations'), this.connection.identity);}
  async resume(row: PendingDecision): Promise<{taskId:string; delivery:string}> {
    if(row.identity_id!==this.connection.identity || !row.can_resume) throw malformed();
    const key = 'confirmation.resume.' + scopeOf(this.connection) + '.' + row.id + '.' + row.revision;
    let requestKey = await this.store.get<string>(key);
    if (!requestKey) {requestKey=this.id(); await this.store.put(key,requestKey);}
    if(!/^[A-Za-z0-9_-]{16,120}$/.test(requestKey)) throw malformed();
    const result = await this.request('/api/confirmations/'+encodeURIComponent(row.id)+'/resume',{revision:row.revision,request_key:requestKey});
    if(!object(result) || result.authorized!==false || !object(result.task) || !taskId(result.task.id) || !['live_confirmation','waiting_for_original','queued','saved','submitted'].includes(String(result.delivery))) throw malformed();
    // Keep the durable key even on success. A late/replayed tap cannot create a
    // second recovery if the screen or service restarts before its list updates.
    return {taskId:result.task.id,delivery:String(result.delivery)};
  }
}
