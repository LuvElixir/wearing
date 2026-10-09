# Pajio connection feedback recovery — 2026-10-07

## Observed issue and cause

The coordinating agent observed the iPhone Air simulator showing “暂时连不上 Pajio，请检查连接后重试。” globally while the My page reported “已连接” after the backend had recovered. This audit did not operate the simulator.

`Mobile.synchronize()` previously wrote failures into the same persistent message state as user actions. A later successful synchronization set `connected=true`, but updated the message only when the outbox actually sent a record. An empty queue therefore left the old outage banner visible indefinitely. The connected indicator was also set after bootstrap, before the records snapshot and local persistence had completed.

## Bounded change

- `clients/mobile/src/Mobile.tsx` now tags feedback as `action` or `sync` and sets connected only after bootstrap, snapshot, and local persistence complete for the current connection.
- `clients/mobile/src/mobile-sync-feedback.ts` contains the pure success and failure feedback decisions. A completed synchronization retires its own old outage/receipt, or displays the actual sent count. A nonempty action message is preserved through both a failed refresh and later recovery, even if its text equals a network error or uploads completed while the action was underway.
- The locally queued-record notice is tagged `sync`, allowing its eventual upload receipt to replace it.
- The existing outbox flush condition and development-pairing default remain intact. The feedback helper performs no I/O and cannot flush the queue.
- Final review additionally introduced a synchronous capture lock shared by saving, photo/media persistence, and identity activation. The accepted draft is persisted before waiting on an outbox commit; identity activation resolves the destination draft before exposing its identity. A late media write checks the current connection before updating the form. See `capture-lifecycle.md` for the six committed actual-source handler tests and their limits.
- The synchronization cleanup now releases `syncBusy` and the busy indicator in an inner `finally`, even when `local(connection)` rejects. A local-read failure is surfaced as an action warning instead of leaving future synchronizations permanently locked.

Final source SHA-256:

```text
df3aac6f27416cb0a5ca8c104e62018da36200fd8d1d260d49354f619dd541dc  clients/mobile/src/Mobile.tsx
8ce4e710e3ea2c22b3d3026bb13b19657381b1861dc84a9f771216b6669e2927  clients/mobile/src/mobile-sync-feedback.ts
72cd0f5d1f1da9a5a119963033c8fef57e3d57963e93f484f9d798c902b81276  clients/mobile/src/mobile-sync-feedback.test.ts
db7a0a01b1b0a7f8f2166754d82976bea64bd7fd9dc2e0bd00801b8a1d484776  clients/mobile/src/mobile-capture-lifecycle.test.ts
```

## Repeatable verification

Run from `clients/mobile`:

```sh
node --import tsx --test src/mobile-sync-feedback.test.ts
node --import tsx --test src/mobile-capture-lifecycle.test.ts
npm test
npm run typecheck
node node_modules/eslint/bin/eslint.js src
```

Final-review result:

- The root agent ran the full mobile suite after the final-review changes: **196 passed, 0 failed**, including 8 feedback-decision tests and 6 capture/synchronization lifecycle handler tests. This documentation update read the actual log at `/tmp/pajio-final-mobile-tests-20261007.log` and copied it unchanged to `connection-recovery-final-mobile-suite.log`; it did not rerun the suite. The final log includes the new failure → recovery action-warning preservation case and all six handler cases.

Earlier checkpoint results, retained for audit history; these logs predate the final-review source hashes above:

- Focused regression suite: 7 passed, 0 failed. Covers empty-queue outage recovery; identical text with action provenance; preservation of unconfirmed edits and failed draft saves with and without sent records; a newer action before completion; an actual upload receipt replacing the queue notice; dismissal/empty-message behavior; and retiring an old synchronization receipt without mutating its input. Log: `connection-recovery-focused.log`. The final review added an eighth case.
- Mobile suite: 189 passed, 0 failed. Log: `connection-recovery-mobile-suite.log`. Superseded by the root agent's final 196-test result above.
- Earlier typecheck: exit 0. Log: `connection-recovery-typecheck.log`.
- Earlier source lint: exit 0, no output. Log: `connection-recovery-lint.log`.

The two earlier static-check logs are not presented as static-check results for the final source. This document-only follow-up did not rerun typecheck or lint; any final static-check evidence remains with the coordinating agent.

`npm run lint` was attempted earlier, but Expo's invocation of this machine's global npx failed with `ReferenceError: require is not defined in ES module scope`. The local ESLint binary above uses the repository's ESLint configuration and successfully checks `src`. A broad direct lint of the project directory also traversed existing `dist-*` generated bundles, which the current configuration does not exclude; that generated-output run is not a successful lint result. No global tooling or lint configuration was changed.

An earlier ad hoc VM harness extracted `synchronize()` and exercised 9 mocked scenarios. That harness was temporary, was not committed, and is **not** counted as a formal suite or as native/runtime acceptance. The repeatable feedback regression is now the committed 8-test suite. A separate committed 6-test lifecycle harness executes handlers extracted from the actual current `Mobile.tsx`, with an in-memory store and stubbed native/services. These are repeatable JavaScript tests, not a mounted React/native application or a real backend outage test.

## Late snapshot and identity review

Source review of `Mobile.tsx` (`local`, `synchronize`, and `activateConnection`) and `core.ts:54` found no path for a late old-identity snapshot to populate the new identity's UI or storage scope:

1. Each synchronization captures its `connection` argument. API requests and the `snapshot:` / `receipts:` keys use that captured connection. `scopeOf` includes the normalized endpoint and identity.
2. If identity changes during the snapshot request, the old snapshot may still update the **old** connection's scoped cache. It does not use `current.current` to choose a new cache key. This behavior has not been changed into cancellation/discard.
3. Success and failure feedback/connected updates are gated by `current.current === connection`. The bootstrap identity-list update has the same guard immediately after its await.
4. `local(connection)` loads the old scoped data but checks the current connection after its reads before calling `setRecords` or `setPending`.
5. The single synchronization lock is released before initiating a synchronization of the newly selected connection. Its flush callback already checks current connection and foreground state. Final review put this release in an inner `finally`, so failed local refresh cannot strand the lock.
6. Final review makes identity activation share the capture write lock and load/persist the destination draft before publishing its connection/form pair. The committed handler test exercises a deferred destination-draft read and verifies that the old identity remains current until the new draft is ready.

The old-snapshot isolation assessment is a source-review conclusion; the new handler tests cover selected controlled asynchronous races with synthetic storage and promises. They do not exercise React scheduling, a real network/storage failure, a physical/native identity switch, or all possible race interleavings.

## Backend and model status evidence

At `2026-10-07T10:45:58Z`, a read-only `GET http://127.0.0.1:8765/api/runtime` with `X-Wearing-Identity: daily` returned HTTP success and:

```json
{
  "running": true,
  "phase": "running",
  "revision": "367441274c48",
  "product": {"name": "Pajio", "profile_version": 24, "applied": true},
  "model": {"state": "configured", "provider": "deepseek"}
}
```

`SettingsHubContent` reads `PersonalHubApi.runtime()` on mount, connection-state changes, and explicit refresh; that API reads `/api/runtime`. Bootstrap is not the model-data source. A continuously mounted My page with unchanged connection state does not poll provider/model changes. This API read confirms the backend's reported configuration; it does not prove a model completion or that an already installed simulator bundle contains this patch.

## Native acceptance still required at handoff

The source hashes above were refreshed after the final review; the original helper handoff hashes are superseded. This follow-up changed documentation/evidence only and reused the root agent's final suite log. This audit made no service/process change and performed no GUI actions. The following claims require the root agent's separate evidence: the final simulator bundle contains these source changes; a real network failure followed by recovery removes the old banner with an empty queue; user drafts remain intact in the native UI; and a native identity-switch race cannot expose stale content.
