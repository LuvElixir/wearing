import {useEffect, useMemo, useSyncExternalStore} from 'react';
import {Connection, scopeOf} from './core';
import {storage} from './storage';
import {WardrobeSession} from './wardrobe';

export function useWardrobe(connection: Connection | null) {
  const scope = connection ? scopeOf(connection) : 'local-preview';
  const session = useMemo(() => new WardrobeSession(storage, scope), [scope]);
  const state = useSyncExternalStore(session.subscribe, session.snapshot, session.snapshot);
  useEffect(() => {void session.load();}, [session]);
  return {session, state};
}
export type WardrobeController = ReturnType<typeof useWardrobe>;
