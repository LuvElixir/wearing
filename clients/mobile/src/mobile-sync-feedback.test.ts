import assert from 'node:assert/strict';
import {test} from 'node:test';
import {feedbackAfterSynchronization, feedbackAfterSyncFailure, type MobileFeedback} from './mobile-sync-feedback';

test('an empty-queue recovery clears the old synchronization outage', () => {
  const outage: MobileFeedback = {text: '暂时连不上 Pajio，请检查连接后重试。', source: 'sync'};
  assert.deepEqual(feedbackAfterSynchronization(outage, 0), {text: '', source: 'sync'});
});

test('an identical message from a user action stays unresolved after network recovery', () => {
  const action: MobileFeedback = {text: '暂时连不上 Pajio，请检查连接后重试。', source: 'action'};
  assert.equal(feedbackAfterSynchronization(action, 0), action);
});

test('completed uploads do not dismiss an unconfirmed edit or a failed local save', () => {
  for (const text of ['修改尚未确认。输入保留在当前页面。', '草稿还没保存好，请保留输入并检查存储空间。']) {
    const action: MobileFeedback = {text, source: 'action'};
    for (const sent of [0, 2]) assert.equal(feedbackAfterSynchronization(action, sent), action);
  }
});

test('a newer action wins when a synchronization completes after the action', () => {
  let feedback: MobileFeedback = {text: '暂时没连上，原件仍在本机。', source: 'sync'};
  const complete = () => {feedback = feedbackAfterSynchronization(feedback, 3);};
  feedback = {text: '录音暂时没保存好，请保留页面。', source: 'action'};
  complete();
  assert.deepEqual(feedback, {text: '录音暂时没保存好，请保留页面。', source: 'action'});
});

test('a successful upload replaces a queued-record notice with its actual receipt count', () => {
  const queued: MobileFeedback = {text: '已留在本机。连接后会同步给 Pajio。', source: 'sync'};
  assert.deepEqual(feedbackAfterSynchronization(queued, 2), {text: '2 条记录已同步，Pajio 也能接着看。', source: 'sync'});
});

test('a dismissed action allows a later synchronization receipt, without an invented receipt on an empty queue', () => {
  const dismissed: MobileFeedback = {text: '', source: 'action'};
  assert.deepEqual(feedbackAfterSynchronization(dismissed, 1), {text: '1 条记录已同步，Pajio 也能接着看。', source: 'sync'});
  assert.deepEqual(feedbackAfterSynchronization(dismissed, 0), {text: '', source: 'sync'});
});

test('the next empty synchronization retires its previous receipt without changing the input state', () => {
  const receipt: MobileFeedback = Object.freeze({text: '1 条记录已同步，Pajio 也能接着看。', source: 'sync'});
  assert.deepEqual(feedbackAfterSynchronization(receipt, 0), {text: '', source: 'sync'});
  assert.equal(receipt.text, '1 条记录已同步，Pajio 也能接着看。');
});


test('a failed background refresh cannot retire an unresolved save warning through later recovery', () => {
  const action: MobileFeedback = {text: '草稿还没保存好，请保留输入。', source: 'action'};
  const failed = feedbackAfterSyncFailure(action, '连接暂时断开');
  assert.equal(failed, action);
  assert.equal(feedbackAfterSynchronization(failed, 0), action);
  assert.deepEqual(feedbackAfterSyncFailure({text: '', source: 'action'}, '连接暂时断开'), {text: '连接暂时断开', source: 'sync'});
});
