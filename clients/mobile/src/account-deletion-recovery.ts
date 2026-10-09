import type {Connection} from './core';
import {type DeletionRecovery, type DeletionStatus} from './account-deletion-client';
export type DeletionDisposition = 'clear' | 'review';
export type DeletionRecoveryReader = {fenced(connection: Connection): Promise<boolean>; load(connection: Connection): Promise<DeletionRecovery | null>; status(recovery: DeletionRecovery): Promise<DeletionStatus>};
/** Unknown submission delivery is a recovery screen, never proof of live business access. */
export async function deletionDisposition(connection: Connection, reader: DeletionRecoveryReader): Promise<DeletionDisposition> {
  if (!connection.session) return 'clear';
  try {
    if (await reader.fenced(connection)) return 'review';
    const saved = await reader.load(connection);
    if (!saved) return 'clear';
    if (saved.phase === 'submitted') return 'review';
    return (await reader.status(saved)).state === 'not_submitted' ? 'clear' : 'review';
  } catch {return 'review';}
}
