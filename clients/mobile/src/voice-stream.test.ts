import assert from 'node:assert/strict';
import test from 'node:test';
import {createLiveRecognition, supportsLiveRecognition} from './voice-stream';
import type {Connection} from './core';
import {VoicePcm, wavHeader} from './voice-pcm';

const turn = () => new Promise(resolve => setImmediate(resolve));
test('quota failures keep their actionable code but never expose arbitrary provider text',async()=>{
  for(const code of ['quota_exhausted','quota_busy']){
    const f=fixture();await turn();f.socket.onopen();
    f.reply({type:'error',take:'take-a',code,message:'private provider traceback'});
    await assert.rejects(f.live.finish(),error=>error instanceof Error && (error as Error&{code:string}).code===code && !error.message.includes('private'));
    assert.equal(f.closed,1);
  }
});
function fixture(connection: Connection = {endpoint: 'https://wearing.example/', identity: 'daily'}) {
  const sent: (string | Uint8Array)[] = [];
  let closed = 0, urls: string[] = [];
  const socket = {bufferedAmount: 0, onopen: null as any, onclose: null as any, onerror: null as any, onmessage: null as any,
    send: (value: any) => sent.push(value), close: () => {closed++;}};
  const live = createLiveRecognition(connection, 'take-a', async () => 'private-token', url => {urls.push(url); return socket;});
  const reply = (value: unknown) => socket.onmessage({data: JSON.stringify(value)});
  return {live, socket, sent, reply, get closed() {return closed;}, urls};
}

test('cloud iOS uses realtime audio with tenant-bound first frame and no credentials in URL', async () => {
  const connection: Connection = {endpoint:'https://pajio.example/',identity:'daily',session:{accessToken:'t'.repeat(64),tenantId:'tenant-a',userId:'user_'+'a'.repeat(32),credentialId:'d'.repeat(32),expiresAt:new Date(Date.now()+3600000).toISOString()}};
  assert.equal(supportsLiveRecognition(connection,'ios'),true);
  assert.equal(supportsLiveRecognition(connection,'android'),false);
  assert.equal(supportsLiveRecognition({...connection,session:undefined},'ios'),false);
  const f=fixture(connection); await turn(); f.socket.onopen();
  assert.equal(f.urls[0],'wss://pajio.example/api/voice/stream');
  assert.equal(JSON.parse(f.sent[0] as string).expected_tenant,'tenant-a');
  assert.equal(JSON.parse(f.sent[0] as string).access,connection.session!.accessToken);
  f.live.cancel(); await assert.rejects(f.live.finish());
});

test('startup preserves every chunk and explicit finish delivers only final text', async () => {
  const f = fixture();
  f.live.push(new Uint8Array([1, 0])); await turn(); f.socket.onopen();
  assert.equal(f.urls[0], 'wss://wearing.example/api/voice/stream');
  assert.equal(f.sent.length, 1);
  f.reply({type: 'ready', take: 'take-a'});
  f.live.push(new Uint8Array([2, 0]));
  const result = f.live.finish();
  assert.deepEqual(f.sent.slice(1, 3), [new Uint8Array([1, 0]), new Uint8Array([2, 0])]);
  assert.deepEqual(JSON.parse(f.sent[3] as string), {type: 'finish', bytes: 4});
  f.reply({type: 'final', take: 'take-a', text: '明天3点'});
  assert.deepEqual(await result, {text: '明天3点'}); assert.equal(f.closed, 1);
});

test('cancel region buffers audio and returning sends it in order without reconnecting', async () => {
  const f = fixture(); await turn(); f.socket.onopen(); f.reply({type: 'ready', take: 'take-a'});
  f.live.pause(true); f.live.push(new Uint8Array([1, 0])); f.live.push(new Uint8Array([2, 0]));
  assert.equal(f.sent.length, 1); f.live.pause(false); assert.equal(f.sent.length, 3);
  f.live.cancel(); await assert.rejects(f.live.finish()); assert.equal(f.urls.length, 1);
});

test('cancellation discards late final and startup never connects after cancel', async () => {
  const f = fixture(); f.live.cancel(); await turn();
  assert.equal(f.urls.length, 0); await assert.rejects(f.live.finish());
  const g = fixture(); await turn(); g.socket.onopen(); g.live.push(new Uint8Array([0, 0]));
  const result = g.live.finish(); g.live.cancel(); g.reply({type: 'final', take: 'take-a', text: 'late'});
  await assert.rejects(result); assert.equal(g.closed, 1);
});

test('a foreign take, premature final, or network backlog cannot produce text', async () => {
  for (const mode of ['foreign', 'early', 'backlog']) {
    const f = fixture(); await turn(); f.socket.onopen(); f.reply({type: 'ready', take: 'take-a'});
    if (mode === 'backlog') {f.socket.bufferedAmount = 192000; f.live.push(new Uint8Array([0, 0]));}
    else f.reply({type: 'final', take: mode === 'foreign' ? 'take-b' : 'take-a', text: 'not accepted'});
    await assert.rejects(f.live.finish()); assert.equal(f.closed, 1);
  }
});

test('PCM conversion is identical across arbitrary buffer boundaries at every supported rate', () => {
  for (const rate of [16000, 24000, 32000, 44100, 48000]) {
    const audio = Float32Array.from({length: rate}, (_, i) => Math.sin(i / rate * 2 * Math.PI * 440) * .8);
    const expected = new VoicePcm().push(audio.buffer, rate, 1);
    assert.equal(expected.length, 32000);
    const converter = new VoicePcm(), chunks: Uint8Array[] = [];
    for (let i = 0; i < rate; i += 317) chunks.push(converter.push(audio.slice(i, i + 317).buffer, rate, 1));
    assert.deepEqual(Buffer.concat(chunks), Buffer.from(expected));
  }
});

test('WAV metadata matches preserved PCM and malformed hardware format fails closed', () => {
  const header = wavHeader(32000), view = new DataView(header.buffer);
  assert.equal(Buffer.from(header.slice(0, 4)).toString(), 'RIFF'); assert.equal(view.getUint32(40, true), 32000);
  assert.equal(view.getUint32(24, true), 16000); assert.equal(view.getUint16(34, true), 16);
  assert.throws(() => new VoicePcm().push(new Float32Array([NaN]).buffer, 16000, 1));
  assert.throws(() => new VoicePcm().push(new Float32Array([0]).buffer, 16000, 2));
  const pcm = new VoicePcm(); pcm.push(new Float32Array([0]).buffer, 16000, 1);
  assert.throws(() => pcm.push(new Float32Array([0]).buffer, 48000, 1));
});
