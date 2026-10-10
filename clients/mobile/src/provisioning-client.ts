import {ApiError, connectionHeaders, type Connection} from './core';
import {isPublicConnection, PUBLIC_PAJIO_ENDPOINT} from './connection-default';

export type ProvisioningMemberState = 'pending' | 'preparing' | 'ready' | 'needs_review';
export type ProvisioningSnapshot = {
  state: 'reserved' | 'preparing' | 'installing' | 'pairing' | 'ready' | 'needs_review';
  members: Record<'core' | 'linux' | 'android', {state: ProvisioningMemberState}>;
  updated_at: number; reason: string | null; retry_after: number;
};
export class ProvisioningError extends ApiError {
  constructor(public code: 'unavailable' | 'invalid' | 'expired' | 'unconfirmed', status = 0) {
    super(({unavailable: '还没有查询到你的环境交付记录，请稍后刷新或联系邀请人。', invalid: '准备状态暂时无法确认，请刷新核对。', expired: '登录已失效，请重新登录。本机记录会保留。', unconfirmed: '暂时无法连接，正在保留上次核对结果。'} as const)[code], status);
  }
}
export function provisioningSnapshot(value: unknown): ProvisioningSnapshot {
  const data = value as ProvisioningSnapshot | null;
  const memberStates = ['pending', 'preparing', 'ready', 'needs_review'];
  if (!data || !['reserved','preparing','installing','pairing','ready','needs_review'].includes(data.state) || !data.members ||
    ['core','linux','android'].some(key => !memberStates.includes(data.members[key as keyof typeof data.members]?.state)) ||
    !Number.isSafeInteger(data.updated_at) || data.updated_at <= 0 || !Number.isSafeInteger(data.retry_after) || data.retry_after < 3 || data.retry_after > 30 ||
    (data.reason !== null && (typeof data.reason !== 'string' || !/^[a-z][a-z0-9_]{0,63}$/.test(data.reason))) ||
    (data.state === 'ready' && Object.values(data.members).some(member => member.state !== 'ready'))) throw new ProvisioningError('invalid');
  return {state:data.state, members:{core:{state:data.members.core.state},linux:{state:data.members.linux.state},android:{state:data.members.android.state}},updated_at:data.updated_at,reason:data.reason,retry_after:data.retry_after};
}
export const needsProvisioning = (connection: Connection | null): connection is Connection => !!connection && isPublicConnection(connection) && !!connection.session;
/** In-memory grant bound to this exact activation; never persisted or derived from device lists. */
export class ProvisioningGate {
  private active: Connection | null = null;
  private approved = false;
  activate(connection: Connection) {this.active = connection; this.approved = false;}
  accept(connection: Connection, snapshot: ProvisioningSnapshot) {
    if (this.active !== connection || provisioningSnapshot(snapshot).state !== 'ready') return false;
    this.approved = true; return true;
  }
  allows(connection: Connection) {return !needsProvisioning(connection) || (this.active === connection && this.approved);}
}
export async function readProvisioning(connection: Connection, signal: AbortSignal, fetcher: typeof fetch = fetch): Promise<ProvisioningSnapshot> {
  if (!needsProvisioning(connection)) throw new ProvisioningError('invalid');
  const controller = new AbortController(), abort = () => controller.abort();
  if (signal.aborted) controller.abort();
  signal.addEventListener('abort', abort);
  const timer = setTimeout(abort, 15000);
  try {
    if (controller.signal.aborted) throw new ProvisioningError('unconfirmed');
    const response = await fetcher(new URL('/auth/provisioning', PUBLIC_PAJIO_ENDPOINT).toString(), {method:'GET', headers:connectionHeaders(connection), credentials:'omit', redirect:'error', cache:'no-store', signal:controller.signal});
    if (controller.signal.aborted) throw new ProvisioningError('unconfirmed');
    if (response.status === 401) throw new ProvisioningError('expired',401);
    if (response.status === 404) throw new ProvisioningError('unavailable',404);
    if (!response.ok) throw new ProvisioningError('unconfirmed',response.status);
    const raw = await response.text();
    if (controller.signal.aborted) throw new ProvisioningError('unconfirmed');
    if (raw.length > 8192) throw new ProvisioningError('invalid');
    return provisioningSnapshot(JSON.parse(raw));
  } catch (error) {
    if (error instanceof ProvisioningError) throw error;
    if (error instanceof ApiError && error.status === 401) throw new ProvisioningError('expired',401);
    throw new ProvisioningError('unconfirmed');
  } finally {clearTimeout(timer); signal.removeEventListener('abort',abort);}
}
