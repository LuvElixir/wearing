import assert from 'node:assert/strict';
import test from 'node:test';
import type {Connection} from './core';
import {initialConnection, PUBLIC_PAJIO_ENDPOINT} from './connection-default';

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

test('saved local, development and cloud connections are preserved before any default', () => {
  const connections: Connection[] = [
    {endpoint: 'http://127.0.0.1:8892/', identity: 'qa'},
    {endpoint: 'http://192.168.1.10:8765/', identity: 'work', development: {accessToken: 'synthetic-development', expiresAt: '2026-10-11T00:00:00Z'}},
    {endpoint: 'https://private.example/', identity: 'daily', session: {accessToken: 'synthetic-session', expiresAt: '2026-10-11T00:00:00Z', userId: 'synthetic-user', tenantId: 'synthetic-tenant', credentialId: 'synthetic-credential'}},
  ];
  for (const stored of connections) {
    const before = structuredClone(stored);
    for (const platform of ['ios', 'android', 'web']) {
      const restored = initialConnection(stored, platform);
      assert.deepEqual(restored, before);
      assert.notEqual(restored, stored);
      restored.endpoint = 'https://changed.example/';
      assert.deepEqual(stored, before);
    }
  }
});
