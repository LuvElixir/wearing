import {voiceQuotaMessages} from './voice-diagnostics';
import {connectionEndpoint, type Connection} from './core';

export type LiveRecognition = {
  push(pcm: Uint8Array): void;
  pause(paused: boolean): void;
  finish(): Promise<{text: string}>;
  cancel(): void;
};
export function supportsLiveRecognition(connection: Connection, platform: string): boolean {
  return platform === 'ios' && !!(connection.session?.accessToken || connection.development?.accessToken);
}
type Socket = Pick<WebSocket, 'send' | 'close' | 'bufferedAmount' | 'onopen' | 'onmessage' | 'onerror' | 'onclose'>;
const error = () => new Error('实时识别中断，录音已保留，可以重试。');

/** One take, one socket. Bounded startup buffering; never replay a paid session. */
export function createLiveRecognition(connection: Connection, take: string, authorize: () => Promise<string>,
  factory: (url: string) => Socket = url => new WebSocket(url)): LiveRecognition {
  let socket: Socket | undefined, ended = false, ready = false, finishing = false, paused = false;
  let total = 0, queued = 0;
  const queue: Uint8Array[] = [];
  let resolve!: (value: {text: string}) => void, reject!: (reason: Error) => void;
  const result = new Promise<{text: string}>((yes, no) => {resolve = yes; reject = no;});
  void result.catch(() => {}); // Failure during recording is presented after the original is saved.
  let timer = setTimeout(() => fail(), 10000);
  const cleanup = () => {clearTimeout(timer); queue.length = 0; queued = 0; socket?.close();};
  const fail = (reason?: Error) => {if (ended) return; ended = true; reject(reason || error()); cleanup();};
  const flush = () => {
    if (ended || !ready || paused || !socket) return;
    try {
      for (const chunk of queue) {
        if (socket.bufferedAmount + chunk.byteLength > 192000) return fail();
        socket.send(chunk);
      }
      queue.length = 0; queued = 0;
      if (finishing) socket.send(JSON.stringify({type: 'finish', bytes: total}));
    } catch {fail();}
  };
  void (async () => {
    try {
      const token = await authorize();
      if (ended) return;
      const base = connectionEndpoint(connection);
      socket = factory(new URL('api/voice/stream', base).toString().replace(/^http/, 'ws'));
      socket.onopen = () => {
        if (ended) {socket?.close(); return;}
        try {socket!.send(JSON.stringify({type: 'start', identity: connection.identity, take,
          token, access: connection.session?.accessToken || connection.development?.accessToken, expected_tenant:connection.session?.tenantId, format: 'pcm_s16le_16000_mono'}));} catch {fail();}
      };
      socket.onmessage = event => {
        if (ended) return;
        try {
          if (typeof event.data !== 'string' || event.data.length > 65536) return fail();
          const response = JSON.parse(event.data);
          if (response.type === 'error' && typeof response.code === 'string' && voiceQuotaMessages[response.code]) return fail(Object.assign(new Error(voiceQuotaMessages[response.code]),{code:response.code}));
          if (response.type === 'ready' && response.take === take && !ready) {
            ready = true; clearTimeout(timer);
            timer = setTimeout(fail, finishing ? 12000 : 210000);
            flush();
          } else if (response.type === 'final' && response.take === take && finishing &&
            typeof response.text === 'string' && response.text.trim() && response.text.length <= 12000) {
            ended = true; resolve({text: response.text.trim()}); cleanup();
          } else fail();
        } catch {fail();}
      };
      socket.onerror = () => fail();
      socket.onclose = () => {if (!ended) fail();};
    } catch {fail();}
  })();
  return {
    push(pcm) {
      if (ended || finishing) return;
      if (!pcm.byteLength || pcm.byteLength % 2 || pcm.byteLength > 32000 || total + pcm.byteLength > 5760000 || queued + pcm.byteLength > 192000) return fail();
      total += pcm.byteLength; queued += pcm.byteLength; queue.push(pcm); flush();
    },
    pause(value) {if (ended || finishing) return; paused = value; if (!value) flush();},
    finish() {
      if (!ended && !finishing) {
        finishing = true; paused = false; clearTimeout(timer); timer = setTimeout(fail, 12000); flush();
      }
      return result;
    },
    cancel: fail,
  };
}
