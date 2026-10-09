import {test} from 'node:test';
import assert from 'node:assert/strict';
import {HoldVoiceGesture, type HoldVoiceCallbacks, type HoldVoiceTiming} from './hold-voice';

class Clock implements HoldVoiceTiming {
  time = 0;
  nextId = 0;
  jobs = new Map<number, {at: number; callback: () => void}>();
  now = () => this.time;
  setTimeout = (callback: () => void, delayMs: number) => {
    const id = ++this.nextId;
    this.jobs.set(id, {at: this.time + delayMs, callback});
    return id;
  };
  clearTimeout = (handle: unknown) => {this.jobs.delete(handle as number);};
  advance(ms: number) {
    const until = this.time + ms;
    for (;;) {
      const next = [...this.jobs].filter(([, job]) => job.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      this.time = next[1].at;
      this.jobs.delete(next[0]);
      next[1].callback();
    }
    this.time = until;
  }
}

function fixture(overrides: Partial<HoldVoiceCallbacks> = {}) {
  const clock = new Clock(), events: string[] = [];
  const gesture = new HoldVoiceGesture({
    onPhase: phase => events.push(phase),
    onStart: () => events.push('start'),
    onCommit: () => events.push('commit'),
    onCancel: () => events.push('cancel'),
    onShortPress: () => events.push('short'),
    ...overrides,
  }, clock);
  return {clock, events, gesture};
}

test('holding starts at 220ms, and release at 600ms commits exactly once', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin(); clock.advance(219);
  assert.equal(gesture.phase, 'pressing');
  assert.deepEqual(events, ['pressing']);
  clock.advance(1);
  assert.deepEqual(events, ['pressing', 'listening', 'start']);
  clock.advance(380); gesture.release(); gesture.release(); gesture.cancel();
  assert.deepEqual(events, ['pressing', 'listening', 'start', 'idle', 'commit']);
  assert.equal(clock.jobs.size, 0);
});

test('a brief tap never starts recording and leaves no delayed start', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin(); clock.advance(219); gesture.release(); clock.advance(1000);
  assert.deepEqual(events, ['pressing', 'idle', 'short']);
  assert.equal(gesture.phase, 'idle');
  assert.equal(clock.jobs.size, 0);
});

test('a started hold shorter than 600ms cancels before the short-press hint', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin(); clock.advance(599); gesture.release();
  assert.deepEqual(events, ['pressing', 'listening', 'start', 'idle', 'cancel', 'short']);
});

test('swiping up before the start threshold cannot lose the cancellation intent', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin(); clock.advance(50); gesture.move(-64); clock.advance(1000); gesture.release();
  assert.deepEqual(events, ['pressing', 'cancelling', 'idle']);
  assert.equal(clock.jobs.size, 0);
});

test('sliding back after an early upward move starts once after the delay', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin(); gesture.move(-80); clock.advance(300);
  gesture.move(-40);
  assert.equal(gesture.phase, 'cancelling');
  gesture.move(-39);
  assert.equal(gesture.phase, 'listening');
  clock.advance(300); gesture.release();
  assert.deepEqual(events, ['pressing', 'cancelling', 'listening', 'start', 'idle', 'commit']);
});

test('sliding back before the delay returns to pressing until the normal start time', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin(); clock.advance(40); gesture.move(-70); clock.advance(40); gesture.move(0);
  assert.equal(gesture.phase, 'pressing');
  clock.advance(139); assert.ok(!events.includes('start'));
  clock.advance(1); assert.equal(events.filter(event => event === 'start').length, 1);
  gesture.cancel();
});

test('upward cancellation uses hysteresis and can recover without restarting recording', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin(); clock.advance(700);
  gesture.move(-63); assert.equal(gesture.phase, 'listening');
  gesture.move(-64); assert.equal(gesture.phase, 'cancelling');
  gesture.move(-45); gesture.move(-40); assert.equal(gesture.phase, 'cancelling');
  gesture.move(-39); assert.equal(gesture.phase, 'listening');
  gesture.move(Number.NaN); gesture.move(Number.NEGATIVE_INFINITY);
  gesture.release();
  assert.equal(events.filter(event => event === 'start').length, 1);
  assert.equal(events.filter(event => event === 'commit').length, 1);
  assert.ok(!events.includes('cancel'));
});

test('release in the cancellation region cancels without transcription or a tap hint', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin(); clock.advance(700); gesture.move(-80); gesture.release(); gesture.release();
  assert.deepEqual(events, ['pressing', 'listening', 'start', 'cancelling', 'idle', 'cancel']);
});

test('gesture loss before or after recording starts never commits', () => {
  for (const elapsed of [40, 800]) {
    const {clock, events, gesture} = fixture();
    gesture.begin(); clock.advance(elapsed); gesture.cancel(); gesture.cancel(); gesture.release(); clock.advance(1000);
    assert.equal(gesture.phase, 'idle');
    assert.equal(clock.jobs.size, 0);
    assert.ok(!events.includes('commit'));
    assert.ok(!events.includes('short'));
    assert.equal(events.filter(event => event === 'cancel').length, elapsed >= 220 ? 1 : 0);
  }
});

test('dispose cancels an active hold and permanently ignores further input', () => {
  for (const elapsed of [100, 800]) {
    const {clock, events, gesture} = fixture();
    gesture.begin(); clock.advance(elapsed); gesture.dispose();
    const completed = [...events];
    gesture.begin(); gesture.move(-80); gesture.release(); gesture.cancel(); gesture.dispose(); clock.advance(1000);
    assert.deepEqual(events, completed);
    assert.equal(gesture.phase, 'idle');
    assert.equal(clock.jobs.size, 0);
    assert.ok(!events.includes('commit'));
  }
});

test('repeated begin does not reset elapsed time, and the next gesture starts cleanly', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin(); clock.advance(400); gesture.begin(); clock.advance(200); gesture.release();
  gesture.begin(); clock.advance(10); gesture.release();
  assert.equal(events.filter(event => event === 'commit').length, 1);
  assert.equal(events.filter(event => event === 'short').length, 1);
});

test('a delayed or stale timer cannot start or commit a finished gesture', () => {
  const {clock, events, gesture} = fixture();
  gesture.begin();
  const oldCallback = [...clock.jobs.values()][0].callback;
  clock.time = 900; gesture.release();
  assert.deepEqual(events, ['pressing', 'idle', 'short']);
  gesture.begin(); oldCallback();
  assert.equal(gesture.phase, 'pressing');
  assert.ok(!events.includes('start'));
  clock.advance(220); gesture.cancel();
});

test('a phase observer can cancel before recording begins without a late start', () => {
  const clock = new Clock(), events: string[] = [];
  let gesture: HoldVoiceGesture;
  gesture = new HoldVoiceGesture({
    onPhase: phase => {events.push(phase); if (phase === 'listening') gesture.cancel();},
    onStart: () => events.push('start'), onCommit: () => events.push('commit'),
    onCancel: () => events.push('cancel'), onShortPress: () => events.push('short'),
  }, clock);
  gesture.begin(); clock.advance(1000); gesture.release();
  assert.deepEqual(events, ['pressing', 'listening', 'idle']);
});

test('terminal callbacks cannot reenter the same gesture or create a duplicate commit', () => {
  const clock = new Clock();
  let gesture: HoldVoiceGesture, commits = 0;
  gesture = new HoldVoiceGesture({
    onPhase: () => {}, onStart: () => {}, onCancel: () => {}, onShortPress: () => {},
    onCommit: () => {commits++; gesture.begin(); gesture.release();},
  }, clock);
  gesture.begin(); clock.advance(700); gesture.release();
  assert.equal(commits, 1);
  assert.equal(gesture.phase, 'idle');
  assert.equal(clock.jobs.size, 0);
});
