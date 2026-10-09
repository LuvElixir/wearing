# Pajio capture and synchronization lifecycle — final review, 2026-10-07

This record describes the final-review changes already present in `clients/mobile/src/Mobile.tsx`. The evidence follow-up changed no source and ran no additional suite. It inspected the committed tests and the root agent's completed final test log.

## Final-review behavior

- A synchronous `captureWriting` ref acquires the capture lock before React can render an updated disabled state. Saving, photo selection/persistence, and identity activation share this lock; form changes return while it is held. Pending draft debounce is cleared on acquisition.
- Save first preserves the accepted form in the current identity's draft storage, then waits for the existing outbox's atomic enqueue/draft-clear operation. A failed commit retains the form and releases the lock for retry. A late completion checks the current connection before publishing the empty form.
- Photo selection keeps the same lock until media and its draft are persisted. `addOriginal` checks the current connection again after writing the draft before publishing form state.
- Identity activation saves the old draft, resolves the destination draft, and persists the connection before making the destination connection/form visible together.
- Voice stop invoked inside save retains the outer save lock; a nested voice cleanup cannot release it before the save's commit completes.
- Synchronization always releases its lock/busy state even if its final local refresh rejects. Its failure feedback now preserves a nonempty action warning; a later recovery also preserves that warning.

## Repeatable actual-source tests

Run from `clients/mobile`:

```sh
node --import tsx --test src/mobile-capture-lifecycle.test.ts
node --import tsx --test src/mobile-sync-feedback.test.ts
```

`mobile-capture-lifecycle.test.ts` parses the current `Mobile.tsx` with TypeScript, selects the named function declarations, transpiles them, and runs those actual handlers in a VM. It uses the real `Outbox`, `makeDraft`, and `scopeOf`, an in-memory `Store`, deferred promises, and stubbed native/service APIs. It is a committed repeatable test harness rather than the earlier temporary nine-scenario harness.

Six lifecycle cases were present and passed in the root agent's final full-suite log:

1. A slow older outbox upload keeps a new save waiting while the accepted draft is persisted; late edit callbacks are ignored during the lock, and identity activation is rejected until completion.
2. A failed capture batch commit retains the input, releases saving/lock state, and allows another edit.
3. Deferred photo persistence holds the lock, prevents save/identity activation, and retains the original text alongside the saved media.
4. A deferred destination draft read keeps the old identity visible until the destination draft is loaded; the old draft remains in its own scope.
5. A failed final local refresh releases the sync lock and permits a subsequent synchronization attempt.
6. Stopping an active recording inside save cannot release the outer save lock before its deferred atomic commit completes; the queued record retains the audio media.

The separate feedback suite has eight cases, including the final failure → recovery case proving that an unresolved save warning survives both operations.

## Inspected results and source identity

The root agent's `/tmp/pajio-final-mobile-tests-20261007.log` reports **196 tests, 196 passed, 0 failed**. The unchanged evidence copy is `connection-recovery-final-mobile-suite.log`. The 196 include the six lifecycle and eight feedback tests above, rather than being additional to them. Earlier 189-test and 7-test logs in this directory describe the earlier checkpoint only.

```text
df3aac6f27416cb0a5ca8c104e62018da36200fd8d1d260d49354f619dd541dc  clients/mobile/src/Mobile.tsx
8ce4e710e3ea2c22b3d3026bb13b19657381b1861dc84a9f771216b6669e2927  clients/mobile/src/mobile-sync-feedback.ts
72cd0f5d1f1da9a5a119963033c8fef57e3d57963e93f484f9d798c902b81276  clients/mobile/src/mobile-sync-feedback.test.ts
db7a0a01b1b0a7f8f2166754d82976bea64bd7fd9dc2e0bd00801b8a1d484776  clients/mobile/src/mobile-capture-lifecycle.test.ts
```

## Limits

The VM does not mount React, run hook effects, open an image picker, record real audio, use native SQLite/filesystem, or contact a live service. The tests deliberately control promise completion order; they do not prove all scheduler interleavings. The six cases do not explicitly test every rapid double-tap or an old network snapshot returning after a native identity change. The latter remains a source-review conclusion described in `connection-recovery.md`.

These results therefore support the handler's draft/lock/feedback decisions under the named scenarios. Final iOS bundle inclusion, device interactions, actual service outage/recovery, and real media/draft persistence require the root agent's separate native acceptance evidence. No source/build/service changes were made by this document-only follow-up.
