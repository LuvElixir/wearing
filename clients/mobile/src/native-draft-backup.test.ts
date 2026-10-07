import {test} from 'node:test';
import assert from 'node:assert/strict';
import type {Store} from './core';
import {NativeDraftBackup} from './native-draft-backup';

class Memory implements Pick<Store, 'get' | 'put'> {
  data = new Map<string, unknown>();
  async get<T>(key: string) {return structuredClone(this.data.get(key) ?? null) as T | null;}
  async put(key: string, value: unknown) {this.data.set(key, structuredClone(value));}
}
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => {resolve = done;});
  return {promise, resolve};
}
const scope = 'native-conversation-draft:https://wearing.example/|daily';
const contextKey = JSON.stringify({identity: 'daily', goal: null, life: null});
const draft = (text: string) => ({text, contextKey});
function fixture() {
  const store = new Memory(); let next = 0;
  const create = (key = scope) => new NativeDraftBackup(store, key, () => 'backup-' + ++next);
  return {store, create};
}

test('each saved version is unique and an old receipt cannot clear newer identical text', async () => {
  const f = fixture(), backups = f.create();
  const first = await backups.save(draft('原话')), second = await backups.save(draft('原话'));
  assert.notEqual(first.id, second.id);
  assert.equal(await backups.clear(first.id), false); assert.deepEqual(await backups.load(), second);
  assert.equal(await backups.clear(second.id), true); assert.equal(await backups.load(), null);
});

test('a remount waits for the old pending write before restoring and writing new input', async () => {
  const f = fixture(), old = f.create(), gate = deferred(), started = deferred();
  const put = f.store.put.bind(f.store); let first = true;
  f.store.put = async (key, value) => {if (first) {first = false; started.resolve(); await gate.promise;} await put(key, value);};
  const oldSave = old.save(draft('旧页尚未保存完的输入')); await started.promise;
  const next = f.create(), restored = next.load(), newSave = next.save(draft('新页输入'));
  let restoredEarly = false; void restored.then(() => {restoredEarly = true;});
  await Promise.resolve(); assert.equal(restoredEarly, false);
  gate.resolve(); const prior = await oldSave;
  assert.deepEqual(await restored, prior);
  const latest = await newSave; assert.deepEqual(await next.load(), latest);
  assert.equal(await old.clear(prior.id), false); assert.deepEqual(await old.load(), latest);
});

test('an old clear already waiting on storage cannot race past a remount save', async () => {
  const f = fixture(), old = f.create(), previous = await old.save(draft('已确认的旧输入'));
  const gate = deferred(), started = deferred(), get = f.store.get.bind(f.store); let first = true;
  f.store.get = async <T>(key: string) => {if (first) {first = false; started.resolve(); await gate.promise;} return get<T>(key);};
  const clear = old.clear(previous.id); await started.promise;
  const next = f.create(), save = next.save(draft('随后输入的新内容'));
  gate.resolve(); assert.equal(await clear, true);
  const saved = await save; assert.deepEqual(await next.load(), saved);
});

test('a late completion clears only its captured version after another screen has saved', async () => {
  const f = fixture(), old = f.create(), sent = await old.save(draft('已发送'));
  const next = f.create(), newDraft = await next.save(draft('下一条还未发出'));
  assert.equal(await old.clear(sent.id), false); assert.deepEqual(await next.load(), newDraft);
});

test('independent identities do not block each other behind a pending write', async () => {
  const f = fixture(), gate = deferred(), started = deferred(), put = f.store.put.bind(f.store);
  f.store.put = async (key, value) => {if (key === scope) {started.resolve(); await gate.promise;} await put(key, value);};
  const daily = f.create().save(draft('日常')); await started.promise;
  const foreign = f.create('native-conversation-draft:https://wearing.example/|overseas');
  const other = await foreign.save({text: '另一身份', contextKey: JSON.stringify({identity: 'overseas'})});
  assert.deepEqual(await foreign.load(), other); gate.resolve(); await daily;
});

test('failed writes reject honestly and do not poison the shared queue or erase an older version', async () => {
  const f = fixture(), old = f.create(), previous = await old.save(draft('已保存'));
  const put = f.store.put.bind(f.store); let fail = true;
  f.store.put = async (key, value) => {if (fail) {fail = false; throw new Error('disk full');} await put(key, value);};
  await assert.rejects(old.save(draft('未保存')), /disk full/);
  const next = f.create(); assert.deepEqual(await next.load(), previous);
  const current = await next.save(draft('重试成功')); assert.equal(await old.clear(previous.id), false);
  assert.deepEqual(await next.load(), current);
});

test('a failed clear retains the exact backup for later recovery', async () => {
  const f = fixture(), backups = f.create(), saved = await backups.save(draft('仍然保留'));
  const put = f.store.put.bind(f.store);
  f.store.put = async () => {throw new Error('storage unavailable');};
  await assert.rejects(backups.clear(saved.id), /storage unavailable/);
  assert.deepEqual(await f.create().load(), saved); f.store.put = put;
  assert.equal(await backups.clear(saved.id), true);
});

test('legacy backups receive one persisted version without losing their text or context', async () => {
  const f = fixture(); await f.store.put(scope, draft('升级前的未确认输入'));
  const a = f.create(), b = f.create(), [first, second] = await Promise.all([a.load(), b.load()]);
  assert.deepEqual(first, second); assert.equal(first?.text, '升级前的未确认输入'); assert.ok(first?.id);
  assert.deepEqual(await f.store.get(scope), first); assert.equal(await b.clear(first!.id), true);
});

test('failed migration preserves the legacy backup and can recover on the next mount', async () => {
  const f = fixture(), legacy = draft('旧草稿'); await f.store.put(scope, legacy);
  const put = f.store.put.bind(f.store); f.store.put = async () => {throw new Error('disk full');};
  await assert.rejects(f.create().load(), /disk full/); assert.deepEqual(await f.store.get(scope), legacy);
  f.store.put = put; assert.equal((await f.create().load())?.text, legacy.text);
});

test('queued saves capture values before callers mutate their objects', async () => {
  const f = fixture(), backups = f.create(), value = draft('原始输入');
  const saving = backups.save(value); value.text = '调用后的变更';
  const saved = await saving; assert.equal(saved.text, '原始输入');
  saved.text = '修改返回对象'; assert.equal((await backups.load())?.text, '原始输入');
});

test('invalid data is rejected without replacing a recoverable backup', async () => {
  const f = fixture(), backups = f.create(), prior = await backups.save(draft('保留'));
  await assert.rejects(backups.save(draft('x'.repeat(12001))));
  await assert.rejects(backups.save({text: 'x', contextKey: ''}));
  assert.deepEqual(await backups.load(), prior); assert.equal(await backups.clear(''), false);
  await f.store.put(scope, {id: 4, text: '原文', contextKey});
  await assert.rejects(backups.load()); assert.deepEqual(await f.store.get(scope), {id: 4, text: '原文', contextKey});
});
