import {test} from 'node:test';
import assert from 'node:assert/strict';
import {WardrobeTransition, wardrobePreviewReady} from './wardrobe-transition';
import {outfits} from './wardrobe';

function prepared() {
  const transition = new WardrobeTransition('mist-blue');
  transition.select('mist-blue', false);
  transition.loaded(transition.snapshot().requested.key);
  return transition;
}

test('all eight outfits stay unsaveable until their decoded preview is visible and uncovered', () => {
  const transition = prepared();
  for (const outfit of outfits.slice(1)) {
    transition.select(outfit.id, false);
    const request = transition.snapshot();
    assert.equal(request.phase, 'loading');
    assert.equal(wardrobePreviewReady(request, outfit.id), false);
    transition.loaded(request.requested.key);
    assert.equal(transition.snapshot().phase, 'closing');
    assert.equal(transition.snapshot().shown.outfit, request.shown.outfit);
    transition.closed(request.revision);
    assert.equal(transition.snapshot().shown.outfit, outfit.id);
    assert.equal(wardrobePreviewReady(transition.snapshot(), outfit.id), false);
    transition.opened(request.revision);
    assert.equal(wardrobePreviewReady(transition.snapshot(), outfit.id), true);
  }
  // Blue/cream uses the same phases as every other pair, with no film branch.
  transition.select('mist-blue', false);
  const request = transition.snapshot();
  transition.loaded(request.requested.key);
  transition.closed(request.revision);
  transition.opened(request.revision);
  transition.select('cream-moon', false);
  transition.loaded(transition.snapshot().requested.key);
  assert.equal(transition.snapshot().phase, 'closing');
});

test('rapid taps reject stale image loads, failures, and animation completions', () => {
  const transition = prepared();
  transition.select('cream-moon', false);
  const first = transition.snapshot();
  transition.loaded(first.requested.key);
  transition.select('peach-check', false);
  const second = transition.snapshot();
  transition.closed(first.revision);
  transition.opened(first.revision);
  transition.loaded(first.requested.key);
  transition.failed(first.requested.key);
  assert.equal(transition.snapshot(), second);
  transition.loaded(second.requested.key);
  transition.closed(second.revision);
  assert.equal(transition.snapshot().shown.outfit, 'peach-check');
  transition.select('rose-dot', false);
  const last = transition.snapshot();
  transition.opened(second.revision);
  assert.equal(transition.snapshot(), last);
  transition.loaded(last.requested.key);
  transition.closed(last.revision);
  transition.opened(last.revision);
  assert.equal(wardrobePreviewReady(transition.snapshot(), 'rose-dot'), true);
  assert.equal(wardrobePreviewReady(transition.snapshot(), 'peach-check'), false);
});

test('returning to the displayed outfit cancels pending work without decoding it again', () => {
  const transition = prepared();
  const original = transition.snapshot().shown;
  transition.select('cream-moon', false);
  const abandoned = transition.snapshot();
  transition.loaded(abandoned.requested.key);
  transition.select('mist-blue', false);
  transition.closed(abandoned.revision);
  transition.opened(abandoned.revision);
  assert.equal(transition.snapshot().shown, original);
  assert.equal(transition.snapshot().requested, original);
  assert.equal(wardrobePreviewReady(transition.snapshot(), 'mist-blue'), true);
});

test('load failure keeps the last visible outfit and retry ignores the failed frame', () => {
  const transition = prepared();
  transition.select('cocoa-moon', false);
  const failed = transition.snapshot();
  transition.failed(failed.requested.key);
  assert.equal(transition.snapshot().phase, 'error');
  assert.equal(transition.snapshot().shown.outfit, 'mist-blue');
  assert.equal(wardrobePreviewReady(transition.snapshot(), 'cocoa-moon'), false);
  transition.retry();
  const retry = transition.snapshot();
  assert.notEqual(retry.requested.key, failed.requested.key);
  transition.failed(failed.requested.key);
  transition.loaded(failed.requested.key);
  assert.equal(transition.snapshot(), retry);
  transition.loaded(retry.requested.key);
  transition.closed(retry.revision);
  transition.opened(retry.revision);
  assert.equal(wardrobePreviewReady(transition.snapshot(), 'cocoa-moon'), true);
});

test('reduced motion reveals only decoded images and can interrupt an active curtain', () => {
  const transition = prepared();
  transition.select('cream-moon', true);
  const request = transition.snapshot();
  assert.equal(request.shown.outfit, 'mist-blue');
  transition.loaded(request.requested.key);
  assert.equal(wardrobePreviewReady(transition.snapshot(), 'cream-moon'), true);
  transition.select('sage-check', false);
  const animated = transition.snapshot();
  transition.loaded(animated.requested.key);
  assert.equal(transition.snapshot().phase, 'closing');
  transition.select('sage-check', true);
  assert.equal(wardrobePreviewReady(transition.snapshot(), 'sage-check'), true);
  transition.closed(animated.revision);
  assert.equal(wardrobePreviewReady(transition.snapshot(), 'sage-check'), true);
});

test('leaving the stage invalidates callbacks and a new identity has no carried preview', () => {
  const transition = prepared();
  transition.select('rose-dot', false);
  const old = transition.snapshot();
  transition.loaded(old.requested.key);
  transition.cancel();
  const cancelled = transition.snapshot();
  transition.closed(old.revision);
  transition.opened(old.revision);
  transition.loaded(old.requested.key);
  assert.equal(transition.snapshot(), cancelled);
  assert.equal(wardrobePreviewReady(cancelled, 'mist-blue'), true);
  const nextIdentity = new WardrobeTransition('oat-knit');
  nextIdentity.loaded(nextIdentity.snapshot().requested.key);
  assert.equal(wardrobePreviewReady(nextIdentity.snapshot(), 'oat-knit'), true);
});

test('a failed first image can be retried without prematurely enabling save', () => {
  const transition = new WardrobeTransition('mist-blue');
  transition.failed(transition.snapshot().requested.key);
  transition.retry();
  const request = transition.snapshot();
  assert.equal(wardrobePreviewReady(request, 'mist-blue'), false);
  transition.loaded(request.requested.key);
  assert.equal(wardrobePreviewReady(transition.snapshot(), 'mist-blue'), true);
});
