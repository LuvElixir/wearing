# Background commitment account provenance

Implemented 2026-10-08. This closes the missing account chain from an explicitly created goal or schedule to its later native-phone task. It does not grant unattended iOS execution or additional OS permissions.

## Trusted entry and storage

- App goal creation/control/linked conversation and schedule creation/change use the trusted ASGI `pajio.storage_scope` in cloud mode. Request JSON and raw client headers cannot choose the principal. Cloud preview without a scope remains unowned. The schedule installer receives `local_devices` explicitly, so a missing tenant middleware cannot turn a cloud request into a local principal.
- A normal local API request can use the existing local authority. Agent tools inherit only the persisted principal of the sole admitted active task in the tenant and current identity. No current phone installation, logged-in phone, or single available device is used to infer the creator.
- `background_principals(kind, source_id, owner_scope, source_task_id)` is inserted in the same `BEGIN IMMEDIATE` transaction as a new commitment. No backfill or owner reassignment exists. MCP schedules recheck the captured source task in the committing transaction. Goal MCP creation/change already select and check the sole source task inside that transaction.
- Goal steps and schedule occurrences insert `task_principals` in the same transaction as the child task. A failed principal write rolls back the commitment or reserved step. Restarts and subsequent occurrences read the original persisted principal.

## Mutation and replay

An owned goal/schedule can be changed, resumed, cancelled, or replayed only by the same account principal. Goal-linked user messages follow the same check and receive the current trusted user's task principal. Tool arguments cannot supply an owner. Cross-account mutations return the existing 409 domain error and do not change revisions.

A life-change watcher linked to a goal must have exactly the same original account provenance; this is checked both when configured and when a child task is reserved. A mismatch is paused without dispatch. Background tasks retain the previous restrictions against expanding their own goals or schedules.

Existing shared-identity content visibility is unchanged. Provenance is execution authority, not a claim that identity-scoped goals, record contents, or historical reports have become private between members of that identity. The principal is not included in public goal/schedule JSON.

## Legacy behavior and phone authorization

Old commitments without a principal remain readable and may be managed under the previous shared-identity behavior, but resuming, editing, or reconnecting a phone never assigns them an owner. Their child tasks remain unowned. Both local and cloud native-phone dispatch reject these unowned background tasks, including device enumeration. The returned message directs the user to explicitly create a new commitment; clients must not retry or reconnect in a loop to acquire authority.

Ordinary historical local conversations retain the existing local compatibility behavior. New local commitments explicitly created from trusted local entry points can carry `local`. Cloud execution continues to require a verified 64-hex account scope.

Owner inheritance is not a phone grant snapshot. Each request/claim still validates the current device owner, live foreground connection, policy revision, current OS capability report, task status, and run ID. Revoking the phone policy cancels queued work; inherited owner provenance cannot bypass it. Writes still require the existing per-command confirmation and result readback.

## Verification and limits

Synthetic tests exercise real `GoalBook`/`ScheduleBook`, SQLite transactions/reopen, the MCP dispatch entry, `TaskService` with an injected HTTP engine transport, and native command queue claim/finish. They cover two owners in one identity, forged body/header values, missing cloud boundary, immutable replay ownership, stale source rejection, linked watcher ownership, later runs, legacy local/cloud refusal, rollback, and phone grant revocation.

Final regression: 15 dedicated provenance tests plus existing goal, schedule, native action, list, and life suites: **236 passed**. Python compilation and the scoped whitespace check passed. Existing HTTP dependency deprecation warnings remain.

The current MCP infrastructure still binds tool calls through the tenant's single-active-task ledger and runtime identity. This change revalidates that ledger transactionally; it does not introduce a per-tool signed runtime task token or claim validation against an independently supplied engine invocation identity. Parallel active tasks fail closed. No real account, phone OS, or cloud resource was used for these tests.

## File boundary

`background_principals.py`, `goals.py`, `schedules.py`, `schedule_api.py`, `native_actions.py` (legacy background guard), `life_proxy.py`, and only the schedule installer plus goal creation/control/message call sites in `app.py`. Dedicated tests are in `test_background_principals.py`; an existing schedule MCP test now admits a genuine synthetic local user task before mutation.

The `life_proxy.py` task-list import/tool/dispatch hook was also connected on behalf of the separate task-list implementation. Its storage, list semantics, App UI, and engine discovery assertion remain owned by that implementation.
