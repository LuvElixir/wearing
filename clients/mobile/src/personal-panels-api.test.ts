import assert from 'node:assert/strict';
import {test} from 'node:test';
import {WearingApi} from './core';

const connection = {endpoint: 'https://wearing.example/', identity: 'daily'};
function api(value: unknown, seen: string[] = []) {
  return new WearingApi(connection, (async (url, init) => {
    seen.push(new URL(String(url)).pathname);
    assert.equal(init?.method, 'GET');
    assert.equal(new Headers(init?.headers).get('X-Wearing-Identity'), 'daily');
    return Response.json(value);
  }) as typeof fetch);
}
test('memory review reads the current identity without writing or creating a chat', async () => {
  const value = {identity_id: 'daily', available: true, targets: {user: {enabled: true, entries: ['喜欢安静的地方']}, memory: {enabled: false, entries: []}}};
  const seen: string[] = [];
  assert.deepEqual(await api(value, seen).memory(), value);
  assert.deepEqual(seen, ['/api/memory']);
  await assert.rejects(api({...value, identity_id: 'another'}).memory(), /当前身份/);
  await assert.rejects(api({...value, targets: {user: {enabled: true, entries: [3]}}}).memory(), /完整记忆/);
  assert.equal((await api({identity_id: 'daily', available: false, message: '执行引擎未启动'}).memory()).available, false);
});
test('ongoing review distinguishes real goals from scheduled instructions', async () => {
  const seen: string[] = [];
  assert.deepEqual(await api([{id: 'goal-1', objective: '整理搬家安排', status: 'paused', next_step: '核对时间'}], seen).ongoing('goals'), [{id: 'goal-1', title: '整理搬家安排', status: 'paused', detail: '核对时间'}]);
  assert.deepEqual(seen, ['/api/goals']);
  assert.deepEqual(await api({items: [{id: 'schedule-1', schedule: {title: '日程有变化时留意', kind: 'life_change'}, status: 'active', next_run: null}]}).ongoing('schedules'), [{id: 'schedule-1', title: '日程有变化时留意', status: 'active', detail: '有相关变化时留意'}]);
  await assert.rejects(api({items: [{id: 'bad', status: 'active'}]}).ongoing('schedules'), /完整安排/);
  assert.deepEqual(await api([]).ongoing('goals'), []);
});
