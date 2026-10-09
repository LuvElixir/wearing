import test from 'node:test';
import assert from 'node:assert/strict';
import {createTaskRequestQueue} from './task-request-queue';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => {resolve = done;});
  return {promise, resolve};
}

test('a refresh requested during polling runs afterward exactly once', async () => {
  const queue = createTaskRequestQueue(), read = deferred(), events: string[] = [];
  const background = queue.background(async () => {events.push('read'); await read.promise; events.push('read done');});
  await Promise.resolve();
  const refresh = queue.user(async () => {events.push('refresh');});
  assert.equal(queue.userPending, true);
  assert.equal(await queue.user(async () => {events.push('duplicate');}), false);
  assert.equal(await queue.background(async () => {events.push('poll');}), false);
  read.resolve();
  assert.equal(await background, true);
  assert.equal(await refresh, true);
  assert.deepEqual(events, ['read', 'read done', 'refresh']);
  assert.equal(queue.userPending, false);
});

test('failed polling still permits the queued user action', async () => {
  const queue = createTaskRequestQueue(), read = deferred();
  const background = queue.background(async () => {await read.promise; throw new Error('offline');});
  const failure = assert.rejects(background, /offline/);
  let controls = 0;
  const control = queue.user(async () => {controls++;});
  read.resolve(); await failure;
  assert.equal(await control, true);
  assert.equal(controls, 1);
});

test('closing a page prevents a waiting action from running in another account', async () => {
  const oldQueue = createTaskRequestQueue(), read = deferred();
  const background = oldQueue.background(async () => {await read.promise;});
  await Promise.resolve(); await Promise.resolve();
  let controls = 0;
  const control = oldQueue.user(async () => {controls++;});
  oldQueue.close(); read.resolve();
  await background;
  assert.equal(await control, false);
  assert.equal(await oldQueue.user(async () => {controls++;}), false);
  const nextQueue = createTaskRequestQueue();
  assert.equal(await nextQueue.user(async () => {controls++;}), true);
  assert.equal(controls, 1);
});

test('an uncertain control is not repeated and releases the next read', async () => {
  const queue = createTaskRequestQueue(); let writes = 0;
  await assert.rejects(queue.user(async () => {writes++; throw new Error('unknown acknowledgement');}), /unknown acknowledgement/);
  assert.equal(writes, 1);
  assert.equal(queue.userPending, false);
  assert.equal(await queue.background(async () => {}), true);
});
