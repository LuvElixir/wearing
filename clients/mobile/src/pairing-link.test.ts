import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {afterEach, beforeEach, test} from 'node:test';
import {pairingConnection} from './core';

const require = createRequire(import.meta.url);
const {pairingLink} = require('../scripts/pairing-link.cjs');
// Exercise the installed Expo Go route pipeline, not a substitute URL parser.
const {extractExpoPathFromURL} = require('expo-router/build/fork/extractPathFromURL');
const {parseQueryParams} = require('expo-router/build/fork/getStateFromPath-forks');
const now = Date.parse('2026-10-07T10:00:00Z');
const metro = 'exp://192.168.1.25:8081';
const pair = {endpoint: 'http://192.168.1.25:8795/', identity: 'daily', accessToken: 'safe_SYNTHETIC-token_'.repeat(3), expiresAt: '2026-10-07T13:00:00.900120+00:00'};
const descriptors = new Map<string, PropertyDescriptor | undefined>();
const realNow = Date.now;
let previousDevelopmentFlag: string | undefined;
beforeEach(() => {
  previousDevelopmentFlag = process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS;
  process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS = 'true';
  for (const [key, value] of Object.entries({__DEV__: true, expo: {modules: {ExpoGo: {}}}})) {
    descriptors.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, {configurable: true, value});
  }
  Date.now = () => now;
});
afterEach(() => {
  if (previousDevelopmentFlag === undefined) delete process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS;
  else process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS = previousDevelopmentFlag;
  Date.now = realNow;
  for (const [key, descriptor] of descriptors) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
  descriptors.clear();
});
const routeParams = (url: string) => parseQueryParams(extractExpoPathFromURL([], url), {name: 'connect'});

test('installed Expo Router reproduces the rejected numeric-offset pairing expiry', () => {
  const url = new URL(metro + '/--/connect');
  for (const [key, value] of Object.entries(pair)) url.searchParams.set(key, value);
  const params = routeParams(url.href);
  assert.equal(params.expiresAt, '2026-10-07T13:00:00.900120 00:00');
  assert.throws(() => pairingConnection(params), /配对凭据不完整/);
});

test('QR generator expiry survives real Expo Go extraction and Wearing validation', () => {
  for (const expiresAt of [pair.expiresAt, '2026-10-07T21:00:00.900120+08:00', '2026-10-07T08:00:00.900120-05:00', '2026-10-07T13:00:00.900Z']) {
    const params = routeParams(pairingLink({...pair, expiresAt}, metro, now));
    const connection = pairingConnection(params);
    assert.equal(params.expiresAt, '2026-10-07T13:00:00.900Z');
    assert.equal(Date.parse(params.expiresAt), Date.parse(expiresAt));
    assert.deepEqual(connection, {endpoint: pair.endpoint, identity: pair.identity, development: {accessToken: pair.accessToken, expiresAt: params.expiresAt}});
  }
});

test('QR generation refuses expired or malformed credentials and a different Metro host', () => {
  for (const expiresAt of ['bad', '2026-10-07T09:00:00Z', '2026-10-07T13:00:00 00:00']) {
    assert.throws(() => pairingLink({...pair, expiresAt}, metro, now));
  }
  assert.throws(() => pairingLink({...pair, accessToken: 'short'}, metro, now));
  assert.throws(() => pairingLink({...pair, accessToken: [pair.accessToken]}, metro, now));
  assert.throws(() => pairingLink(pair, 'exp://192.168.1.26:8081', now));
});
