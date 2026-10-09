import assert from 'node:assert/strict';
import test from 'node:test';
import {memoryDraft, memoryDraftKey, persistMemoryDraft, readMemoryDraft, rebaseMemoryDraft, type MemoryDraft} from './memory-drafts';
const draft: MemoryDraft = {version: 1, index: 1, baseText: '原始条目', text: '本机草稿', revision: 'a'.repeat(64)};
test('a conflict rebinds only the exact original rather than replacing the old index', () => {
  const moved = rebaseMemoryDraft(draft, ['新插入', '另一条', '原始条目'], 'b'.repeat(64));
  assert.equal(moved.draft?.index, 2); assert.equal(moved.draft?.text, '本机草稿');
  assert.equal(rebaseMemoryDraft(draft, ['原始条目已改变', '另一条'], 'b'.repeat(64)).draft, null);
  assert.equal(rebaseMemoryDraft(draft, ['本机草稿'], 'b'.repeat(64)).alreadyPresent, true);
});
test('queued drafts survive view refresh and a later clear cannot be overwritten by an older save', async () => {
  let saved: unknown; const store = {put: async (_: string, value: unknown) => {await new Promise(resolve => setTimeout(resolve, value ? 8 : 0)); saved = value;}, get: async <T,>() => saved as T};
  const first = persistMemoryDraft(store, 'one', draft);
  assert.deepEqual(await readMemoryDraft(store, 'one'), draft); await first;
  await Promise.all([persistMemoryDraft(store, 'one', {...draft, text: '更改'}), persistMemoryDraft(store, 'one', null)]);
  assert.equal(saved, null);
});
test('draft scope has identity but no credentials and rejects corrupted input', () => {
  assert.notEqual(memoryDraftKey({endpoint: 'https://pajio.example/', identity: 'daily'}, 'user'), memoryDraftKey({endpoint: 'https://pajio.example/', identity: 'work'}, 'user'));
  assert.equal(memoryDraft({...draft, index: -1}), null);
  assert.equal(memoryDraft({...draft, revision: ''}), null);
});
