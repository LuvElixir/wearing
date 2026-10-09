import type {Connection} from './core';
import type {AccountCleanupReport} from './account-cleanup-native';
export type {AccountCleanupReport} from './account-cleanup-native';
export async function isDeletedAccountLocal(_connection: Connection): Promise<boolean> {return false;}
export async function clearDeletedAccountLocalData(_connection: Connection, _options?: {recordingUris: string[]}): Promise<AccountCleanupReport> {throw new Error('请在 Pajio App 中管理账户注销。');}
