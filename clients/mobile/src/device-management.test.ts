import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError, type Connection} from './core';
import {DeviceManagementApi, approvalDescription, canDecide, deviceStatus, parseCloudDevice, parseDeviceOffer, selectedDeviceOffer,
  type CloudDevice, type DeviceApproval, type DeviceOffer, type DeviceReview, type PairingIntent, type PermissionIntent} from './device-management';

const connection: Connection = {endpoint: 'https://device-tests.invalid', identity: 'test_identity'};
const manifest: DeviceOffer = {schema_version: 1, resources: [{resource_id: 'computer_test', name: '合成电脑', kind: 'computer', methods: ['computer.input', 'computer.observe', 'computer.status']}]};
const device = (patch: Partial<CloudDevice> = {}): CloudDevice => ({...manifest.resources[0], connector_id: 'connector_' + 'a'.repeat(32),
  connected: true, online: true, paused: false, control_pending: false, control_generation: 3,
  permission_revision: 'b'.repeat(64), policy_revision: 1, needs_review: false, last_seen_at: '2026-10-07T00:00:00Z', ...patch});
const approval = (patch: Partial<DeviceApproval> = {}): DeviceApproval => ({approval_id: 'proposal_test', resource_id: 'computer_test', revision: 'c'.repeat(64),
  action: {app: 'TextEdit', action: 'set_value', element_label: '文稿', value: '合成内容'}, reason: '填写用户的文稿', state: 'awaiting_user', can_decide: true,
  task_eligible: false, expires_at: new Date(Date.now() + 60000).toISOString(), ...patch});
const review: DeviceReview = {command_id: 'command_test', resource_id: 'computer_test', revision: 'd'.repeat(64), name: '合成电脑', method: 'computer.input', state: 'unknown', can_review: true};
const intent: PairingIntent = {request_id: 'e'.repeat(32), offer: manifest, createdAt: 0};
const permission: PermissionIntent = {request_id: 'f'.repeat(32), resource_id: 'computer_test', revision: 'b'.repeat(64), mode: 'observe', delivery: 'connector'};
const bundle = (patch: Record<string, unknown> = {}) => ({...manifest, schema_version: undefined, identity_id: connection.identity, tenant_id: 'tenant_synthetic',
  endpoint: 'https://synthetic-relay.invalid', ca_pem: 'synthetic-test-certificate', code: 'a'.repeat(43), connector_id: 'connector_' + 'a'.repeat(32), pairing_generation: 1, policy_revision: 1, ...patch});
const bootstrap = (token = 'csrf-synthetic', identity = connection.identity, deployment = 'cloud') => ({version: '0.2.0', deployment, token, identities: [{id: identity}]});
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers: {'Content-Type': 'application/json'}});
type Call = {url: URL; method: string; headers: Headers; body: unknown; redirect: RequestRedirect | undefined};
function harness(replies: (() => Response | Promise<Response>)[], selected = connection) {
  const calls: Call[] = [];
  const api = new DeviceManagementApi(selected, (async (input, init = {}) => {
    calls.push({url: new URL(String(input)), method: init.method || 'GET', headers: new Headers(init.headers),
      body: typeof init.body === 'string' ? JSON.parse(init.body) : null, redirect: init.redirect});
    const reply = replies.shift(); assert.ok(reply, 'unexpected request'); return reply();
  }) as typeof fetch);
  return {api, calls};
}
const status = (expected: number) => (cause: unknown) => cause instanceof ApiError && cause.status === expected;

test('manifest import strips resource metadata and rejects executable top-level data, duplicate resources and empty scopes', () => {
  const parsed = parseDeviceOffer({...manifest, resources: [{...manifest.resources[0], script: 'never execute this', methods: ['computer.status', 'computer.status']}]});
  assert.deepEqual(parsed.resources[0], {...manifest.resources[0], methods: ['computer.status']});
  assert.throws(() => parseDeviceOffer({...manifest, endpoint: 'https://evil.invalid'}), status(422));
  assert.throws(() => parseDeviceOffer({...manifest, resources: [...manifest.resources, ...manifest.resources]}), status(422));
  assert.throws(() => parseDeviceOffer({...manifest, resources: [{...manifest.resources[0], methods: []}]}), status(422));
});

test('selecting devices defaults to observations and can grant only scopes present in the inspected offer', () => {
  const rows = [{...manifest.resources[0], already_paired: false}, {resource_id: 'phone_test', name: '合成手机', kind: 'android' as const,
    methods: ['phone.mobile_take_screenshot', 'phone.mobile_click_on_screen_at_coordinates'], already_paired: false}];
  assert.deepEqual(selectedDeviceOffer(rows, ['computer_test', 'phone_test'], []).resources.map(r => r.methods), [
    ['computer.observe', 'computer.status'], ['phone.mobile_take_screenshot'],
  ]);
  assert.deepEqual(selectedDeviceOffer(rows, ['computer_test'], ['computer_test']).resources, manifest.resources);
  assert.throws(() => selectedDeviceOffer([{...rows[0], already_paired: true}], ['computer_test'], []), status(409));
  assert.throws(() => selectedDeviceOffer(rows, ['another_device'], []), status(409));
});

test('cloud device state never equates a cloud acknowledgement or a live connector with a ready device', () => {
  assert.equal(deviceStatus(device({paused: true, control_pending: true})), '暂停已送达云端，等待设备确认');
  assert.equal(deviceStatus(device({control_pending: true})), '等待设备确认恢复');
  assert.equal(deviceStatus(device({online: false, connected: true})), '连接器在线 · 设备未就绪');
  assert.equal(deviceStatus(device({needs_review: true})), '旧动作需要核对');
  assert.equal(deviceStatus(device({methods: ['computer.observe']})), '在线 · 仅观察');
  assert.throws(() => parseCloudDevice({...device(), control_generation: -1}), status(422));
  assert.throws(() => parseCloudDevice({...device(), paused: 'false'}), status(422));
});

test('inventory reads use identity authentication and reject duplicate device receipts', async () => {
  const {api, calls} = harness([() => response({devices: [device()]}), () => response({devices: [device(), device()]})]);
  assert.equal((await api.cloudDevices())[0].resource_id, 'computer_test');
  assert.deepEqual([calls[0].url.pathname, calls[0].method, calls[0].headers.get('X-Wearing-Identity')], ['/api/devices', 'GET', connection.identity]);
  assert.equal(calls[0].headers.has('X-Wearing-Token'), false);
  assert.equal(calls[0].redirect, 'error');
  await assert.rejects(() => api.cloudDevices(), status(422));
});

test('pause sends the observed generation and validates resource, pause state and next generation', async () => {
  const {api, calls} = harness([() => response(bootstrap()), () => response({resource_id: 'computer_test', paused: true, generation: 4})]);
  await api.control(device(), true);
  assert.deepEqual(calls[1].body, {resource_id: 'computer_test', paused: true, expected_generation: 3});
  assert.equal(calls[1].headers.get('X-Wearing-Token'), 'csrf-synthetic');
  assert.equal(calls[1].url.pathname, '/api/devices/control');
  const invalid = harness([() => response(bootstrap()), () => response({resource_id: 'another_device', paused: true, generation: 4})]);
  await assert.rejects(() => invalid.api.control(device(), true), status(422));
});

test('CSRF expiry refreshes once and replays the identical generation-bound action', async () => {
  const {api, calls} = harness([() => response(bootstrap('old')), () => response({detail: 'expired'}, 403),
    () => response(bootstrap('new')), () => response({resource_id: 'computer_test', paused: true, generation: 4})]);
  await api.control(device(), true);
  assert.deepEqual(calls.map(c => c.method), ['GET', 'POST', 'GET', 'POST']);
  assert.deepEqual(calls[1].body, calls[3].body);
  assert.equal(calls[3].headers.get('X-Wearing-Token'), 'new');
});

test('a second 403 and a generation conflict do not loop, refetch or issue a different action', async () => {
  const repeated = harness([() => response(bootstrap()), () => response({}, 403), () => response(bootstrap()), () => response({}, 403)]);
  await assert.rejects(() => repeated.api.control(device(), false), status(403));
  assert.equal(repeated.calls.length, 4);
  const conflict = harness([() => response(bootstrap()), () => response({detail: '设备状态刚有变化'}, 409)]);
  await assert.rejects(() => conflict.api.control(device(), true), status(409));
  assert.equal(conflict.calls.length, 2);
});

test('wrong identity bootstrap prevents mutations and later caller edits cannot redirect the API identity', async () => {
  const wrong = harness([() => response(bootstrap('csrf', 'someone_else'))]);
  await assert.rejects(() => wrong.api.control(device(), true), status(422));
  assert.equal(wrong.calls.length, 1);
  const shared = {...connection};
  const isolated = harness([() => response({devices: []})], shared);
  shared.identity = 'another_identity'; shared.endpoint = 'https://another.invalid';
  await isolated.api.cloudDevices();
  assert.equal(isolated.calls[0].headers.get('X-Wearing-Identity'), connection.identity);
  assert.equal(isolated.calls[0].url.host, 'device-tests.invalid');
});

test('network interruption reports uncertainty without retrying the mutation', async () => {
  const {api, calls} = harness([() => response(bootstrap()), () => {throw new Error('connection lost after commit');}]);
  await assert.rejects(() => api.control(device(), true), /先重新检测状态/);
  assert.equal(calls.length, 2);
});

test('inspecting a manifest requires the server to return exactly those devices and scopes', async () => {
  const {api, calls} = harness([() => response(bootstrap()), () => response({resources: [{...manifest.resources[0], already_paired: false}]})]);
  assert.equal((await api.inspect(manifest))[0].already_paired, false);
  assert.deepEqual(calls[1].body, manifest);
  const swapped = harness([() => response(bootstrap()), () => response({resources: [{...manifest.resources[0], resource_id: 'other', already_paired: false}]})]);
  await assert.rejects(() => swapped.api.inspect(manifest), status(422));
});

test('pair creation and explicit lost-response recovery use the exact same request id and manifest', async () => {
  const {api, calls} = harness([() => response(bootstrap()), () => response({bundle: bundle(), expires_in: 600}), () => response({bundle: bundle(), expires_in: 600})]);
  await api.pair(intent); await api.pair(intent);
  assert.deepEqual(calls[1].body, {request_id: intent.request_id, offer: manifest});
  assert.deepEqual(calls[1].body, calls[2].body);
});

test('pairing download checks identity, credentials destination and selected permissions before exporting bytes', async () => {
  const {api, calls} = harness([() => response(bundle())]);
  const value = JSON.parse(new TextDecoder().decode(await api.pairingBytes(intent)));
  assert.equal(value.identity_id, connection.identity);
  assert.equal(value.endpoint, 'https://synthetic-relay.invalid');
  assert.equal(calls[0].url.pathname, `/api/devices/pair/${intent.request_id}/download`);
  for (const change of [{identity_id: 'another'}, {endpoint: 'http://unsafe.invalid'}, {endpoint: 'https://user:password@unsafe.invalid'},
    {endpoint: 'https://relay.invalid/download?secret=x'}, {resources: [{...manifest.resources[0], methods: ['computer.status']}]}]) {
    const invalid = harness([() => response(bundle(change))]);
    await assert.rejects(() => invalid.api.pairingBytes(intent), status(422));
  }
});

test('expired pairing returns 404 without silently generating a new pairing or accepting another identity', async () => {
  const {api, calls} = harness([() => response({detail: '配对文件已过期'}, 404)]);
  await assert.rejects(() => api.pairingBytes(intent), status(404));
  assert.equal(calls.length, 1);
});

test('permission changes submit a stable request, revision and connector delivery, then read separate status', async () => {
  const {api, calls} = harness([() => response(bootstrap()), () => response({request_id: permission.request_id, expires_in: 600, policy_revision: 2}),
    () => response({state: 'pending', connected: true, policy_revision: 2}), () => response({state: 'applied', connected: false, policy_revision: 2})]);
  await api.permission(permission);
  assert.deepEqual(calls[1].body, permission);
  assert.equal((await api.permissionStatus(permission.request_id)).state, 'pending');
  assert.deepEqual(await api.permissionStatus(permission.request_id), {state: 'applied', connected: false, policy_revision: 2});
  const malformed = harness([() => response(bootstrap()), () => response({request_id: 'wrong', expires_in: 600, policy_revision: 2})]);
  await assert.rejects(() => malformed.api.permission(permission), status(422));
});

test('an expired or task-ineligible approval cannot send a decision', async () => {
  const {api, calls} = harness([]);
  assert.equal(canDecide(approval({expires_at: '2000-01-01T00:00:00Z'})), false);
  await assert.rejects(() => api.decide(approval({expires_at: '2000-01-01T00:00:00Z'}), 'once'), status(409));
  await assert.rejects(() => api.decide(approval(), 'task'), status(409));
  await assert.rejects(() => api.decide(approval({can_decide: false}), 'deny'), status(409));
  assert.equal(calls.length, 0);
});

test('decision uses the displayed approval revision and does not mark an awaiting decision complete', async () => {
  const a = approval({task_eligible: true});
  assert.equal(approvalDescription(a), 'TextEdit · 填写 · 文稿 · 合成内容');
  const {api, calls} = harness([() => response(bootstrap()), () => response({approval_id: a.approval_id, state: 'decision_sent'})]);
  await api.decide(a, 'task');
  assert.deepEqual(calls[1].body, {approval_id: a.approval_id, revision: a.revision, choice: 'task'});
  const invalid = harness([() => response(bootstrap()), () => response({approval_id: a.approval_id, state: 'awaiting_user'})]);
  await assert.rejects(() => invalid.api.decide(a, 'once'), status(422));
});

test('unknown-action review needs real readiness, an explicit check and a meaningful note', async () => {
  const {api, calls} = harness([]);
  for (const [r, text, checked] of [[review, '已经打开目标页面', false], [review, '短', true], [{...review, can_review: false}, '已经打开目标页面', true]] as const) {
    await assert.rejects(() => api.review(r, text, checked), status(422));
  }
  assert.equal(calls.length, 0);
});

test('review sends exact old-action revision and requires a no-replay receipt', async () => {
  const {api, calls} = harness([() => response(bootstrap()), () => response({reviewed: true, replayed: false})]);
  await api.review(review, '  实际页面已打开，旧动作已结束。  ', true);
  assert.deepEqual(calls[1].body, {command_id: review.command_id, revision: review.revision, note: '实际页面已打开，旧动作已结束。', checked: true});
  const invalid = harness([() => response(bootstrap()), () => response({reviewed: true, replayed: true})]);
  await assert.rejects(() => invalid.api.review(review, '实际页面已打开', true), status(422));
});

test('local computer parser accepts the actual runtime connector without an installed field', async () => {
  const raw = {installed: true, ready: true, accessibility: true, screen_recording: true, can_grant: true,
    control: {holder: 'human'}, connector: {phase: 'idle', error: null, enrolled: true, active: false}, resource_id: 'computer_local'};
  const {api, calls} = harness([() => response(raw), () => response(bootstrap('csrf', connection.identity, 'local')), () => response(raw)]);
  assert.equal((await api.localComputer()).held, true);
  assert.equal((await api.localComputer(true)).connector.enrolled, true);
  assert.deepEqual(calls.map(c => [c.method, c.url.pathname]), [['GET', '/api/computer'], ['GET', '/api/bootstrap'], ['POST', '/api/computer/refresh']]);
});

test('local phone binding, pause and resume target the selected serial or resource only', async () => {
  const raw = {state: 'checked', connector: {installed: true, phase: 'idle', active: true, error: null}, devices: [{serial: 'synthetic-serial', state: 'device', model: '合成手机'}],
    resources: [{resource_id: 'phone_test', serial: 'synthetic-serial', name: '合成手机', online: true, enabled: true}]};
  const {api, calls} = harness([() => response(raw), () => response(bootstrap()), () => response(raw), () => response({message: 'paused'}), () => response(raw)]);
  assert.equal((await api.localPhone()).devices[0].serial, 'synthetic-serial');
  await api.phoneAction('bind', 'synthetic-serial'); await api.phoneAction('pause', 'phone_test'); await api.phoneAction('resume', 'phone_test');
  assert.deepEqual(calls.slice(2).map(c => [c.url.pathname, c.body]), [
    ['/api/phone/bind', {serial: 'synthetic-serial'}], ['/api/phone/pause', {resource_id: 'phone_test'}], ['/api/phone/resume', {resource_id: 'phone_test'}],
  ]);
});

test('prepare and OS permissions use real endpoints without pretending the grant is complete', async () => {
  const {api, calls} = harness([() => response(bootstrap()), () => response({phase: 'installing', enrolled: false, active: false}, 202), () => response({message: 'complete OS permission on computer'})]);
  await api.computerAction('prepare'); await api.computerAction('permissions');
  assert.deepEqual(calls.slice(1).map(c => [c.url.pathname, c.body]), [['/api/computer/prepare', {}], ['/api/computer/permissions', {}]]);
});
