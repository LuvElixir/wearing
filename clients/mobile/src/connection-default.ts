import type {Connection} from './core';

export const PUBLIC_PAJIO_ENDPOINT = 'https://pajio.luckyloading.com/';

/** Defaults apply only to a fresh installation; saved identities and sessions win. */
export function initialConnection(stored: Connection | null, platform: string, webOrigin?: string): Connection {
  if (stored) return {...stored};
  if (platform === 'web') {
    if (!webOrigin) throw new Error('网页预览地址暂时无法读取。');
    return {endpoint: webOrigin.replace(/\/$/, '') + '/', identity: 'daily'};
  }
  return {endpoint: PUBLIC_PAJIO_ENDPOINT, identity: 'daily'};
}
