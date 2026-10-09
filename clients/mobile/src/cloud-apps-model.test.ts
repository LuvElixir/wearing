import assert from 'node:assert/strict';
import test from 'node:test';
import {Connection} from './core';
import {CloudAppsApi, cloudState, officialFeishuUrl, upcomingCalendarRange} from './cloud-apps-model';

const sample = {provider: 'feishu', state: 'configured', configured: true, revision: 'a'.repeat(32), app_id: 'cli_testapp', account_name: null, account_id: null, checked_at: null, error: null, revocation_pending: false, authorization: null, capabilities: [{id: 'documents', label: '文档', requested: true, authorized: false, scopes: ['docx:document:readonly']}, {id: 'calendar', label: '日历', requested: true, authorized: false, scopes: ['calendar:calendar:read']}]};

test('configuration never becomes authorized in the model; external login links are rejected', () => {
  assert.equal(cloudState(sample).state, 'configured');
  assert.ok(cloudState(sample).capabilities.every(item => !item.authorized));
  const authorization = {id: 'b'.repeat(32), url: 'https://accounts.feishu.cn/device', user_code: 'TEST', expires_at: 1800000000, interval: 5};
  assert.equal(cloudState({...sample, state: 'authorizing', authorization}).authorization?.user_code, 'TEST');
  assert.throws(() => cloudState({...sample, authorization: {...authorization, url: 'https://feishu.cn.example.net/device'}}));
  assert.equal(officialFeishuUrl('https://secret@accounts.feishu.cn/device'), false);
  assert.equal(officialFeishuUrl('http://accounts.feishu.cn/device'), false);
  assert.equal(officialFeishuUrl('https://accounts.feishu.cn:444/device'), false);
  assert.throws(() => cloudState({...sample, capabilities: [sample.capabilities[0], sample.capabilities[0]]}));
});

test('OAuth setup and poll use current identity, CSRF and request body without URL credentials', async () => {
  const connection: Connection = {endpoint: 'http://127.0.0.1:8765/', identity: 'daily'}, calls: {url: string; init?: RequestInit}[] = [];
  const api = new CloudAppsApi(connection, (async (url, init) => {calls.push({url: String(url), init}); return new Response(JSON.stringify(String(url).endsWith('/api/bootstrap') ? {version: '0.2.0', deployment: 'local', token: 'csrf-test', identities: [{id: 'daily'}]} : sample));}) as typeof fetch);
  await api.configure('cli_testapp', 'private-secret-test', ['documents']);
  await api.poll('b'.repeat(32));
  const configure = calls.find(call => call.init?.method === 'PUT')!;
  assert.ok(!configure.url.includes('private-secret-test'));
  assert.equal(new Headers(configure.init?.headers).get('X-Wearing-Identity'), 'daily');
  assert.equal(new Headers(configure.init?.headers).get('X-Wearing-Token'), 'csrf-test');
  assert.equal(configure.init?.redirect, 'error');
  assert.equal(JSON.parse(String(configure.init?.body)).secret, 'private-secret-test');
  assert.equal(JSON.parse(String(calls.at(-1)?.init?.body)).authorization_id, 'b'.repeat(32));
});

test('document parameters are encoded and calendar interval stays exactly seven days', async () => {
  let requested = '';
  const api = new CloudAppsApi({endpoint: 'http://127.0.0.1:8765/', identity: 'daily'}, (async url => {requested = String(url); return new Response(JSON.stringify({content: 'actual text', title: null, document_id: 'doc-one', offset: 0, next_offset: null, total_characters: 11}));}) as typeof fetch);
  const data = await api.document('https://a.feishu.cn/docx/example?from=x&x=y');
  assert.equal(new URL(requested).searchParams.get('document'), 'https://a.feishu.cn/docx/example?from=x&x=y');
  assert.equal(data.content, 'actual text');
  const range = upcomingCalendarRange(1800000000000);
  assert.equal(range.start, 1800000000);
  assert.equal(range.end - range.start, 604800);
});
