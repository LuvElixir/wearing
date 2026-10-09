import {ApiError,connectionEndpoint,connectionHeaders,scopeOf,type Connection,type Store} from './core';
import {onboardingDraftKey,onboardingPendingKey,onboardingRequest,onboardingSnapshot,onboardingValues,type OnboardingRequest,type OnboardingSnapshot,type OnboardingValues} from './onboarding-model';

/** Imperative lifecycle fence shared by network and local writes, never rendered. */
export class OnboardingActivity {
  private live=true;
  constructor(private current:()=>boolean){}
  active=()=>this.live&&this.current();
  update(current:()=>boolean){this.current=current;}
  mount(){this.live=true;}
  stop(){this.live=false;}
}

export class OnboardingApi {
  constructor(readonly connection:Connection,private fetcher:typeof fetch,private active:()=>boolean=()=>true,private signal?:AbortSignal){}
  private assertActive(){if(!this.active()||this.signal?.aborted)throw new ApiError('当前身份已改变，请返回后重新打开。',0);}
  private async call(path:string,body?:OnboardingRequest,token?:string):Promise<unknown>{
    this.assertActive();
    const controller=new AbortController(),cancel=()=>controller.abort(),timer=setTimeout(cancel,15000);
    this.signal?.addEventListener('abort',cancel);
    try{
      const response=await this.fetcher(new URL(path,connectionEndpoint(this.connection)),{method:body?'POST':'GET',redirect:'error',signal:controller.signal,headers:{...connectionHeaders(this.connection),'X-Wearing-Identity':this.connection.identity,...(body?{'Content-Type':'application/json','X-Wearing-Token':token||''}:{})},...(body?{body:JSON.stringify(body)}:{})});
      this.assertActive();
      if(!response.ok)throw new ApiError(response.status===409?'偏好已在另一处更新。请读取最新版本后核对。':response.status===404?'这台服务还未提供初始偏好设置，可以先进入产品。':'偏好暂时无法保存或读取，请重试。',response.status);
      const result=await response.json();this.assertActive();return result;
    }catch(cause){if(cause instanceof ApiError)throw cause;throw new ApiError(body?'保存结果尚未确认，请重试同一次保存。':'暂时无法读取初始偏好。',0);}
    finally{clearTimeout(timer);this.signal?.removeEventListener('abort',cancel);}
  }
  async load(){return onboardingSnapshot(await this.call('/api/onboarding'),this.connection.identity);}
  async save(input:OnboardingRequest){
    const body=onboardingRequest(input),boot=await this.call('/api/bootstrap') as {token?:unknown;identities?:{id:string}[]};
    if(typeof boot.token!=='string'||!boot.token||!Array.isArray(boot.identities)||!boot.identities.some(item=>item.id===this.connection.identity))throw new ApiError('当前身份尚未核对，请重新连接。',422);
    const raw=await this.call('/api/onboarding',body,boot.token) as Record<string,unknown>;
    try{
      const saved=onboardingSnapshot(raw,this.connection.identity);
      if(raw.request_key!==body.request_key||saved.revision!==body.revision+1||saved.status!==body.status||saved.step!==body.step||JSON.stringify(saved.values)!==JSON.stringify(body.values))throw new Error('mismatched receipt');
      return saved;
    }catch{throw new ApiError('保存回执还没核对，请重试同一次保存。',0);}
  }
}
export type OnboardingDraft = {version:1;revision:number;step:number;values:OnboardingValues};
export function onboardingDraft(value:unknown):OnboardingDraft|null{
  if(value===null)return null;
  const row=value as Partial<OnboardingDraft>;
  if(!row||row.version!==1||!Number.isSafeInteger(row.revision)||row.revision!<0||!Number.isSafeInteger(row.step)||row.step!<0||row.step!>5)throw new ApiError('本机选择暂时无法读取，请重试。',422);
  return {version:1,revision:row.revision!,step:row.step!,values:onboardingValues(row.values)};
}
/** One queued journal per identity: exact pending commands survive failed receipts and reloads. */
export class OnboardingChanges {
  readonly draftKey:string;readonly pendingKey:string;
  private tail:Promise<unknown>=Promise.resolve();
  constructor(private store:Pick<Store,'get'|'put'>,readonly api:OnboardingApi,private active:()=>boolean=()=>true){const scope=scopeOf(api.connection);this.draftKey=onboardingDraftKey(scope);this.pendingKey=onboardingPendingKey(scope);}
  private queue<T>(work:()=>Promise<T>):Promise<T>{const next=this.tail.catch(()=>{}).then(async()=>{if(!this.active())throw new ApiError('当前身份已改变，保存已停止。',0);return work();});this.tail=next;return next;}
  async draft(){return onboardingDraft(await this.store.get(this.draftKey));}
  async pending(){const value=await this.store.get(this.pendingKey);return value===null?null:onboardingRequest(value);}
  retain(value:OnboardingDraft){const draft=onboardingDraft(value)!;return this.queue(()=>this.store.put(this.draftKey,draft));}
  save(input?:OnboardingRequest){return this.queue(async()=>{
    const saved=await this.pending();if(!this.active())throw new ApiError('当前身份已改变，保存已停止。',0);
    const body=saved||(input&&onboardingRequest(input));if(!body)throw new ApiError('没有等待保存的选择。',422);
    if(saved&&input&&JSON.stringify(saved)!==JSON.stringify(onboardingRequest(input)))throw new ApiError('请先重试上一次保存。',409);
    if(!saved)await this.store.put(this.pendingKey,body);
    if(!this.active())throw new ApiError('当前身份已改变，保存已停止。',0);
    const exact=await this.api.save(body);
    // The idempotency receipt may precede changes from another device. Only a
    // fresh server snapshot can become the next editing checkpoint.
    const receipt=await this.api.load();
    if(receipt.revision<exact.revision||receipt.revision===exact.revision&&(receipt.status!==exact.status||receipt.step!==exact.step||JSON.stringify(receipt.values)!==JSON.stringify(exact.values)))throw new ApiError('最新偏好还没有核对，请重试同一次保存。',0);
    if(!this.active())throw new ApiError('当前身份已改变，请重新读取保存结果。',0);
    // Keep a draft checkpoint until the receipt journal has been cleared. A crash
    // can replay the request key without resurrecting a different mutation.
    await this.store.put(this.draftKey,receipt.status==='draft'?{version:1,revision:receipt.revision,step:receipt.step,values:receipt.values}:null);
    await this.store.put(this.pendingKey,null);return receipt;
  });}
  /** Only a definite 409 permits abandoning an exact pending command. */
  resolveConflict(fresh:OnboardingSnapshot){return this.queue(async()=>{
    const pending=await this.pending();if(pending&&fresh.revision<=pending.revision)throw new ApiError('还没读到较新的版本，请保留原选择并重试。',409);
    await this.store.put(this.pendingKey,null);
  });}
}
