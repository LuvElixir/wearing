import {ApiError, Connection, connectionEndpoint, endpoint, NativeSession, Store} from './core';

export const AUTH_CALLBACK = 'pajio://auth';
export type Vault = {get(key: string): Promise<string | null>; put(key: string, value: string): Promise<void>; remove(key: string): Promise<void>};
const vaultKey = (session: NativeSession) => 'pajio.session.' + session.credentialId;

export type SignInEntry = 'account' | 'invite';
export function authorizationURL(address: string, challenge: string, state: string, entry: SignInEntry = 'account') {
  const origin = endpoint(address);
  if (!origin.startsWith('https://') || !/^[A-Za-z0-9_-]{43}$/.test(challenge) || !/^[A-Za-z0-9_-]{32,128}$/.test(state) || !['account', 'invite'].includes(entry)) throw new ApiError('登录信息不完整，请重新打开登录。', 422);
  const url = new URL('auth/mobile/start', origin); url.searchParams.set('challenge', challenge); url.searchParams.set('state', state);
  if (entry === 'invite') url.searchParams.set('entry', 'invite');
  return url.toString();
}
export function authorizationCode(result: string, state: string) {
  const url = new URL(result);
  if (url.protocol !== 'pajio:' || url.hostname !== 'auth' || url.pathname || url.username || url.password || url.port || url.hash || url.searchParams.getAll('state').length !== 1 || url.searchParams.get('state') !== state || url.searchParams.getAll('code').length !== 1 || !/^[A-Za-z0-9_-]{43}$/.test(url.searchParams.get('code') || '') || [...url.searchParams.keys()].some(key => !['code','state'].includes(key))) throw new ApiError('这次登录关联不匹配，请重新登录。', 401);
  return url.searchParams.get('code')!;
}
export function sessionReceipt(address: string, data: unknown, credentialId: string): Connection {
  if (!data || typeof data !== 'object') throw new ApiError('服务没有返回完整的登录信息。', 422);
  const receipt = data as Record<string, unknown>;
  if (receipt.token_type !== 'Bearer' || !['access_token','expires_at','user_id','tenant_id'].every(k => typeof receipt[k] === 'string')) throw new ApiError('服务没有返回完整的登录信息。', 422);
  const connection: Connection = {endpoint: endpoint(address), identity: 'daily', session: {accessToken: receipt.access_token as string, expiresAt: receipt.expires_at as string, userId: receipt.user_id as string, tenantId: receipt.tenant_id as string, credentialId}};
  connectionEndpoint(connection);
  if (Date.parse(connection.session!.expiresAt) > Date.now() + 28860_000) throw new ApiError('登录有效期不正确，请重新登录。', 422);
  return connection;
}
/** Never put the bearer in SQLite, logs, route params, or WebView JavaScript. */
export async function saveConnection(connection: Connection, storage: Pick<Store,'put'>, vault: Vault) {
  connectionEndpoint(connection, true);
  if (!connection.session) {await storage.put('connection', connection); return;}
  const {accessToken, ...metadata} = connection.session;
  if (accessToken) await vault.put(vaultKey(connection.session), accessToken);
  await storage.put('connection', {...connection, session: metadata});
}
export async function loadConnection(storage: Pick<Store,'get'>, vault: Vault, select: (stored: Connection | null) => Connection | null = stored => stored): Promise<Connection | null> {
  // Apply the build's origin policy before retrieving any bearer from the vault.
  const connection = select(await storage.get<Connection>('connection'));
  if (!connection?.session) return connection;
  connectionEndpoint(connection, true);
  const accessToken = await vault.get(vaultKey(connection.session));
  return {...connection, session: {...connection.session, accessToken: accessToken || undefined}};
}
export async function forgetSession(connection: Connection, storage: Pick<Store,'put'>, vault: Vault) {
  if (!connection.session) return connection;
  await vault.remove(vaultKey(connection.session));
  const {accessToken: _discarded, ...metadata} = connection.session;
  const signedOut = {...connection, session: metadata};
  await storage.put('connection', signedOut);
  return signedOut;
}

export type PendingAuthorization = {address: string; verifier: string; state: string; createdAt: number; expected?: {userId: string; tenantId: string; identity: string; credentialId: string}};
const pendingKey = 'pajio.authorization.pending';
/** Serialized across the browser callback and Router, with a private, restart-safe PKCE record. */
export class AuthorizationFlow {
  private queue: Promise<unknown> = Promise.resolve();
  private flight?: {url: string; result: Promise<Connection>};
  constructor(private vault: Vault, private exchange: (pending: PendingAuthorization, code: string) => Promise<Connection>, private persist: (connection: Connection) => Promise<void>, private clock = Date.now) {}
  private serial<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.queue.then(operation); this.queue = result.catch(() => undefined); return result;
  }
  begin(pending: PendingAuthorization) {
    return this.serial(async () => {
      if (!/^[A-Za-z0-9_-]{43,128}$/.test(pending.verifier) || !/^[A-Za-z0-9_-]{32,128}$/.test(pending.state) || !endpoint(pending.address).startsWith('https://')) throw new ApiError('登录信息不完整，请重试。',422);
      this.flight = undefined;
      await this.vault.put(pendingKey, JSON.stringify({...pending, address: endpoint(pending.address), createdAt: this.clock()}));
    });
  }
  complete(url: string): Promise<Connection> {
    if (this.flight?.url === url) return this.flight.result;
    const result = this.serial(async () => {
      const raw = await this.vault.get(pendingKey);
      if (!raw) throw new ApiError('这次登录已结束，请重新登录。',401);
      const pending = JSON.parse(raw) as PendingAuthorization;
      if (!Number.isFinite(pending.createdAt) || this.clock() - pending.createdAt > 600_000 || this.clock() < pending.createdAt) {await this.vault.remove(pendingKey); throw new ApiError('登录已超时，请重新登录。',401);}
      // An unrelated deep link must not destroy the legitimate pending login.
      const code = authorizationCode(url, pending.state);
      try {
        const connection = await this.exchange(pending, code);
        await this.persist(connection);
        return connection;
      } finally {await this.vault.remove(pendingKey);}
    });
    this.flight = {url, result};
    result.catch(() => {if (this.flight?.result === result) this.flight = undefined;});
    return result;
  }
  cancel(state?: string) {
    return this.serial(async () => {
      const raw = await this.vault.get(pendingKey);
      if (!state || (raw && (JSON.parse(raw) as PendingAuthorization).state === state)) {await this.vault.remove(pendingKey); this.flight = undefined;}
    });
  }
}
