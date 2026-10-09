import assert from 'node:assert/strict';
import {test} from 'node:test';
import {appendActivityPage} from './activity-pages';
import {ApiError, type ActivitySnapshot} from './core';

const page = (id: string, last: boolean): ActivitySnapshot => ({checked_at: '2026-10-07T10:00:00Z', total: 2, unread: 0, counts: {attention: 0, active: 0, waiting: 0, results: 2}, has_more: !last, filtered_total: 2, next_cursor: last ? null : 'page2', revision: 'a'.repeat(64), changed_since: null,
  items: [{task_id: id, goal_id: null, source: 'task', bucket: 'results', status: 'completed_unverified', label: '结果返回', title: id, summary: '', version: 'b'.repeat(64), updated_at: '2026-10-07T10:00:00Z', unread: false}]});

test('history pages retain earlier items and reach a real end without changing totals', () => {
  const result = appendActivityPage(page('first', false), page('second', true));
  assert.deepEqual(result.items.map(item => item.task_id), ['first', 'second']);
  assert.equal(result.total, 2);
  assert.equal(result.has_more, false);
  assert.equal(result.next_cursor, null);
});

test('changed revisions, read states, overlap and short final pages require refresh without losing the current list', () => {
  const previous = page('first', false), next = page('second', true);
  for (const value of [{...next, revision: 'c'.repeat(64)}, {...next, unread: 1}, page('first', true), {...next, items: []}]) {
    assert.throws(() => appendActivityPage(previous, value), error => error instanceof ApiError && error.status === 409);
    assert.equal(previous.items[0].task_id, 'first');
    assert.equal(previous.items.length, 1);
  }
});
