/** Polling may finish first, but it must never swallow an explicit user action.
 * One user action can wait behind the current read. Repeated taps and later polls
 * are ignored until it finishes; uncertain writes are never retried here. */
export function createTaskRequestQueue() {
  let live = true;
  let pending: Promise<boolean> | null = null;
  let userPending = false;

  const run = (user: boolean, work: () => Promise<void>): Promise<boolean> => {
    if (!live || userPending || (!user && pending)) return Promise.resolve(false);
    const previous = pending;
    if (user) userPending = true;
    const operation = Promise.resolve(previous).catch(() => {}).then(async () => {
      if (!live) return false;
      await work();
      return true;
    }).finally(() => {
      if (user) userPending = false;
      if (pending === operation) pending = null;
    });
    pending = operation;
    return operation;
  };

  return {
    get userPending() {return userPending;},
    background: (work: () => Promise<void>) => run(false, work),
    user: (work: () => Promise<void>) => run(true, work),
    close() {live = false;},
  };
}
