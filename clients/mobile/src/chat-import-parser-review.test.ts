/** Independent fixture-based checks. Every message and attachment is synthetic. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {parseChatImport, parseChatText, strictUTF8} from './chat-import-parser';

const fixture = (name: string) => new Uint8Array(readFileSync(new URL(
  `../test-fixtures/chat-import/${name}`, import.meta.url)));

test('real ZIP container yields bounded transcript and honest unimported attachments', async () => {
  const preview = await parseChatImport(fixture('合成选定聊天.zip'), '微信分享.zip');
  assert.equal(preview.messages.length, 3);
  assert.deepEqual(preview.authors, ['测试用户', '测试同事']);
  assert.equal(preview.start, '2026年10月9日 10:30');
  assert.equal(preview.end, '2026年10月9日 10:32');
  assert.equal(preview.attachments[0].name, '附件/说明.txt');
  assert.equal(preview.attachments[0].sha256, null);
  assert.ok(preview.messages.every(message => message.attachments.length === 0));
  assert.equal(preview.messages[1].author, '测试同事');
  assert.match(preview.messages[2].text, /不要自动发送消息/);
});

for (const name of ['path-traversal.zip', 'ambiguous.zip', 'nested.zip', 'case-alias.zip', 'bad-date.zip']) {
  test(`reject unsafe or ambiguous imported container: ${name}`, async () => {
    await assert.rejects(parseChatImport(fixture(name), name));
  });
}

test('cancellation during decompression prevents returning a usable preview', async () => {
  let calls = 0;
  await assert.rejects(parseChatImport(fixture('合成选定聊天.zip'), '聊天.zip', () => ++calls === 1));
});

test('unsupported UTF16, overlong UTF8 and UTF8 surrogate encodings never become replacement text', () => {
  for (const bytes of [[0xff,0xfe,0x61,0], [0xc0,0xaf], [0xed,0xa0,0x80], [0xf4,0x90,0x80,0x80]]) {
    assert.throws(() => strictUTF8(new Uint8Array(bytes)));
  }
});

test('plain text supports BOM CRLF while preserving quoted instructions as text', () => {
  const original = new TextDecoder().decode(fixture('合成聊天记录.txt'));
  const preview = parseChatText(new TextEncoder().encode('\uFEFF' + original.replaceAll('\n', '\r\n')));
  assert.equal(preview.messages.length, 3);
  assert.match(preview.messages[0].text, /合成测试/);
  assert.equal(preview.messages[1].sent_at, '2026年10月9日 10:31');
});
