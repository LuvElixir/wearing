import {useCallback, useEffect, useMemo, useSyncExternalStore} from 'react';
import {AppState} from 'react-native';
import {WearingApi, type Connection} from './core';
import {activityScope, createActivityStore} from './activity-store';
import {serviceFetch} from './transport';

const activityStore = createActivityStore({load: (connection, query) => new WearingApi(connection, serviceFetch).activity(query)});
export const refreshActivitySnapshot = (connection: Connection) => activityStore.refresh(connection);
let lifecycleUsers = 0;
let detachLifecycle: (() => void) | null = null;
const isForeground = () => AppState.currentState === 'active' || AppState.currentState === null;
function attachLifecycle() {
  if (!lifecycleUsers++) {
    activityStore.setForeground(isForeground());
    const subscription = AppState.addEventListener('change', state => activityStore.setForeground(state === 'active'));
    detachLifecycle = () => subscription.remove();
  }
  return () => {if (!--lifecycleUsers) {detachLifecycle?.(); detachLifecycle = null;}};
}

/** Navigation consumers share the same immutable snapshot; retained/hidden views can opt out. */
export function useActivitySnapshot(connection: Connection, enabled = true) {
  const scope = activityScope(connection);
  useEffect(attachLifecycle, []);
  const scopedConnection = useMemo<Connection>(() => ({...connection,
    ...(connection.development ? {development: {...connection.development}} : {}),
    ...(connection.session ? {session: {...connection.session}} : {}),
  }), [connection]);
  const subscribe = useCallback((listener: () => void) => {
    activityStore.setForeground(isForeground());
    return enabled ? activityStore.subscribe(scopedConnection, listener) : () => {};
  }, [scopedConnection, enabled]);
  const getSnapshot = useCallback(() => activityStore.getSnapshot(scopedConnection), [scopedConnection]);
  const state = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const refresh = useCallback(() => activityStore.refresh(scopedConnection), [scopedConnection]);
  return {...state, scope, refresh};
}
