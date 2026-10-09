import test from 'node:test';
import assert from 'node:assert/strict';
import {canStream, parseRemoteAccess, remotePoint, RemoteDeviceApi, type RemoteAccess} from './remote-device-model';
import type {Connection} from './core';
const connection: Connection = {endpoint: 'https://pajio.example', identity: 'daily'};
const base = (): RemoteAccess => ({resource_id: 'phone_one', supported: true, state: 'human_private', control_generation: 2, session_id: 'human_one', epoch: 1, gateway_epoch: 7, device_confirmed: true, expires_at: Date.now() / 1000 + 300});
test('private frames require authoritative ACK, live session and future expiry', () => {
  const value = base(); assert.equal(canStream(value), true);
  for (const patch of [{state: 'handoff_pending'}, {state: 'return_pending'}, {device_confirmed: false}, {supported: false}, {gateway_epoch: null}, {session_id: null}, {expires_at: 1}, {epoch: 0}]) assert.equal(canStream({...value, ...patch} as RemoteAccess), false);
  assert.throws(() => parseRemoteAccess({...value, resource_id: 'phone_two'}, 'phone_one'));
  assert.throws(() => parseRemoteAccess({...value, epoch: -1}, 'phone_one'));
  assert.equal(parseRemoteAccess({supported: false}, 'phone_one').state, 'unavailable');
});
test('touch geometry excludes letterbox, resized and invalid frames', () => {
  assert.deepEqual(remotePoint(160, 200, 320, 400, 1080, 1920), {x: 540, y: 960});
  assert.equal(remotePoint(0, 200, 320, 400, 1080, 1920), null);
  assert.equal(remotePoint(160, 400, 320, 400, 1080, 1920), null);
  assert.equal(remotePoint(20, 20, 0, 400, 1080, 1920), null);
  assert.equal(remotePoint(NaN, 20, 320, 400, 1080, 1920), null);
  assert.deepEqual(remotePoint(100, 50, 200, 100, 1920, 1080), {x: 960, y: 540});
});
test('control request has one send even if response is lost or forbidden', async () => {
  for (const fail of ['network', 'forbidden']) {
    let posts = 0;
    const api = new RemoteDeviceApi(connection, (async (_url: unknown, init?: RequestInit) => {
      if (init?.method === 'GET') return Response.json({token: 'csrf', identities: [{id: 'daily'}]});
      posts++; assert.equal((init?.headers as Record<string,string>).Origin, 'https://pajio.example');
      if (fail === 'network') throw new Error('lost');
      return Response.json({detail: 'denied'}, {status: 403});
    }) as typeof fetch);
    await assert.rejects(api.begin({...base(), state: 'agent_ready'}, 'a'.repeat(32)));
    assert.equal(posts, 1);
  }
});
test('transport cannot swap a session and never receives credentials via query', async () => {
  const access = base(), calls: string[] = [];
  const api = new RemoteDeviceApi(connection, (async (url: string) => {
    calls.push(url); return Response.json({kind: 'webrtc', session_id: 'another_session', epoch: 1, gateway_epoch: 7, ice_servers: []});
  }) as typeof fetch);
  await assert.rejects(api.transport(access)); assert.equal(calls[0], 'https://pajio.example/api/devices/access/phone_one/transport');
  await assert.rejects(api.transport({...access, device_confirmed: false})); assert.equal(calls.length, 1);
});
test('return and offer reject unconfirmed private ownership without network writes', async () => {
  let sent = 0; const api = new RemoteDeviceApi(connection, (async () => {sent++; return Response.json({});}) as typeof fetch);
  await assert.rejects(api.giveBack(base(), false, true));
  await assert.rejects(api.offer({...base(), device_confirmed: false}, 'v=0\r\n'));
  assert.equal(sent, 0);
});
test('leaving during CSRF bootstrap prevents a later takeover POST', async () => {
  let active = true, calls = 0;
  const api = new RemoteDeviceApi(connection, (async () => {calls++; active = false; return Response.json({token: 'csrf', identities: [{id: 'daily'}]});}) as typeof fetch, () => active);
  await assert.rejects(api.begin(base(), 'a'.repeat(32)), /页面已切换/);
  assert.equal(calls, 1);
});
