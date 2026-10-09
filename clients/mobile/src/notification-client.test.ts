import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError, type Connection, type Store} from './core';
import {NotificationClient, notificationInstallation, notificationTarget, providerMessage, type NotificationStatus} from './notification-client';
import {notificationPermissionGranted, registerNativeNotifications, type NativeNotificationApi} from './notification-native';
const project = '12345678-abcd-1234-abcd-123456789abc', install = 'synthetic-phone-001', token = 'ExpoPushToken[syntheticToken12345]';
const connection: Connection = {endpoint: 'https://notification-tests.invalid', identity: 'daily'};
const target = {v: 1 as const, type: 'pajio.task' as const, server_id: 'a'.repeat(32), event_key: 'b'.repeat(64), task_id: 'task_123', identity_id: 'daily'};
const status = (patch: Partial<NotificationStatus> = {}): NotificationStatus => ({identity_id: 'daily', installation_id: install, server_id: target.server_id, configured: true,
  project_id: project, enabled: true, reason: null, provider_status: 'unverified', provider_error: null, counts: {}, ...patch});
const bootstrap = {version: '0.2.0', token: 'csrf-test', identities: [{id: 'daily'}]};
const response = (data: unknown, code = 200) => new Response(JSON.stringify(data), {status: code});
type Call = {url: URL; method: string; headers: Headers; body: unknown; redirect?: RequestRedirect};
function harness(replies: (() => Response | Promise<Response>)[], c = connection) {
  const calls: Call[] = [];
  const api = new NotificationClient(c, install, (async (input, init = {}) => {
    calls.push({url: new URL(String(input)), method: init.method || 'GET', headers: new Headers(init.headers), body: init.body ? JSON.parse(String(init.body)) : null, redirect: init.redirect});
    const reply = replies.shift(); assert.ok(reply, 'unexpected request'); return reply();
  }) as typeof fetch); return {api, calls};
}
function native(options: {granted?: boolean; canAsk?: boolean; onToken?: () => void} = {}) {
  const calls: string[] = [], permission = {granted: options.granted ?? true, canAskAgain: options.canAsk ?? true, status: 'granted', expires: 'never'};
  const api = {getPermissionsAsync: async () => {calls.push('read'); return permission;}, requestPermissionsAsync: async () => {calls.push('ask'); return {...permission, granted: true};},
    setNotificationChannelAsync: async () => {calls.push('channel'); return null;}, getExpoPushTokenAsync: async () => {calls.push('token'); options.onToken?.(); return {type: 'expo', data: token};}} as unknown as NativeNotificationApi;
  return {api, calls};
}
test('payload keeps fixed identifiers, discards arbitrary URLs, rejects malformed routing', () => {
  assert.deepEqual(notificationTarget({...target, url: 'https://evil.invalid'}), target);
  for (const patch of [{v: 2}, {type: 'other'}, {identity_id: '../daily'}, {task_id: ''}, {server_id: 'bad'}, {event_key: 'a'}]) assert.equal(notificationTarget({...target, ...patch}), null);
});
test('installation ID survives concurrent callers and failed persistence never returns an ID', async () => {
  const values = new Map<string, unknown>(); let generated = 0;
  const store: Pick<Store, 'get' | 'put'> = {get: async <T>(key: string) => (values.get(key) as T) || null, put: async (key, value) => {values.set(key, value);}};
  const ids = await Promise.all([notificationInstallation(store, () => {generated++; return install;}), notificationInstallation(store, () => {generated++; return install + 'x';})]);
  assert.deepEqual(ids, [install, install]); assert.equal(generated, 1);
  await assert.rejects(notificationInstallation({get: async () => null, put: async () => {throw Error('disk');}}, () => install), /disk/);
  assert.equal(await notificationInstallation(store, () => 'never'), install);
});
test('register and disable are exact identity-scoped mutations with verified receipts', async () => {
  const {api, calls} = harness([() => response(bootstrap), () => response(status()), () => response(status({enabled: false}))]);
  assert.equal((await api.register(token, project, 'ios')).enabled, true); assert.equal((await api.disable()).enabled, false);
  assert.equal(calls[1].url.pathname, '/api/notifications/register'); assert.equal(calls[1].method, 'POST');
  assert.deepEqual(calls[1].body, {installation_id: install, expo_push_token: token, project_id: project, platform: 'ios'});
  for (const call of calls) {assert.equal(call.headers.get('X-Wearing-Identity'), 'daily'); assert.equal(call.redirect, 'error');}
  assert.equal(calls[1].headers.get('X-Wearing-Token'), 'csrf-test');
});
test('one CSRF refresh is allowed; bootstrap must contain current identity', async () => {
  const {api, calls} = harness([() => response(bootstrap), () => response({}, 403), () => response({...bootstrap, token: 'fresh'}), () => response(status())]);
  await api.register(token, project, 'android'); assert.equal(calls.length, 4); assert.equal(calls[3].headers.get('X-Wearing-Token'), 'fresh');
  const bad = harness([() => response({...bootstrap, identities: [{id: 'work'}]})]);
  await assert.rejects(bad.api.register(token, project, 'ios'), (e: unknown) => e instanceof ApiError && e.status === 422); assert.equal(bad.calls.length, 1);
});
test('malformed success and network uncertainty are not reported as enabled or retried', async () => {
  const wrong = harness([() => response(bootstrap), () => response(status({enabled: false}))]);
  await assert.rejects(wrong.api.register(token, project, 'ios'), (e: unknown) => e instanceof ApiError && e.status === 422);
  const offline = harness([() => response(bootstrap), () => {throw Error('private upstream trace');}]);
  await assert.rejects(offline.api.register(token, project, 'ios'), /没有收到/); assert.equal(offline.calls.length, 2);
});
test('bearer and identity are fixed to constructor snapshot', async () => {
  const c: Connection = {...connection, session: {accessToken: 's'.repeat(64), expiresAt: new Date(Date.now() + 60000).toISOString(), userId: 'user_' + 'a'.repeat(32), tenantId: 't', credentialId: 'c'.repeat(32)}};
  const h = harness([() => response(status())], c); c.identity = 'work'; c.session!.accessToken = 'changed';
  await h.api.status(); assert.equal(h.calls[0].headers.get('Authorization'), 'Bearer ' + 's'.repeat(64)); assert.equal(h.calls[0].headers.get('X-Wearing-Identity'), 'daily');
});
test('tap resolution verifies identity, server, task and event before navigation', async () => {
  const h = harness([() => response({...target, kind: 'approval'})]);
  assert.deepEqual(await h.api.resolve(target), {type: 'task', taskId: target.task_id, identityId: 'daily', kind: 'approval'});
  await assert.rejects(h.api.resolve({...target, identity_id: 'work'}), /切换/); assert.equal(h.calls.length, 1);
  const wrong = harness([() => response({...target, kind: 'result', server_id: 'c'.repeat(32)})]); await assert.rejects(wrong.api.resolve(target), /回执/);
});
test('permission request requires matching server and EAS project', async () => {
  const n = native(), h = harness([() => response(status({configured: false}))]);
  await assert.rejects(registerNativeNotifications(n.api, h.api, project, 'ios', true), /尚未准备/); assert.deepEqual(n.calls, []);
  await assert.rejects(registerNativeNotifications(n.api, h.api, null, 'ios', true), /安装包/); assert.deepEqual(n.calls, []);
});
test('Android channel precedes permission prompt, then native token is registered', async () => {
  const n = native({granted: false}), h = harness([() => response(status({enabled: false})), () => response(bootstrap), () => response(status())]);
  await registerNativeNotifications(n.api, h.api, project, 'android', true); assert.deepEqual(n.calls, ['channel', 'read', 'ask', 'token']); assert.equal(h.calls[2].method, 'POST');
});
test('background refresh cannot silently opt in an installation', async () => {
  const n = native(), h = harness([() => response(status({enabled: false, configured: false}))]);
  assert.equal((await registerNativeNotifications(n.api, h.api, project, 'ios', false)).enabled, false); assert.deepEqual(n.calls, []);
});
test('OS permission revocation disables token without asking again', async () => {
  const n = native({granted: false, canAsk: false}), h = harness([() => response(status()), () => response(bootstrap), () => response(status({enabled: false}))]);
  assert.equal((await registerNativeNotifications(n.api, h.api, project, 'ios', false)).enabled, false);
  assert.deepEqual(n.calls, ['read']); assert.equal(h.calls[2].url.pathname, '/api/notifications/disable');
});
test('identity switch while native token is fetching prevents old registration', async () => {
  let active = true; const n = native({onToken: () => {active = false;}}), h = harness([() => response(status())]);
  await assert.rejects(registerNativeNotifications(n.api, h.api, project, 'ios', true, () => active), /身份已切换/); assert.equal(h.calls.length, 1);
});
test('iOS provisional is usable; provider wording never claims device delivery', () => {
  assert.equal(notificationPermissionGranted({granted: false, ios: {status: 3}}), true); assert.equal(notificationPermissionGranted({granted: false, ios: {status: 1}}), false);
  assert.match(providerMessage(status({provider_status: 'provider_accepted'})), /仍受手机通知设置/); assert.match(providerMessage(status()), /首次送达尚未验证/);
  assert.match(providerMessage(status({provider_error: 'InvalidCredentials'})), /凭据需要修复/);
});
