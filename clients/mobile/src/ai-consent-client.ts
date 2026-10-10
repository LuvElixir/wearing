import {ApiError, connectionEndpoint, connectionHeaders, type Connection} from './core';
import {isPublicConnection} from './connection-default';

export const AI_PRIVACY_URL = 'https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html';
export type AIConsentSnapshot = {
  required: true; provider: {id: 'deepseek'; name: 'DeepSeek'; origin: 'https://api.deepseek.com'; privacy_url: typeof AI_PRIVACY_URL};
  policy_version: string; disclosure: {title: string; purpose: string; data_categories: string[]; withdrawal: string};
  accepted: boolean; state: 'not_granted' | 'accepted' | 'revoked'; revision: number; updated_at: number | null;
};
export type AIConsentAction = 'accept' | 'revoke';
export class AIConsentError extends ApiError {
  constructor(public code: 'invalid' | 'expired' | 'changed' | 'unavailable' | 'unconfirmed', status = 0) {
    super(({invalid:'AI 服务说明暂时无法确认，请刷新后再选择。',expired:'登录已过期，请重新登录。',changed:'授权状态已经变化，请刷新后重新核对。',unavailable:'当前账户的 AI 授权暂时不可用，请联系邀请人。',unconfirmed:'暂时无法确认结果。请刷新核对状态，不会自动重复提交。'} as const)[code], status);
  }
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, max: number): v is string => typeof v === 'string' && v.trim().length > 0 && v.length <= max;
export function aiConsentSnapshot(value: unknown): AIConsentSnapshot {
  if (!object(value) || value.required !== true || !object(value.provider) || value.provider.id !== 'deepseek' || value.provider.name !== 'DeepSeek' || value.provider.origin !== 'https://api.deepseek.com' || value.provider.privacy_url !== AI_PRIVACY_URL || !text(value.policy_version,128) || !object(value.disclosure) || !text(value.disclosure.title,200) || !text(value.disclosure.purpose,2000) || !text(value.disclosure.withdrawal,2000) || !Array.isArray(value.disclosure.data_categories) || !value.disclosure.data_categories.length || value.disclosure.data_categories.length > 12 || !value.disclosure.data_categories.every(v=>text(v,500)) || typeof value.accepted !== 'boolean' || !['not_granted','accepted','revoked'].includes(String(value.state)) || value.accepted !== (value.state === 'accepted') || !Number.isSafeInteger(value.revision) || (value.revision as number) < 0 || !(value.updated_at === null || typeof value.updated_at === 'number' && Number.isFinite(value.updated_at) && (value.updated_at as number) > 0) || (value.revision === 0 && (value.state !== 'not_granted' || value.updated_at !== null)) || (value.revision !== 0 && value.updated_at === null)) throw new AIConsentError('invalid');
  return {required:true,provider:{id:'deepseek',name:'DeepSeek',origin:'https://api.deepseek.com',privacy_url:AI_PRIVACY_URL},policy_version:value.policy_version,disclosure:{title:value.disclosure.title,purpose:value.disclosure.purpose,data_categories:[...value.disclosure.data_categories],withdrawal:value.disclosure.withdrawal},accepted:value.accepted,state:value.state as AIConsentSnapshot['state'],revision:value.revision as number,updated_at:value.updated_at as number|null};
}
export const needsAIConsent = (connection: Connection | null): connection is Connection => !!connection && isPublicConnection(connection) && !!connection.session;
/** UI authority is memory-only and scoped to an exact activation. The Core enforces every model call. */
export class AIConsentGate {
  private active: Connection | null = null;
  private accepted = false;
  activate(connection: Connection | null) {this.active=connection;this.accepted=false;}
  invalidate(connection: Connection) {if(this.active===connection)this.accepted=false;}
  observe(connection: Connection, snapshot: AIConsentSnapshot) {
    if(this.active!==connection)return false;
    this.accepted=aiConsentSnapshot(snapshot).accepted;return true;
  }
  allows(connection: Connection) {return !needsAIConsent(connection) || this.active===connection && this.accepted;}
}
export class AIConsentClient {
  constructor(readonly connection: Connection, private fetcher: typeof fetch = fetch) {}
  private async request(path: string, signal: AbortSignal, body?: unknown, token?: string): Promise<unknown> {
    const controller=new AbortController(), abort=()=>controller.abort();
    if(signal.aborted)controller.abort();signal.addEventListener('abort',abort);
    const timer=setTimeout(abort,15000);
    try {
      if(controller.signal.aborted)throw new AIConsentError('unconfirmed');
      const response=await this.fetcher(new URL(path,connectionEndpoint(this.connection)).toString(),{method:body===undefined?'GET':'POST',headers:{...connectionHeaders(this.connection),'X-Wearing-Identity':this.connection.identity,...(body===undefined?{}:{'Content-Type':'application/json','X-Wearing-Token':token||''})},body:body===undefined?undefined:JSON.stringify(body),credentials:'omit',redirect:'error',cache:'no-store',signal:controller.signal});
      if(controller.signal.aborted)throw new AIConsentError('unconfirmed');
      if(!response.ok)throw new AIConsentError(response.status===401?'expired':response.status===409?'changed':response.status===403?'unavailable':'unconfirmed',response.status);
      const raw=await response.text();
      if(controller.signal.aborted)throw new AIConsentError('unconfirmed');
      if(raw.length>16384)throw new AIConsentError('invalid');
      return JSON.parse(raw);
    } catch(error) {if(error instanceof AIConsentError)throw error;if(error instanceof ApiError&&error.status===401)throw new AIConsentError('expired',401);throw new AIConsentError('unconfirmed');}
    finally {clearTimeout(timer);signal.removeEventListener('abort',abort);}
  }
  async read(signal: AbortSignal) {return aiConsentSnapshot(await this.request('/api/ai-consent',signal));}
  async change(action: AIConsentAction, snapshot: AIConsentSnapshot, requestId: string, signal: AbortSignal) {
    aiConsentSnapshot(snapshot);
    if(!['accept','revoke'].includes(action)||!/^[a-f0-9]{32}$/.test(requestId))throw new AIConsentError('invalid');
    const bootstrap=await this.request('/api/bootstrap',signal);
    if(!object(bootstrap)||bootstrap.version!=='0.2.0'||typeof bootstrap.token!=='string'||!bootstrap.token||bootstrap.token.length>512||!Array.isArray(bootstrap.identities)||!bootstrap.identities.some(i=>object(i)&&i.id===this.connection.identity))throw new AIConsentError('invalid');
    // Exactly one POST, including on a 403 or timeout. Recovery is a read, never an automatic replay.
    const value=await this.request('/api/ai-consent',signal,{action,policy_version:snapshot.policy_version,expected_revision:snapshot.revision,request_id:requestId},bootstrap.token);
    const result=aiConsentSnapshot(value);
    if(!object(value)||!object(value.receipt)||value.receipt.request_id!==requestId||value.receipt.action!==action||!Number.isSafeInteger(value.receipt.revision)||(value.receipt.revision as number)<=snapshot.revision||(value.receipt.revision as number)>result.revision||!(typeof value.receipt.recorded_at === 'number' && Number.isFinite(value.receipt.recorded_at))||(value.receipt.recorded_at as number)<=0)throw new AIConsentError('invalid');
    return result;
  }
}
