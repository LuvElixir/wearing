import assert from 'node:assert/strict';
import test from 'node:test';
import {measureVoice, voiceErrorCode, voiceErrorMessage, type VoiceDiagnostic} from './voice-diagnostics';

test('native exceptions never become input messages or diagnostic payloads', async () => {
  const failure = new Error("FunctionCallException: Calling 'finalizeAsync' failed\nSQLiteErrorException: database is locked (/private/user-recording.m4a:471)");
  const events: VoiceDiagnostic[] = [];
  await assert.rejects(measureVoice('save', async () => {throw failure;}, event => events.push(event)), error => error === failure);
  assert.equal(voiceErrorCode(failure), 'storage_busy');
  assert.equal(voiceErrorMessage(failure, '保存暂时未完成，可以重试。'), '保存暂时未完成，可以重试。');
  assert.equal(events[0].code, 'storage_busy');
  assert.deepEqual(Object.keys(events[0]).sort(), ['code', 'elapsedMs', 'outcome', 'stage']);
  assert.doesNotMatch(JSON.stringify(events), /private|m4a|finalizeAsync/);
});

test('known microphone and no-speech errors remain actionable', () => {
  assert.equal(voiceErrorMessage(new Error('NotAllowedError'), '未完成'), '麦克风未获允许，可以改用文字输入。');
  assert.equal(voiceErrorMessage(new Error('没有听清这段话，录音已保留。可以重录或用文字输入。'), '未完成'), '没有听清，可以再试一次或打字。');
  assert.equal(voiceErrorMessage(new Error('远端错误 token=secret'), '暂时未完成'), '暂时未完成');
});

test('diagnostic observer failure cannot corrupt an otherwise successful operation', async () => {
  assert.equal(await measureVoice('upload', async () => 'asset', () => {throw new Error('observer unavailable');}), 'asset');
});
