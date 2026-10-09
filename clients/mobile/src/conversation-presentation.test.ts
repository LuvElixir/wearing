import assert from 'node:assert/strict';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import {canSubmitConversation, conversationFontScale, conversationTextScaleScript, isDeviceOffline} from './conversation-presentation';

test('only known network loss is offline, and LAN use does not require public internet', () => {
  assert.equal(isDeviceOffline({}), false);
  assert.equal(isDeviceOffline({type: 'UNKNOWN', isConnected: false}), false);
  assert.equal(isDeviceOffline({type: 'NONE'}), true);
  assert.equal(isDeviceOffline({type: 'WIFI', isConnected: false}), true);
  assert.equal(isDeviceOffline({type: 'WIFI', isConnected: true}), false);
});

test('reconnecting permits an explicit send without treating offline, loading or a duplicate tap as submitted', () => {
  const ready = {text: '帮我整理资料', sending: false, offline: false, ready: true};
  assert.equal(canSubmitConversation({...ready, offline: true}), false);
  assert.equal(canSubmitConversation({...ready, ready: false}), false);
  assert.equal(canSubmitConversation({...ready, sending: true}), false);
  assert.equal(canSubmitConversation({...ready, text: '   '}), false);
  assert.equal(canSubmitConversation(ready), true);
});

test('system text sizes update a retained page without touching its draft or viewport', () => {
  const styles = new Map<string, string>();
  const document = {documentElement: {style: {setProperty: (key: string, value: string) => styles.set(key, value)}}};
  const draft = {pageId: 'page-one', contextKey: 'daily', text: '明天帮我整理', ackSeq: 7};
  const context = {document, window: {draft}};
  runInNewContext(conversationTextScaleScript(2), context);
  assert.equal(styles.get('--app-font-scale'), '2');
  assert.deepEqual(draft, {pageId: 'page-one', contextKey: 'daily', text: '明天帮我整理', ackSeq: 7});
  runInNewContext(conversationTextScaleScript(1), context);
  assert.equal(styles.get('--app-font-scale'), '1');
  assert.equal(conversationFontScale(Number.NaN), 1);
  assert.equal(conversationFontScale(Infinity), 1);
  assert.equal(conversationFontScale(-10), .85);
  runInNewContext(conversationTextScaleScript(2), {document: {documentElement: null}});
});
