import type {ActivityQuery, ActivitySnapshot, Connection} from './core';

export type ActivityState = Readonly<{snapshot: ActivitySnapshot | null; loading: boolean; error: string; stale: boolean}>;
type Listener = () => void;
type Options = {
  load: (connection: Connection, query: ActivityQuery) => Promise<ActivitySnapshot>;
  now?: () => number;
  pollMs?: number;
  schedule?: (callback: () => void, milliseconds: number) => () => void;
};
type Entry = {
  connection: Connection;
  state: ActivityState;
  listeners: Set<Listener>;
  pending: Promise<ActivitySnapshot | null> | null;
  cancelTimer: (() => void) | null;
  epoch: number;
  readAt: number;
};

/** Private in-memory key only: credentials isolate a renewed pairing as well as identities. */
export const activityScope = (connection: Connection) => JSON.stringify([
  connection.endpoint.trim().replace(/\/$/, ''), connection.identity,
  connection.development?.accessToken || '', connection.development?.expiresAt || '',
  connection.session?.userId || '', connection.session?.tenantId || '', connection.session?.credentialId || '',
  connection.session?.accessToken || '', connection.session?.expiresAt || '',
]);

/** One first-page snapshot and polling clock per authenticated identity. No background worker,
 * read acknowledgement, optimistic task state, or persistent credential cache lives here. */
export function createActivityStore({load, now = Date.now, pollMs = 15000, schedule = (callback, ms) => {
  const timer = setInterval(callback, ms); return () => clearInterval(timer);
}}: Options) {
  const entries = new Map<string, Entry>();
  let foreground = true;
  function entryFor(connection: Connection) {
    const key = activityScope(connection);
    let entry = entries.get(key);
    if (!entry) {
      // Bound retained snapshots. Active or inflight scopes are never evicted.
      if (entries.size >= 12) {
        for (const [oldKey, old] of entries) {
          if (!old.listeners.size && !old.pending) {entries.delete(oldKey); if (entries.size < 12) break;}
        }
      }
      entry = {connection: {...connection, session: connection.session ? {...connection.session} : undefined, development: connection.development ? {...connection.development} : undefined},
        state: {snapshot: null, loading: false, error: '', stale: true}, listeners: new Set(), pending: null, cancelTimer: null, epoch: 0, readAt: -Infinity};
      entries.set(key, entry);
    }
    return entry;
  }
  function publish(entry: Entry, state: ActivityState) {
    entry.state = state;
    for (const listener of [...entry.listeners]) listener();
  }
  function stop(entry: Entry) {
    entry.cancelTimer?.(); entry.cancelTimer = null;
    entry.epoch++;
    if (entry.state.loading) publish(entry, {...entry.state, loading: false});
  }
  function read(entry: Entry): Promise<ActivitySnapshot | null> {
    if (!foreground || !entry.listeners.size) return Promise.resolve(null);
    if (entry.pending) return entry.pending;
    const epoch = entry.epoch;
    // Assign the promise before notifying listeners, so synchronous refreshes also deduplicate.
    const pending = Promise.resolve().then(() => epoch === entry.epoch && foreground && entry.listeners.size
      ? load(entry.connection, entry.state.snapshot?.revision ? {since: entry.state.snapshot.revision} : {}) : null)
      .then(snapshot => {
        if (!snapshot || epoch !== entry.epoch || !foreground || !entry.listeners.size) return null;
        entry.readAt = now();
        publish(entry, {snapshot, loading: false, error: '', stale: false});
        return snapshot;
      }, cause => {
        if (epoch === entry.epoch && foreground && entry.listeners.size) {
          publish(entry, {...entry.state, loading: false, stale: true, error: cause instanceof Error ? cause.message : '暂时读不到进展，请稍后重试。'});
        }
        return null;
      }).finally(() => {
        if (entry.pending === pending) entry.pending = null;
        // A new subscriber/resume waits for the discarded request to finish; never overlap it.
        if (epoch !== entry.epoch && foreground && entry.listeners.size) void read(entry);
      });
    entry.pending = pending;
    publish(entry, {...entry.state, loading: true});
    return pending;
  }
  function start(entry: Entry) {
    if (!foreground || !entry.listeners.size) return;
    if (!entry.cancelTimer) entry.cancelTimer = schedule(() => {void read(entry);}, pollMs);
    if (entry.state.stale || now() - entry.readAt >= pollMs) void read(entry);
  }
  return {
    getSnapshot(connection: Connection): ActivityState {return entryFor(connection).state;},
    subscribe(connection: Connection, listener: Listener) {
      const entry = entryFor(connection);
      entry.listeners.add(listener); start(entry);
      let subscribed = true;
      return () => {
        if (!subscribed) return;
        subscribed = false; entry.listeners.delete(listener);
        if (!entry.listeners.size) stop(entry);
      };
    },
    refresh(connection: Connection) {return read(entryFor(connection));},
    setForeground(value: boolean) {
      if (foreground === value) return;
      foreground = value;
      for (const entry of entries.values()) {
        if (!value) {
          stop(entry);
          if (entry.state.snapshot && !entry.state.stale) publish(entry, {...entry.state, stale: true});
        } else start(entry);
      }
    },
  };
}
