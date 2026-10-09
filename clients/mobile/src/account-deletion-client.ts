import {ApiError, connectionEndpoint, connectionHeaders, type Connection} from './core';

export const DELETION_PATH = 'auth/account-deletion/';
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const id = (value: unknown) => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
const hex = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const bad = () => new ApiError('注销信息不完整，尚未确认处理结果。请刷新核对。', 422);
export type DeletionScope = {tenant_id: string; classification: 'private' | 'shared' | 'unknown'; action: 'erase_private' | 'leave_shared' | 'blocked'};
export type DeletionPlan = {user_id: string; tenants: DeletionScope[]; blockers: {tenant_id: string | null; code: string}[]; revision: string; ready: boolean; request_key: string; receipt_token: string; receipt_expires_in: number; reauth_required: boolean};
export type DeletionStatus = ({id: string; user_id: string; request_key: string; plan_revision: string; tenants: DeletionScope[]; created_at: number; updated_at: number} & ({state: 'awaiting_operator' | 'frozen' | 'waiting'; code: string; data_erased: false} | {state: 'completed'; code: 'verified'; data_erased: true})) | {state: 'not_submitted'; code: 'not_submitted'};
const waitingCodes = ['adapter_unconfigured', 'adapter_failed', 'adapter_mismatch', 'invalid_receipt', 'ownership_changed', 'instance_busy', 'provider_unavailable', 'backup_retained', 'fixture_busy', 'unsafe_storage', 'incomplete_registry'];
export type DeletionRecovery = {version: 1; target: Connection; requestKey: string; planRevision: string; token: string; phase: 'prepared' | 'uncertain' | 'submitted'; createdAt: number};
export const accountKey = (connection: Connection) => {
  const address = connectionEndpoint(connection, true);
  if (!connection.session) throw new ApiError('账户注销需要通过云端账户登录。', 401);
  return address + '|' + connection.session.userId;
};
export const sameAccount = (a: Connection, b: Connection) => accountKey(a) === accountKey(b);
const validScope = (value: unknown): value is DeletionScope => object(value) && id(value.tenant_id) && ['private', 'shared', 'unknown'].includes(String(value.classification)) && ['erase_private', 'leave_shared', 'blocked'].includes(String(value.action));
export function deletionPlan(value: unknown, connection: Connection): DeletionPlan {
  if (!object(value) || value.schema !== 1 || value.user_id !== connection.session?.userId || !Array.isArray(value.tenants) || !value.tenants.every(validScope) || new Set(value.tenants.map(v => v.tenant_id)).size !== value.tenants.length || !Array.isArray(value.blockers) || value.blockers.some(v => !object(v) || !(v.tenant_id === null || id(v.tenant_id)) || !id(v.code)) || !hex(value.revision) || typeof value.ready !== 'boolean' || value.ready !== (value.blockers.length === 0) || typeof value.reauth_required !== 'boolean' || !id(value.request_key) || (value.request_key as string).length < 32 || typeof value.receipt_token !== 'string' || !/^pdr1\.[A-Za-z0-9_.-]{20,2043}$/.test(value.receipt_token) || !Number.isSafeInteger(value.receipt_expires_in) || (value.receipt_expires_in as number) <= 0) throw bad();
  if (value.ready && (!value.tenants.length || value.tenants.some(v => v.action === 'blocked' || (v.action === 'erase_private' && v.classification !== 'private') || (v.action === 'leave_shared' && v.classification !== 'shared')))) throw bad();
  return value as unknown as DeletionPlan;
}
export function recoveryFor(connection: Connection, plan: DeletionPlan): DeletionRecovery {
  accountKey(connection);
  if (plan.user_id !== connection.session?.userId) throw bad();
  const {accessToken: _removed, ...session} = connection.session!;
  return {version: 1, target: {...connection, session}, requestKey: plan.request_key, planRevision: plan.revision, token: plan.receipt_token, phase: 'prepared', createdAt: Date.now()};
}
export function readRecovery(value: unknown): DeletionRecovery {
  if (!object(value) || value.version !== 1 || !object(value.target) || !id(value.requestKey) || (value.requestKey as string).length < 32 || !hex(value.planRevision) || typeof value.token !== 'string' || !/^pdr1\.[A-Za-z0-9_.-]{20,2043}$/.test(value.token) || !['prepared', 'uncertain', 'submitted'].includes(String(value.phase)) || typeof value.createdAt !== 'number' || !Number.isFinite(value.createdAt)) throw bad();
  const result = value as unknown as DeletionRecovery;
  accountKey(result.target);
  if (result.target.session?.accessToken || typeof result.target.identity !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(result.target.identity)) throw bad();
  return result;
}
export function deletionStatus(value: unknown, recovery: DeletionRecovery): DeletionStatus {
  if (object(value) && value.state === 'not_submitted' && value.code === 'not_submitted') return {state: 'not_submitted', code: 'not_submitted'};
  if (!object(value) || !/^[a-f0-9]{32}$/.test(String(value.id)) || value.user_id !== recovery.target.session?.userId || value.request_key !== recovery.requestKey || value.plan_revision !== recovery.planRevision || !((['awaiting_operator', 'frozen', 'waiting'].includes(String(value.state)) && waitingCodes.includes(String(value.code)) && value.data_erased === false) || (value.state === 'completed' && value.code === 'verified' && value.data_erased === true)) || !Array.isArray(value.tenants) || !value.tenants.length || !value.tenants.every(validScope) || value.tenants.some(v => v.action === 'blocked' || (v.action === 'erase_private' ? v.classification !== 'private' : v.classification !== 'shared')) || new Set(value.tenants.map(v => v.tenant_id)).size !== value.tenants.length || !Number.isSafeInteger(value.created_at) || !Number.isSafeInteger(value.updated_at) || (value.created_at as number) < 0 || (value.updated_at as number) < (value.created_at as number)) throw bad();
  return value as unknown as DeletionStatus;
}
export function reauthURL(value: unknown, connection: Connection): string {
  if (!object(value) || typeof value.authorize_url !== 'string') throw bad();
  const url = new URL(value.authorize_url), base = new URL(connectionEndpoint(connection));
  if (url.origin !== base.origin || url.pathname !== '/auth/account-deletion/reauth/start' || url.username || url.password || url.hash || [...url.searchParams.keys()].join(',') !== 'ticket' || !/^[A-Za-z0-9_-]{43}$/.test(url.searchParams.get('ticket') || '')) throw bad();
  return url.toString();
}
export class AccountDeletionClient {
  constructor(readonly connection: Connection, private fetcher: typeof fetch = fetch) {accountKey(connection);}
  private async request(path: string, body?: unknown, recovery?: DeletionRecovery) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const headers = recovery ? {Authorization: 'Bearer ' + recovery.token} : connectionHeaders(this.connection);
      const response = await this.fetcher(connectionEndpoint(this.connection, !!recovery) + DELETION_PATH + path, {method: body === undefined ? 'GET' : 'POST', headers: {...headers, ...(body === undefined ? {} : {'Content-Type': 'application/json'})}, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal, credentials: 'omit', redirect: 'error'});
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new ApiError(data?.code === 'reauth_required' ? '请重新验证身份后再确认注销。' : response.status === 409 ? '账户范围已改变或尚未明确，请刷新注销计划。' : response.status === 401 ? '账户验证已失效；已保存的注销凭证仍可查询进度。' : '服务暂时无法处理，请稍后重试。', response.status);
      }
      return await response.json();
    } catch (cause) {if (cause instanceof ApiError) throw cause; throw new ApiError('暂时无法确认注销状态。查询凭证已保留，请稍后刷新。', 0);}
    finally {clearTimeout(timer);}
  }
  async plan() {return deletionPlan(await this.request('plan'), this.connection);}
  async reauth(challenge: string, state: string) {return reauthURL(await this.request('reauth', {challenge, state}), this.connection);}
  async status(recovery: DeletionRecovery) {
    readRecovery(recovery);
    if (!sameAccount(recovery.target, this.connection)) throw bad();
    return deletionStatus(await this.request('status', undefined, recovery), recovery);
  }
  async submit(plan: DeletionPlan, save: (value: DeletionRecovery) => Promise<void>) {
    const recovery = recoveryFor(this.connection, plan);
    if (!plan.ready) throw new ApiError('账户范围尚未确认，暂不能提交注销。', 409);
    await save(recovery); // No HTTP mutation until the restricted recovery token is durable.
    try {
      const status = deletionStatus(await this.request('request', {request_key: recovery.requestKey, plan_revision: recovery.planRevision, receipt_token: recovery.token, confirm: 'DELETE'}), recovery);
      if (status.state === 'not_submitted') throw bad();
      await save({...recovery, phase: 'submitted'}).catch(() => {});
      return {status, recovery: {...recovery, phase: 'submitted'} as DeletionRecovery};
    } catch (cause) {
      // The pre-saved token survives even if this best-effort phase update fails.
      await save({...recovery, phase: 'uncertain'}).catch(() => {});
      throw cause;
    }
  }
}
