import type {Connection} from './core';

export type ComposerState = {
  type: 'wearing-composer-state'; identity: string; pageId: string; contextKey: string;
  text: string; sending: boolean; ready: boolean; ackSeq: number; error?: string;
  contextLabel?: string; ackVoiceId?: string;
};
export type ComposerCommand = {kind: 'sync' | 'change' | 'send' | 'append'; text?: string; voiceId?: string};

/** Only accept draft presentation receipts from the connected page, never native commands. */
export function readComposerState(raw: string, source: string, connection: Connection): ComposerState | null {
  try {
    if (raw.length > 30000 || new URL(source).origin !== new URL(connection.endpoint).origin) return null;
    const value = JSON.parse(raw);
    if (value?.type !== 'wearing-composer-state' || value.identity !== connection.identity ||
      typeof value.pageId !== 'string' || value.pageId.length < 8 || value.pageId.length > 100 ||
      typeof value.contextKey !== 'string' || value.contextKey.length > 4000 ||
      typeof value.text !== 'string' || value.text.length > 12000 ||
      typeof value.sending !== 'boolean' || typeof value.ready !== 'boolean' ||
      !Number.isSafeInteger(value.ackSeq) || value.ackSeq < 0 ||
      (value.error !== undefined && (typeof value.error !== 'string' || value.error.length > 2000)) ||
      (value.contextLabel !== undefined && (typeof value.contextLabel !== 'string' || value.contextLabel.length > 1000)) ||
      (value.ackVoiceId !== undefined && (typeof value.ackVoiceId !== 'string' || !/^voice-[a-f0-9-]{36}$/.test(value.ackVoiceId)))) return null;
    const context = JSON.parse(value.contextKey);
    if (context?.identity !== connection.identity) return null;
    return value;
  } catch {return null;}
}

export function composerScript(state: ComposerState, seq: number, command: ComposerCommand): string {
  const payload = {...command, identity: state.identity, pageId: state.pageId, contextKey: state.contextKey, seq};
  return `window.WearingHost?.composerCommand?.(${JSON.stringify(payload)}); true;`;
}
