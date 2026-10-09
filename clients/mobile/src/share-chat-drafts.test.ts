import {test} from 'node:test';
import assert from 'node:assert/strict';
import {SharedChatDrafts} from './share-chat-drafts';
const id = '11111111-1111-4111-8111-111111111111';
const input = {requestId: id, scope: 'account-a|daily', text: '分享的网页', files: []};
function fixture() {const data = new Map(); const store = {get: async <T>(key: string) => structuredClone(data.get(key) ?? null) as T | null, put: async (key: string, value: unknown) => {data.set(key, structuredClone(value));}}; return {data, store, queue: new SharedChatDrafts(store)};}
test('shared draft survives a new instance, stays separate and is scoped to the chosen account', async () => {
  const f = fixture(); await f.queue.save(input); await f.queue.save(input);
  assert.equal((await new SharedChatDrafts(f.store).list(input.scope)).length, 1);
  assert.equal((await f.queue.list('account-b|daily')).length, 0);
  assert.equal(f.data.size, 1);
});
test('append is journaled before delivery and a retry has the same receipt identifier', async () => {
  const f = fixture(); await f.queue.save(input);
  const command = await f.queue.append(input.scope, id, 'original-topic', '已有草稿');
  assert.deepEqual(await new SharedChatDrafts(f.store).append(input.scope, id, 'original-topic', '已有草稿\n分享的网页'), command);
  await assert.rejects(f.queue.append(input.scope, id, 'other-topic', ''), /原对话/);
  assert.equal(await f.queue.acknowledge(input.scope, command.voiceId, 'other-topic'), false);
  assert.equal(await f.queue.acknowledge(input.scope, 'voice-22222222-2222-4222-8222-222222222222', 'original-topic'), false);
  assert.equal(await f.queue.acknowledge(input.scope, command.voiceId, 'original-topic'), true);
  assert.deepEqual(await f.queue.list(input.scope), []);
  await f.queue.save(input); assert.deepEqual(await f.queue.list(input.scope), []);
});
test('full composer and failed durable write preserve the share without acknowledging it', async () => {
  const f = fixture(); await f.queue.save(input);
  await assert.rejects(f.queue.append(input.scope, id, 'topic', '字'.repeat(12000)), /草稿太长/);
  const put = f.store.put; f.store.put = async () => {throw new Error('disk');};
  await assert.rejects(f.queue.append(input.scope, id, 'topic', ''), /disk/);
  f.store.put = put;
  assert.equal((await f.queue.list(input.scope))[0].state, 'ready');
});
test('removing an unacknowledged copy unblocks later shares without replay or resurrection', async () => {
  const f = fixture(); await f.queue.save(input);
  const command = await f.queue.append(input.scope, id, 'old-topic', '');
  const next = {...input, requestId: '22222222-2222-4222-8222-222222222222', text: '下一份分享'};
  await f.queue.save(next); await f.queue.dismiss(input.scope, id);
  assert.deepEqual((await f.queue.list(input.scope)).map(item => item.id), [next.requestId]);
  assert.equal(await f.queue.acknowledge(input.scope, command.voiceId, 'old-topic'), false);
  await f.queue.save(input);
  assert.equal((await f.queue.list(input.scope)).length, 1);
  await assert.rejects(f.queue.append(input.scope, id, 'old-topic', ''), /已处理/);
  assert.equal((await f.queue.append(input.scope, next.requestId, 'new-topic', '')).text, next.text);
});
