import assert from 'node:assert/strict';
import test from 'node:test';
import {boxKey, Connection, Outbox, Pending, scopeOf, Store} from './core';
import {createShareCaptureHandler, shareDeliveryKey} from './share-intake-delivery';
import {ShareSubmission} from './share-intake-model';

const connection: Connection = {endpoint: 'http://127.0.0.1:8765/', identity: 'daily'};
const scope = scopeOf(connection), id = '11111111-2222-4333-8444-555555555555';
const submission = (count = 0): ShareSubmission => ({requestId: id, scope, text: '分享来的原始文字', files: Array.from({length: count}, (_, index) => ({id: `share-${id}-${index}`, path: `${index}.pdf`, uri: `file:///private/share/${index}.pdf`, name: `资料-${index}.pdf`, size: 3, mime: 'application/pdf'}))});
function fixture() {
  const values = new Map<string, unknown>(); let failBatch = false;
  const store: Store = {async get<T>(key: string) {return structuredClone(values.get(key) ?? null) as T | null;}, async put(key, value) {values.set(key, structuredClone(value));}, async batch(writes) {if (failBatch) throw new Error('disk full'); for (const [key, value] of writes) values.set(key, structuredClone(value));}, async blob() {return new Blob(['pdf']);}};
  return {store, values, outbox: new Outbox(store), failBatch(value: boolean) {failBatch = value;}};
}

test('text and URL only share writes one text-only note with no model request', async () => {
  const f = fixture(); let uploaded = false;
  const handler = createShareCaptureHandler(connection, {store: f.store, outbox: f.outbox, readFile: async () => {throw new Error('no files');}, upload: async () => {uploaded = true; throw new Error('no upload');}});
  const request = {...submission(), text: 'https://example.com/test\n原始文字'};
  assert.deepEqual(await handler(request), {requestId: id, scope});
  const items = await f.outbox.items(scope); assert.equal(items.length, 1); assert.equal(items[0].draft.content, request.text); assert.equal(items[0].organize, false); assert.deepEqual(items[0].media, []); assert.equal(uploaded, false);
});

test('multi-file failure saves each receipt and resumes with the same per-file request id', async () => {
  const f = fixture(), called: string[] = []; let fail = true;
  const upload = async (_c: Connection, request: {id: string; name: string; size: number}) => {
    called.push(request.id); if (request.id.endsWith('-1') && fail) throw new Error('network');
    return {path: `imports/${request.id}/${request.name}`, size: request.size, modified: 100};
  };
  const deps = {store: f.store, outbox: f.outbox, readFile: async () => new Blob(['pdf']), upload};
  await assert.rejects(createShareCaptureHandler(connection, deps)(submission(2)));
  assert.equal((await f.outbox.items(scope)).length, 0);
  fail = false; await createShareCaptureHandler(connection, deps)(submission(2));
  assert.deepEqual(called, [`share-${id}-file-0`, `share-${id}-file-1`, `share-${id}-file-1`]);
  const record = (await f.outbox.items(scope))[0]; assert.equal(record.organize, false); assert.deepEqual(record.media, []);
  assert(record.draft.content.includes(`imports/share-${id}-file-0/资料-0.pdf`)); assert(record.draft.content.includes(`imports/share-${id}-file-1/资料-1.pdf`));
});

test('durable completion is atomic with outbox and survives flush without recreating note', async () => {
  const f = fixture(), handler = createShareCaptureHandler(connection, {store: f.store, outbox: f.outbox, readFile: async () => {throw new Error('no files');}});
  await handler(submission());
  assert.equal((f.values.get(shareDeliveryKey(scope, id)) as {state: string}).state, 'completed');
  await f.outbox.flush(scope, {async upload() {throw new Error('no capture attachment');}, async create(entry: Pending) {return {...entry.draft, id: 'record-1', revision: 1, updated_at: new Date().toISOString()};}}, () => true);
  assert.equal((await f.outbox.items(scope)).length, 0);
  await handler(submission()); assert.equal((await f.outbox.items(scope)).length, 0);
});

test('failed atomic enqueue never reports completion and a restart retries once', async () => {
  const f = fixture(), deps = {store: f.store, outbox: f.outbox, readFile: async () => new Blob(['pdf'])}; f.failBatch(true);
  await assert.rejects(createShareCaptureHandler(connection, deps)(submission()));
  assert.equal((f.values.get(shareDeliveryKey(scope, id)) as {state: string}).state, 'uploading'); assert(!f.values.has(boxKey(scope)));
  f.failBatch(false); await createShareCaptureHandler(connection, deps)(submission()); assert.equal((await f.outbox.items(scope)).length, 1);
});

test('full composed length and invalid names are rejected before any file upload', async () => {
  const f = fixture(); let calls = 0;
  const handler = createShareCaptureHandler(connection, {store: f.store, outbox: f.outbox, readFile: async () => {calls++; return new Blob(['pdf']);}});
  const tooLong = {...submission(1), text: '中'.repeat(12000)};
  await assert.rejects(handler(tooLong)); assert.equal(calls, 0); assert.equal(f.values.size, 0);
  const nameLong = submission(1); nameLong.files[0].name = '中'.repeat(80) + '.pdf';
  await assert.rejects(handler(nameLong)); assert.equal(calls, 0);
});

test('wrong file path/size receipt and changed local bytes never create a note', async () => {
  const f = fixture(), base = {store: f.store, outbox: f.outbox, readFile: async () => new Blob(['pdf'])};
  await assert.rejects(createShareCaptureHandler(connection, {...base, upload: async () => ({path: '../../wrong', size: 3, modified: 100})})(submission(1)));
  await assert.rejects(createShareCaptureHandler(connection, {...base, readFile: async () => new Blob(['changed'])})(submission(1)));
  assert.equal((await f.outbox.items(scope)).length, 0);
});

test('identity change during upload retains original receipt but prevents next file/note', async () => {
  const f = fixture(); let current = true, uploads = 0;
  const handler = createShareCaptureHandler(connection, {store: f.store, outbox: f.outbox, readFile: async () => new Blob(['pdf']), isCurrent: () => current, upload: async (_c, request) => {uploads++; current = false; return {path: `imports/${request.id}/${request.name}`, size: 3, modified: 100};}});
  await assert.rejects(handler(submission(2))); assert.equal(uploads, 1); assert.equal((await f.outbox.items(scope)).length, 0);
  assert.equal((f.values.get(shareDeliveryKey(scope, id)) as {uploaded: unknown[]}).uploaded.length, 1);
  await assert.rejects(handler({...submission(2), scope: 'another-account'})); assert.equal(uploads, 1);
});

test('concurrent handlers and changed content cannot duplicate or silently overwrite', async () => {
  const f = fixture(), deps = {store: f.store, outbox: f.outbox, readFile: async () => new Blob(['pdf'])};
  await Promise.all([createShareCaptureHandler(connection, deps)(submission()), createShareCaptureHandler(connection, deps)(submission())]);
  assert.equal((await f.outbox.items(scope)).length, 1);
  await assert.rejects(createShareCaptureHandler(connection, deps)({...submission(), text: 'different'}));
  assert.equal((await f.outbox.items(scope))[0].draft.content, submission().text);
});
