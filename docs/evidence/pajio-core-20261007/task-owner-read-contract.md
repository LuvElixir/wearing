# Task owner read and engine history contract

The trusted `pajio.storage_scope` supplied by TenantBoundary defines the account. Public headers, query parameters and model arguments cannot set it. Cloud task-derived reads without that verified scope fail with 401; local routes use the explicit local owner. Task principals cannot change after admission. A task with no principal remains the existing legacy identity-shared record; it never inherits the current phone account.

`task_visibility.predicate` is used before search pagination, artifact retrieval and export accounting. Conversation, task list/detail, search result/snippet, artifact metadata/HTML/download/choices, durable confirmation reads and export snapshots project the same task owner rule. Goal/schedule read models, their derived reports and model context additionally check their persistent background principal and source task. The MCP dispatcher derives its read owner from the sole admitted runtime task, never caller-supplied tool fields. With no admitted task it sees only legacy unowned results. Internal coordinator methods retain explicit unrestricted reads for operation, separate from public projections.

Identity-level life records, calendars, task lists, preferences, memory and workspace retain their existing sharing definition. This change does not turn a shared workspace into a private file vault: a file deliberately present in that space remains accessible there, independently of the protected immutable artifact copy.

## Engine sessions

`owner_conversations(identity_id,owner_scope,session_id)` stores a fresh random conversation session per identity/account. New owners never copy the pre-upgrade identity session. `task_conversation_sessions(task_id,identity_id,owner_scope,session_id)` records the session actually admitted within the same transaction as `reserve_start`. The outgoing payload is rebound there, including old queued owned messages. Only a matching admission ledger can update that owner's canonical remote session and its pending drafts. Pre-upgrade active-run responses without this ledger cannot inject old shared history. Unowned conversation history stays on `identity_conversations`, and its returned session cannot update owned drafts. Standalone goal/schedule sessions are not redirected.

Both new tables are internal runtime state: never exported, never client-writable. Whole-tenant deletion erases them with the verified data store; an identity-specific future delete must remove entries with that identity, and task session rows with its tasks. Session IDs/credentials are not ported into product data archives.

Ordinary new tasks and record-linked conversations bind the trusted caller in their creation transaction. Confirmation recovery binds the original task principal, not a caller's current phone account. Legacy unowned recovery stays unowned.

## Exports and upgrade

Exports project task rows, messages, events, goal reports, schedule occurrences, confirmations and immutable artifact bodies before row/byte limits. List/series data retain the shared identity semantics. Export metadata requires `task_visibility_version=1`. Old archives without this marker cannot be listed, replayed or downloaded; they remain subject to ordinary TTL cleanup. Reusing their request key creates a new projected archive if capacity permits. Request receipts are still private to identity and owner.

## Verification

Synthetic tests use temporary SQLite stores, full ASGI/TenantBoundary, injected Hermes responses and ZIP inspection. They cover two accounts in one identity, another identity, legacy content, missing/faked scope, search cursor replay, artifact HTML/download/choice reads, export membership and old archive rejection; A/B successive engine turns, queued drafts, service restart and pre-upgrade late responses; goal/schedule MCP/context and seen isolation; confirmation recovery inheritance and foreign replay. They do not prove real provider, device or production deployment behavior.

## Exact task-detail read receipts

`ActivityBook.detail_snapshot(identity_id, task_id, owner_scope)` opens one SQLite read transaction for the projected task, events, queue delivery state, artifact metadata and activity version. Absent/foreign returns `None`. GET task exposes the same product fields as before plus `activity_receipt: {task_id,version} | null`; only a result has a receipt. Payload and idempotency key remain stripped by the route. The client acknowledges that exact receipt after rendering through the existing POST `/api/activity/seen`.

The seen endpoint intentionally returns 200 for a stale but visible version while leaving a newer result unread; a foreign task is 409. The client must not fetch a new version and silently acknowledge it. A WAL test writes a new result between the task SELECT and activity projection: the response remains the old coherent snapshot and its receipt cannot clear the newer unread result.
