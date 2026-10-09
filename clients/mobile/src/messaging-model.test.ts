import assert from 'node:assert/strict';
import test from 'node:test';
import {Connection} from './core';
import {allowedMessagingUsers, MessagingApi, messagingConfigurationError, messagingSnapshot} from './messaging-model';

const connection: Connection = {endpoint: 'http://127.0.0.1:8765/', identity: 'daily'};
const sample = {configured: false, enabled: false, state: 'not_configured', allowed_users: [], can_enable: true, uncertain_replies: 0, revision: null, error: null, checked_at: null};
const snapshot = {channels: [{...sample, provider: 'telegram', name: 'Telegram'}, {...sample, provider: 'feishu', name: '飞书'}]};
const secret = '123456789:' + 'a'.repeat(32);

test('channels validate per-provider credentials and explicit personal allowlists', () => {
  assert.deepEqual(allowedMessagingUsers('42，43\n42;44'), ['42', '43', '44']);
  assert.equal(messagingConfigurationError('telegram', {secret, allowed_users: ['42']}), null);
  assert.ok(messagingConfigurationError('telegram', {secret, allowed_users: ['@nickname']}));
  assert.ok(messagingConfigurationError('telegram', {secret, allowed_users: []}));
  assert.equal(messagingConfigurationError('feishu', {secret: 'abcdefghijklmnop', app_id: 'cli_testapp', allowed_users: ['ou_testuser']}), null);
  assert.ok(messagingConfigurationError('feishu', {secret: 'abcdefghijklmnop', app_id: 'cli_testapp', allowed_users: ['42']}));
});

test('credentials verified and socket connecting do not become connected in parsing', () => {
  const parsed = messagingSnapshot({...snapshot, channels: [{...snapshot.channels[0], configured: true, state: 'configured'}, {...snapshot.channels[1], configured: true, enabled: true, state: 'connecting'}]});
  assert.equal(parsed.channels[0].state, 'configured');
  assert.equal(parsed.channels[1].state, 'connecting');
  assert.throws(() => messagingSnapshot({channels: [snapshot.channels[0], snapshot.channels[0]]}));
});

test('saving sends credentials in a body to the bound service with identity and CSRF headers', async () => {
  const calls: {url: string; init?: RequestInit}[] = [];
  const fetcher = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({url: String(url), init});
    return new Response(JSON.stringify(String(url).endsWith('/api/bootstrap') ? {version: '0.2.0', deployment: 'local', token: 'csrf-test', identities: [{id: 'daily'}]} : snapshot));
  }) as typeof fetch;
  await new MessagingApi(connection, fetcher).configure('telegram', {secret, allowed_users: ['42']});
  assert.equal(calls.length, 2);
  assert.equal(calls[1].init?.method, 'PUT');
  assert.ok(!calls[1].url.includes(secret));
  assert.equal(new Headers(calls[1].init?.headers).get('X-Wearing-Token'), 'csrf-test');
  assert.equal(new Headers(calls[1].init?.headers).get('X-Wearing-Identity'), 'daily');
  assert.equal(calls[1].init?.redirect, 'error');
  assert.equal(JSON.parse(String(calls[1].init?.body)).secret, secret);
});
