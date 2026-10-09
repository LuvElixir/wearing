import assert from 'node:assert/strict';
import {test} from 'node:test';
import {TabScrollMemory} from './tab-scroll-memory';

function measured(memory: TabScrollMemory, key: string, offset: number) {
  const visit = memory.begin(key);
  memory.viewport(visit, 600); memory.content(visit, 2400);
  memory.restore(visit); memory.interact(visit); memory.record(visit, offset);
  memory.end(visit);
}

test('a returning tab waits for both native sizes and asynchronous content', () => {
  const memory = new TabScrollMemory(); measured(memory, 'account-a:today', 820);
  const visit = memory.begin('account-a:today');
  assert.equal(memory.restore(visit), null);
  memory.viewport(visit, 600); memory.content(visit, 250);
  memory.record(visit, 0);
  assert.equal(memory.restore(visit), null);
  memory.content(visit, 1800);
  assert.equal(memory.restore(visit), 820);
  assert.equal(memory.restore(visit), null);
});

test('user touch takes priority over delayed layout restoration', () => {
  const memory = new TabScrollMemory(); measured(memory, 'a:memory', 800);
  const visit = memory.begin('a:memory');
  memory.viewport(visit, 600); memory.content(visit, 900);
  memory.interact(visit); memory.record(visit, 35);
  memory.content(visit, 2200);
  assert.equal(memory.restore(visit, true), null);
  const next = memory.begin('a:memory'); memory.viewport(next, 600); memory.content(next, 2200);
  assert.equal(memory.restore(next), 35);
});

test('identity and task subtab positions stay independent and stale callbacks are ignored', () => {
  const memory = new TabScrollMemory(); measured(memory, 'a:tasks:tasks', 500);
  measured(memory, 'a:tasks:lists', 200); measured(memory, 'b:tasks:tasks', 100);
  const stale = memory.begin('a:tasks:tasks');
  const active = memory.begin('b:tasks:tasks');
  memory.viewport(stale, 600); memory.content(stale, 3000); memory.interact(stale); memory.record(stale, 900);
  memory.end(stale);
  assert.equal(memory.restore(stale, true), null);
  memory.viewport(active, 600); memory.content(active, 3000);
  assert.equal(memory.restore(active), 100);
  const original = memory.begin('a:tasks:tasks'); memory.viewport(original, 600); memory.content(original, 3000);
  assert.equal(memory.restore(original), 500);
});

test('shortened content clamps after the bounded layout wait and initial events do not erase it', () => {
  const memory = new TabScrollMemory(); measured(memory, 'a:today', 1200);
  const visit = memory.begin('a:today'); memory.viewport(visit, 600); memory.content(visit, 1000);
  assert.equal(memory.restore(visit), null);
  assert.equal(memory.restore(visit, true), 400);
  memory.record(visit, 0);
  memory.record(visit, 400);
  const next = memory.begin('a:today'); memory.viewport(next, 600); memory.content(next, 1000);
  assert.equal(memory.restore(next), 400);
});

test('deep routes never restore or overwrite a top-level position', () => {
  const memory = new TabScrollMemory(); measured(memory, 'a:memory', 750);
  const deep = memory.begin(null); memory.viewport(deep, 600); memory.content(deep, 2400);
  memory.interact(deep); memory.record(deep, 1200);
  assert.equal(memory.restore(deep, true), null);
  const root = memory.begin('a:memory'); memory.viewport(root, 600); memory.content(root, 2400);
  assert.equal(memory.restore(root), 750);
});

test('switching tabs during iOS bottom rubber-band restores the reachable bottom immediately', () => {
  const memory = new TabScrollMemory();
  const tasks = memory.begin('a:tasks:tasks'); memory.viewport(tasks, 600); memory.content(tasks, 1400);
  memory.restore(tasks); memory.interact(tasks);
  memory.record(tasks, 800);
  memory.record(tasks, 937.5); // Leave before the spring settles back to 800.
  memory.end(tasks);
  const other = memory.begin('a:memory'); memory.viewport(other, 600); memory.content(other, 1800);
  memory.restore(other); memory.end(other);
  const returned = memory.begin('a:tasks:tasks'); memory.viewport(returned, 600); memory.content(returned, 1400);
  assert.equal(memory.restore(returned), 800); // No timeout / allowClamping required.
});

test('iOS top rubber-band and a short page retain a valid zero offset', () => {
  const memory = new TabScrollMemory();
  const visit = memory.begin('a:today'); memory.viewport(visit, 600); memory.content(visit, 1400);
  memory.restore(visit); memory.interact(visit); memory.record(visit, -84);
  const top = memory.begin('a:today'); memory.viewport(top, 600); memory.content(top, 1400);
  assert.equal(memory.restore(top), 0);
  memory.interact(top); memory.content(top, 400); memory.record(top, 45);
  const short = memory.begin('a:today'); memory.viewport(short, 600); memory.content(short, 400);
  assert.equal(memory.restore(short), 0);
});

test('scroll callbacks before native sizes do not overwrite an existing reading position', () => {
  const memory = new TabScrollMemory(); measured(memory, 'a:today', 750);
  const early = memory.begin('a:today'); memory.interact(early); memory.record(early, 990);
  memory.viewport(early, 600); memory.record(early, 990); memory.end(early);
  const next = memory.begin('a:today'); memory.viewport(next, 600); memory.content(next, 1600);
  assert.equal(memory.restore(next), 750);
});

test('subpoint native layout rounding does not force the delayed clamp path', () => {
  const memory = new TabScrollMemory();
  const visit = memory.begin('a:tasks:tasks'); memory.viewport(visit, 600); memory.content(visit, 1400.5);
  memory.restore(visit); memory.interact(visit); memory.record(visit, 950);
  const next = memory.begin('a:tasks:tasks'); memory.viewport(next, 600.5); memory.content(next, 1400.5);
  assert.equal(memory.restore(next), 800);
});
