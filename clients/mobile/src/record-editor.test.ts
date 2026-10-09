import {test} from 'node:test';
import assert from 'node:assert/strict';
import type {RecordItem} from './core';
import {recordEdit, recordEditChanged, recordPatch, withRecordDraft} from './record-editor';

const note = (patch: Partial<RecordItem> = {}): RecordItem => ({id: 'life_synthetic', kind: 'note', title: '合成笔记', content: '合成笔记正文', timezone: 'Asia/Shanghai', revision: 3, updated_at: '2026-10-07T10:00:00Z', ...patch});
const event = (patch: Partial<RecordItem> = {}): RecordItem => note({kind: 'event', start_at: '2026-10-08', end_at: '2026-10-09', ...patch});

test('opening an editor preserves the observed revision, literal content and original dates', () => {
  const source = event();
  const edit = recordEdit(source);
  assert.deepEqual(edit, {revision: 3, text: source.content, start: '2026-10-08', end: '2026-10-09'});
  edit.text = '尚未保存的修改';
  assert.equal(source.content, '合成笔记正文');
  assert.equal(recordEdit(note({content: ''})).text, '合成笔记');
});

test('editing only an all-day event title never converts date-only values to UTC timestamps', () => {
  const source = event();
  const patch = recordPatch(source, {...recordEdit(source), text: '  全天合成日程\n改了说明  '});
  assert.deepEqual(patch, {title: '全天合成日程', content: '全天合成日程\n改了说明'});
  assert.equal(source.start_at, '2026-10-08');
  assert.equal(source.end_at, '2026-10-09');
});

test('text-only edits preserve timed event offsets and metadata by omitting unchanged time fields', () => {
  const source = event({start_at: '2026-10-08T09:00:00+08:00', end_at: '2026-10-08T10:00:00+08:00'});
  const patch = recordPatch(source, {...recordEdit(source), text: '新说明'});
  assert.deepEqual(patch, {title: '新说明', content: '新说明'});
  assert.equal(Object.hasOwn(patch, 'timezone'), false);
  assert.equal(Object.hasOwn(patch, 'kind'), false);
});

test('explicit time changes produce ordered ISO timestamps for both ends', () => {
  const source = event();
  const patch = recordPatch(source, {...recordEdit(source), start: '2026-10-08T21:30:00+08:00', end: '2026-10-08T22:15:00+08:00'});
  assert.equal(patch.start_at, '2026-10-08T13:30:00.000Z');
  assert.equal(patch.end_at, '2026-10-08T14:15:00.000Z');
  assert.equal(patch.all_day, false);
  assert.equal(source.start_at, '2026-10-08');
});

test('equal, reversed and malformed changed event times are rejected before an API write', () => {
  const source = event();
  for (const [start, end] of [
    ['2026-10-08T10:00:00Z', '2026-10-08T10:00:00Z'],
    ['2026-10-08T11:00:00Z', '2026-10-08T10:00:00Z'],
    ['', '2026-10-09'], ['invalid', '2026-10-09'], ['2026-10-08', 'invalid'],
  ]) assert.throws(() => recordPatch(source, {...recordEdit(source), start, end}), /结束时间需要晚于开始时间/);
});

test('editing one time cannot silently discard the other time or turn an event into a note', () => {
  const source = event({start_at: '2026-10-08T09:00:00Z', end_at: '2026-10-08T10:00:00Z'});
  const patch = recordPatch(source, {...recordEdit(source), end: '2026-10-08T10:30:00Z'});
  assert.equal(patch.start_at, '2026-10-08T09:00:00.000Z');
  assert.equal(patch.end_at, '2026-10-08T10:30:00.000Z');
  assert.equal(Object.hasOwn(patch, 'kind'), false);
});

test('blank edits and oversized content fail while 12000 trimmed characters remain valid', () => {
  const source = note();
  for (const text of ['', ' \n\t ', '字'.repeat(12001)]) {
    assert.throws(() => recordPatch(source, {...recordEdit(source), text}), /请写一点内容，最多 12000 字/);
  }
  const content = '字'.repeat(12000);
  assert.equal(recordPatch(source, {...recordEdit(source), text: `  ${content}\n `}).content, content);
});

test('record patches trim content and bound its first-line title without dropping the full body', () => {
  const text = '头'.repeat(230) + '\n完整第二行';
  const patch = recordPatch(note(), {...recordEdit(note()), text});
  assert.equal(patch.title, '头'.repeat(200));
  assert.equal(patch.content, text);
});

test('note and task editing cannot accidentally modify status, identity, revision or dates', () => {
  for (const source of [note(), note({kind: 'task', completed: true})]) {
    const patch = recordPatch(source, {...recordEdit(source), text: '改正文', start: 'invalid', end: ''});
    assert.deepEqual(patch, {title: '改正文', content: '改正文'});
    assert.equal(source.revision, 3);
  }
});

test('dirty checking distinguishes user content and time changes from a refreshed revision', () => {
  const source = event(), edit = recordEdit(source);
  assert.equal(recordEditChanged(source, edit), false);
  assert.equal(recordEditChanged(source, {...edit, revision: 99}), false);
  assert.equal(recordEditChanged(source, {...edit, text: edit.text + '补充'}), true);
  assert.equal(recordEditChanged(source, {...edit, start: '2026-10-10'}), true);
  assert.equal(recordEditChanged(source, {...edit, end: '2026-10-11'}), true);
});

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}

test('a remounted editor reads only after all older writes for the same record have completed', async () => {
  const key = 'synthetic-same-record';
  const gate = deferred<void>(), entered = deferred<void>();
  let stored = 'old server text';
  const order: string[] = [];
  const first = withRecordDraft(key, async () => {order.push('old instance write 1'); entered.resolve(); await gate.promise; stored = 'first keystroke';});
  await entered.promise;
  const second = withRecordDraft(key, async () => {order.push('old instance write 2'); stored = 'last old-instance edit';});
  const remounted = withRecordDraft(key, async () => {order.push('new instance hydration'); return stored;});
  assert.deepEqual(order, ['old instance write 1']);
  gate.resolve();
  assert.equal(await remounted, 'last old-instance edit');
  await Promise.all([first, second]);
  assert.deepEqual(order, ['old instance write 1', 'old instance write 2', 'new instance hydration']);
  await withRecordDraft(key, async () => {stored = 'new-instance edit';});
  assert.equal(await withRecordDraft(key, async () => stored), 'new-instance edit');
});

test('a slow draft belonging to another identity cannot block current-identity hydration', async () => {
  const gate = deferred<void>(), entered = deferred<void>();
  const oldIdentity = withRecordDraft('https://synthetic.invalid|old|life_1', async () => {entered.resolve(); await gate.promise; return 'old';});
  await entered.promise;
  const fresh = await withRecordDraft('https://synthetic.invalid|new|life_1', async () => 'new identity draft');
  assert.equal(fresh, 'new identity draft');
  gate.resolve();
  assert.equal(await oldIdentity, 'old');
});

test('a failed draft write rejects honestly but releases later recovery reads and writes', async () => {
  const key = 'synthetic-failed-write';
  const gate = deferred<void>(), entered = deferred<void>();
  let stored = 'prior durable input';
  const failed = withRecordDraft(key, async () => {entered.resolve(); await gate.promise; throw new Error('synthetic full disk');});
  const observedFailure = assert.rejects(failed, /synthetic full disk/);
  await entered.promise;
  const read = withRecordDraft(key, async () => stored);
  const recovery = withRecordDraft(key, async () => {stored = 'recovered input';});
  gate.resolve();
  await observedFailure;
  assert.equal(await read, 'prior durable input');
  await recovery;
  assert.equal(await withRecordDraft(key, async () => stored), 'recovered input');
});

test('finishing an older draft cannot remove the queue of a still-pending newer write', async () => {
  const key = 'synthetic-queue-cleanup';
  const gate = deferred<void>(), entered = deferred<void>();
  const order: string[] = [];
  const first = withRecordDraft(key, async () => {order.push('first');});
  const second = withRecordDraft(key, async () => {order.push('second'); entered.resolve(); await gate.promise; order.push('second completed');});
  await first;
  await entered.promise;
  const third = withRecordDraft(key, async () => {order.push('third');});
  assert.deepEqual(order, ['first', 'second']);
  gate.resolve();
  await Promise.all([second, third]);
  assert.deepEqual(order, ['first', 'second', 'second completed', 'third']);
});
