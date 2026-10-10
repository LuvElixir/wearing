import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {runInNewContext} from 'node:vm';
import * as ts from 'typescript';
import {makeDraft, Outbox, scopeOf, type Connection, type Media, type Store, type RecordItem} from './core';
import {RecordMutations, projectRecordMutations, type RecordMutation} from './record-mutations';
import {commitRecordReceipt, commitRecordSnapshot, localRecords} from './record-sync';
import {observeDiagnosticError, recentDiagnosticErrors, clearDiagnosticErrors} from './diagnostics-client';
import {feedbackAfterSynchronization, feedbackAfterSyncFailure, type MobileFeedback} from './mobile-sync-feedback';
import {ProvisioningGate, type ProvisioningSnapshot} from './provisioning-client';
import {AIConsentGate, AI_PRIVACY_URL, type AIConsentSnapshot} from './ai-consent-client';
import {accountWorkAllowed} from './account-work';
import {sameAccount} from './account-deletion-client';
import {assertNativeServiceAddress, PUBLIC_PAJIO_ENDPOINT, requiresNativeSignIn} from './connection-default';

// Exercise the actual shell handlers without loading native modules or a live service.
const source = ts.createSourceFile('Mobile.tsx', readFileSync(new URL('./Mobile.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const mobile = source.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'Mobile') as ts.FunctionDeclaration;
const printer = ts.createPrinter();
function handlerCode(names: string[]) {
  const functions = mobile.body!.statements.filter(node => ts.isFunctionDeclaration(node) && names.includes(node.name!.text));
  assert.equal(functions.length, names.length);
  return ts.transpileModule(functions.map(node => printer.printNode(ts.EmitHint.Unspecified, node, source)).join('\n'), {compilerOptions: {target: ts.ScriptTarget.ES2022}}).outputText;
}
function deferred<T>() {let resolve!: (value: T) => void; const promise = new Promise<T>(yes => {resolve = yes;}); return {promise, resolve};}
const settle = async () => {for (let count = 0; count < 20; count++) await Promise.resolve();};
const daily: Connection = {endpoint: PUBLIC_PAJIO_ENDPOINT, identity: 'daily', session:{userId:'user_'+'a'.repeat(32),tenantId:'tenant-fixture',credentialId:'b'.repeat(32),accessToken:'s'.repeat(64),expiresAt:'2099-01-01T00:00:00Z'}};
const work: Connection = {...daily, identity: 'work'};
const consentReceipt = (state: AIConsentSnapshot['state'] = 'accepted'): AIConsentSnapshot => ({
  required: true, provider: {id: 'deepseek', name: 'DeepSeek', origin: 'https://api.deepseek.com', privacy_url: AI_PRIVACY_URL},
  policy_version: 'deepseek-2026-10-10-v1', disclosure: {title: '合成授权说明', purpose: '合成同步测试', data_categories: ['合成记录'], withdrawal: '撤回后停止新的 AI 处理。'},
  accepted: state === 'accepted', state, revision: state === 'not_granted' ? 0 : state === 'revoked' ? 2 : 1,
  updated_at: state === 'not_granted' ? null : 1791600000.125,
});
type Form = {id: string; text: string; kind: 'note'; media: Media[]; organize: boolean; start: string; end: string};
const blank = (): Form => ({id: 'next', text: '', kind: 'note', media: [], organize: false, start: '2026-10-07T00:00:00Z', end: '2026-10-07T01:00:00Z'});
function fixture(names = ['beginCaptureWrite', 'changeForm', 'save', 'activateConnection', 'photo', 'addOriginal']) {
  const data = new Map<string, unknown>();
  const storage: Store = {
    get: async <T>(key: string) => structuredClone(data.get(key) ?? null) as T | null,
    put: async (key, value) => {data.set(key, structuredClone(value));},
    batch: async entries => {for (const [key, value] of entries) data.set(key, structuredClone(value));},
    blob: async () => new Blob(['synthetic']),
  };
  const state = {form: {...blank(), id: 'draft-one', text: '已输入的原话'}, locked: false, saving: false, busy: false, feedback: {text: '', source: 'action'} as MobileFeedback, connected: false, frozen: false, screen: '', connection: daily, records: [] as RecordItem[], edits: [] as RecordMutation[], pending: [] as unknown[]};
  const apiState = {items: [] as RecordItem[], version: 0, updates: 0, snapshots: 0, bootstraps:0, bootstrapFailure: null as Error | null, updateFailure: null as Error | null};
  let requestKey = 0;
  const provisioningGate = {current:new ProvisioningGate()};
  provisioningGate.current.activate(daily); provisioningGate.current.accept(daily,readyReceipt());
  const aiConsent = new AIConsentGate();
  aiConsent.activate(daily); aiConsent.observe(daily, consentReceipt());
  const context = {
    Error, Promise, Date, clearTimeout, setTimeout, provisioningGate, aiConsent, accountWorkAllowed, Platform:{OS:'ios'}, data, state, apiState, storage, sameAccount, assertNativeServiceAddress, requiresNativeSignIn, persistNativeConnection:(connection:Connection)=>storage.put('connection',connection), outbox: new Outbox(storage), makeDraft, scopeOf, blank,
    connection: daily, current: {current: daily}, formRef: {current: state.form}, ready: true, saving: false,
    startupDeletionDisposition: async (_connection: Connection) => 'clear', setDeletionFrozen: (value: boolean) => {state.frozen = value;}, setScreen: (value: string) => {state.screen = value;},
    mutations: new RecordMutations(storage, () => `synthetic-request-${++requestKey}`), localRead: {current: 0}, commitRecordReceipt, commitRecordSnapshot, localRecords, projectRecordMutations, observeDiagnosticError,
    recordWrites: {current: new Set<string>()}, setWritingRecords: (_value: string[]) => {},
    activationEpoch: {current: 0}, captureWriting: {current: false}, draftTimer: {current: null}, syncBusy: {current: false},
    voiceBusy: {current: false}, voiceStop: {current: null}, voiceRecovery: {current: null}, recorder: {isRecording: false},
    setCaptureLocked: (value: boolean) => {state.locked = value;}, setSaving: (value: boolean) => {state.saving = value;},
    setForm: (value: Form) => {state.form = value;}, setMessage: (text: string) => {state.feedback = {text, source: 'action'};},
    setFeedback: (value: MobileFeedback | ((previous: MobileFeedback) => MobileFeedback)) => {state.feedback = typeof value === 'function' ? value(state.feedback) : value;},
    setBusy: (value: boolean) => {state.busy = value;}, stopVoice: async () => true, local: async (_connection: Connection) => {}, synchronize: async (_connection?: Connection) => {},
    setConnection: (value: Connection) => {state.connection = value;}, setConnected: (value: boolean) => {state.connected = value;}, setRecords: (value: RecordItem[]) => {state.records = value;}, setPending: (value: unknown[]) => {state.pending = value;}, setPendingMutations: (value: RecordMutation[]) => {state.edits = value;},
    setDetail: (_value: unknown) => {}, setChatRecord: (_value: unknown) => {}, setReviewRequest: (_value: unknown) => {}, setActivityOpen: (_value: boolean) => {},
    setLastReview: (_value: string) => {}, setAddress: (_value: string) => {}, setIdentity: (_value: string) => {}, setIdentities: (_value: unknown) => {},
    router: {setParams: (_value: unknown) => {}}, Crypto: {randomUUID: () => 'synthetic-id'}, AppState: {currentState: 'active'},
    keepMedia: async (_uri: string, media: Media) => ({...media, size: 25}),
    Picker: {launchImageLibraryAsync: async () => ({canceled: false, assets: [{uri: 'file://synthetic', mimeType: 'image/jpeg', fileName: '合成.jpg', width: 20, height: 20}]})},
    feedbackAfterSynchronization, feedbackAfterSyncFailure,
    WearingApi: class {
      async bootstrap() {apiState.bootstraps++;if (apiState.bootstrapFailure) throw apiState.bootstrapFailure; return {identities: []};}
      async snapshot() {apiState.snapshots++;return {items: structuredClone(apiState.items), version: apiState.version};}
      async update(base: RecordItem, patch: Partial<RecordItem>) {apiState.updates++;if (apiState.updateFailure) throw apiState.updateFailure;const receipt = {...base, ...patch, revision: base.revision + 1};apiState.items = [receipt];apiState.version++;return receipt;}
      async record(id: string) {const item = apiState.items.find(row => row.id === id);if (!item) throw Error('synthetic missing record');return structuredClone(item);}
    }, serviceFetch: () => {},
  };
  runInNewContext(handlerCode(names), context);
  return context as typeof context & {save: () => Promise<void>; photo: (camera: boolean) => Promise<void>; activateConnection: (connection: Connection) => Promise<void>; changeForm: (change: (form: Form) => Form) => void; toggle: (record: RecordItem) => Promise<void>};
}

test('a slow existing upload locks capture before enqueue waits and preserves every accepted edit', async () => {
  const h = fixture(); const releaseUpload = deferred<void>(), uploadStarted = deferred<void>();
  await h.outbox.enqueue({id: 'older', scope: scopeOf(daily), draft: makeDraft('older', 'note'), media: [], uploaded: [], organize: false, state: 'pending', attempts: 0, nextAt: 0, createdAt: ''});
  const flushing = h.outbox.flush(scopeOf(daily), {upload: async () => '', create: async () => {uploadStarted.resolve(); await releaseUpload.promise; throw new Error('offline');}}, () => true);
  await uploadStarted.promise;
  h.changeForm(form => ({...form, text: '最后一次已接受的编辑'}));
  const saving = h.save();
  assert.equal(h.state.locked, true);
  h.changeForm(form => ({...form, text: '锁定后到达的原生回调'}));
  assert.equal(h.state.form.text, '最后一次已接受的编辑');
  await assert.rejects(h.activateConnection(work), /正在保存/);
  await settle(); assert.equal((await h.storage.get<Form>(`draft:${scopeOf(daily)}`))?.text, '最后一次已接受的编辑');
  releaseUpload.resolve(); await flushing; await saving;
  const saved = (await h.outbox.items(scopeOf(daily))).find(item => item.id === 'draft-one');
  assert.equal(saved?.draft.content, '最后一次已接受的编辑');
  assert.equal(h.state.form.text, ''); assert.equal(h.state.locked, false);
  h.changeForm(form => ({...form, text: '下一条'})); assert.equal(h.state.form.text, '下一条');
});

test('failed capture commit retains input and unlocks editing for retry', async () => {
  const h = fixture(); h.storage.batch = async () => {throw new Error('storage unavailable');};
  await h.save();
  assert.equal(h.state.form.text, '已输入的原话'); assert.equal(h.state.locked, false); assert.equal(h.state.saving, false);
  h.changeForm(form => ({...form, text: '继续补充'})); assert.equal(h.state.form.text, '继续补充');
});

test('photo selection owns the same lock until its media and draft are persisted', async () => {
  const h = fixture(); const mediaSaved = deferred<Media>();
  h.keepMedia = async () => mediaSaved.promise;
  const selecting = h.photo(false); await settle();
  assert.equal(h.state.locked, true);
  await h.save(); assert.equal((await h.outbox.items(scopeOf(daily))).length, 0);
  await assert.rejects(h.activateConnection(work), /正在保存/);
  h.changeForm(form => ({...form, text: '不会覆盖原文'}));
  mediaSaved.resolve({id: 'photo', name: '合成.jpg', mime: 'image/jpeg', size: 25}); await selecting;
  assert.equal(h.state.form.text, '已输入的原话'); assert.equal(h.state.form.media[0].id, 'photo'); assert.equal(h.state.locked, false);
  assert.deepEqual(await h.storage.get(`draft:${scopeOf(daily)}`), structuredClone(h.state.form));
});

test('identity changes become visible only after the destination draft has loaded', async () => {
  const h = fixture(); const destination = deferred<Form | null>(); const get = h.storage.get;
  h.storage.get = async <T>(key: string) => key === `draft:${scopeOf(work)}` ? await destination.promise as T | null : get<T>(key);
  const activating = h.activateConnection(work); await settle();
  assert.equal(h.current.current, daily); assert.equal(h.state.locked, true);
  h.changeForm(form => ({...form, text: '切换期间迟到的编辑'}));
  destination.resolve({...blank(), id: 'work-draft', text: '工作身份的草稿'}); await activating;
  assert.equal(h.current.current, work); assert.equal(h.state.form.text, '工作身份的草稿'); assert.equal(h.state.locked, false);
  assert.equal((await h.storage.get<Form>(`draft:${scopeOf(daily)}`))?.text, '已输入的原话');
});

test('a failed local refresh releases the sync lock and permits a later recovery', async () => {
  const h = fixture(['synchronize']); let attempts = 0;
  h.local = async () => {if (++attempts === 1) throw new Error('temporary local read failure');};
  await h.synchronize(daily);
  assert.equal(h.syncBusy.current, false); assert.equal(h.state.busy, false);
  await h.synchronize(daily); assert.equal(attempts, 2); assert.equal(h.syncBusy.current, false);
});

test('unsigned native entry cannot bootstrap or flush a queued draft before account login', async () => {
  const h=fixture(['synchronize']);
  const unsigned:Connection={endpoint:PUBLIC_PAJIO_ENDPOINT,identity:'daily'};
  await h.outbox.enqueue({id:'unsigned-draft',scope:scopeOf(unsigned),draft:makeDraft('本机旧草稿','note'),media:[],uploaded:[],organize:false,state:'pending',attempts:0,nextAt:0,createdAt:''});
  h.apiState.bootstrapFailure=Error('must not contact service');
  await h.synchronize(unsigned);
  assert.equal(h.apiState.snapshots,0);assert.equal(h.apiState.updates,0);assert.equal(h.state.connected,false);
  assert.equal((await h.outbox.items(scopeOf(unsigned)))[0].state,'pending');
  assert.equal(h.state.feedback.text,'');
});

test('foreign service activation fails before credentials, drafts or current account can change', async () => {
  const h=fixture();
  const foreign={...daily,endpoint:'https://retired-service.invalid/'};
  await assert.rejects(h.activateConnection(foreign),/重新登录/);
  assert.equal(h.current.current,daily);assert.equal(h.state.locked,false);
  assert.equal(await h.storage.get('connection'),null);assert.equal(h.data.size,0);
});


test('stopping a recording inside save cannot release the outer save lock early', async () => {
  const h = fixture(['beginCaptureWrite', 'changeForm', 'save', 'stopVoice', 'addOriginal']);
  const commit = deferred<void>(); const batch = h.storage.batch;
  h.storage.batch = async entries => {await commit.promise; await batch(entries);};
  Object.assign(h, {Platform: {OS: 'ios'}, voiceConnection: {current: daily}});
  Object.assign(h.recorder, {isRecording: true, uri: 'file://synthetic-voice', stop: async () => {h.recorder.isRecording = false;}});
  const saving = h.save(); await settle();
  assert.equal(h.voiceBusy.current, false); assert.equal(h.state.locked, true);
  assert.equal(h.state.form.media[0]?.mime, 'audio/mp4');
  h.changeForm(form => ({...form, text: '仍然锁定'})); assert.equal(h.state.form.text, '已输入的原话');
  commit.resolve(); await saving;
  assert.equal(h.state.locked, false); assert.equal(h.state.form.text, '');
  assert.equal((await h.outbox.items(scopeOf(daily)))[0].media[0].mime, 'audio/mp4');
});

const syntheticRecord = (): RecordItem => ({id:'life_synthetic',kind:'task',title:'合成待办',content:'合成待办',timezone:'Asia/Shanghai',revision:1,completed:false,updated_at:'2026-10-08T00:00:00Z'});
test('actual synchronize flushes edits, commits its snapshot and updates local records only after a verified receipt',async()=>{
  const h=fixture(['synchronize','local']);
  const item=syntheticRecord();h.apiState.items=[item];h.apiState.version=1;
  await h.mutations.enqueue(scopeOf(daily),item,{completed:true});
  await h.synchronize(daily);
  assert.equal(h.apiState.updates,1);assert.equal(h.apiState.snapshots,1);assert.equal(h.state.connected,true);
  assert.equal(h.state.records[0].revision,2);assert.equal(h.state.records[0].completed,true);assert.equal(h.state.edits.length,0);
  assert.equal((await h.storage.get<RecordItem[]>(`snapshot:${scopeOf(daily)}`))?.[0].revision,2);
  assert.equal(h.syncBusy.current,false);assert.equal(h.state.busy,false);
});
test('actual synchronize preserves edits through service failure and records only a diagnostic category',async()=>{
  const h=fixture(['synchronize','local']),item=syntheticRecord();clearDiagnosticErrors(daily);
  await h.mutations.enqueue(scopeOf(daily),item,{completed:true});h.apiState.bootstrapFailure=Error('synthetic network failure with private text');
  await h.synchronize(daily);
  assert.equal(h.apiState.updates,0);assert.equal(h.apiState.snapshots,0);assert.equal(h.state.connected,false);assert.equal(h.state.records[0].completed,true);assert.equal(h.state.edits.length,1);
  assert.deepEqual(recentDiagnosticErrors(daily).map(row=>[row.source,row.category]),[['sync','network_unavailable']]);
  assert.equal(JSON.stringify(recentDiagnosticErrors(daily)).includes('private text'),false);
  h.apiState.bootstrapFailure=null;await h.synchronize(daily);assert.equal(h.apiState.updates,1);assert.equal(h.state.edits.length,0);clearDiagnosticErrors(daily);
});
test('actual toggle accepts offline completion locally and retries without the connected gate',async()=>{
  const h=fixture(['toggle','local']),item=syntheticRecord();h.apiState.updateFailure=Error('synthetic offline');
  await h.toggle(item);await settle();
  const pending=await h.mutations.items(scopeOf(daily));assert.equal(pending.length,1);assert.equal(pending[0].patch.completed,true);
  assert.equal(h.state.records[0].completed,true);assert.equal(h.recordWrites.current.size,0);
});
test('a late old-identity refresh cannot invalidate or replace the selected identity records',async()=>{
  const h=fixture(['local']),item=syntheticRecord();h.current.current=work;h.state.records=[{...item,title:'当前身份'}];
  await h.local(daily);assert.equal(h.localRead.current,0);assert.equal(h.state.records[0].title,'当前身份');
});

test('an uncertain deletion at startup exposes only recovery with no token or business refresh', async () => {
  const h = fixture();
  const account: Connection = {...work, session: {userId:'user_'+'a'.repeat(32), tenantId:'tenant-one', credentialId:'b'.repeat(32), accessToken:'c'.repeat(64), expiresAt:'2099-01-01T00:00:00Z'}};
  await h.storage.put(`draft:${scopeOf(account)}`, {...blank(), text:'private prior draft'});
  h.startupDeletionDisposition = async () => 'review';
  let requests = 0, persisted = 0;
  h.local = async () => {requests++;}; h.synchronize = async () => {requests++;};
  h.persistNativeConnection = async () => {persisted++;};
  await h.activateConnection(account);
  assert.equal(requests,0); assert.equal(persisted,0); assert.equal(h.current.current,null);
  assert.equal(h.state.frozen,true); assert.equal(h.state.screen,'account-deletion');
  assert.equal(h.state.connection.session?.accessToken,undefined); assert.equal(h.state.connection.session?.userId,account.session!.userId);
  assert.equal(h.state.form.text,''); assert.equal(h.state.locked,false);
  assert.equal((await h.storage.get<Form>(`draft:${scopeOf(account)}`))?.text,'private prior draft');
  h.startupDeletionDisposition = async () => 'clear';
  await h.activateConnection(daily);
  assert.equal(h.state.frozen,false); assert.equal(h.current.current,daily); assert.equal(requests,2); assert.equal(persisted,1);
});

test('account freeze fences callbacks before OS cleanup and cannot clear a newly selected account', async () => {
  const h = fixture(['freezeAccount']);
  const a: Connection = {...daily, session:{userId:'user_'+'a'.repeat(32), tenantId:'one',credentialId:'b'.repeat(32),accessToken:'c'.repeat(64),expiresAt:'2099-01-01T00:00:00Z'}};
  const b: Connection = {...a, session:{...a.session!,userId:'user_'+'d'.repeat(32)}};
  h.connection=a; h.current.current=a;
  const release=deferred<void>(); let captured:string[]=[];
  const extra={searchOpen:{current:0},searchContext:{current:null},setMenu:()=>{},setAdding:()=>{},voiceConnection:{current:a as Connection|null},
    clearDeletedAccountLocalData:async(target:Connection,options:{recordingUris:string[]})=>{assert.equal(target,a);captured=options.recordingUris;await release.promise;return {pendingFiles:0,unownedLegacy:0};}};
  Object.assign(h,extra);
  Object.assign(h.recorder,{isRecording:true,uri:'file://managed-recording',stop:async()=>{h.recorder.isRecording=false;extra.voiceConnection.current=null;}});
  const frozen=(h as unknown as {freezeAccount:(c:Connection)=>Promise<void>}).freezeAccount(a);
  assert.equal(h.current.current,null); assert.equal(h.state.frozen,true);assert.equal(h.state.connection.session?.accessToken,undefined);
  await settle(); assert.deepEqual(Array.from(captured),['file://managed-recording']);
  h.current.current=b;h.state.feedback={text:'新账户的消息',source:'action'};h.state.records=[syntheticRecord()];
  release.resolve();await frozen;
  assert.equal(h.current.current,b);assert.equal(h.state.feedback.text,'新账户的消息');assert.equal(h.state.records.length,1);
});


test('a connection persisted after account freeze cannot reactivate credentials or business UI', async () => {
  const h = fixture(['beginCaptureWrite', 'activateConnection', 'freezeAccount']);
  const a: Connection = {...daily, session:{userId:'user_'+'a'.repeat(32), tenantId:'one',credentialId:'b'.repeat(32),accessToken:'c'.repeat(64),expiresAt:'2099-01-01T00:00:00Z'}};
  h.connection=a; h.current.current=a;
  Object.assign(h,{searchOpen:{current:0},searchContext:{current:null},setMenu:()=>{},setAdding:()=>{},voiceConnection:{current:null},clearDeletedAccountLocalData:async()=>({pendingFiles:0,unownedLegacy:0})});
  const persisted=deferred<void>(); let businessReads=0;
  h.persistNativeConnection=async()=>persisted.promise;
  h.local=async()=>{businessReads++;};h.synchronize=async()=>{businessReads++;};
  const activation=h.activateConnection({...a,identity:'work'});
  const rejected=assert.rejects(activation,/账户状态已变化/);
  await settle();
  await (h as unknown as {freezeAccount:(c:Connection)=>Promise<void>}).freezeAccount(a);
  persisted.resolve();await rejected;
  assert.equal(h.current.current,null);assert.equal(h.state.frozen,true);assert.equal(h.state.connection.session?.accessToken,undefined);
  assert.equal(h.state.screen,'account-deletion');assert.equal(businessReads,0);assert.equal(h.state.locked,false);
});

const readyReceipt=():ProvisioningSnapshot=>({state:'ready',members:{core:{state:'ready'},linux:{state:'ready'},android:{state:'ready'}},updated_at:1791600000,retry_after:5,reason:null});
test('actual synchronize blocks bootstrap and queued mutations until the current activation has a confirmed complete bundle',async()=>{
 const h=fixture(['synchronize','local']);const item=syntheticRecord();h.apiState.items=[item];h.apiState.version=1;
 h.provisioningGate.current.activate(daily);await h.mutations.enqueue(scopeOf(daily),item,{completed:true});
 await h.synchronize(daily);assert.equal(h.apiState.bootstraps,0);assert.equal(h.apiState.updates,0);assert.equal(h.apiState.snapshots,0);assert.equal(h.state.connected,false);assert.equal((await h.mutations.items(scopeOf(daily))).length,1);
 assert.equal(h.provisioningGate.current.accept(daily,{...readyReceipt(),state:'pairing'}),false);await h.synchronize(daily);assert.equal(h.apiState.bootstraps,0);
 h.provisioningGate.current.accept(daily,readyReceipt());await h.synchronize(daily);assert.equal(h.apiState.bootstraps,1);assert.equal(h.apiState.updates,1);assert.equal(h.state.connected,true);
});
test('activation reset during an outstanding bootstrap cannot flush old work even when the connection object is reused',async()=>{
 const h=fixture(['synchronize','local']);const item=syntheticRecord();await h.mutations.enqueue(scopeOf(daily),item,{completed:true});
 const pending=deferred<{identities:never[]}>();h.WearingApi.prototype.bootstrap=async()=>pending.promise;
 const syncing=h.synchronize(daily);await settle();h.provisioningGate.current.activate(daily);pending.resolve({identities:[]});await syncing;
 assert.equal(h.apiState.updates,0);assert.equal(h.apiState.snapshots,0);assert.equal(h.state.connected,false);assert.equal((await h.mutations.items(scopeOf(daily))).length,1);
});

test('actual synchronize preserves queued originals and edits without consent or after withdrawal', async () => {
  for (const state of ['not_granted', 'revoked'] as const) {
    const h = fixture(['synchronize', 'local']), item = syntheticRecord();
    h.aiConsent.observe(daily, consentReceipt(state));
    await h.outbox.enqueue({id: 'unconsented-original', scope: scopeOf(daily), draft: makeDraft('合成待授权原件', 'note'), media: [], uploaded: [], organize: true, state: 'pending', attempts: 0, nextAt: 0, createdAt: ''});
    await h.mutations.enqueue(scopeOf(daily), item, {completed: true});
    await h.synchronize(daily);
    assert.equal(h.apiState.bootstraps, 0); assert.equal(h.apiState.updates, 0); assert.equal(h.apiState.snapshots, 0);
    assert.equal(h.state.connected, false); assert.equal(h.syncBusy.current, false); assert.equal(h.state.busy, false);
    const originals = await h.outbox.items(scopeOf(daily));
    assert.equal(originals.length, 1); assert.equal(originals[0].state, 'pending'); assert.equal(originals[0].attempts, 0);
    assert.equal((await h.mutations.items(scopeOf(daily))).length, 1);
  }
});

test('consent withdrawal during the actual bootstrap prevents late queue flush and connected state', async () => {
  const h = fixture(['synchronize', 'local']), pending = deferred<{identities: never[]}>();
  await h.mutations.enqueue(scopeOf(daily), syntheticRecord(), {completed: true});
  h.WearingApi.prototype.bootstrap = async () => {h.apiState.bootstraps++; return pending.promise;};
  const syncing = h.synchronize(daily); await settle();
  assert.equal(h.apiState.bootstraps, 1); assert.equal(h.syncBusy.current, true);
  h.aiConsent.observe(daily, consentReceipt('revoked')); pending.resolve({identities: []}); await syncing;
  assert.equal(h.apiState.updates, 0); assert.equal(h.apiState.snapshots, 0); assert.equal(h.state.connected, false);
  assert.equal((await h.mutations.items(scopeOf(daily))).length, 1);
  assert.equal(h.syncBusy.current, false); assert.equal(h.state.busy, false);
});
