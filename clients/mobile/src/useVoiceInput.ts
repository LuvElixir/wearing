import {useEffect, useLayoutEffect, useMemo, useState, useSyncExternalStore} from 'react';
import {AppState, Platform} from 'react-native';
import * as Crypto from 'expo-crypto';
import {scopeOf, WearingApi, type Connection} from './core';
import {keepMedia, preview, storage} from './storage';
import {serviceFetch} from './transport';
import {createVoiceRecorder} from './voice-recorder';
import {VoiceSession, type VoiceText} from './voice-session';
import {createLiveRecognition} from './voice-stream';

export type {VoiceText, VoiceDraft, VoicePhase} from './voice-session';
const empty = {phase: 'idle' as const, ready: false, message: '', draft: null};
const noopSubscribe = () => () => {};
const emptySnapshot = () => empty;
const noop = async () => {};
const foreground = () => AppState.currentState !== 'background' && AppState.currentState !== 'inactive' && (Platform.OS !== 'web' || typeof document === 'undefined' || !document.hidden);

/** Only start/commit/retry are user actions; mounting never opens the microphone. */
export function useVoiceInput({connection, active, onText}: {connection: Connection | null; active: boolean; onText: (text: VoiceText) => void}) {
  const scope = connection ? scopeOf(connection) : '';
  const [current] = useState(() => ({scope, active, foreground: foreground(), onText}));
  const session = useMemo(() => {
    if (!scope) return null;
    const selected = connection!;
    const api = new WearingApi(selected, serviceFetch);
    return new VoiceSession({
      connection: selected, store: storage,
      recorder: take => createVoiceRecorder(selected.development && Platform.OS === 'ios'
        ? {take, connect: () => createLiveRecognition(selected, take, () => api.voiceAuthorization())} : undefined), keepMedia,
      upload: (media, blob, key) => api.upload(media, blob, key), transcribe: asset => api.transcribe(asset), newId: Crypto.randomUUID,
      isAvailable: () => current.scope === scope && current.active && current.foreground,
      onText: text => {if (current.scope === text.scope) current.onText(text);},
      onDiagnostic: event => {if (__DEV__) console.info('[Wearing voice]', JSON.stringify(event));},
    });
    // A normalized endpoint and identity own a session, not the connection object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);
  const state = useSyncExternalStore(session?.subscribe ?? noopSubscribe, session?.getSnapshot ?? emptySnapshot, emptySnapshot);
  const [duration, setDuration] = useState({snapshot: state, millis: 0});
  const [isForeground, setForeground] = useState(foreground);
  useLayoutEffect(() => {
    Object.assign(current, {scope, active, foreground: foreground(), onText});
    if (!active || !current.foreground) void session?.interrupt();
  }, [scope, active, onText, session, current]);
  useEffect(() => {
    session?.activate();
    void session?.restore();
    return () => {void session?.dispose();};
  }, [session]);
  useEffect(() => {
    const check = () => {
      current.foreground = foreground();
      setForeground(current.foreground);
      if (!current.foreground) void session?.interrupt();
    };
    const subscription = AppState.addEventListener('change', check);
    if (Platform.OS === 'web' && typeof document !== 'undefined') document.addEventListener('visibilitychange', check);
    return () => {subscription.remove(); if (Platform.OS === 'web' && typeof document !== 'undefined') document.removeEventListener('visibilitychange', check);};
  }, [session, current]);
  useEffect(() => {
    if (state.phase !== 'recording' || !session) return;
    const timer = setInterval(() => {
      const duration = session.durationMillis();
      setDuration({snapshot: state, millis: duration});
      if (duration >= 180000) void session.interrupt();
    }, 250);
    return () => clearInterval(timer);
  }, [session, state]);
  const originalUri = async () => {
    const draft = session?.getSnapshot().draft;
    return draft?.media ? preview(draft.media.id) : draft?.uri ?? null;
  };
  return {...state, durationMillis: duration.snapshot === state && state.phase === 'recording' ? duration.millis : 0, canStart: active && isForeground && !!session?.canStart,
    start: session?.start ?? noop, commit: session?.commit ?? noop, cancel: session?.cancel ?? noop,
    pauseRecognition: session?.pauseRecognition,
    retry: session?.retry ?? noop, ack: session?.ack ?? noop, interrupt: session?.interrupt ?? noop, originalUri};
}
