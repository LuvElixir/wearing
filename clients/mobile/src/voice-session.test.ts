import assert from 'node:assert/strict';
import test from 'node:test';
import type {Store} from './core';
import {VoiceSession, type VoiceDraft, type VoiceRecorder, type VoiceText} from './voice-session';
import {createVoiceRecorder} from './voice-recorder.web';
import type {VoiceDiagnostic} from './voice-diagnostics';

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
const until = async (condition: () => boolean) => {
  for (let tries = 0; tries < 100; tries++) {if (condition()) return; await new Promise(resolve => setImmediate(resolve));}
  throw new Error('Expected state was not reached');
};
function fixture(identity = 'alice', shared?: Store) {
  const values = new Map<string, unknown>(), events: string[] = [], delivered: VoiceText[] = [];
  const diagnostics: VoiceDiagnostic[] = [];
  let serial = 0, available = true, failWrites = false;
  let prepare: (() => Promise<boolean>) | undefined;
  let recording: (() => Promise<void>) | undefined;
  let stopping: (() => Promise<void>) | undefined;
  let copying: (() => Promise<void>) | undefined;
  let uploading: (() => Promise<string>) | undefined;
  let transcribing: (() => Promise<{text: string}>) | undefined;
  let streaming: (() => Promise<{text: string}>) | undefined;
  const store: Store = shared ?? {
    async get<T>(key: string) {return structuredClone(values.get(key) ?? null) as T | null;},
    async put(key, value) {if (failWrites) throw new Error('disk unavailable'); values.set(key, structuredClone(value));},
    async batch(entries) {if (failWrites) throw new Error('disk unavailable'); for (const [key, value] of entries) values.set(key, structuredClone(value));},
    async blob() {events.push('blob'); return new Blob(['audio']);},
  };
  const session = new VoiceSession({
    connection: {endpoint: 'https://wearing.example/', identity}, store,
    recorder(): VoiceRecorder {return {
      async prepare(held) {events.push('prepare'); const result = prepare ? await prepare() : true; return result && held();},
      record() {events.push('record'); return recording?.();},
      async stop() {events.push('stop'); await stopping?.(); return {uri: 'file:///voice.m4a', mime: 'audio/mp4', name: '语音输入.m4a'};},
      async dispose() {events.push('dispose');}, durationMillis: () => 900,
      ...(streaming ? {recognition: () => {events.push('stream-final'); return streaming!();}, abortRecognition: () => {events.push('stream-cancel');}} : {}),
    };},
    async keepMedia(uri, media) {events.push('copy'); await copying?.(); return {...media, size: 100};},
    async upload() {events.push('upload'); return uploading ? uploading() : 'asset_a';},
    async transcribe() {events.push('transcribe'); return transcribing ? transcribing() : {text: '明天提醒我带伞'};},
    newId: () => identity + '-' + (++serial), isAvailable: () => available, onText: text => {events.push('deliver'); delivered.push(text);},
    onDiagnostic: event => diagnostics.push(event),
  });
  return {session, store, values, events, delivered, diagnostics,
    unavailable() {available = false;}, available() {available = true;}, failWrites(value: boolean) {failWrites = value;},
    prepare(value: () => Promise<boolean>) {prepare = value;}, stopping(value: () => Promise<void>) {stopping = value;},
    recording(value: () => Promise<void>) {recording = value;},
    copying(value: () => Promise<void>) {copying = value;}, uploading(value: () => Promise<string>) {uploading = value;}, transcribing(value: () => Promise<{text: string}>) {transcribing = value;},
    streaming(value: () => Promise<{text: string}>) {streaming = value;},
  };
}

test('live final preserves the local original and avoids duplicate file upload and recognition', async () => {
  const f = fixture(); f.streaming(async () => ({text: '实时识别结果'}));
  await f.session.restore(); await f.session.start(); await f.session.commit();
  assert.equal(f.delivered[0].text, '实时识别结果');
  assert.equal(f.events.includes('upload'), false); assert.equal(f.events.includes('transcribe'), false);
  assert.ok(f.events.indexOf('copy') < f.events.indexOf('stream-final'));
  assert.ok(f.session.getSnapshot().draft?.media);
});

test('live failure keeps original without automatic paid retry and an explicit retry uses the file', async () => {
  const f = fixture(); f.streaming(async () => {throw new Error('network');});
  await f.session.restore(); await f.session.start(); await f.session.commit();
  assert.equal(f.delivered.length, 0); assert.equal(f.events.includes('upload'), false);
  assert.ok(f.session.getSnapshot().draft?.media);
  await f.session.retry(); assert.equal(f.delivered.length, 1); assert.equal(f.events.filter(e => e === 'transcribe').length, 1);
});

test('background stops live recognition and retains only the original without accepting late text', async () => {
  const f = fixture(); f.streaming(async () => ({text: '不得送出'}));
  await f.session.restore(); await f.session.start(); await f.session.interrupt();
  assert.ok(f.events.includes('stream-cancel')); assert.equal(f.events.includes('stream-final'), false);
  assert.ok(f.session.getSnapshot().draft?.media); assert.equal(f.delivered.length, 0);
});

test('local persistence failure closes the live session before finalization and keeps the original URI', async () => {
  const f = fixture(); f.streaming(async () => ({text: '不得送出'}));
  await f.session.restore(); await f.session.start(); f.failWrites(true); await f.session.commit();
  assert.ok(f.events.includes('stream-cancel')); assert.equal(f.events.includes('stream-final'), false);
  assert.equal(f.session.getSnapshot().draft?.uri, 'file:///voice.m4a');
  assert.equal(f.delivered.length, 0); assert.equal(f.events.includes('upload'), false);
});

test('cancelling while native start is pending still stops and releases the acquired microphone', async () => {
  const f = fixture(), native = deferred<void>();
  f.streaming(async () => ({text: '不得送出'})); f.recording(() => native.promise);
  await f.session.restore(); const starting = f.session.start(); await until(() => f.events.includes('record'));
  const cancelling = f.session.cancel(); native.resolve(); await Promise.all([starting, cancelling]);
  assert.ok(f.events.includes('stream-cancel')); assert.ok(f.events.includes('stop')); assert.ok(f.events.includes('dispose'));
  assert.equal(f.session.getSnapshot().phase, 'idle'); assert.equal(f.delivered.length, 0);
  assert.equal(await f.store.get(f.session.key), null);
});

test('mount and restore never access microphone or retranscribe a saved draft', async () => {
  const f = fixture();
  await f.store.put(f.session.key, {id: 'old', text: '已识别的文字', media: {id: 'audio', size: 4, name: 'a.m4a', mime: 'audio/mp4'}});
  await f.session.restore();
  assert.deepEqual(f.events, []);
  assert.equal(f.session.canStart, false);
  assert.equal(f.session.getSnapshot().draft?.id, 'old');
  await f.session.retry();
  assert.equal(f.delivered[0].text, '已识别的文字');
  assert.deepEqual(f.events, ['deliver']);
});

test('release while permission/preparation is pending cannot begin late recording', async () => {
  const f = fixture(), permission = deferred<boolean>();
  f.prepare(() => permission.promise); await f.session.restore();
  const starting = f.session.start();
  await until(() => f.events.includes('prepare'));
  const releasing = f.session.commit();
  permission.resolve(true); await Promise.all([starting, releasing]);
  assert.deepEqual(f.events, ['prepare', 'dispose']);
  assert.equal(f.session.getSnapshot().phase, 'idle');
  assert.equal(f.session.canStart, true);
});

test('upward cancellation during pending prepare releases resources without saving or ASR', async () => {
  const f = fixture(), permission = deferred<boolean>();
  f.prepare(() => permission.promise); await f.session.restore();
  const starting = f.session.start(); await until(() => f.events.includes('prepare'));
  const cancelling = f.session.cancel(); permission.resolve(true);
  await Promise.all([starting, cancelling]);
  assert.deepEqual(f.events, ['prepare', 'dispose']);
  assert.equal(await f.store.get(f.session.key), null);
});

test('cancel stops a real recording and never persists, uploads or transcribes it', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start();
  await Promise.all([f.session.cancel(), f.session.cancel(), f.session.commit()]);
  assert.deepEqual(f.events, ['prepare', 'record', 'stop', 'dispose']);
  assert.equal(f.delivered.length, 0);
  assert.equal(await f.store.get(f.session.key), null);
});

test('commit preserves the original before upload and only delivers editable text', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start();
  f.uploading(async () => {
    const draft = await f.store.get<VoiceDraft>(f.session.key);
    assert.ok(draft?.media); assert.equal(draft.uri, 'file:///voice.m4a');
    return 'asset_a';
  });
  await Promise.all([f.session.commit(), f.session.commit()]);
  assert.deepEqual(f.events, ['prepare', 'record', 'stop', 'dispose', 'copy', 'blob', 'upload', 'transcribe', 'deliver']);
  assert.equal(f.delivered.length, 1);
  assert.equal(f.delivered[0].identity, 'alice');
  assert.equal(f.delivered[0].scope, f.session.scope);
  assert.equal(f.session.canStart, false);
  await f.session.ack('wrong'); assert.equal(f.session.canStart, false);
  await f.session.ack(f.delivered[0].id); assert.equal(f.session.canStart, true);
  const original = await f.store.get<VoiceDraft>('voice-original:' + f.session.scope + ':' + f.delivered[0].id);
  assert.ok(original?.media); assert.equal(original.text, f.delivered[0].text);
});

test('offline recording is retained and simultaneous retries use one request and upload key', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start();
  f.uploading(async () => {throw new Error('offline');}); await f.session.commit();
  const saved = f.session.getSnapshot().draft;
  assert.ok(saved?.media); assert.equal(f.session.getSnapshot().message, '识别未完成，录音还在，可以重试。');
  const wait = deferred<string>(); f.uploading(() => wait.promise);
  const first = f.session.retry(), second = f.session.retry();
  await until(() => f.events.filter(event => event === 'upload').length === 2);
  wait.resolve('asset_a'); await Promise.all([first, second]);
  assert.equal(f.events.filter(event => event === 'upload').length, 2);
  assert.equal(f.events.filter(event => event === 'transcribe').length, 1);
  assert.equal(f.delivered[0].id, saved.id);
  assert.equal(f.session.getSnapshot().draft?.media?.id, saved.media.id);
});

test('retry after ASR error reuses uploaded asset and saved original', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start();
  f.transcribing(async () => {throw new Error('ASR unavailable');}); await f.session.commit();
  assert.equal(f.session.getSnapshot().draft?.asset, 'asset_a');
  f.transcribing(async () => ({text: '修改前的草稿'})); await f.session.retry();
  assert.equal(f.events.filter(event => event === 'upload').length, 1);
  assert.equal(f.events.filter(event => event === 'copy').length, 1);
  assert.equal(f.delivered.length, 1);
});

test('background while recording stops the microphone and saves without ASR', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start();
  f.unavailable(); await f.session.interrupt();
  assert.deepEqual(f.events, ['prepare', 'record', 'stop', 'dispose', 'copy']);
  assert.ok(f.session.getSnapshot().draft?.media);
  f.available(); await f.session.retry(); assert.equal(f.delivered.length, 1);
});

test('background while stopping downgrades commit to local recovery', async () => {
  const f = fixture(), stopped = deferred<void>(); await f.session.restore(); await f.session.start();
  f.stopping(() => stopped.promise); const commit = f.session.commit();
  await until(() => f.events.includes('stop'));
  const interrupt = f.session.interrupt(); stopped.resolve(); await Promise.all([commit, interrupt]);
  assert.ok(f.session.getSnapshot().draft?.media);
  assert.equal(f.events.includes('upload'), false);
});

test('late ASR after background is saved but does not insert even after returning', async () => {
  const f = fixture(), response = deferred<{text: string}>();
  f.transcribing(() => response.promise); await f.session.restore(); await f.session.start();
  const commit = f.session.commit(); await until(() => f.events.includes('transcribe'));
  f.unavailable(); void f.session.interrupt(); f.available(); response.resolve({text: '稍后收到的文字'}); await commit;
  assert.equal(f.delivered.length, 0);
  assert.equal(f.session.getSnapshot().draft?.text, '稍后收到的文字');
  await f.session.retry(); assert.equal(f.delivered[0].text, '稍后收到的文字');
});

test('identity switch leaves the old result in the old scope and cannot insert into the new one', async () => {
  const a = fixture('alice'), response = deferred<{text: string}>();
  a.transcribing(() => response.promise); await a.session.restore(); await a.session.start();
  const commit = a.session.commit(); await until(() => a.events.includes('transcribe'));
  a.unavailable(); void a.session.dispose();
  const b = fixture('bob', a.store); await b.session.restore();
  response.resolve({text: 'Alice 的私人草稿'}); await commit;
  assert.equal(a.delivered.length, 0); assert.equal(b.delivered.length, 0);
  assert.equal(b.session.getSnapshot().draft, null);
  assert.equal((await a.store.get<VoiceDraft>(a.session.key))?.text, 'Alice 的私人草稿');
  assert.equal(await a.store.get(b.session.key), null);
});

test('unmount during prepare stops after acquisition and a second owner waits for cleanup', async () => {
  const a = fixture('alice'), prepared = deferred<boolean>(); a.prepare(() => prepared.promise); await a.session.restore();
  const startA = a.session.start(); await until(() => a.events.includes('prepare'));
  const disposeA = a.session.dispose();
  const b = fixture('bob'); await b.session.restore(); const startB = b.session.start();
  await new Promise(resolve => setImmediate(resolve)); assert.deepEqual(b.events, []);
  prepared.resolve(true); await Promise.all([startA, disposeA, startB]);
  assert.deepEqual(a.events, ['prepare', 'dispose']); assert.deepEqual(b.events, ['prepare', 'record']);
  await b.session.cancel();
});

test('unmount during recording preserves the original without delivering text', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start(); await f.session.dispose();
  assert.deepEqual(f.events, ['prepare', 'record', 'stop', 'dispose', 'copy']);
  assert.ok((await f.store.get<VoiceDraft>(f.session.key))?.media);
  assert.equal(f.session.canStart, false);
});

test('failed local copy leaves the URI recoverable and retry can finish preservation', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start();
  f.copying(async () => {throw new Error('copy unavailable');}); await f.session.commit();
  assert.equal((await f.store.get<VoiceDraft>(f.session.key))?.uri, 'file:///voice.m4a');
  assert.equal(f.events.includes('upload'), false);
  f.copying(async () => {}); await f.session.retry();
  assert.ok(f.session.getSnapshot().draft?.media); assert.equal(f.delivered.length, 1);
});

test('failed journal write retains the in-memory URI for retry instead of losing the take', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start();
  f.failWrites(true); await f.session.commit();
  assert.equal(f.session.getSnapshot().draft?.uri, 'file:///voice.m4a');
  assert.equal(f.events.includes('upload'), false);
  f.failWrites(false); await f.session.retry();
  assert.equal(f.delivered.length, 1);
});

test('acknowledgement keeps original audio and an older id cannot acknowledge a new take', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start(); await f.session.commit();
  const first = f.delivered[0].id; await f.session.ack(first);
  await f.session.start(); await f.session.commit();
  const second = f.delivered[1].id; assert.notEqual(first, second);
  await f.session.ack(first);
  assert.equal(f.session.getSnapshot().draft?.id, second);
  assert.equal(f.session.getSnapshot().draft?.acknowledged, false);
  assert.ok((await f.store.get<VoiceDraft>('voice-original:' + f.session.scope + ':' + first))?.media);
});

test('empty transcription cannot be delivered or acknowledge the original', async () => {
  const f = fixture(); f.transcribing(async () => ({text: '  '}));
  await f.session.restore(); await f.session.start(); await f.session.commit();
  assert.equal(f.delivered.length, 0); assert.ok(f.session.getSnapshot().draft?.media);
  await f.session.ack(f.session.getSnapshot().draft!.id); assert.equal(f.session.canStart, false);
});

test('repeated WebView receipts do not rewrite voice originals on every input update', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start(); await f.session.commit();
  assert.equal(f.session.getSnapshot().message, '');
  const id = f.delivered[0].id;
  await Promise.all([f.session.ack(id), f.session.ack(id), f.session.ack(id)]);
  f.failWrites(true); // A repeat receipt must not reach a write, even after the first acknowledgement.
  await f.session.ack(id);
  assert.equal(f.session.getSnapshot().draft?.acknowledged, true);
  assert.equal(f.session.getSnapshot().message, '');
  assert.equal(f.diagnostics.filter(event => event.stage === 'ack').length, 1);
  assert.equal(f.diagnostics.filter(event => event.stage === 'release_to_draft').length, 1);
});

test('voice save failures retain the take and expose a short recovery message', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start();
  f.failWrites(true); await f.session.commit();
  assert.ok(f.session.getSnapshot().draft?.uri);
  assert.equal(f.session.getSnapshot().message, '识别未完成，录音还在，可以重试。');
  assert.equal(f.diagnostics.find(event => event.outcome === 'error')?.code, 'storage_unavailable');
  f.failWrites(false); await f.session.retry();
  assert.equal(f.delivered.length, 1);
});

test('effect replay reattaches without restarting an interrupted recorder', async () => {
  const f = fixture(); await f.session.restore(); await f.session.start();
  const cleanup = f.session.dispose(); f.session.activate(); await f.session.restore(); await cleanup;
  assert.equal(f.events.filter(event => event === 'record').length, 1);
  assert.ok(f.session.getSnapshot().draft?.media);
  assert.equal(f.delivered.length, 0);
});

test('inactive voice surface cannot start recording even if its saved state is ready', async () => {
  const f = fixture(); await f.session.restore(); f.unavailable(); await f.session.start();
  assert.deepEqual(f.events, []);
});

function browserFixture() {
  const oldNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const oldRecorder = Object.getOwnPropertyDescriptor(globalThis, 'MediaRecorder');
  let stopped = 0, created = 0, recorded = 0;
  const permission = deferred<MediaStream>();
  const stream = {getTracks: () => [{stop: () => stopped++}]} as unknown as MediaStream;
  class Recorder extends EventTarget {
    static isTypeSupported(type: string) {return type === 'audio/mp4';}
    state = 'inactive';
    mimeType: string;
    constructor(_stream: MediaStream, options: MediaRecorderOptions) {super(); created++; this.mimeType = options.mimeType!;}
    start() {recorded++; this.state = 'recording';}
    stop() {
      assert.equal(this.state, 'recording', 'stop must never run on an unstarted MediaRecorder');
      this.state = 'inactive';
      queueMicrotask(() => {
        this.dispatchEvent(Object.assign(new Event('dataavailable'), {data: new Blob(['actual original'], {type: this.mimeType})}));
        this.dispatchEvent(new Event('stop'));
      });
    }
  }
  Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {mediaDevices: {getUserMedia: () => permission.promise}}});
  Object.defineProperty(globalThis, 'MediaRecorder', {configurable: true, value: Recorder});
  return {permission, stream, counts: () => ({stopped, created, recorded}), restore() {
    for (const [key, descriptor] of [['navigator', oldNavigator], ['MediaRecorder', oldRecorder]] as const) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }};
}

test('web permission completion after release stops all tracks without creating a decoder', async () => {
  const web = browserFixture();
  try {
    const recorder = createVoiceRecorder(); let held = true;
    const preparing = recorder.prepare(() => held); held = false;
    web.permission.resolve(web.stream);
    assert.equal(await preparing, false); await recorder.dispose();
    assert.equal(web.counts().created, 0); assert.equal(web.counts().recorded, 0); assert.ok(web.counts().stopped >= 1);
  } finally {web.restore();}
});

test('web prepared cancellation releases tracks without calling stop on an inactive recorder', async () => {
  const web = browserFixture();
  try {
    const recorder = createVoiceRecorder(); web.permission.resolve(web.stream);
    assert.equal(await recorder.prepare(() => true), true); await recorder.dispose();
    assert.equal(web.counts().recorded, 0); assert.ok(web.counts().stopped >= 1);
  } finally {web.restore();}
});

test('web recording preserves actual browser MIME and releases tracks before transcription', async () => {
  const web = browserFixture(); let uri: string | undefined;
  try {
    const recorder = createVoiceRecorder(); web.permission.resolve(web.stream);
    await recorder.prepare(() => true); recorder.record();
    const audio = await recorder.stop(); uri = audio.uri; await recorder.dispose();
    assert.equal(audio.mime, 'audio/mp4'); assert.equal(audio.name, '语音输入.m4a');
    assert.equal(await (await fetch(audio.uri)).text(), 'actual original');
    assert.equal(web.counts().recorded, 1); assert.ok(web.counts().stopped >= 1);
  } finally {if (uri) URL.revokeObjectURL(uri); web.restore();}
});
