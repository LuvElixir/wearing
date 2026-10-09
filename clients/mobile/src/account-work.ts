import {accountKey} from './account-deletion-client';
import type {Connection} from './core';
const stops = new Map<string, Set<() => Promise<void>>>(), frozen = new Set<string>();
const key = (connection: Connection) => connection.session ? accountKey(connection) : null;
export function accountWorkAllowed(connection: Connection) {const target = key(connection); return !target || !frozen.has(target);}
export function registerAccountWork(connection: Connection, stop: () => Promise<void>) {
  const target = key(connection); if (!target) return () => {};
  const entries = stops.get(target) || new Set(); entries.add(stop); stops.set(target, entries);
  if (frozen.has(target)) void stop();
  return () => {entries.delete(stop); if (!entries.size) stops.delete(target);};
}
export async function stopDeletedAccountWork(connection: Connection) {
  const target = key(connection); if (!target) return;
  frozen.add(target);
  await Promise.all([...(stops.get(target) || [])].map(stop => stop()));
}
