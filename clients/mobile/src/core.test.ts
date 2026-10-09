import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ActivitySnapshot, activitySnapshot, activitySummary, ApiError, boxKey, endpoint, makeDraft, Outbox, Pending, RecordItem, Store, Transport, WearingApi} from './core';
import {allowsConversationNavigation, conversationLink, nativeConversationLink} from './conversationLink';
class Memory implements Store {
  data = new Map<string, unknown>();
  async get<T>(key: string) {return structuredClone(this.data.get(key) ?? null) as T | null;}
  async put(key: string, value: unknown) {this.data.set(key, structuredClone(value));}
  async batch(values: [string, unknown][]) {for (const [key, value] of values) this.data.set(key, structuredClone(value));}
  async blob() {return new Blob(['synthetic original']);}
}
const scope = 'http://127.0.0.1:8765/|daily';
const entry = (id = 'one'): Pending => ({id, scope, draft: makeDraft('合成验收', 'note'), media: [], uploaded: [], organize: false, state: 'pending', attempts: 0, nextAt: 0, createdAt: '2026-10-04T00:00:00Z'});
const record = {id: 'life_1', revision: 1, updated_at: '2026-10-04T00:00:00Z', ...makeDraft('合成验收', 'note')} as RecordItem;
const success: Transport = {upload: async () => 'asset_1', create: async () => record};
test('only HTTPS remote or clean loopback HTTP roots are accepted', () => {
  assert.equal(endpoint(' https://example.com '), 'https://example.com/'); assert.equal(endpoint('http://127.0.0.1:8765'), 'http://127.0.0.1:8765/');
  for (const value of ['http://example.com/', 'https://user:secret@example.com/', 'https://example.com/?key=secret', 'https://example.com/path', 'file:///tmp/x', 'https://example.com/#x']) assert.throws(() => endpoint(value));
});
test('event dates are zoned, ordered, and cannot silently become a note', () => {
  assert.throws(() => makeDraft('安排', 'event', new Date(100), new Date(0)));
  assert.throws(() => makeDraft('', 'note')); assert.throws(() => makeDraft('x'.repeat(12001), 'note'));
  assert.equal(makeDraft('安排', 'event', new Date(0), new Date(60000)).end_at, '1970-01-01T00:01:00.000Z');
});
test('a failed network keeps the creation and original, backing off before another attempt', async () => {
  const store = new Memory(), outbox = new Outbox(store); await outbox.enqueue(entry());
  let calls = 0; const offline = {...success, create: async () => {calls++; throw new ApiError('offline');}};
  await outbox.flush(scope, offline, () => true, 100); await outbox.flush(scope, offline, () => true, 101);
  assert.equal(calls, 1); const item = (await outbox.items(scope))[0]; assert.equal(item.attempts, 1); assert.equal(item.state, 'pending'); assert.equal(item.nextAt, 5100);
});
test('an ambiguous create response replays the same request key, producing one server record', async () => {
  const store = new Memory(), outbox = new Outbox(store); await outbox.enqueue(entry()); const ids = new Set(); let calls = 0;
  const network: Transport = {...success, create: async item => {ids.add(item.id); if (++calls === 1) throw new ApiError('response lost'); return record;}};
  await outbox.flush(scope, network, () => true, 0); await outbox.flush(scope, network, () => true, 6000);
  assert.equal(ids.size, 1); assert.equal((await outbox.items(scope)).length, 0); assert.deepEqual(await store.get(`receipts:${scope}`), [record]);
});
test('uploaded originals retain stable keys and resume after a restart', async () => {
  const store = new Memory(); let box = new Outbox(store); const item = entry(); item.media = [{id: 'm1', name: '合成.jpg', mime: 'image/jpeg', size: 10}, {id: 'm2', name: '合成2.jpg', mime: 'image/jpeg', size: 10}]; await box.enqueue(item);
  const calls: string[] = []; let fail = true;
  const transport: Transport = {...success, upload: async (_, __, key) => {calls.push(key); if (key.endsWith('-1') && fail) throw new ApiError('offline'); return key;}};
  await box.flush(scope, transport, () => true, 0); assert.deepEqual((await box.items(scope))[0].uploaded, ['one-asset-0']);
  box = new Outbox(store); fail = false; await box.flush(scope, transport, () => true, 6000); assert.deepEqual(calls, ['one-asset-0', 'one-asset-1', 'one-asset-1']);
});
test('parallel synchronization attempts cannot issue the same write concurrently', async () => {
  const store = new Memory(), box = new Outbox(store); await box.enqueue(entry()); let calls = 0;
  const transport = {...success, create: async () => {calls++; await new Promise(resolve => setTimeout(resolve, 10)); return record;}};
  await Promise.all([box.flush(scope, transport, () => true), box.flush(scope, transport, () => true)]); assert.equal(calls, 1);
});
test('a changed identity stops before any new upload or create', async () => {
  const store = new Memory(), box = new Outbox(store); const item = entry(); item.media = [{id: 'm1', name: 'a.jpg', mime: 'image/jpeg', size: 10}, {id: 'm2', name: 'b.jpg', mime: 'image/jpeg', size: 10}]; await box.enqueue(item);
  let current = true; let writes = 0; const transport: Transport = {upload: async () => {current = false; writes++; return 'a';}, create: async () => {writes++; return record;}};
  await box.flush(scope, transport, () => current); assert.equal(writes, 1); assert.equal((await box.items(scope))[0].state, 'pending'); assert.equal(await box.flush(scope, transport, () => current), 0);
});
test('foreign identity entries fail closed instead of being routed to the current server', async () => {
  const store = new Memory(), box = new Outbox(store); await store.put(boxKey(scope), [{...entry(), scope: 'another'}]); await assert.rejects(box.flush(scope, success, () => true));
});
test('permanent validation errors and six failures stop automatic retries without discarding input', async () => {
  const store = new Memory(), box = new Outbox(store); await box.enqueue(entry());
  await box.flush(scope, {...success, create: async () => {throw new ApiError('invalid', 422);}}, () => true); assert.equal((await box.items(scope))[0].state, 'attention');
  await box.retry(scope, 'one'); for (let i = 0; i < 6; i++) await box.flush(scope, {...success, create: async () => {throw new ApiError('offline');}}, () => true, 1000000 * i);
  assert.equal((await box.items(scope))[0].state, 'attention'); assert.equal((await box.items(scope))[0].attempts, 6);
});
test('media limits prevent a queue entry being accepted without usable originals', async () => {
  const box = new Outbox(new Memory()), item = entry(); item.media = [{id: 'x', name: 'x', mime: 'image/jpeg', size: 16 * 1024 * 1024}]; await assert.rejects(box.enqueue(item));
});
test('queue creation and clearing its composer use one atomic storage commit', async () => {
  const store = new Memory(), box = new Outbox(store); await store.put('draft', {text: '合成验收'});
  await box.enqueue(entry(), ['draft', {text: ''}]); assert.deepEqual(await store.get('draft'), {text: ''}); assert.equal((await box.items(scope)).length, 1);
  await box.enqueue(entry()); assert.equal((await box.items(scope)).length, 1);
  await assert.rejects(box.enqueue({...entry(), draft: makeDraft('changed', 'note')}));
});
test('session renewal does not change the key or persist a token in local state', async () => {
  let writes = 0; const keys: string[] = [];
  const api = new WearingApi({endpoint: 'http://127.0.0.1:8765/', identity: 'daily'}, (async (url: string, init: RequestInit) => {
    if (new URL(url).pathname === '/api/bootstrap') return Response.json({version: '0.2.0', deployment: 'local', token: 'synthetic-token', identities: [{id: 'daily'}]});
    keys.push(JSON.parse(init.body as string).request_key); return writes++ === 0 ? Response.json({detail: 'expired'}, {status: 403}) : Response.json(record);
  }) as typeof fetch);
  await api.create(entry()); assert.deepEqual(keys, ['one', 'one']);
});
test('a non-Wearing or missing-identity service is rejected before uploads', async () => {
  const fake = (value: unknown) => (async () => Response.json(value)) as typeof fetch;
  await assert.rejects(new WearingApi({endpoint: 'https://example.com/', identity: 'daily'}, fake({token: 'x'})).bootstrap());
  await assert.rejects(new WearingApi({endpoint: 'https://example.com/', identity: 'other'}, fake({version: '0.2.0', deployment: 'cloud', token: 'x', identities: [{id: 'daily'}]})).bootstrap());
});
test('a network error never promises unsaved edits will synchronize automatically', async () => {
  const api = new WearingApi({endpoint: 'http://127.0.0.1:8765/', identity: 'daily'}, (async () => {throw new Error('offline');}) as typeof fetch);
  await assert.rejects(api.update(record, {content: 'unsaved edit'}), error => error instanceof ApiError && !/已保存|恢复连接后再同步/.test(error.message));
});
test('record conversation links carry identity and revision without note text in the URL', () => {
  const url = new URL(conversationLink('http://127.0.0.1:8787/', 'overseas', {...record, title: 'private title', content: 'private content'}, 'http://127.0.0.1:8787'));
  assert.equal(url.pathname, '/wearing'); assert.equal(url.searchParams.get('identity'), 'overseas');
  assert.equal(url.searchParams.get('life_record'), record.id); assert.equal(url.searchParams.get('life_revision'), '1'); assert.ok(!url.toString().includes('private'));
});


test('native conversation uses App chrome without changing ordinary web links or record scope', () => {
  const native = new URL(nativeConversationLink('https://wearing.example/', 'daily', record));
  assert.equal(native.searchParams.get('host'), 'mobile');
  assert.equal(native.searchParams.get('identity'), 'daily');
  assert.equal(native.searchParams.get('life_record'), record.id);
  assert.equal(native.searchParams.get('life_revision'), String(record.revision));
  assert.equal(native.hash, '#conversation-main');
  assert.equal(new URL(conversationLink('https://wearing.example/', 'daily')).searchParams.has('host'), false);
});
test('activity preview links preserve identity and the exact task without leaking record content', () => {
  const request = {id: 1, target: 'activity' as const, taskId: 'task_123'};
  const local = new URL(conversationLink('http://127.0.0.1:8787/', 'overseas', record, 'http://127.0.0.1:8787', request));
  assert.equal(local.pathname, '/wearing'); assert.equal(local.searchParams.get('identity'), 'overseas');
  assert.equal(local.searchParams.get('activity_task'), 'task_123'); assert.equal(local.searchParams.has('life_record'), false);
  assert.deepEqual([...local.searchParams.keys()], ['identity', 'activity_task']);
  const remote = new URL(conversationLink('https://wearing.example/', 'daily', null, 'http://127.0.0.1:8787', request));
  assert.equal(remote.origin, 'https://wearing.example'); assert.equal(remote.pathname, '/');
  assert.equal(remote.searchParams.get('activity_task'), 'task_123');
  assert.throws(() => conversationLink('https://wearing.example/', 'daily', null, undefined, {...request, taskId: '../foreign'}));
});
test('embedded conversation never delegates external or privileged schemes to the operating system', () => {
  const source = nativeConversationLink('https://wearing.example/', 'daily');
  assert.equal(allowsConversationNavigation(source, source), true);
  assert.equal(allowsConversationNavigation('https://wearing.example/api/artifacts/art_1/preview?identity=daily', source), true);
  assert.equal(allowsConversationNavigation('about:blank', source), true);
  for (const url of ['https://other.example/', 'http://wearing.example/', 'https://wearing.example.evil/', 'https://user:secret@wearing.example/', 'file:///tmp/private', 'javascript:alert(1)', 'intent://app', 'tel:123', 'malformed']) {
    assert.equal(allowsConversationNavigation(url, source), false, url);
  }
});

test('voice transcription is identity scoped input with no note or conversation write', async () => {
  const requests: {path:string; init:RequestInit}[]=[];
  const asset='asset_'+'a'.repeat(32);
  const api=new WearingApi({endpoint:'http://127.0.0.1:8765/',identity:'daily'},(async (url:string,init:RequestInit)=>{
    const path=new URL(url).pathname; requests.push({path,init});
    if(path==='/api/bootstrap')return Response.json({version:'0.2.0',deployment:'local',token:'synthetic',identities:[{id:'daily'}]});
    return Response.json({asset_id:asset,text:'周末想出去走走。'});
  }) as typeof fetch);
  assert.equal((await api.transcribe(asset)).text,'周末想出去走走。');
  assert.deepEqual(requests.map(r=>r.path),['/api/bootstrap',`/api/life/assets/${asset}/transcribe`]);
  assert.equal((requests[1].init.headers as Record<string,string>)['X-Wearing-Identity'],'daily');
});
test('mismatched or empty transcription never enters native input', async()=>{
  const asset='asset_'+'a'.repeat(32);
  for(const transcript of [{asset_id:asset,text:''},{asset_id:'other',text:'wrong voice'},{asset_id:asset,text:12}]){
    const api=new WearingApi({endpoint:'http://127.0.0.1:8765/',identity:'daily'},(async(url:string)=>new URL(url).pathname==='/api/bootstrap'?Response.json({version:'0.2.0',deployment:'local',token:'synthetic',identities:[{id:'daily'}]}):Response.json(transcript)) as typeof fetch);
    await assert.rejects(api.transcribe(asset));
  }
});

function activityFixture(): ActivitySnapshot {
  return {checked_at: '2026-10-06T09:00:00Z', total: 1, unread: 1, counts: {attention: 0, active: 0, waiting: 0, results: 1}, has_more: false, items: [{task_id: 'a'.repeat(32), goal_id: null, source: 'conversation', bucket: 'results', status: 'completed', label: '已有结果', title: '测试任务', summary: '只在测试中使用的保存结果。', version: 'b'.repeat(64), updated_at: '2026-10-06T08:59:00Z', unread: true}]};
}
function queuedActivityFixture(): ActivitySnapshot {
  const base = activityFixture();
  return {...base, total: 3, unread: 0, counts: {attention: 0, active: 1, waiting: 2, results: 0}, items: [
    {...base.items[0], task_id: 'working', bucket: 'active', status: 'running', label: '正在执行', unread: false},
    {...base.items[0], task_id: 'queued-one', bucket: 'waiting', status: 'draft', label: '已排队', unread: false},
    {...base.items[0], task_id: 'queued-two', bucket: 'waiting', status: 'draft', label: '已排队', unread: false},
  ]};
}
test('activity decodes queued work as waiting without counting it as active or attention', async () => {
  const expected = queuedActivityFixture();
  const api = new WearingApi({endpoint: 'https://wearing.example/', identity: 'daily'}, (async () => Response.json(expected)) as typeof fetch);
  const received = await api.activity();
  assert.deepEqual(received, expected);
  assert.equal(received.counts.attention, 0); assert.equal(received.counts.active, 1); assert.equal(received.counts.waiting, 2);
  assert.deepEqual(received.items.filter(item => item.bucket === 'waiting').map(item => item.task_id), ['queued-one', 'queued-two']);
  assert.equal(activitySummary(received), '1 件事正在推进 · 2 件已排队');
  const onlyWaiting = activitySnapshot({...expected, total: 2, counts: {...expected.counts, active: 0}, items: expected.items.slice(1)});
  assert.equal(activitySummary(onlyWaiting), '2 件事已排队');
});
test('legacy activity missing waiting normalizes to zero without mutating its response', () => {
  const current = activityFixture();
  const legacy = Object.freeze({...current, counts: Object.freeze({attention: 0, active: 0, results: 1})});
  const received = activitySnapshot(legacy);
  assert.equal(received.counts.waiting, 0); assert.equal('waiting' in legacy.counts, false);
  assert.equal(activitySummary(received), '1 份新结果');
  const empty = activitySnapshot({...legacy, total: 0, unread: 0, counts: {attention: 0, active: 0, results: 0}, items: []});
  assert.equal(empty.counts.waiting, 0); assert.equal(activitySummary(empty), '交代过的事，从这里回看');
});
test('waiting count corruption and unread queued work cannot become apparently valid progress', () => {
  const queued = queuedActivityFixture();
  for (const waiting of [null, -1, 1.5, '2', undefined, 0, 3]) {
    assert.throws(() => activitySnapshot({...queued, counts: {...queued.counts, waiting}}), error => error instanceof ApiError && error.status === 422);
  }
  assert.throws(() => activitySnapshot({...queued, unread: 1, items: queued.items.map(item => ({...item, unread: item.bucket === 'waiting'}))}));
  const paged = activitySnapshot({...queued, total: 5, counts: {...queued.counts, waiting: 4}, has_more: true});
  assert.equal(paged.counts.waiting, 4); assert.equal(paged.items.length, 3);
});
test('blocked work stays attention and real new results retain summary priority over the queue', () => {
  const queued = queuedActivityFixture(), result = activityFixture().items[0];
  const blocked = activitySnapshot({...queued, total: 4, counts: {...queued.counts, attention: 1}, items: [{...result, task_id: 'blocked', bucket: 'attention', status: 'draft', label: '暂时无法开始', unread: false}, ...queued.items]});
  assert.equal(activitySummary(blocked), '1 件事等你处理');
  const resultAndQueue = activitySnapshot({...queued, total: 4, unread: 1, counts: {...queued.counts, results: 1}, items: [...queued.items, result]});
  assert.equal(activitySummary(resultAndQueue), '1 份新结果');
});
test('activity reads persisted progress with the selected identity and no write', async () => {
  const calls: {path: string; init: RequestInit}[] = [];
  const expected = activityFixture();
  const api = new WearingApi({endpoint: 'https://wearing.example/', identity: 'daily'}, (async (url: string, init: RequestInit) => {calls.push({path: new URL(url).pathname, init}); return Response.json(expected);}) as typeof fetch);
  assert.deepEqual(await api.activity(), expected);
  assert.deepEqual(calls.map(call => [call.path, call.init.method]), [['/api/activity', 'GET']]);
  assert.equal((calls[0].init.headers as Record<string, string>)['X-Wearing-Identity'], 'daily');
  assert.equal(calls[0].init.body, undefined);
});
test('invalid or unavailable activity cannot become an empty or fabricated successful snapshot', async () => {
  const valid = activityFixture();
  const invalid: unknown[] = [null, {}, {...valid, checked_at: 'not-a-date'}, {...valid, unread: 2}, {...valid, counts: {...valid.counts, active: 1}}, {...valid, items: []}, {...valid, items: [{...valid.items[0], version: 1}]}, {...valid, items: [{...valid.items[0], bucket: 'running'}]}, {...valid, items: [{...valid.items[0], task_id: '../other'}]}, {...valid, total: 2, unread: 2, counts: {...valid.counts, results: 2}, items: [valid.items[0], valid.items[0]]}];
  for (const body of invalid) {
    const api = new WearingApi({endpoint: 'https://wearing.example/', identity: 'daily'}, (async () => Response.json(body)) as typeof fetch);
    await assert.rejects(api.activity(), error => error instanceof ApiError && error.status === 422);
  }
  const offline = new WearingApi({endpoint: 'https://wearing.example/', identity: 'daily'}, (async () => {throw new Error('offline');}) as typeof fetch);
  await assert.rejects(offline.activity(), error => error instanceof ApiError && error.status === 0);
  const partial = {...valid, total: 3, unread: 2, counts: {...valid.counts, results: 3}, has_more: true};
  const paged = new WearingApi({endpoint: 'https://wearing.example/', identity: 'daily'}, (async () => Response.json(partial)) as typeof fetch);
  assert.deepEqual(await paged.activity(), partial);
});
test('read receipts send only the displayed task version and preserve it through token renewal', async () => {
  const calls: {path: string; init: RequestInit}[] = [];
  const snapshot = activityFixture(); let receipts = 0;
  const api = new WearingApi({endpoint: 'https://wearing.example/', identity: 'daily'}, (async (url: string, init: RequestInit) => {
    const path = new URL(url).pathname; calls.push({path, init});
    if (path === '/api/bootstrap') return Response.json({version: '0.2.0', deployment: 'cloud', token: 'synthetic', identities: [{id: 'daily'}]});
    if (receipts++ === 0) return Response.json({detail: 'expired'}, {status: 403});
    // A newer result remains unread when an old version is acknowledged.
    return Response.json({...snapshot, items: [{...snapshot.items[0], version: 'c'.repeat(64)}]});
  }) as typeof fetch);
  const result = await api.activitySeen([snapshot.items[0]]);
  assert.equal(result.unread, 1); assert.equal(result.items[0].version, 'c'.repeat(64));
  assert.deepEqual(calls.map(call => call.path), ['/api/bootstrap', '/api/activity/seen', '/api/bootstrap', '/api/activity/seen']);
  const writes = calls.filter(call => call.init.method === 'POST');
  assert.equal(writes.length, 2);
  for (const call of writes) {
    assert.deepEqual(JSON.parse(call.init.body as string), {items: [{task_id: snapshot.items[0].task_id, version: snapshot.items[0].version}]});
    assert.equal((call.init.headers as Record<string, string>)['X-Wearing-Identity'], 'daily');
  }
});
test('malformed read receipts fail before network access and cannot acknowledge a different task', async () => {
  let calls = 0; const item = activityFixture().items[0];
  const api = new WearingApi({endpoint: 'https://wearing.example/', identity: 'daily'}, (async () => {calls++; throw new Error('must not request');}) as typeof fetch);
  for (const items of [[], [{task_id: '../foreign', version: item.version}], [{task_id: item.task_id, version: ''}], [item, item], Array.from({length: 101}, (_, index) => ({task_id: `task_${index}`, version: item.version}))]) await assert.rejects(api.activitySeen(items), error => error instanceof ApiError && error.status === 422);
  assert.equal(calls, 0);
});

test('activity pagination carries identity-scoped cursor and accepts a final partial page', async () => {
  const base = activityFixture();
  const finalPage = {...base, total: 3, counts: {...base.counts, results: 3}, filtered_total: 3, next_cursor: null, revision: 'd'.repeat(64), changed_since: false};
  let called: URL | undefined;
  const api = new WearingApi({endpoint: 'https://wearing.example/', identity: 'daily'}, (async (url: string) => {called = new URL(url); return Response.json(finalPage);}) as typeof fetch);
  assert.deepEqual(await api.activity({limit: 20, cursor: 'opaque+/token=', bucket: 'results', since: 'e'.repeat(64)}), finalPage);
  assert.equal(called?.searchParams.get('cursor'), 'opaque+/token=');
  assert.equal(called?.searchParams.get('since'), 'e'.repeat(64));
  assert.equal(called?.searchParams.get('bucket'), 'results');
  assert.equal(called?.searchParams.get('limit'), '20');
});

test('incomplete pagination never changes corruption into a valid partial snapshot', () => {
  const base = activityFixture();
  const valid = {...base, total: 3, counts: {...base.counts, results: 3}, has_more: true, filtered_total: 3, next_cursor: 'next', revision: 'd'.repeat(64), changed_since: null};
  assert.equal(activitySnapshot(valid).next_cursor, 'next');
  for (const value of [
    {...base, total: 3, counts: {...base.counts, results: 3}},
    {...valid, revision: undefined}, {...valid, next_cursor: null}, {...valid, filtered_total: -1},
    {...valid, filtered_total: 4}, {...valid, changed_since: 'yes'},
    {...valid, has_more: false, next_cursor: null},
  ]) assert.throws(() => activitySnapshot(value));
});

test('cursor invalidation remains an explicit refresh error and invalid queries never reach the service', async () => {
  let calls = 0;
  const api = new WearingApi({endpoint: 'https://wearing.example/', identity: 'daily'}, (async () => {calls++; return Response.json({detail: '进展列表已更新，请刷新后继续查看。'}, {status: 409});}) as typeof fetch);
  await assert.rejects(api.activity({cursor: 'old-cursor'}), error => error instanceof ApiError && error.status === 409);
  for (const query of [{limit: 0}, {limit: 101}, {cursor: ''}, {since: 'invalid'}]) await assert.rejects(api.activity(query), error => error instanceof ApiError && error.status === 422);
  assert.equal(calls, 1);
});
