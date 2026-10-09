import assert from 'node:assert/strict';
import test from 'node:test';
import {parseShareManifest, SHARE_LIMITS, ShareEntry, ShareIntakeQueue, ShareManifest, shareWebUrl} from './share-intake-model';

const ID = '11111111-2222-4333-8444-555555555555';
const manifest = (changes: Partial<ShareManifest> = {}): ShareManifest => ({version: 1, id: ID, createdAt: '2026-10-08T00:00:00Z', text: '明天开会前整理这些资料', files: [], ...changes});
const file = {path: '0.pdf', name: '资料.pdf', mime: 'application/pdf', size: 123};
function fixture() {
  let entries: ShareEntry[] = [], failWrite = false, discarded = 0, staged = 0;
  const io = {
    async read() {return structuredClone(entries);},
    async write(value: ShareEntry[]) {if (failWrite) throw new Error('disk full'); entries = structuredClone(value);},
    async stage(m: ShareManifest) {staged++; return m.files.map((f, i) => ({...f, id: `${m.id}-${i}`, uri: `file:///private/${m.id}/${f.path}`}));},
    async discard() {discarded++;},
  };
  return {io, queue: new ShareIntakeQueue(io), get entries() {return entries;}, get staged() {return staged;}, get discarded() {return discarded;}, failWrite(value: boolean) {failWrite = value;}};
}

test('manifest rejects traversal, duplicate paths, credentials URLs, unsupported content and bounds', () => {
  for (const path of ['../secret', '/private/file.pdf', '0%2fpdf', '0.pdf/secret', '4.pdf']) assert.throws(() => parseShareManifest(manifest({files: [{...file, path}]})));
  assert.throws(() => parseShareManifest(manifest({files: [file, file]})));
  for (const size of [0, -1, 0.5, SHARE_LIMITS.fileBytes + 1]) assert.throws(() => parseShareManifest(manifest({files: [{...file, size}]})));
  assert.throws(() => parseShareManifest(manifest({files: [{...file, mime: 'text/html'}]})));
  assert.throws(() => parseShareManifest(manifest({files: [0, 1, 2].map(i => ({...file, path: `${i}.pdf`, size: 11 * 1024 * 1024}))})));
  assert.throws(() => parseShareManifest(manifest({text: 'x'.repeat(12001)})));
  assert.throws(() => parseShareManifest(manifest({text: ''})));
  for (const url of ['file:///private/data', 'javascript:alert(1)', 'https://token:secret@example.com']) assert.throws(() => shareWebUrl(url));
  assert.equal(shareWebUrl('https://example.com/a?q=b'), 'https://example.com/a?q=b');
});

test('intake only queues local content; explicit action is required', async () => {
  const f = fixture();
  await f.queue.ingest(manifest({files: [file]}), ['content://test/file']);
  assert.equal(f.staged, 1); assert.equal(f.entries[0].state, 'pending'); assert.equal(f.entries[0].scope, undefined);
  assert.equal((await f.queue.list('account-A|identity-A')).length, 1);
});

test('duplicates including simultaneous receive preserve original data and never stage twice', async () => {
  const f = fixture();
  await Promise.all([f.queue.ingest(manifest(), []), f.queue.ingest(manifest({text: 'changed'}), [])]);
  assert.equal(f.entries.length, 1); assert.equal(f.staged, 1); assert.equal(f.entries[0].text, manifest().text);
});

test('cancel survives queue restart and receiving the same native request again', async () => {
  const f = fixture(); await f.queue.ingest(manifest(), []); await f.queue.cancel(ID);
  const recovered = new ShareIntakeQueue(f.io); await recovered.ingest(manifest(), []);
  assert.equal((await recovered.list('A')).length, 0); assert.equal(f.entries[0].state, 'cancelled'); assert.equal(f.discarded, 1);
});

test('scope/action bind is durable before dispatch and blocks another identity after uncertain result', async () => {
  const f = fixture(); await f.queue.ingest(manifest(), []);
  await assert.rejects(f.queue.submit(ID, 'account-A|work', 'draft', async request => {
    assert.equal(f.entries[0].scope, request.scope); assert.equal(f.entries[0].state, 'bound');
    throw new Error('receipt lost');
  }));
  const recovered = new ShareIntakeQueue(f.io);
  assert.equal((await recovered.list('account-B|work')).length, 0);
  await assert.rejects(recovered.submit(ID, 'account-B|work', 'draft', async r => r));
  await assert.rejects(recovered.submit(ID, 'account-A|work', 'capture', async r => r));
  await assert.rejects(recovered.cancel(ID));
  const receipt = await recovered.submit(ID, 'account-A|work', 'draft', async r => r);
  assert.equal(receipt.requestId, ID); assert.equal(f.entries[0].state, 'completed');
});

test('bad receipt leaves queue recoverable and never deletes attachments', async () => {
  const f = fixture(); await f.queue.ingest(manifest({files: [file]}), ['file:///test.pdf']);
  await assert.rejects(f.queue.submit(ID, 'A', 'capture', async () => ({requestId: ID, scope: 'B'})));
  assert.equal(f.entries[0].state, 'bound'); assert.equal(f.entries[0].files.length, 1); assert.equal(f.discarded, 0);
});

test('restart after receiving draft but before receipt uses stable id for idempotent writer', async () => {
  const f = fixture(); await f.queue.ingest(manifest(), []);
  const drafts = new Map<string, unknown>(); let first = true;
  const writer = async (request: {requestId: string; scope: string}) => {
    drafts.set(request.requestId, request);
    if (first) {first = false; throw new Error('interrupted');}
    return request;
  };
  await assert.rejects(f.queue.submit(ID, 'A', 'draft', writer));
  await new ShareIntakeQueue(f.io).submit(ID, 'A', 'draft', writer);
  assert.equal(drafts.size, 1); assert.equal(f.entries[0].text, '');
  await f.queue.submit(ID, 'A', 'draft', async () => {throw new Error('must not send again');});
});

test('failed durable scope write cannot invoke downstream handler', async () => {
  const f = fixture(); await f.queue.ingest(manifest(), []); f.failWrite(true);
  let called = false;
  await assert.rejects(f.queue.submit(ID, 'A', 'draft', async r => {called = true; return r;}));
  assert.equal(called, false); assert.equal(f.entries[0].state, 'pending');
});

test('late receipt remains scoped to original identity and repeat cannot resurrect content', async () => {
  const f = fixture(); await f.queue.ingest(manifest(), []);
  let resolve!: (receipt: {requestId: string; scope: string}) => void;
  const request = f.queue.submit(ID, 'A', 'capture', () => new Promise(r => {resolve = r;}));
  await new Promise(r => setTimeout(r, 0)); resolve({requestId: ID, scope: 'A'}); await request;
  await f.queue.ingest(manifest(), []);
  assert.equal((await f.queue.list('B')).length, 0); assert.equal(f.entries[0].scope, 'A'); assert.equal(f.entries[0].files.length, 0);
});

test('queue bounds and attachment action prevent accidental text-only sending', async () => {
  const f = fixture(); await f.queue.ingest(manifest({files: [file]}), ['file:///test.pdf']);
  await assert.rejects(f.queue.submit(ID, 'A', 'draft', async r => r));
  for (let i = 1; i < 8; i++) await f.queue.ingest(manifest({id: `11111111-2222-4333-8444-${String(i).padStart(12, '0')}`}), []);
  await assert.rejects(f.queue.ingest(manifest({id: '11111111-2222-4333-8444-999999999999'}), []));
  assert.equal(f.entries.length, 8);
});

test('chat ZIP can only enter its explicit preview path, never ordinary capture upload', async () => {
  const f = fixture(), zip = {path: '0.zip', name: '合成聊天.zip', mime: 'application/zip', size: 123};
  await f.queue.ingest(manifest({files: [zip]}), ['content://test/zip']);
  let called = false;
  await assert.rejects(f.queue.submit(ID, 'A', 'capture', async r => {called = true; return r;}), /先预览/);
  assert.equal(called, false);
  await f.queue.claimChatImport(ID, 'A'); assert.equal((await f.queue.list('B')).length, 0);
  await assert.rejects(f.queue.claimChatImport(ID, 'B'));
  await f.queue.beginChatImport(ID, 'A'); await assert.rejects(f.queue.cancel(ID));
  await assert.rejects(f.queue.submit(ID, 'A', 'capture', async r => r));
  const restarted = new ShareIntakeQueue(f.io); await restarted.completeChatImport(ID, 'A');
  assert.equal(f.entries[0].state, 'completed'); assert.equal(f.entries[0].files.length, 0);
  await restarted.ingest(manifest({files: [zip]}), []); assert.equal(f.staged, 1);
});
test('a chat preview can be discarded before confirmation, without importing or keeping a private copy', async () => {
  const f = fixture(); await f.queue.ingest(manifest({files: [{path:'0.txt',name:'聊天.txt',mime:'text/plain',size:123}]}), ['content://test/txt']);
  await f.queue.claimChatImport(ID, 'A'); await f.queue.cancel(ID);
  assert.equal(f.discarded, 1); await assert.rejects(f.queue.beginChatImport(ID, 'A'));
});
