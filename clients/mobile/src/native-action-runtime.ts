import {AppState, Platform} from 'react-native';
import {requireOptionalNativeModule} from 'expo';
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import {scopeOf, type Connection} from './core';
import {serviceFetch} from './transport';
import {withNativeState} from './storage';
import {registerAccountCredential} from './account-cleanup-state';
import {withRecordDraft} from './record-editor';
import {NativeActionClient} from './native-action-client';
import {NativeActionDriver, type ActionCalendar, type ActionLocation} from './native-action-driver';
import {hex, type NativeCredential} from './native-action-model';

const listeners = new Set<() => void>();
export const nativeActionsChanged = () => {for (const listener of listeners) listener();};
export const observeNativeActions = (listener: () => void) => {listeners.add(listener); return () => {listeners.delete(listener);};};
export const nativeActionNonce = () => Crypto.randomUUID().replaceAll('-','');
export function createNativeActionDriver(active: () => boolean): NativeActionDriver | null {
  if (Platform.OS !== 'ios') return null;
  // Load only modules actually linked into this installed binary.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const calendar = requireOptionalNativeModule('ExpoCalendar') ? require('expo-calendar/legacy') as ActionCalendar : null;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const location = requireOptionalNativeModule('ExpoLocation') ? require('expo-location') as ActionLocation : null;
  return new NativeActionDriver(calendar,location,() => active() && AppState.currentState === 'active',Date.now,
    value=>Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,value));
}
export async function nativeActionClient(connection: Connection, create = false): Promise<NativeActionClient | null> {
  if (Platform.OS !== 'ios') return null;
  const key = 'pajio.native.' + await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, scopeOf(connection));
  return withRecordDraft(key, () => withNativeState(async db => {
    await registerAccountCredential(db, connection);
    const saved = await SecureStore.getItemAsync(key), options = {keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY};
    let credential: NativeCredential;
    if (saved) {
      credential = JSON.parse(saved) as NativeCredential;
      if (!hex(credential.installation_id,32) || !hex(credential.secret,64)) throw new Error('手机能力凭据无法读取，请先检查安装版本。');
    } else {
      if (!create) return null;
      credential = {installation_id:nativeActionNonce(),secret:Array.from(await Crypto.getRandomBytesAsync(32), b => b.toString(16).padStart(2,'0')).join('')};
      await SecureStore.setItemAsync(key,JSON.stringify(credential),options);
    }
    return new NativeActionClient(connection,credential,serviceFetch);
  }));
}
