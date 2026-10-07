import {test} from 'node:test';
import assert from 'node:assert/strict';
import {defaultOutfit, wardrobeKey, WardrobeSession} from './wardrobe';

function memory() {
  const data = new Map<string, unknown>();
  return {data, async get<T>(key: string) {return data.get(key) as T ?? null;}, async put(key: string, value: unknown) {data.set(key, value);}};
}
test('a chosen outfit survives reopening and is isolated by identity and service', async () => {
  const store = memory();
  const first = new WardrobeSession(store, 'https://one.example/|daily');
  await first.load(); await first.save('peach-check');
  const reopened = new WardrobeSession(store, first.scope);
  const otherIdentity = new WardrobeSession(store, 'https://one.example/|work');
  const otherService = new WardrobeSession(store, 'https://two.example/|daily');
  await Promise.all([reopened.load(), otherIdentity.load(), otherService.load()]);
  assert.equal(reopened.snapshot().outfit, 'peach-check');
  assert.equal(otherIdentity.snapshot().outfit, defaultOutfit);
  assert.equal(otherService.snapshot().outfit, defaultOutfit);
});
test('failed saving preserves the worn outfit and permits retry', async () => {
  const store = memory(); let fail = true;
  const session = new WardrobeSession({...store, async put(key, value) {if (fail) throw Error('disk'); await store.put(key, value);}}, 'daily');
  await session.load(); assert.equal(await session.save('rose-dot'), false);
  assert.equal(session.snapshot().outfit, defaultOutfit); assert.match(session.snapshot().error, /没保存/);
  fail = false; assert.equal(await session.save('rose-dot'), true);
  assert.equal(session.snapshot().outfit, 'rose-dot'); assert.equal(session.snapshot().error, '');
});
test('read failure cannot overwrite an unread preference, retry restores it', async () => {
  const store = memory(); let fail = true;
  await store.put(wardrobeKey('daily'), {version: 1, outfit: 'oat-knit'});
  const session = new WardrobeSession({...store, async get<T>(key: string) {if (fail) throw Error('busy'); return store.get<T>(key);}}, 'daily');
  await session.load(); assert.equal(session.snapshot().ready, false);
  assert.equal(await session.save('rose-dot'), false);
  fail = false; await session.load(); assert.equal(session.snapshot().outfit, 'oat-knit');
});
test('duplicate taps cannot race and late saves cannot change a new identity', async () => {
  const store = memory(); let release!: () => void; let writes = 0;
  const gate = new Promise<void>(resolve => {release = resolve;});
  const first = new WardrobeSession({...store, async put(key, value) {writes++; await gate; await store.put(key, value);}}, 'daily');
  await first.load(); const saving = first.save('cocoa-moon');
  assert.equal(first.snapshot().outfit, defaultOutfit);
  assert.equal(await first.save('rose-dot'), false);
  const next = new WardrobeSession(store, 'work'); await next.load();
  release(); await saving;
  assert.equal(writes, 1); assert.equal(first.snapshot().outfit, 'cocoa-moon'); assert.equal(next.snapshot().outfit, defaultOutfit);
});
test('unknown outfits and incompatible saved versions use the default without deleting data', async () => {
  const store = memory();
  for (const saved of [{version: 1, outfit: 'missing'}, {version: 2, outfit: 'rose-dot'}, null]) {
    await store.put(wardrobeKey('daily'), saved);
    const session = new WardrobeSession(store, 'daily'); await session.load();
    assert.equal(session.snapshot().outfit, defaultOutfit);
    assert.equal(store.data.get(wardrobeKey('daily')), saved);
  }
});
