# App chat-import account cleanup verification

Date: 2026-10-09. This review used source code and synthetic in-memory SQLite rows only. No real account, chat archive, app database or Keychain was opened. No App implementation or App test source was changed during this evidence pass.

## Conclusion

The inherited account-deletion path actually deletes both `chat-import-draft:v1:<scope>` and `chat-import-pending:v1:<scope>` from SQLite. This is not inferred merely from a generic cleanup name. The exact namespaces were verified against the real planning function and the real SQL transaction, with both daily and work identities of one account. Another account's rows remained intact. The persisted account fence prevented late writes from restoring deleted import contents.

## Source chain

- `clients/mobile/src/chat-import-client.ts:9-10` defines the exact draft and pending keys.
- `clients/mobile/src/account-cleanup-model.ts:14-18` extracts authenticated scope from both key prefixes. Lines 43-46 add every owned scoped key to the removal plan. Ownership is canonical service endpoint plus user; it includes that user's identities and tenants.
- `clients/mobile/src/account-cleanup-state.ts:36-43` starts `BEGIN IMMEDIATE`, reads actual `local_state` rows and builds the plan. Lines 49-53 persist the account fence and execute `DELETE FROM local_state WHERE key = ?` for every planned key. Line 61 commits; the exception path rolls back.
- `clients/mobile/src/account-cleanup-native.ts:20-29` is the native account-deletion entry point: after the gateway admits the deletion request it stops account work and invokes this transaction under the shared SQLite queue. Its following loops remove inventoried Pajio-owned files and credentials, retaining failed cleanup references for retry.
- `clients/mobile/src/storage.ts:12-14` checks persisted fences before ordinary writes. `account-cleanup-model.ts:20-23` recognizes the same scoped key namespaces for write rejection.

## Test evidence

1. Existing `clients/mobile/src/chat-import-client.test.ts:65-71`, “account deletion removes private import contents only from its owner”, directly checks both exact key namespaces in `accountCleanupPlan` and foreign-account preservation. This tests the plan, not SQL execution by itself.
2. Existing `clients/mobile/src/account-cleanup.test.ts:30-34`, “atomic cleanup and durable fence reject old single/batch saves without touching switched account”, exercises the actual in-memory SQLite cleanup transaction and late-write fence with generic scoped rows.
3. Evidence-only `app-account-cleanup-verification.ts` combines these properties: actual draft and pending keys for two own identities (four rows), two foreign-account rows, real `prepareAccountCleanup`, real `createSqliteStore` with the production fence predicate, and single/batch late-write attempts. The four own rows are absent after cleanup, foreign rows remain, all owned late writes fail, and an atomic mixed batch leaves foreign rows unchanged. Result: **1/1 passed, exit 0**; see `app-account-cleanup-verification.log`.

The existing App full suite passed **720/720**, including the first two tests, in `app-tests-720.log`. The additional evidence-only check is not included in that 720 count.

## Logout versus account deletion

`native-session.ts:22-23` calls `clearChatImportPrivateDrafts` before forgetting session credentials. `chat-import-native.ts:37-72` clears every owned identity's preview body, strips pending requests down to a body-free request key, and removes claimed chat-import share copies. File deletion occurs before clearing the share inventory, so a failed deletion can be retried. The three `chat-import-native.test.ts` cases cover all-own-identity privacy clearing, a claimed share that failed before a draft was created, and file-deletion failure retaining its retry reference.

The distinction is intentional: logout retains only the opaque request key to resolve an unknown server result after signing back in; account deletion removes the entire pending key and blocks later writes. An unknown result with no retained body cannot be silently resubmitted after logout. Draft bodies are locally persisted before explicit confirmation to support return/recovery; cancel and logout clear them. Server upload requires explicit confirmation.

## Limits

This verifies source behavior and synthetic SQLite execution for authenticated cloud-account scopes (`https://…|user_<id>|tenant|identity`). It does not claim a real iOS/Android account-deletion run or real WeChat export compatibility. Native build and simulator evidence are recorded separately. Unscoped legacy data is intentionally not attributed to an account; the existing cleanup report exposes that limitation.
