import {test} from 'node:test';
import assert from 'node:assert/strict';
import {defaultOutfit, wardrobeKey, WardrobeSession} from './wardrobe';

function memory() {
  const data = new Map<string, unknown>();
  return {data, async get<T>(key: string) {return data.get(key) as T ?? null;}, async put(key: string, value: unknown) {data.set(key, value);}};
}
test('a new identity starts with the bear and does not write an unchanged default choice', async () => {
  const store = memory(), session = new WardrobeSession(store, 'daily');
  assert.equal(session.snapshot().companion, 'bear');
  await session.load();
  assert.equal(session.snapshot().ready, true);
  assert.equal(session.snapshot().outfit, defaultOutfit);
  assert.equal(session.snapshot().companion, 'bear');
  assert.equal(store.data.size, 0);
  assert.equal(await session.save(defaultOutfit), true);
  assert.equal(session.snapshot().companion, 'bear');
  assert.equal(store.data.size, 0);
});
test('legacy symbol mode restores its outfit and now displays the bear without rewriting storage', async () => {
  const store = memory();
  await store.put('wardrobe:v1:daily', {version: 1, outfit: 'oat-knit'});
  const migrated = new WardrobeSession(store, 'daily'); await migrated.load();
  assert.equal(migrated.snapshot().outfit, 'oat-knit');
  assert.equal(migrated.snapshot().companion, 'bear');
  const saved = {version: 2, outfit: 'rose-dot', companion: 'symbol'};
  await store.put(wardrobeKey('daily'), saved);
  const reopened = new WardrobeSession(store, 'daily'); await reopened.load();
  assert.equal(reopened.snapshot().companion, 'bear');
  assert.equal(reopened.snapshot().outfit, 'rose-dot');
  assert.deepEqual(store.data.get(wardrobeKey('daily')), saved);
  assert.equal(await reopened.save('cream-moon'), true);
  assert.deepEqual(store.data.get(wardrobeKey('daily')), {version: 2, outfit: 'cream-moon', companion: 'bear'});
  assert.deepEqual(store.data.get('wardrobe:v1:daily'), {version: 1, outfit: 'oat-knit'});
});
test('a chosen outfit survives reopening and is isolated by identity and service', async () => {
  const store = memory();
  const first = new WardrobeSession(store, 'https://one.example/|daily');
  await first.load(); await first.save('peach-check');
  const reopened = new WardrobeSession(store, first.scope);
  const otherIdentity = new WardrobeSession(store, 'https://one.example/|work');
  const otherService = new WardrobeSession(store, 'https://two.example/|daily');
  await Promise.all([reopened.load(), otherIdentity.load(), otherService.load()]);
  assert.equal(reopened.snapshot().outfit, 'peach-check');
  assert.equal(reopened.snapshot().companion, 'bear');
  assert.equal(otherIdentity.snapshot().outfit, defaultOutfit);
  assert.equal(otherIdentity.snapshot().companion, 'bear');
  assert.equal(otherService.snapshot().outfit, defaultOutfit);
  assert.equal(otherService.snapshot().companion, 'bear');
});
test('failed saving preserves the worn outfit and permits retry', async () => {
  const store = memory(); let fail = true;
  const session = new WardrobeSession({...store, async put(key, value) {if (fail) throw Error('disk'); await store.put(key, value);}}, 'daily');
  await session.load(); assert.equal(await session.save('rose-dot'), false);
  assert.equal(session.snapshot().outfit, defaultOutfit); assert.match(session.snapshot().error, /没保存/);
  assert.equal(session.snapshot().companion, 'bear');
  fail = false; assert.equal(await session.save('rose-dot'), true);
  assert.equal(session.snapshot().outfit, 'rose-dot'); assert.equal(session.snapshot().companion, 'bear'); assert.equal(session.snapshot().error, '');

});
test('read failure cannot overwrite an unread preference, retry restores it', async () => {
  const store = memory(); let fail = true;
  await store.put('wardrobe:v1:daily', {version: 1, outfit: 'oat-knit'});
  const session = new WardrobeSession({...store, async get<T>(key: string) {if (fail) throw Error('busy'); return store.get<T>(key);}}, 'daily');
  await session.load(); assert.equal(session.snapshot().ready, false);
  assert.equal(await session.save('rose-dot'), false);
  fail = false; await session.load(); assert.equal(session.snapshot().outfit, 'oat-knit'); assert.equal(session.snapshot().companion, 'bear');
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
  assert.equal(first.snapshot().companion, 'bear'); assert.equal(next.snapshot().companion, 'bear');
});
test('unknown outfits and incompatible saved versions use the default without deleting data', async () => {
  const store = memory();
  for (const saved of [{version: 2, outfit: 'missing', companion: 'bear'}, {version: 2, outfit: 'rose-dot', companion: 'missing'}, {version: 3, outfit: 'rose-dot', companion: 'bear'}, null]) {
    await store.put(wardrobeKey('daily'), saved);
    const session = new WardrobeSession(store, 'daily'); await session.load();
    assert.equal(session.snapshot().outfit, defaultOutfit);
    assert.equal(session.snapshot().companion, 'bear');
    assert.equal(store.data.get(wardrobeKey('daily')), saved);
  }
});
