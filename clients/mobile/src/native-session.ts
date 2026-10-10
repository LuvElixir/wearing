import {clearChatImportPrivateDrafts} from './chat-import-native';
import {disableInstallationNotifications, notificationProject} from './NativeNotificationsPanel';
import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import * as WebBrowser from 'expo-web-browser';
import {Platform} from 'react-native';
import {ApiError, Connection, connectionEndpoint} from './core';
import {AccountDeletionClient} from './account-deletion-client';
import {storage, withNativeState} from './storage';
import {commitNativeConnection} from './native-connection-commit';
import {serviceFetch} from './transport';
import {clearDiagnosticErrors} from './diagnostics-client';
import {assertNativeServiceAddress, initialConnection, PUBLIC_PAJIO_ENDPOINT} from './connection-default';
import {AUTH_CALLBACK, AuthorizationFlow, authorizationURL, forgetSession, loadConnection, saveConnection, sessionReceipt, type SignInEntry, Vault} from './session-protocol';
import {EnrollmentFlow} from './enrollment-client';
import {base64urlBytes, EnrollmentError} from './enrollment-model';

const options = {keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY};
const vault: Vault = {get: key => SecureStore.getItemAsync(key, options), put: (key,value) => SecureStore.setItemAsync(key,value,options), remove: key => SecureStore.deleteItemAsync(key,options)};
let authGeneration = 0;
export const createNativeEnrollment = () => {
  return new EnrollmentFlow({vault, fetcher: serviceFetch,
  proof: async () => {
    const bytes = await Crypto.getRandomBytesAsync(32);
    const verifier = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    const state = Array.from(await Crypto.getRandomBytesAsync(24), byte => byte.toString(16).padStart(2, '0')).join('');
    const base64url = (value: string) => value.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/,'');
    const challenge = base64url(await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, verifier, {encoding: Crypto.CryptoEncoding.BASE64}));
    // An independently random recovery proof; not derived from the PKCE verifier.
    const receipt = base64urlBytes(await Crypto.getRandomBytesAsync(32));
    return {operation_id: Crypto.randomUUID().replace(/-/g, ''), receipt, verifier, challenge, state};
  },
  finish: async (pending, handoff, isCurrent) => {
    const generation = authGeneration;
    if (browserOpen || !isCurrent()) throw new EnrollmentError('enrollment_inactive');
    assertNativeServiceAddress(pending.origin);
    const response = await boundedFetch(new URL('/auth/mobile/exchange', pending.origin).toString(), {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code: handoff.code, verifier: pending.verifier, state: pending.state})});
    if (!response.ok) throw new EnrollmentError('enrollment_unconfirmed');
    const next = sessionReceipt(pending.origin, await response.json(), Crypto.randomUUID().replace(/-/g,''));
    if (!isCurrent() || generation !== authGeneration) throw new EnrollmentError('enrollment_inactive');
    await persistNativeConnection(next, () => isCurrent() && generation === authGeneration);
    return next;
  },
});};
export const restoreNativeConnection = () => loadConnection(storage, vault, stored => Platform.OS === 'web' ? stored : initialConnection(stored, Platform.OS));
export const persistNativeConnection = (connection: Connection, isCurrent: () => boolean = () => true) => {
  if (Platform.OS === 'web') return saveConnection(connection, storage, vault);
  assertNativeServiceAddress(connection.endpoint);
  return withNativeState(db => commitNativeConnection(db, vault, connection, isCurrent));
};
export const clearNativeSession = async (connection: Connection) => {
  await clearChatImportPrivateDrafts(connection);
  const result = await forgetSession(connection, storage, vault);
  clearDiagnosticErrors(connection);
  return result;
};

async function boundedFetch(url: string, init: RequestInit) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try {return await serviceFetch(url, {...init, redirect: 'error', credentials: 'omit', signal: controller.signal});}
  catch {throw new ApiError('暂时连不上登录服务，请检查网络后重试。', 0);}
  finally {clearTimeout(timer);}
}
const authorization = new AuthorizationFlow(vault, async (pending, code) => {
  assertNativeServiceAddress(pending.address);
  const response = await boundedFetch(new URL('/auth/mobile/exchange', pending.address).toString(), {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,verifier:pending.verifier,state:pending.state})});
  if (!response.ok) throw new ApiError(response.status === 403 ? '此账号尚未加入 Pajio 试用，请使用收到邀请的账号。' : '这次登录没有完成，请重新登录。', response.status);
  const next = sessionReceipt(pending.address, await response.json(), Crypto.randomUUID().replace(/-/g,''));
  if (pending.expected) {
    const previous = await storage.get<Connection>('connection');
    if (next.session?.userId !== pending.expected.userId || next.session?.tenantId !== pending.expected.tenantId || previous?.session?.userId !== pending.expected.userId || previous.session.tenantId !== pending.expected.tenantId || previous.session.credentialId !== pending.expected.credentialId) throw new ApiError('账户已切换，已停止这次身份验证。', 409);
    next.identity = pending.expected.identity;
  }
  return next;
}, persistNativeConnection);
export const completeNativeSignIn = (url: string) => authorization.complete(url);
let browserOpen = false;
export async function signIn(entry: SignInEntry = 'account'): Promise<Connection | null> {return openSignIn(PUBLIC_PAJIO_ENDPOINT, undefined, entry);}
export async function reauthenticateNativeForDeletion(connection: Connection): Promise<Connection | null> {
  if (!connection.session) throw new ApiError('请先登录云端账户。', 401);
  return openSignIn(connectionEndpoint(connection), connection);
}
async function openSignIn(address: string, expectedConnection?: Connection, entry: SignInEntry = 'account'): Promise<Connection | null> {
  if (Platform.OS === 'web') throw new Error('账户登录请在 Pajio App 中打开；当前为开发预览。');
  assertNativeServiceAddress(address);
  if (browserOpen) throw new Error('登录窗口已经打开，请先完成这次登录。');
  authGeneration += 1;
  browserOpen = true;
  try {
    const verifier = Array.from(await Crypto.getRandomBytesAsync(32), b => b.toString(16).padStart(2,'0')).join('');
    const state = Array.from(await Crypto.getRandomBytesAsync(24), b => b.toString(16).padStart(2,'0')).join('');
    const digest = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, verifier, {encoding: Crypto.CryptoEncoding.BASE64});
    const challenge = digest.replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
    const url = expectedConnection ? await new AccountDeletionClient(expectedConnection, serviceFetch).reauth(challenge, state) : authorizationURL(address, challenge, state, entry);
    const session = expectedConnection?.session;
    await authorization.begin({address,verifier,state,createdAt:Date.now(), ...(session ? {expected: {userId: session.userId, tenantId: session.tenantId, credentialId: session.credentialId, identity: expectedConnection!.identity}} : {})});
    const result = await WebBrowser.openAuthSessionAsync(url, AUTH_CALLBACK);
    if (result.type !== 'success') {await authorization.cancel(state); return null;}
    return await completeNativeSignIn(result.url);
  } finally {browserOpen = false;}
}
export async function signOut(connection: Connection) {
  authGeneration += 1;
  await authorization.cancel();
  if (!connection.session?.accessToken) return clearNativeSession(connection);
  if(notificationProject() && Date.parse(connection.session.expiresAt)>Date.now()) await disableInstallationNotifications(connection);
  const response = await boundedFetch(connectionEndpoint(connection, true) + 'auth/logout', {method:'POST',headers:{Authorization:'Bearer '+connection.session.accessToken}});
  if (!response.ok && response.status !== 401 && response.status !== 403) throw new ApiError('服务尚未确认退出，请重试。本机账户未切换。',response.status);
  return clearNativeSession(connection);
}
