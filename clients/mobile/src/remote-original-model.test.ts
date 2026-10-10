import {test} from 'node:test';
import assert from 'node:assert/strict';
import {audioOriginalState, downloadRemoteOriginal, REMOTE_ORIGINAL_LIMIT, remoteOriginalKind, remoteOriginalSource} from './remote-original-model';

const asset = {id: 'asset_synthetic', name: '合成图片.png', mime: 'image/png'};
const connection = {endpoint: 'http://127.0.0.1:8765/', identity: 'daily'};

test('only supported media is previewed; documents and untrusted MIME types never become images', () => {
  assert.equal(remoteOriginalKind(asset), 'image');
  assert.equal(remoteOriginalKind({...asset, mime: 'audio/mp4'}), 'audio');
  for (const mime of ['application/pdf', 'text/html', 'image/svg+xml', 'image/not-real', 'video/mp4', '']) {
    assert.equal(remoteOriginalKind({...asset, mime}), 'file');
  }
  assert.equal(remoteOriginalKind({...asset, mime: 'IMAGE/JPEG; charset=binary'}), 'image');
});

test('audio loading, buffering, playback error and ready states remain distinct', () => {
  const status = {isLoaded: false, isBuffering: false, playing: false, playbackState: 'idle', error: null};
  assert.equal(audioOriginalState(status), 'loading');
  assert.equal(audioOriginalState({...status, isLoaded: true}), 'ready');
  assert.equal(audioOriginalState({...status, isLoaded: true, playing: true}), 'playing');
  assert.equal(audioOriginalState({...status, isLoaded: true, isBuffering: true, playing: true}), 'loading');
  assert.equal(audioOriginalState({...status, error: 'decoder failed'}), 'error');
  assert.equal(audioOriginalState(status, 'timed out'), 'error');
});

test('original requests bind current identity in headers and reject invalid identifiers', async context => {
  const dev = Object.getOwnPropertyDescriptor(globalThis, '__DEV__');
  Object.defineProperty(globalThis, '__DEV__', {configurable: true, value: true});
  const previousDevelopmentFlag = process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS;
  process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS = 'true';
  context.after(() => {if (previousDevelopmentFlag === undefined) delete process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS; else process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS = previousDevelopmentFlag;});
  context.after(() => {if (dev) Object.defineProperty(globalThis, '__DEV__', dev); else Reflect.deleteProperty(globalThis, '__DEV__');});
  const configured = {endpoint: 'http://192.168.1.25:8795/', identity: 'work', development: {accessToken: 'a'.repeat(48), expiresAt: new Date(Date.now() + 3600000).toISOString()}};
  const source = remoteOriginalSource(configured, asset);
  assert.equal(new URL(source.uri).search, '');
  assert.equal(source.uri.includes('aaaaaaa'), false);
  assert.equal(source.headers.Authorization, 'Bearer ' + 'a'.repeat(48));
  assert.equal(source.headers['X-Wearing-Identity'], 'work');
  let seen: RequestInit | undefined;
  const bytes = await downloadRemoteOriginal(configured, asset, (async (_url, init) => {seen = init; return new Response(new Uint8Array([1, 2]), {headers: {'content-type': asset.mime}});}) as typeof fetch);
  assert.deepEqual(bytes, new Uint8Array([1, 2]));
  assert.equal(seen?.redirect, 'error');
  assert.equal(seen?.method, undefined);
  for (const id of ['../keys', 'https://other.example/private', 'asset_x?query']) assert.throws(() => remoteOriginalSource(configured, {...asset, id}));
});

test('exports reject oversized declared and streamed bodies, even without a Content-Length', async () => {
  const declared = (async () => new Response(new Uint8Array(), {headers: {'content-length': String(REMOTE_ORIGINAL_LIMIT + 1)}})) as typeof fetch;
  await assert.rejects(() => downloadRemoteOriginal(connection, asset, declared), /15 MB/);
  let requestSignal: AbortSignal | undefined;
  const streamed = (async (_url, init) => {
    requestSignal = init?.signal || undefined;
    return new Response(new ReadableStream<Uint8Array>({start(controller) {
      controller.enqueue(new Uint8Array(REMOTE_ORIGINAL_LIMIT)); controller.enqueue(new Uint8Array(1)); controller.close();
    }}));
  }) as typeof fetch;
  await assert.rejects(() => downloadRemoteOriginal(connection, asset, streamed), /15 MB/);
  assert.equal(requestSignal?.aborted, true);
});

test('format mismatch and failed service errors cannot enter the system share workflow', async () => {
  const wrong = (async () => new Response('secret HTML', {headers: {'content-type': 'text/html'}})) as typeof fetch;
  await assert.rejects(() => downloadRemoteOriginal(connection, asset, wrong), /格式与记录不一致/);
  const missing = (async () => new Response('private stack', {status: 404})) as typeof fetch;
  await assert.rejects(() => downloadRemoteOriginal(connection, asset, missing), error => error instanceof Error && /不存在/.test(error.message) && !error.message.includes('private'));
  const broken = (async () => {throw new Error('secret server address');}) as typeof fetch;
  await assert.rejects(() => downloadRemoteOriginal(connection, asset, broken), error => error instanceof Error && /检查连接/.test(error.message) && !error.message.includes('secret'));
});
