export type MobileFeedback = {text: string; source: 'action' | 'sync'};

/** Call only after the current connection has completed synchronization. */
export function feedbackAfterSynchronization(previous: MobileFeedback, sent: number): MobileFeedback {
  // A successful background read cannot resolve an error from editing or saving.
  if (previous.source === 'action' && previous.text) return previous;
  return {text: sent ? sent + ' 条记录已同步，Pajio 也能接着看。' : '', source: 'sync'};
}

/** A transport outage cannot supersede an unresolved local save or edit. */
export function feedbackAfterSyncFailure(previous: MobileFeedback, text: string): MobileFeedback {
  return previous.source === 'action' && previous.text ? previous : {text, source: 'sync'};
}
