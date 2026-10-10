import {ApiError, connectionEndpoint, endpoint, type Connection} from './core';
import {developmentConnectionsEnabled} from './development-access';

export const PUBLIC_PAJIO_ENDPOINT = 'https://pajio.luckyloading.com/';

export function isPublicConnection(connection: Connection): boolean {
  try {return !connection.development && endpoint(connection.endpoint) === PUBLIC_PAJIO_ENDPOINT;}
  catch {return false;}
}

export function assertNativeServiceAddress(address: string): void {
  if (!developmentConnectionsEnabled() && endpoint(address) !== PUBLIC_PAJIO_ENDPOINT) throw new ApiError('请从 Pajio 重新登录。', 401);
}

export function requiresNativeSignIn(connection: Connection | null, platform: string): boolean {
  if (platform === 'web') return false;
  if (!connection) return true;
  if (developmentConnectionsEnabled() && !isPublicConnection(connection)) return false;
  if (!isPublicConnection(connection) || !connection.session) return true;
  try {connectionEndpoint(connection); return false;} catch {return true;}
}

/** Never rebind a saved credential or queued draft to a different service. */
export function initialConnection(stored: Connection | null, platform: string, webOrigin?: string): Connection {
  if (platform === 'web') {
    if (stored) return {...stored};
    if (!webOrigin) throw new Error('网页预览地址暂时无法读取。');
    return {endpoint: webOrigin.replace(/\/$/, '') + '/', identity: 'daily'};
  }
  if (stored && (developmentConnectionsEnabled() || isPublicConnection(stored))) return {...stored};
  return {endpoint: PUBLIC_PAJIO_ENDPOINT, identity: 'daily'};
}
