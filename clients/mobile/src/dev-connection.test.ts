import assert from 'node:assert/strict';
import {afterEach, beforeEach, test} from 'node:test';
import {connectionEndpoint, connectionHeaders, endpoint, pairingConnection, scopeOf, WearingApi, type Connection} from './core';

const now = Date.parse('2026-10-07T10:00:00.000Z');
const token = 'a'.repeat(43);
const paired = (address = 'http://192.168.1.25:8795/'): Connection => ({endpoint: address, identity: 'daily', development: {accessToken: token, expiresAt: new Date(now + 4 * 60 * 60 * 1000).toISOString()}});
let devDescriptor: PropertyDescriptor | undefined;
let realNow: typeof Date.now;
beforeEach(() => {
  devDescriptor = Object.getOwnPropertyDescriptor(globalThis, '__DEV__');
  Object.defineProperty(globalThis, '__DEV__', {configurable: true, value: true});
  realNow = Date.now; Date.now = () => now;
});
afterEach(() => {
  Date.now = realNow;
  if (devDescriptor) Object.defineProperty(globalThis, '__DEV__', devDescriptor);
  else Reflect.deleteProperty(globalThis, '__DEV__');
});

test('ordinary endpoint validation still refuses LAN HTTP even in a development build', () => {
  for (const address of ['http://192.168.1.25:8795/', 'http://10.1.2.3/', 'http://172.20.1.1/']) {
    assert.throws(() => endpoint(address));
    assert.throws(() => connectionEndpoint({endpoint: address, identity: 'daily'}));
  }
  assert.equal(endpoint('https://wearing.example/'), 'https://wearing.example/');
  assert.equal(endpoint('http://127.0.0.1:8765/'), 'http://127.0.0.1:8765/');
});

test('only explicit RFC1918 IPv4 pairing permits LAN HTTP', () => {
  for (const host of ['10.0.0.1', '10.255.255.254', '172.16.0.1', '172.31.255.254', '192.168.0.1']) {
    assert.equal(connectionEndpoint(paired('http://' + host + ':8795')), 'http://' + host + ':8795/');
  }
  for (const address of ['http://172.15.1.1/', 'http://172.32.1.1/', 'http://192.169.1.1/', 'http://169.254.1.1/', 'http://100.64.0.1/', 'http://127.0.0.1/', 'http://localhost/', 'http://example.com/', 'https://192.168.1.25/', 'http://[::1]/', 'http://192.168.1.25/path', 'http://192.168.1.25/?token=x', 'http://192.168.1.25/#x', 'http://user:pass@192.168.1.25/']) {
    assert.throws(() => connectionEndpoint(paired(address)), address);
  }
});

test('production builds and an absent development flag reject paired LAN connections', () => {
  Object.defineProperty(globalThis, '__DEV__', {configurable: true, value: false});
  assert.throws(() => connectionEndpoint(paired()), /仅供开发版/);
  Reflect.deleteProperty(globalThis, '__DEV__');
  assert.throws(() => connectionEndpoint(paired()), /仅供开发版/);
});

test('pairing requires a well-formed short lived token and ISO expiry', () => {
  const valid = paired();
  for (const accessToken of ['', 'short', token + '\n', 'Bearer ' + token, 'a'.repeat(513)]) {
    assert.throws(() => connectionEndpoint({...valid, development: {...valid.development!, accessToken}}));
  }
  for (const expiresAt of ['', 'tomorrow', String(now + 1000), new Date(now + 24 * 60 * 60 * 1000).toISOString()]) {
    assert.throws(() => connectionEndpoint({...valid, development: {...valid.development!, expiresAt}}));
  }
  assert.equal(connectionHeaders(valid).Authorization, 'Bearer ' + token);
});

test('an expired connection retains its local scope but cannot send a network request', async () => {
  const expired = paired(); expired.development!.expiresAt = new Date(now - 1).toISOString();
  assert.equal(scopeOf(expired), 'http://192.168.1.25:8795/|daily');
  assert.throws(() => connectionHeaders(expired), /已过期/);
  let calls = 0;
  const api = new WearingApi(expired, (async () => {calls++; return Response.json({});}) as typeof fetch);
  await assert.rejects(api.bootstrap(), /已过期/); assert.equal(calls, 0);
});

test('scope is stable across token renewal and never contains bearer credentials', () => {
  const first = paired(), second = paired(); second.development!.accessToken = 'b'.repeat(43);
  assert.equal(scopeOf(first), scopeOf(second));
  assert.equal(scopeOf(first).includes(token), false);
  assert.notEqual(scopeOf(first), scopeOf({...first, identity: 'another'}));
  assert.deepEqual(connectionHeaders({endpoint: 'https://wearing.example/', identity: 'daily'}), {});
});

test('deep link parameters become a normalized connection and duplicate or missing fields fail closed', () => {
  const connection = paired('http://192.168.1.25:8795');
  const params = {endpoint: connection.endpoint, identity: 'daily', accessToken: token, expiresAt: connection.development!.expiresAt};
  assert.deepEqual(pairingConnection(params), paired());
  assert.throws(() => pairingConnection({...params, accessToken: [token, 'different']}));
  assert.throws(() => pairingConnection({...params, identity: '../daily'}));
  assert.throws(() => pairingConnection({...params, expiresAt: undefined}));
});

test('native bootstrap and subsequent reads/writes use bearer headers without URL credentials', async () => {
  const seen: {path: string; method: string; headers: Headers}[] = [];
  const asset = 'asset_' + 'a'.repeat(32);
  const api = new WearingApi(paired(), (async (input, init) => {
    const url = new URL(String(input));
    assert.equal(url.href.includes(token), false);
    assert.equal(url.username, ''); assert.equal(url.password, '');
    const headers = new Headers(init?.headers);
    assert.equal(headers.get('Authorization'), 'Bearer ' + token);
    assert.equal(headers.get('X-Wearing-Identity'), 'daily');
    seen.push({path: url.pathname, method: init?.method ?? 'GET', headers});
    if (url.pathname === '/api/bootstrap') return Response.json({version: '0.2.0', deployment: 'local', token: 'write-token', identities: [{id: 'daily', name: '日常'}]});
    if (url.pathname === '/api/life') return Response.json({items: [], version: 1});
    if (url.pathname.endsWith('/transcribe')) return Response.json({asset_id: asset, text: '可编辑的文字'});
    return Response.json({id: asset});
  }) as typeof fetch);
  await api.bootstrap(); await api.snapshot();
  await api.upload({id: 'original', name: 'a.m4a', mime: 'audio/mp4', size: 4}, new Blob(['audio']), 'same-upload-key');
  await api.transcribe(asset);
  assert.deepEqual(seen.map(({method}) => method), ['GET', 'GET', 'POST', 'POST']);
  assert.equal(seen[2].headers.get('X-Wearing-Token'), 'write-token');
});

test('expiry is checked again on every request after a successful bootstrap', async () => {
  let calls = 0;
  const connection = paired();
  const api = new WearingApi(connection, (async () => {
    calls++; return Response.json({version: '0.2.0', deployment: 'local', token: 'write', identities: [{id: 'daily'}]});
  }) as typeof fetch);
  await api.bootstrap(); Date.now = () => Date.parse(connection.development!.expiresAt);
  await assert.rejects(api.snapshot(), /已过期/);
  assert.equal(calls, 1);
});
