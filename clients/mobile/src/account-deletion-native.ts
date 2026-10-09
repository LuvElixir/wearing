import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import type {Connection} from './core';
import {isDeletedAccountLocal} from './account-cleanup-native';
import {deletionDisposition} from './account-deletion-recovery';
import {serviceFetch} from './transport';
import {AccountDeletionClient, accountKey, readRecovery, type DeletionRecovery} from './account-deletion-client';
const options = {keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY};
const lastKey = 'pajio.deletion.last.v1';
const keyFor = async (connection: Connection) => 'pajio.deletion.' + await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, accountKey(connection));
export async function saveDeletionRecovery(value: DeletionRecovery) {
  readRecovery(value);
  const key = await keyFor(value.target);
  await SecureStore.setItemAsync(key, JSON.stringify(value), options);
  await SecureStore.setItemAsync(lastKey, key, options);
}
export async function loadDeletionRecovery(connection: Connection | null): Promise<DeletionRecovery | null> {
  const key = connection?.session ? await keyFor(connection) : await SecureStore.getItemAsync(lastKey, options);
  if (!key) return null;
  if (!/^pajio\.deletion\.[a-f0-9]{64}$/.test(key)) throw new Error('注销查询凭证暂时无法读取，请稍后重试。');
  const raw = await SecureStore.getItemAsync(key, options);
  if (!raw) return null;
  const recovery = readRecovery(JSON.parse(raw));
  if (await keyFor(recovery.target) !== key) throw new Error('注销查询凭证与账户不一致。');
  return recovery;
}

export const startupDeletionDisposition = (connection: Connection) => deletionDisposition(connection, {
  fenced: isDeletedAccountLocal,
  load: loadDeletionRecovery,
  status: recovery => new AccountDeletionClient(recovery.target, serviceFetch).status(recovery),
});
