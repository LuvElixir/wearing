import assert from 'node:assert/strict';
import test from 'node:test';
import type {ActivityItem, ActivitySnapshot} from './core';
import {activityEntrySummary, activityPresentation, groupActivityItems} from './activity-presentation';

function item(status: string, bucket: ActivityItem['bucket'] = 'results', updated_at = '2026-10-07T10:00:00Z'): ActivityItem {
  return {task_id: status, goal_id: null, source: 'task', status, bucket, label: '', title: status, summary: '', version: 'a'.repeat(64), updated_at, unread: bucket === 'results'};
}

test('failed and stopped API results never acquire a success tick or a result action', () => {
  for (const status of ['failed', 'stopped', 'closed_by_user', 'unknown_future_status']) {
    const shown = activityPresentation({...item(status), label: '已有结果'});
    assert.notEqual(shown.icon, 'check');
    assert.notEqual(shown.tone, 'success');
    assert.notEqual(shown.action, '查看结果');
    assert.notEqual(shown.label, '已有结果');
  }
  assert.equal(activityPresentation(item('failed')).action, '查看原因');
  assert.equal(activityPresentation(item('stopped')).label, '已停止');
  assert.equal(activityPresentation({...item('stopped'), label: '已撤回'}).label, '已撤回');
});

test('returned output and verified outcomes have distinct evidence signals', () => {
  const returned = activityPresentation(item('completed_unverified'));
  assert.equal(returned.label, '结果已返回');
  assert.equal(returned.icon, 'file');
  assert.equal(returned.action, '查看结果');
  assert.notEqual(returned.tone, 'success');
  const verified = activityPresentation(item('verified'));
  assert.equal(verified.label, '已核对');
  assert.equal(verified.icon, 'check');
});

test('terminal status takes precedence over an inconsistent transport bucket', () => {
  assert.equal(activityPresentation(item('failed', 'active')).kind, 'failed');
  assert.equal(activityPresentation(item('stopped', 'attention')).group, 'history');
});

test('server detail is preserved for approval delivery and stopped-running states', () => {
  const approval = {...item('waiting_for_approval', 'attention'), label: '确认送达待核对'};
  assert.equal(activityPresentation(approval).label, approval.label);
  assert.equal(activityPresentation({...item('stopping', 'active'), label: '正在停止'}).kind, 'active');
  assert.equal(activityPresentation({...item('waiting_for_approval', 'active'), label: '正在核对接续'}).group, 'active');
});

test('older unresolved work stays ahead of recent finished work without mutating the snapshot', () => {
  const entries = [item('verified'), item('failed'), item('running', 'active', '2026-10-06T10:00:00Z'), item('waiting_for_approval', 'attention', '2026-10-05T10:00:00Z'), item('draft', 'waiting')];
  const initial = entries.map(entry => entry.task_id);
  const groups = groupActivityItems(entries);
  assert.deepEqual(groups.map(group => group.key), ['attention', 'active', 'waiting', 'history']);
  assert.equal(groups[0].items[0].status, 'waiting_for_approval');
  assert.equal(groups[1].items[0].status, 'running');
  assert.deepEqual(entries.map(entry => entry.task_id), initial);
  assert.equal(groups[3].items.length, 2);
});

test('summary counts unread terminal updates without promising successful results', () => {
  const snapshot: ActivitySnapshot = {checked_at: '2026-10-07T10:00:00Z', total: 22, unread: 22, counts: {attention: 0, active: 0, waiting: 0, results: 22}, has_more: true, items: [item('failed')]};
  assert.equal(activityEntrySummary(snapshot), '22 条新进展');
  assert.equal(activityEntrySummary({...snapshot, total: 23, counts: {...snapshot.counts, attention: 1}}), '1 件事等你处理');
  assert.equal(activityEntrySummary({...snapshot, total: 25, counts: {...snapshot.counts, active: 1, waiting: 2}}), '1 件事正在推进 · 2 件已排队');
});
