import assert from 'node:assert/strict';
import test from 'node:test';
import {Connection} from './core';
import {skillRemoval, skillSnapshot, SkillsApi, validSkillId} from './skills-model';

const revision = 'a'.repeat(64);
const sample = {id: 'documents/letter', name: 'letter', description: 'Write letters', category: 'documents', enabled: true, essential: false, compatible: true, requirements: [], revision};
const snapshot = {revision, installed: [sample], catalog: [{...sample, installed: true}]};
const connection: Connection = {endpoint: 'http://127.0.0.1:8765', identity: 'default'};

test('skill IDs cannot traverse directories and snapshot distinguishes installed from catalog', () => {
  for (const id of ['../secrets', '/etc', 'skills\\file', 'one//two', 'one/.hidden']) assert.equal(validSkillId(id), false);
  assert.equal(validSkillId(sample.id), true);
  assert.equal(skillSnapshot(snapshot).catalog[0].installed, true);
  assert.throws(() => skillSnapshot({...snapshot, catalog: [sample]}));
});

test('changing enabled state bootstraps a CSRF token and binds current identity', async () => {
  const calls: {url: string; init?: RequestInit}[] = [];
  const fetcher = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({url: String(url), init});
    return new Response(JSON.stringify(String(url).endsWith('/api/bootstrap') ? {version: '0.2.0', deployment: 'local', token: 'csrf-test', identities: [{id: 'default'}]} : snapshot));
  }) as typeof fetch;
  const api = new SkillsApi(connection, fetcher);
  await api.enabled(sample.id, false, revision);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].init?.method, 'PATCH');
  assert.equal(new Headers(calls[1].init?.headers).get('X-Wearing-Token'), 'csrf-test');
  assert.equal(new Headers(calls[1].init?.headers).get('X-Wearing-Identity'), 'default');
  assert.equal(calls[1].init?.redirect, 'error');
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)), {id: sample.id, enabled: false, revision});
});

test('conflicts and unavailable catalogs are failures rather than optimistic success', async () => {
  const fetcher = (async () => new Response(JSON.stringify({detail: 'internal-path-secret'}), {status: 409})) as typeof fetch;
  await assert.rejects(new SkillsApi(connection, fetcher).list(), error => error instanceof Error && !error.message.includes('internal-path-secret') && error.message.includes('刷新'));
});

const removal = {...sample, package_revision: 'b'.repeat(64), operation_id: 'c'.repeat(32)};
const removed = {removed: true, id: sample.id, operation_id: removal.operation_id, recovery_id: removal.operation_id,
  snapshot: {...snapshot, installed: [], catalog: [{...sample, installed: false}]}};

test('removal preview never mutates and confirm binds whole package, operation and identity', async () => {
  const calls: {url: string; init?: RequestInit}[] = [];
  const fetcher = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({url: String(url), init});
    return new Response(JSON.stringify(String(url).includes('/api/bootstrap') ? {version: '0.2.0', deployment: 'local', token: 'csrf-test', identities: [{id: 'default'}]} :
      String(url).includes('/api/skills/removal?') ? removal : removed));
  }) as typeof fetch;
  const api = new SkillsApi(connection, fetcher);
  const preview = await api.removal(sample.id);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init?.method, 'GET');
  assert.deepEqual(await api.remove(preview), removed);
  assert.deepEqual(JSON.parse(String(calls[2].init?.body)), {id: sample.id, revision, package_revision: removal.package_revision, operation_id: removal.operation_id});
  assert.equal(calls[2].init?.method, 'POST');
  assert.equal(new Headers(calls[2].init?.headers).get('X-Wearing-Token'), 'csrf-test');
  assert.equal(new Headers(calls[2].init?.headers).get('X-Wearing-Identity'), 'default');
});

test('removal receipt must prove exact operation and refreshed absence, never optimistic deletion', async () => {
  for (const bad of [{...removed, removed: false}, {...removed, operation_id: 'd'.repeat(32)}, {...removed, id: 'other'},
    {...removed, recovery_id: 'd'.repeat(32)}, {...removed, snapshot}]) {
    const fetcher = (async (url: string | URL | Request) => new Response(JSON.stringify(String(url).endsWith('/api/bootstrap') ?
      {version: '0.2.0', deployment: 'local', token: 'csrf-test', identities: [{id: 'default'}]} : bad))) as typeof fetch;
    await assert.rejects(new SkillsApi(connection, fetcher).remove(removal));
  }
  assert.throws(() => skillRemoval({...removal, operation_id: '../recovery'}));
  assert.throws(() => skillRemoval({...removal, package_revision: 'invalid'}));
});

test('active skill use has actionable failure and preview stays reusable for exact retry', async () => {
  let attempts = 0;
  const bodies: string[] = [];
  const fetcher = (async (url: string | URL | Request, init?: RequestInit) => {
    if (String(url).endsWith('/api/bootstrap')) return new Response(JSON.stringify({version: '0.2.0', deployment: 'local', token: 'csrf-test', identities: [{id: 'default'}]}));
    bodies.push(String(init?.body));
    return ++attempts === 1 ? new Response(JSON.stringify({detail: 'private-path'}), {status: 423}) : new Response(JSON.stringify(removed));
  }) as typeof fetch;
  const api = new SkillsApi(connection, fetcher);
  await assert.rejects(api.remove(removal), error => error instanceof Error && error.message.includes('当前有任务') && !error.message.includes('private-path'));
  assert.deepEqual(await api.remove(removal), removed);
  assert.equal(bodies[0], bodies[1]);
});
