import assert from 'node:assert/strict';
import {test} from 'node:test';
import {ApiError} from './core';
import {OngoingManagementApi, ongoingActions, ongoingControlBody, ongoingStatus, parseOngoing, scheduleRule} from './ongoing-management';
import {goalDraft, initialScheduleForm, scheduleDraft, wallClock, wallTimeToInstant} from './ongoing-management-forms';

const connection = {endpoint: 'https://pajio.example/', identity: 'daily'};
const stamp = '2026-10-07T13:00:00+00:00';
const goal = {id: 'goal_1', identity_id: 'daily', revision: 3, objective: '整理搬家安排', boundaries: '先查资料，付款前确认', success_criteria: '给出可执行的时间表',
  status: 'paused', used_steps: 3, max_steps: 100, next_step: '', reason: '先暂停一下', updated_at: stamp, notes: [], steps: []};
const schedule = {id: 'schedule_1', identity_id: 'daily', revision: 2, status: 'active', reason: '', updated_at: stamp, next_run: '2026-10-08T01:00:00Z',
  schedule: {title: '每日简报', instruction: '整理今日待办和日程', kind: 'cron', timezone: 'Asia/Shanghai', cron: '0 9 * * *', at: null}, occurrences: []};
const bootstrap = {version: '0.2.0', deployment: 'local', token: 'csrf-token', identities: [{id: 'daily'}]};
const detail = () => parseOngoing(goal, 'goals', 'daily', goal.id, true);
type Call = {path: string; method: string; headers: Headers; body: any};
function fake(handler: (call: Call, index: number) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const api = new OngoingManagementApi(connection, (async (input, init) => {
    const call = {path: new URL(String(input)).pathname, method: init?.method || 'GET', headers: new Headers(init?.headers), body: init?.body ? JSON.parse(String(init.body)) : null};
    calls.push(call);
    assert.equal(call.headers.get('X-Wearing-Identity'), 'daily');
    assert.equal(init?.redirect, 'error');
    assert.ok(init?.signal);
    return handler(call, calls.length - 1);
  }) as typeof fetch);
  return {api, calls};
}

test('ongoing list and detail are identity scoped reads and never create a chat or change a record', async () => {
  const {api, calls} = fake(call => Response.json(call.path === '/api/goals' ? [goal] : goal));
  assert.equal((await api.list('goals'))[0].title, '整理搬家安排');
  assert.equal((await api.detail('goals', goal.id)).goal?.limit, 100);
  assert.deepEqual(calls.map(call => [call.path, call.method, call.body]), [['/api/goals', 'GET', null], ['/api/goals/goal_1', 'GET', null]]);
});
test('detail refuses wrong identity, wrong object, malformed history or unsupported status', () => {
  assert.throws(() => parseOngoing({...goal, identity_id: 'work'}, 'goals', 'daily'), /当前身份/);
  assert.throws(() => parseOngoing(goal, 'goals', 'daily', 'other'), /完整安排/);
  assert.throws(() => parseOngoing({...goal, status: 'invented'}, 'goals', 'daily'), /完整安排/);
  assert.throws(() => parseOngoing({...goal, steps: [{}]}, 'goals', 'daily', goal.id, true), /完整安排/);
  assert.throws(() => parseOngoing({...goal, notes: [{id: 1, content: 3, created_at: stamp}]}, 'goals', 'daily', goal.id, true), /完整安排/);
  assert.throws(() => parseOngoing({...goal, revision: 0}, 'goals', 'daily'), /完整安排/);
});
test('schedule facts retain correct zone, rule and actual occurrence task ids', () => {
  const item = parseOngoing({...schedule, occurrences: [{id: 4, task_id: 'task_4', status: 'dispatched', task_status: 'running', due_at: stamp, output: '', reason: ''}]}, 'schedules', 'daily', schedule.id, true);
  assert.equal(item.runs[0].taskId, 'task_4');
  assert.equal(item.schedule?.timezone, 'Asia/Shanghai');
  assert.equal(scheduleRule(item), '每天 09:00');
  assert.equal(ongoingStatus(item.status, item.kind), '已开启');
  assert.throws(() => parseOngoing({...schedule, schedule: {...schedule.schedule, timezone: 'no/such-zone'}}, 'schedules', 'daily'), /完整安排/);
  assert.throws(() => parseOngoing({...schedule, next_run: 'yesterday'}, 'schedules', 'daily'), /完整安排/);
});
test('life-change details describe real record scope and limit rather than a fabricated next run', () => {
  const item = parseOngoing({...schedule, next_run: null, schedule: {...schedule.schedule, kind: 'life_change', cron: null,
    changes: {record_kinds: ['task', 'event'], max_runs_per_day: 12}}}, 'schedules', 'daily');
  assert.equal(scheduleRule(item), '待办、日程有变化时 · 每天最多 12 次');
  assert.equal(item.schedule?.nextRun, null);
  assert.throws(() => parseOngoing({...schedule, schedule: {...schedule.schedule, kind: 'life_change', changes: {record_kinds: ['unknown'], max_runs_per_day: 12}}}, 'schedules', 'daily'), /完整安排/);
});
test('history guards and terminal states limit controls', () => {
  assert.deepEqual(ongoingActions(parseOngoing({...goal, status: 'completed'}, 'goals', 'daily')), []);
  assert.deepEqual(ongoingActions(parseOngoing({...schedule, status: 'cancelled'}, 'schedules', 'daily')), []);
  assert.ok(!ongoingActions(parseOngoing(goal, 'goals', 'daily')).includes('complete'));
  assert.ok(ongoingActions(detail()).includes('complete'));
  const unknownRun = {...detail(), runs: [{id: 'task_1', taskId: 'task_1', status: 'connection_lost', at: stamp, summary: ''}]};
  assert.ok(!ongoingActions(unknownRun).includes('complete'));
  assert.ok(!ongoingActions(unknownRun).includes('resume'));
});
test('finishing a goal requires explicit concrete evidence, preserving revision', () => {
  assert.throws(() => ongoingControlBody(detail(), {action: 'complete', note: '好'}), /三个字/);
  assert.deepEqual(ongoingControlBody(detail(), {action: 'complete', note: '  时间表已收到并核对  '}), {revision: 3, action: 'complete', note: '时间表已收到并核对', add_steps: 0});
});
test('resume never increases budget implicitly; limits and noninteger extensions are rejected', () => {
  const limited = parseOngoing({...goal, status: 'limited', used_steps: 100}, 'goals', 'daily');
  assert.throws(() => ongoingControlBody(limited, {action: 'resume'}), /填写愿意增加/);
  assert.deepEqual(ongoingControlBody(limited, {action: 'resume', addSteps: 25}), {revision: 3, action: 'resume', note: '', add_steps: 25});
  for (const addSteps of [-1, 1.5, 901, NaN, Infinity]) assert.throws(() => ongoingControlBody(limited, {action: 'resume', addSteps}), /检查补充/);
  assert.throws(() => ongoingControlBody(detail(), {action: 'note', note: '新的安排', addSteps: 2}), /检查补充/);
});
test('goal mutation uses bootstrap, CSRF and exact revision and verifies updated receipt', async () => {
  const {api, calls} = fake(call => Response.json(call.path === '/api/bootstrap' ? bootstrap : {...goal, revision: 4, status: 'active'}));
  const receipt = await api.control(detail(), {action: 'resume'});
  assert.equal(receipt.status, 'active');
  assert.equal(receipt.historyLoaded, false);
  assert.deepEqual(calls.map(call => [call.path, call.method]), [['/api/bootstrap', 'GET'], ['/api/goals/goal_1/control', 'POST']]);
  assert.equal(calls[1].headers.get('X-Wearing-Token'), 'csrf-token');
  assert.deepEqual(calls[1].body, {revision: 3, action: 'resume', note: '', add_steps: 0});
});
test('schedule pause uses PATCH with no extra permissions or fabricated goal fields', async () => {
  const {api, calls} = fake(call => Response.json(call.path === '/api/bootstrap' ? bootstrap : {...schedule, revision: 3, status: 'paused', next_run: null}));
  const receipt = await api.control(parseOngoing(schedule, 'schedules', 'daily'), {action: 'pause'});
  assert.equal(receipt.status, 'paused');
  assert.deepEqual(calls[1].body, {revision: 2, action: 'pause'});
  assert.equal(calls[1].method, 'PATCH');
  assert.equal(calls[1].path, '/api/schedules/schedule_1');
});
test('in-flight double tap never sends a second mutation', async () => {
  let resolve!: (response: Response) => void;
  const gate = new Promise<Response>(done => {resolve = done;});
  const {api, calls} = fake(call => call.path === '/api/bootstrap' ? Response.json(bootstrap) : gate);
  const first = api.control(detail(), {action: 'resume'});
  await assert.rejects(api.control(detail(), {action: 'resume'}), /正在保存/);
  resolve(Response.json({...goal, revision: 4, status: 'active'}));
  await first;
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
});
test('a conflict never fetches a fresh revision and silently repeats the intent', async () => {
  const {api, calls} = fake(call => call.path === '/api/bootstrap' ? Response.json(bootstrap) : Response.json({detail: '已有新变化，请刷新。'}, {status: 409}));
  await assert.rejects(api.control(detail(), {action: 'resume'}), (error: unknown) => error instanceof ApiError && error.status === 409);
  assert.equal(calls.length, 2);
});
test('network failure leaves outcome uncertain and does not automatically retry a write', async () => {
  const {api, calls} = fake(call => {if (call.path === '/api/bootstrap') return Response.json(bootstrap); throw new Error('lost response');});
  await assert.rejects(api.control(detail(), {action: 'resume'}), /先刷新确认状态/);
  assert.equal(calls.length, 2);
});
test('CSRF failure retries only once with the same revision and intent', async () => {
  const {api, calls} = fake(call => call.path === '/api/bootstrap' ? Response.json(bootstrap) : Response.json({detail: '不能操作'}, {status: 403}));
  await assert.rejects(api.control(detail(), {action: 'resume'}), (error: unknown) => error instanceof ApiError && error.status === 403);
  assert.equal(calls.length, 4);
  assert.deepEqual(calls[1].body, calls[3].body);
});
test('bad identity, invalid path, unadvanced receipt or untrusted bootstrap are rejected', async () => {
  const {api, calls} = fake(call => Response.json(call.path === '/api/bootstrap' ? bootstrap : goal));
  await assert.rejects(api.control({...detail(), identity: 'work'}, {action: 'resume'}), /当前身份/);
  await assert.rejects(api.detail('goals', '../../elsewhere'), /完整安排/);
  assert.equal(calls.length, 0);
  await assert.rejects(api.control(detail(), {action: 'resume'}), /完整安排/);
  const wrong = fake(() => Response.json({...bootstrap, identities: [{id: 'work'}]}));
  await assert.rejects(wrong.api.control(detail(), {action: 'resume'}), /当前身份/);
  assert.equal(wrong.calls.length, 1);
});
test('list rejects mixed identities and duplicate ids instead of silently dropping records', async () => {
  await assert.rejects(fake(() => Response.json([goal, {...goal, id: 'goal_2', identity_id: 'work'}])).api.list('goals'), /当前身份/);
  await assert.rejects(fake(() => Response.json([goal, goal])).api.list('goals'), /完整安排/);
  assert.deepEqual(await fake(() => Response.json({items: []})).api.list('schedules'), []);
});

const key = '74c6b51a-f94e-4b52-832e-40de79df0ab6';
const goalInput = {title: '整理搬家安排', brief: '比较报价和时间', boundaries: '只查资料，付款前确认', success: '收到日期和报价清单', steps: '12'};
const timeInput = {title: '每日简报', instruction: '整理今日待办和日程', repeat: 'daily' as const, timezone: 'Asia/Shanghai', date: '2026-10-08', time: '09:00', weekday: 5};
test('goal creation requires user-entered boundaries, success criteria and an explicit integer limit', () => {
  assert.deepEqual(goalDraft(goalInput), {objective: '整理搬家安排\n\n比较报价和时间', boundaries: '只查资料，付款前确认', success_criteria: '收到日期和报价清单', max_steps: 12});
  for (const steps of ['', '0', '1.5', '-2', '1001', 'NaN']) assert.throws(() => goalDraft({...goalInput, steps}), /轮次/);
  assert.throws(() => goalDraft({...goalInput, boundaries: ' '}), /允许/);
  assert.throws(() => goalDraft({...goalInput, success: ' '}), /完成/);
  assert.throws(() => goalDraft({...goalInput, brief: 'x'.repeat(2000)}), /2000/);
});
test('once schedule resolves the stated zone, validates future time and rejects DST gaps or ambiguity', () => {
  assert.equal(wallTimeToInstant('2026-10-08', '09:00', 'Asia/Shanghai'), '2026-10-08T01:00:00.000Z');
  assert.equal(wallTimeToInstant('2026-10-08', '09:00', 'Asia/Kathmandu'), '2026-10-08T03:15:00.000Z');
  assert.deepEqual(wallClock(new Date('2026-10-08T01:00:00Z'), 'Asia/Shanghai'), {date: '2026-10-08', time: '09:00'});
  assert.throws(() => wallTimeToInstant('2026-03-08', '02:30', 'America/New_York'), /不存在/);
  assert.throws(() => wallTimeToInstant('2026-11-01', '01:30', 'America/New_York'), /重复/);
  assert.throws(() => wallTimeToInstant('2026-02-30', '09:00', 'Asia/Shanghai'), /不存在/);
  assert.throws(() => scheduleDraft({...timeInput, repeat: 'once'}, undefined, Date.parse('2026-10-08T02:00:00Z')), /已经过去/);
  assert.throws(() => scheduleDraft({...timeInput, timezone: 'random/zone'}), /有效时区/);
  const draft = scheduleDraft({...timeInput, repeat: 'once'}, undefined, Date.parse('2026-10-07T00:00:00Z'));
  assert.equal(draft.at, '2026-10-08T01:00:00.000Z'); assert.equal(draft.cron, null);
});
test('daily and weekly contracts preserve wall-clock intent and populate real fields', () => {
  const daily = scheduleDraft(timeInput), weekly = scheduleDraft({...timeInput, repeat: 'weekly'});
  assert.equal(daily.cron, '0 9 * * *'); assert.equal(weekly.cron, '0 9 * * 5');
  assert.equal(daily.kind, 'cron'); assert.equal(daily.timezone, 'Asia/Shanghai');
  assert.throws(() => scheduleDraft({...timeInput, repeat: 'weekly', weekday: 7}), /星期/);
  assert.throws(() => scheduleDraft({...timeInput, time: '25:00'}), /24 小时/);
  const prefill = initialScheduleForm({id: 'test', title: '测试简报', instruction: '整理已授权资料', repeat: 'weekly', time: '17:00', weekday: 5}, undefined, Date.parse(stamp));
  assert.equal(prefill.time, '17:00'); assert.equal(prefill.weekday, 5); assert.equal(prefill.title, '测试简报');
});
test('editing advanced arrangements preserves hidden controls and related goal until an explicit rule change', () => {
  const original = parseOngoing({...schedule, schedule: {...schedule.schedule, kind: 'life_change', cron: null, grace_minutes: 240, goal_id: 'goal_1',
    changes: {record_kinds: ['task'], max_runs_per_day: 3, debounce_seconds: 90, cooldown_minutes: 30}}}, 'schedules', 'daily');
  const fields = initialScheduleForm(undefined, original);
  assert.equal(fields.repeat, 'existing');
  const edited = scheduleDraft({...fields, title: '修改名称'}, original.schedule?.draft);
  assert.equal(edited.grace_minutes, 240); assert.equal(edited.goal_id, 'goal_1'); assert.deepEqual(edited.changes, original.schedule?.draft.changes);
  const converted = scheduleDraft({...fields, repeat: 'daily'}, original.schedule?.draft);
  assert.equal(converted.goal_id, null); assert.equal(converted.changes, null); assert.equal(converted.grace_minutes, 240);
});
test('creating a goal sends an explicit request key and never resumes it as a side effect', async () => {
  const {api, calls} = fake(call => Response.json(call.path === '/api/bootstrap' ? bootstrap : {...goal, revision: 1, used_steps: 0}));
  const receipt = await api.createGoal(goalDraft(goalInput), key);
  assert.equal(receipt.status, 'paused');
  assert.deepEqual(calls.map(call => [call.path, call.method]), [['/api/bootstrap', 'GET'], ['/api/goals', 'POST']]);
  assert.deepEqual(calls[1].body, {...goalDraft(goalInput), request_key: key});
  assert.equal((await api.createGoal(goalDraft(goalInput), key)).id, goal.id);
  assert.equal(calls.length, 2);
  await assert.rejects(api.createGoal({...goalDraft(goalInput), max_steps: 24}, key), /原来的回执/);
});
test('unknown create receipt is retried only explicitly with the same key and unchanged payload', async () => {
  let writes = 0;
  const {api, calls} = fake(call => {
    if (call.path === '/api/bootstrap') return Response.json(bootstrap);
    if (++writes === 1) throw new Error('lost response');
    return Response.json(schedule);
  });
  const draft = scheduleDraft(timeInput);
  await assert.rejects(api.createSchedule(draft, key), /先刷新确认状态/);
  assert.equal(writes, 1);
  await assert.rejects(api.createSchedule({...draft, title: '其他安排'}, key), /原来的回执/);
  await api.createSchedule(draft, key);
  assert.deepEqual(calls[1].body, calls[2].body);
  assert.deepEqual(calls[2].body, {schedule: draft, request_key: key});
});
test('concurrent creation is single-flight and a wrong-scope receipt remains unconfirmed', async () => {
  let resolve!: (response: Response) => void;
  const gate = new Promise<Response>(done => {resolve = done;});
  const {api, calls} = fake(call => call.path === '/api/bootstrap' ? Response.json(bootstrap) : gate);
  const first = api.createSchedule(scheduleDraft(timeInput), key);
  await assert.rejects(api.createSchedule(scheduleDraft(timeInput), key), /正在保存/);
  resolve(Response.json({...schedule, identity_id: 'other'}));
  await assert.rejects(first, (error: unknown) => error instanceof ApiError && error.status === 0);
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
});
test('schedule edit carries the exact revision and complete spec; conflicts are not silently overwritten', async () => {
  const item = parseOngoing(schedule, 'schedules', 'daily', schedule.id, true), draft = scheduleDraft({...timeInput, repeat: 'weekly'});
  const {api, calls} = fake(call => Response.json(call.path === '/api/bootstrap' ? bootstrap : {...schedule, revision: 3, schedule: draft}));
  assert.equal((await api.editSchedule(item, draft)).schedule?.cron, '0 9 * * 5');
  assert.deepEqual(calls[1].body, {revision: 2, action: 'edit', schedule: draft});
  assert.equal(calls[1].path, '/api/schedules/schedule_1'); assert.equal(calls[1].method, 'PATCH');
  await assert.rejects(api.editSchedule({...item, identity: 'other'}, draft), /完整安排/);
  await assert.rejects(api.editSchedule({...item, status: 'cancelled'}, draft), /已经结束/);
  const conflicting = fake(call => call.path === '/api/bootstrap' ? Response.json(bootstrap) : Response.json({detail: '已有新变化'}, {status: 409}));
  await assert.rejects(conflicting.api.editSchedule(item, draft), (error: unknown) => error instanceof ApiError && error.status === 409);
  assert.equal(conflicting.calls.length, 2);
});
