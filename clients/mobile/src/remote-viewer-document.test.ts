import test from 'node:test';
import assert from 'node:assert/strict';
import {runInNewContext} from 'node:vm';
import {remoteViewerDocument} from './remote-viewer-document';

type Message = Record<string, unknown>;
type Handler = (value?: unknown) => void;
async function harness(pointer = false) {
  const sent: Message[] = [], posted: Message[] = [], events: Record<string, Handler> = {}, page: Record<string, Handler> = {};
  let stamp = 1_000_000, frameCallback: (() => void) | null = null, closed = false, remoteDescriptions = 0;
  const intervals = new Map<number, () => void>(), shade = {style: {display: 'block'}};
  const video = {videoWidth: 1080, videoHeight: 1920, srcObject: null, pause() {}, play: async () => {},
    addEventListener: (key: string, fn: Handler) => {events[key] = fn;},
    requestVideoFrameCallback: (fn: () => void) => {frameCallback = fn;}, setPointerCapture() {},
    getBoundingClientRect: () => ({left: 0, top: 0, width: 320, height: 400})};
  const channel = {readyState: 'open', bufferedAmount: 0, onopen: () => {}, onclose: () => {}, onerror: () => {}, onmessage: (_: {data: string}) => {},
    send: (text: string) => {sent.push(JSON.parse(text));}, close: () => {closed = true;}};
  class Peer {
    iceGatheringState = 'complete'; localDescription = {sdp: 'v=0\r\n'}; connectionState = 'connected';
    addTransceiver() {} createDataChannel() {return channel;} close() {closed = true;}
    createOffer = async () => this.localDescription; setLocalDescription = async () => {};
    setRemoteDescription = async () => {remoteDescriptions++;}; getStats = async () => new Map();
  }
  const bridge = {ReactNativeWebView: {postMessage: (text: string) => {posted.push(JSON.parse(text));}},
    addEventListener: (name: string, fn: Handler) => {page[name] = fn;}, pajioReceive: async (_: Message) => {}};
  const doc = {hidden: false, getElementById: (id: string) => id === 'screen' ? video : shade,
    addEventListener: (name: string, fn: Handler) => {page[name] = fn;}};
  const html = remoteViewerDocument({kind: 'webrtc', session_id: 'human_one', epoch: 3, gateway_epoch: 7, ice_servers: []}, pointer ? 'computer' : 'android', 1600);
  const script = html.slice(html.indexOf('<script>') + 8, html.indexOf('</script>'));
  runInNewContext(script, {window: bridge, document: doc, RTCPeerConnection: Peer, TextEncoder, Date: {now: () => stamp},
    setInterval: (fn: () => void, ms: number) => {intervals.set(ms, fn); return ms;}, clearInterval: (ms: number) => intervals.delete(ms),
    setTimeout: () => 0, clearTimeout: () => {}, console});
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  channel.onopen();
  const fromHost = (value: Message) => channel.onmessage({data: JSON.stringify(value)});
  const scope = {session_id: 'human_one', epoch: 3, gateway_epoch: 7};
  const ready = (text = pointer ? 'unicode' : 'ascii') => fromHost({type: 'ready', ...scope, capabilities: {pointer, keyboard: true, text, touch: true}});
  const frame = (values: Message = {}) => {
    fromHost({type: 'frame', frame_id: 'frame_a', width: 1080, height: 1920, gateway_epoch: 7, ...values});
    events.loadeddata(); frameCallback?.();
  };
  const touch = (type: string, x = 160, y = 200) => events[type]({pointerId: 1, clientX: x, clientY: y, button: 0, preventDefault() {}});
  return {sent, posted, ready, frame, touch, fromHost, video, shade, scope,
    native: bridge.pajioReceive, inputs: () => sent.filter(m => m.type === 'input'), isClosed: () => closed, descriptions: () => remoteDescriptions,
    tick: (ms: number) => {stamp += ms; intervals.get(300)?.();}, hide: () => {doc.hidden = true; page.visibilitychange();}, heartbeat: () => intervals.get(5000)?.()};
}
test('viewer waits for device ACK and decoded video; opening viewer does not enable input', async () => {
  const h = await harness(); h.frame(); assert.equal(h.posted.some(m => m.type === 'live'), false);
  h.ready(); h.frame(); assert.equal(h.posted.filter(m => m.type === 'live').length, 1);
  h.touch('pointerdown'); h.touch('pointerup'); assert.equal(h.inputs().length, 0);
  await h.native({type: 'control', enabled: true}); h.touch('pointerdown'); h.touch('pointerup');
  assert.equal(h.inputs().length, 1);
  assert.deepEqual(h.inputs()[0], {type: 'input', ...h.scope, seq: 1, frame_id: 'frame_a', action: 'tap', x: 540, y: 960});
});
test('private input is never queued or replayed after an unacknowledged action', async () => {
  const h = await harness(); h.ready(); h.frame(); await h.native({type: 'control', enabled: true});
  h.touch('pointerdown'); h.touch('pointerup'); assert.equal(h.inputs().length, 1);
  h.tick(2600); assert.equal(h.isClosed(), true);
  await h.native({type: 'text', text: 'secret'}); h.touch('pointerdown'); h.touch('pointerup');
  assert.equal(h.inputs().length, 1); assert.equal(h.video.srcObject, null);
});
test('background immediately destroys private view and ignores late signaling', async () => {
  const h = await harness(); h.ready(); h.frame(); await h.native({type: 'control', enabled: true}); h.hide();
  assert.equal(h.isClosed(), true); assert.equal(h.shade.style.display, 'block');
  await h.native({type: 'answer', gateway_epoch: 7, sdp: 'v=0\r\n'});
  h.fromHost({type: 'ready', ...h.scope}); h.heartbeat();
  assert.equal(h.descriptions(), 0); assert.equal(h.inputs().length, 0);
  assert.equal(h.posted.filter(m => m.type === 'stopped').length, 1);
});
test('rotated video and stale metadata never map touches against another geometry', async () => {
  const h = await harness(true); h.ready(); h.frame(); await h.native({type: 'control', enabled: true});
  h.touch('pointerdown', 0, 200); assert.equal(h.inputs().length, 0);
  h.tick(1900); h.touch('pointerdown'); assert.equal(h.inputs().length, 0);
  h.frame(); h.touch('pointerdown'); assert.equal(h.inputs().length, 1);
  h.frame({width: 1920, height: 1080}); h.touch('pointerup');
  assert.equal(h.isClosed(), true); assert.equal(h.inputs().length, 1);
});
test('Android rejects unsupported text without echoing it and freeze prevents input but keeps heartbeat', async () => {
  const h = await harness(); h.ready(); h.frame(); await h.native({type: 'control', enabled: true});
  await h.native({type: 'text', text: '秘密%123'});
  assert.equal(h.inputs().length, 0); assert.equal(JSON.stringify(h.posted).includes('秘密'), false);
  await h.native({type: 'freeze'}); await h.native({type: 'text', text: 'secret'}); h.heartbeat();
  assert.equal(h.inputs().length, 0); assert.equal(h.isClosed(), false); assert.equal(h.shade.style.display, 'block');
  assert.equal(h.sent.filter(m => m.type === 'heartbeat').length, 2);
});
test('wrong gateway epoch fails closed before displaying a frame', async () => {
  const h = await harness(); h.fromHost({type: 'ready', ...h.scope, gateway_epoch: 8}); h.frame();
  assert.equal(h.isClosed(), true); assert.equal(h.posted.some(m => m.type === 'live'), false);
});
test('legacy adb ASCII and unavailable text capabilities cannot receive private text', async () => {
  for (const capability of ['ascii', 'unavailable', 'unexpected']) {
    const h = await harness(); h.ready(capability); h.frame(); await h.native({type: 'control', enabled: true});
    await h.native({type: 'text', text: 'Private123'});
    assert.equal(h.inputs().length, 0);
    assert.equal(h.posted.at(-1)?.code, 'text_unavailable');
    assert.equal(JSON.stringify(h.posted).includes('Private123'), false);
  }
});
