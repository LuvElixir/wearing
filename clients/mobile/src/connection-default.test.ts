import assert from 'node:assert/strict';
import test, {afterEach, beforeEach} from 'node:test';
import type {Connection} from './core';
import {assertNativeServiceAddress, initialConnection, PUBLIC_PAJIO_ENDPOINT, requiresNativeSignIn} from './connection-default';
import {developmentConnectionsEnabled} from './development-access';

let dev: PropertyDescriptor | undefined, flag: string | undefined;
beforeEach(() => {
  dev = Object.getOwnPropertyDescriptor(globalThis, '__DEV__');
  flag = process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS;
  Object.defineProperty(globalThis, '__DEV__', {configurable: true, value: false});
  delete process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS;
});
afterEach(() => {
  if (dev) Object.defineProperty(globalThis, '__DEV__', dev); else Reflect.deleteProperty(globalThis, '__DEV__');
  if (flag === undefined) delete process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS; else process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS = flag;
});

test('a fresh native installation starts at the public HTTPS service', () => {
  for (const platform of ['ios', 'android']) {
    assert.deepEqual(initialConnection(null, platform), {endpoint: PUBLIC_PAJIO_ENDPOINT, identity: 'daily'});
  }
});

test('web preview retains its current origin', () => {
  assert.deepEqual(initialConnection(null, 'web', 'http://127.0.0.1:8878'), {endpoint: 'http://127.0.0.1:8878/', identity: 'daily'});
  assert.equal(initialConnection(null, 'web', 'https://preview.example/').endpoint, 'https://preview.example/');
  assert.throws(() => initialConnection(null, 'web'), /网页预览地址/);
});

test('release native retires nonofficial connections without rebinding credentials, identity or drafts', () => {
  const connections: Connection[] = [
    {endpoint: 'http://127.0.0.1:8892/', identity: 'qa'},
    {endpoint: 'http://192.168.1.10:8765/', identity: 'work', development: {accessToken: 'synthetic-development', expiresAt: '2026-10-11T00:00:00Z'}},
    {endpoint: 'https://private.example/', identity: 'daily', session: {accessToken: 'synthetic-session', expiresAt: '2026-10-11T00:00:00Z', userId: 'synthetic-user', tenantId: 'synthetic-tenant', credentialId: 'synthetic-credential'}},
  ];
  for (const stored of connections) {
    const before = structuredClone(stored);
    for (const platform of ['ios', 'android']) {
      assert.deepEqual(initialConnection(stored, platform), {endpoint:PUBLIC_PAJIO_ENDPOINT, identity:'daily'});
      assert.deepEqual(stored, before);
    }
    assert.deepEqual(initialConnection(stored, 'web'), before);
    Object.defineProperty(globalThis, '__DEV__', {configurable:true,value:true});
    process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS='true';
    for (const platform of ['ios', 'android']) {
      const restored = initialConnection(stored, platform);
      assert.deepEqual(restored, before);
      assert.notEqual(restored, stored);
      restored.endpoint = 'https://changed.example/';
      assert.deepEqual(stored, before);
    }
    Object.defineProperty(globalThis, '__DEV__', {configurable:true,value:false});
    delete process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS;
  }
});

test('official sessions preserve their owner and identity while unsigned or expired native sessions require login', () => {
  const saved: Connection = {endpoint:PUBLIC_PAJIO_ENDPOINT,identity:'work',session:{userId:'user_'+'a'.repeat(32),tenantId:'tenant-a',credentialId:'b'.repeat(32),accessToken:'s'.repeat(64),expiresAt:new Date(Date.now()+3600000).toISOString()}};
  assert.deepEqual(initialConnection(saved,'ios'),saved);
  assert.equal(requiresNativeSignIn(saved,'ios'),false);
  for (const next of [null,{endpoint:PUBLIC_PAJIO_ENDPOINT,identity:'daily'},{...saved,session:{...saved.session!,accessToken:undefined}},{...saved,session:{...saved.session!,expiresAt:new Date(0).toISOString()}},{...saved,endpoint:'https://foreign.invalid/'}]) {
    assert.equal(requiresNativeSignIn(next,'ios'),true);
    assert.equal(requiresNativeSignIn(next,'android'),true);
  }
});

test('custom services require both explicit build opt-in and dev runtime; hostile public lookalikes never migrate credentials', () => {
  for(const [runtime,optin,enabled] of [[false,'true',false],[true,undefined,false],[true,'false',false],[true,'true',true]] as const) {
    Object.defineProperty(globalThis,'__DEV__',{configurable:true,value:runtime});
    if(optin===undefined)delete process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS;else process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS=optin;
    assert.equal(developmentConnectionsEnabled(),enabled);
    if(enabled)assert.doesNotThrow(()=>assertNativeServiceAddress('http://192.168.1.2:8765/'));else assert.throws(()=>assertNativeServiceAddress('https://foreign.invalid/'));
  }
  Object.defineProperty(globalThis,'__DEV__',{configurable:true,value:false});
  for(const address of ['http://pajio.luckyloading.com/','https://pajio.luckyloading.com.evil.invalid/','https://pajio.luckyloading.com:444/','https://user:secret@pajio.luckyloading.com/','https://pajio.luckyloading.com/path']) {
    assert.throws(()=>assertNativeServiceAddress(address));
    assert.deepEqual(initialConnection({endpoint:address,identity:'private'},'ios'),{endpoint:PUBLIC_PAJIO_ENDPOINT,identity:'daily'});
  }
  assert.doesNotThrow(()=>assertNativeServiceAddress(PUBLIC_PAJIO_ENDPOINT));
});
