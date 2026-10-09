import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ApiError, type Connection} from './core';
import {ArtifactChoiceApi, choicePendingKey, choiceTaskPending, parseChoiceState, parseChoiceReceipt, validChoiceRequest} from './artifact-choices';

const connection: Connection = {endpoint: 'https://choice-tests.invalid', identity: 'daily'};
const artifact = 'art_fixture', source = 'source_task', request = {request_key: 'fixture-request-key', choice_id: 'compare', artifact_revision: 1, selection_revision: 0};
const receipt = {artifact_id: artifact, revision: 1, request_key: request.request_key, choice_id: request.choice_id,
  task_id: 'continuation_task', source_task_id: source, created_at: '2026-10-08T04:00:00Z', task_status: 'draft', queue_state: 'queued'};
const state = {artifact_id: artifact, artifact_revision: 1, revision: 0, newer_id: null, choices: [{id: 'compare', label: '继续比较', instruction: '比较两份测试方案'}], selection: null};
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {status});
function harness(replies: (() => Response | Promise<Response>)[], c = connection) {
  const calls: {url: string; headers: Headers; body: unknown}[] = [];
  const api = new ArtifactChoiceApi(c, artifact, 1, source, (async (url, options) => {
    calls.push({url: String(url), headers: new Headers(options?.headers), body: options?.body ? JSON.parse(String(options.body)) : null});
    const next = replies.shift(); assert.ok(next); return next();
  }) as typeof fetch);
  return {api, calls};
}
test('strict published option and selection state reject wrong result, version or injected shape', () => {
  assert.deepEqual(parseChoiceState(state, artifact, 1, source), state);
  for (const patch of [{artifact_id: 'different'}, {artifact_revision: 2}, {revision: true}, {newer_id: artifact},
    {choices: [{...state.choices[0], id: '../bad'}]}, {choices: state.choices.concat(state.choices)}, {choices: [{...state.choices[0], instruction: 'x'.repeat(1001)}]}, {revision: 1}]) {
    assert.throws(() => parseChoiceState({...state, ...patch}, artifact, 1, source));
  }
  assert.deepEqual(parseChoiceState({...state, revision: 1, selection: receipt}, artifact, 1, source).selection, receipt);
});
test('foreign or malformed task receipts never become a successful selection', () => {
  for (const patch of [{source_task_id: 'foreign'}, {artifact_id: 'foreign'}, {task_id: source}, {task_status: 'invented'},
    {queue_state: 'done'}, {created_at: 'invalid'}, {revision: false}]) assert.throws(() => parseChoiceReceipt({...receipt, ...patch}, artifact, source));
  assert.equal(choiceTaskPending(receipt), true);
  assert.equal(choiceTaskPending({...receipt, task_status: 'completed_unverified'}), false);
});
test('persisted requests are bounded and account/identity/result storage remains separate', () => {
  assert.equal(validChoiceRequest(request), true);
  for (const patch of [{request_key: 'short'}, {choice_id: 'x'.repeat(41)}, {artifact_revision: true}, {selection_revision: -1}]) assert.equal(validChoiceRequest({...request, ...patch}), false);
  assert.notEqual(choicePendingKey('account-a|daily', artifact), choicePendingKey('account-b|daily', artifact));
  assert.notEqual(choicePendingKey('account-a|daily', artifact), choicePendingKey('account-a|work', artifact));
});
test('selection uses product API with CSRF and fixed credentials; never sends arbitrary option text', async () => {
  const c: Connection = {...connection, session: {accessToken: 's'.repeat(64), expiresAt: new Date(Date.now() + 60000).toISOString(), userId: 'user_' + 'a'.repeat(32), tenantId: 'tenant', credentialId: 'c'.repeat(32)}};
  const {api, calls} = harness([() => json({token: 'csrf', identities: [{id: 'daily'}]}), () => json(receipt, 201)], c);
  c.identity = 'work'; c.session!.accessToken = 'changed';
  assert.deepEqual(await api.choose(request), receipt);
  assert.equal(calls[1].url, 'https://choice-tests.invalid/api/artifacts/art_fixture/choices');
  assert.equal(calls[1].headers.get('Authorization'), 'Bearer ' + 's'.repeat(64));
  assert.equal(calls[1].headers.get('X-Wearing-Identity'), 'daily');
  assert.equal(calls[1].headers.get('X-Wearing-Token'), 'csrf');
  assert.deepEqual(calls[1].body, request);
});
test('network uncertainty preserves same key for explicit retry with no automatic second POST', async () => {
  const h = harness([() => json({token: 'csrf', identities: [{id: 'daily'}]}), () => {throw Error('private trace');}, () => json(receipt)]);
  await assert.rejects(h.api.choose(request), (e: unknown) => e instanceof ApiError && e.status === 0 && !e.message.includes('private'));
  assert.equal(h.calls.length, 2);
  assert.deepEqual(await h.api.choose(request), receipt);
  assert.deepEqual(h.calls[1].body, h.calls[2].body);
});
test('wrong successful receipt is ambiguous and not cleared as an ordinary client rejection', async () => {
  const h = harness([() => json({token: 'csrf', identities: [{id: 'daily'}]}), () => json({...receipt, choice_id: 'other'})]);
  await assert.rejects(h.api.choose(request), (e: unknown) => e instanceof ApiError && e.status === 0);
});
test('conflict is returned without silently rereading and resubmitting changed revision', async () => {
  const h = harness([() => json({token: 'csrf', identities: [{id: 'daily'}]}), () => json({detail: '选择状态已变化'}, 409)]);
  await assert.rejects(h.api.choose(request), (e: unknown) => e instanceof ApiError && e.status === 409);
  assert.equal(h.calls.length, 2);
});
