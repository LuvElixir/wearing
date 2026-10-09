# Account deletion operator contract — 2026-10-08

## Implemented software and actual validation boundary

The production adapter is executable software, not a success stub. It imports an accepted account deletion request from the control plane, pins an explicit asset manifest, freezes the tenant, revokes supported grants and device access, drains execution, and calls fixed Tencent APIs. Each phase must have a separate observation before it advances. No real tenant, cloud API, credential, stop or deletion was executed during development. Tests use new temporary control databases and tenant roots, an injected fake Tencent CLI, and synthetic identifiers.

Files:
- `src/wearing/account_deletion_operator.py`: private registry, immutable control-request/journal binding, tenant HTTP client, production phase adapter.
- `src/wearing/cloud/deletion_tencent.py`: separate bounded Tencent transport and state reconciliation. The discovery `TencentCLI.READ_ACTIONS` is unchanged.
- `src/wearing/cloud/account_deletion_tenant.py`: fixed `/internal/account-deletion` operator endpoint, durable tombstone, phase receipt readback.
- `account_deletion_cli.py`: explicit enrollment/import/resume commands.
- Worker, relay and instance startup reject ordinary work after a tombstone. A worker may restart only to expose its operator endpoint, without starting business background workers.

## Operator enrollment

The private `DeletionJobs` journal must use `mode=operator`. `assets-register --file` accepts a private operator-owned JSON file with exactly these fields:

```json
{
  "tenant_id": "tenant_fixture", "instance_id": "instance_fixture",
  "owner_user_id": "user_fixture", "account_id": "123456", "region": "ap-hongkong",
  "cvm_id": "ins-aaaaaaaa", "system_disk_id": "disk-aaaaaaaa",
  "disk_ids": ["disk-aaaaaaaa", "disk-bbbbbbbb"], "snapshot_ids": ["snap-aaaaaaaa"],
  "exclusive": true, "complete": true, "indexes_on_disks": true,
  "backups_only_snapshots": true, "other_resources": [],
  "worker_upstream": "https://tenant.invalid", "operator_credential_ref": "tenant_fixture.key"
}
```

This is a **synthetic schema example, never an existing resource inventory**. An operator must establish every field from deployment inventory and data topology. `complete`, `exclusive`, and storage coverage are explicit audit attestations; they are never inferred from tags, an active member count, a directory name or the existing trial VM. Missing or false declarations, external storage, unsupported backup types and shared assets block execution. Registry rows cannot be reassigned or overwritten. CVM, disks and snapshots cannot appear in two tenant registrations within one account/region.

The separately enrolled 64-character operator key lives at the worker's fixed `deletion-operator.key` and at `<operator-key-root>/<operator_credential_ref>`. It is not the business gateway key; no default key is generated or inherited. The endpoint accepts no filesystem path, SQL, shell command, endpoint URL or resource ID list.

## Control bridge and commands

```sh
python -m wearing.account_deletion_cli --journal <private-journal> assets-register --file <private-manifest>
python -m wearing.account_deletion_cli --journal <private-journal> operator-prepare --gateway-root <gateway-root> --request <accepted-control-request-id>
python -m wearing.account_deletion_cli --journal <private-journal> operator-resume --gateway-root <gateway-root> --job <journal-job-id> --profile <tccli-profile> --operator-keys <private-key-directory> --execute
```

These are operational commands, **not commands run in this development session**. `operator-prepare` changes only accepted request/control metadata and the private journal; it does not call Tencent. `operator-resume` without `--execute` refuses before loading gateway/provider credentials. PostgreSQL uses the existing separate operator database role; no browser role gains registry or membership administration.

Import freezes the accepted user, sessions and private tenants under the control mutation lock. All members, including inactive memberships, are checked. Journal entries naming the same user but outside the accepted request are rejected. The binding pins the accepted control revision, journal revision, tenant instance identity, route and complete assets. Every external phase rechecks frozen control ownership. Private tenants with more than that one member never qualify. Shared tenant requests currently remain `waiting / incomplete_registry` until per-user external credential ownership is implemented; no shared tenant is stopped or erased.

## Tenant phases and receipts

POST body is exactly:
`{job_id, plan_revision, operation_id, tenant_id, instance_id, phase, owner_scope}`.

- `job_id`: 32 lowercase hexadecimal control request ID.
- `plan_revision`, `operation_id`, `owner_scope`: 64 lowercase hexadecimal strings.
- `tenant_id` and `instance_id`: must match this worker's immutable instance and volume owner.
- `phase`: `freeze_tenant`, `revoke_credentials`, `revoke_devices`, `drain_actions`, in this order.
- Dedicated bearer key required; missing/duplicate/ordinary business credentials fail.

The first freeze atomically writes and fsyncs a fixed tombstone binding the request. It cancels and awaits tracked ingress/background work, disables message reception, closes capture processing, and revokes native/relay/push access. The tombstone persists across restart. Already admitted OS writes become `unknown`; they are not claimed reversed. Requests present at freeze leave a durable review flag. Global device revocation obtains tenant freeze receipts before its own success.

Cloud application grants use the existing provider revoke adapter and keep revocation-pending credentials on network failure. Telegram/Feishu bot channels currently lack a safe upstream credential-revoke adapter; they are disabled but retained and the phase returns `adapter_unconfigured`. Local disconnect alone is never accepted as upstream revocation.

Drain first withdraws never-admitted queued messages in the task transaction. An admitted start without a run ID remains ambiguous because its response may have been lost. Existing running tasks receive a stop request followed by explicit status readback, with no engine restart allowed. Drain refuses while any task is active/ambiguous, an owned engine runs, capture work is active, an ingress request remains, or an admitted device operation is unresolved. It does not clear unknown outcomes, delete an external OS event, or invent success to unblock deletion.

POST returns `{request, state:done, evidence:<sha256>}` or `{request,state:waiting,code}`. The client performs a separate GET with exact job/revision/phase/operation fields and requires an identical receipt and exact request. A receipt for another job or operation cannot advance this job.

## Tencent provider and proof

The restricted transport calls only `GetCallerIdentity`, `DescribeInstances`, `DescribeDisks`, `DescribeSnapshots`, `StopInstances`, `TerminateInstances`, `TerminateDisks`, `DeleteSnapshots`. It invokes `tccli` with a command list, fixed China-site endpoints/version, private temporary JSON, bounded timeout, no shell and no secret output.

Before mutation it checks the STS account and configured region; exact CVM and disk IDs; the CVM's entire system/data disk list; every disk's attachment, payment mode, shared attachment list, automatic backup/snapshot policy and backup-point count; and all snapshots for each disk using bounded pagination. Missing/invalid fields, unknown additional snapshots, association with another instance, cross-region copies, locked/shared snapshots or image dependencies block execution. The supported layout is an exclusive on-demand CVM, CBS disks, and ordinary private same-region snapshots. Prepaid resources, remote/index/object/backup services and automatic snapshot policies require separate adapters and remain blocked.

Each mutating attempt is durably recorded **before send**. Repeating an operation queries state; it never blindly resends an ambiguous mutation. A lost send with no observable effect remains waiting for operator reconciliation. A lost response after a successful action can advance only from a matching readback. `RequestId` alone is not a completion condition.

Soft stop requires subsequent `STOPPED` plus successful latest operation. Termination never expands scope to elastic IPs or prepaid disks. CBS termination uses `DeleteSnapshot=0`; every registered snapshot is handled explicitly with `DeleteBindImages=false`. CVM/disks/snapshots must subsequently be absent from authenticated, complete exact-scope queries. `SHUTDOWN`, `TORECYCLE`, pending transitions and retained snapshots are not treated as absence. Only registered disks can prove primary/index deletion, and only a verified empty registered backup inventory can prove backup deletion.

Official sources used for parameter and lifecycle validation:
- [StopInstances](https://cloud.tencent.com/document/api/213/15743): asynchronous soft shutdown and state transition.
- [TerminateInstances](https://cloud.tencent.com/document/api/213/15723): billing-mode behavior and scope-expansion switches.
- [TerminateDisks](https://cloud.tencent.com/document/api/362/16321): explicit disk IDs and snapshot deletion switch.
- [DeleteSnapshots](https://cloud.tencent.com/document/api/362/15645): normal-state requirement and image deletion switch.
- [DescribeDisks](https://cloud.tencent.com/document/api/362/16315), [DescribeSnapshots](https://cloud.tencent.com/document/api/362/15647), [CBS data structures](https://cloud.tencent.com/document/api/362/15669): pagination, attachment, automatic backup/policy, shared and copy metadata.

Operator exclusivity and prevention of simultaneous out-of-band cloud administration remain deployment responsibilities; cloud read/mutate APIs are not a transactional lock across console administrators. The software rechecks before phases and does not conceal that limitation.

## Public status

The existing scoped receipt bearer continues to return only its own request:
`{id,user_id,request_key,plan_revision,state,code,created_at,updated_at,tenants,data_erased}`.

- `awaiting_operator / adapter_unconfigured`: accepted and access fenced; not yet imported.
- `frozen`: control freeze complete, external erasure not proven.
- `waiting`: a real outstanding step, with an existing safe journal code.
- `completed / verified / data_erased:true`: all tenant/device/credential/drain and primary/index/backup phases have succeeded with stored evidence; only then does the operator update control status.

`data_erased` describes registered private tenant content and storage, not deletion of the minimum control identity tombstone, immutable deletion receipt, or operator evidence required to prevent account re-entry and prove the operation. No browser or gateway endpoint can assert completion. Unknown resources or unavailable upstream revoke never produce `completed`.

## Remaining deployment inputs

No current tenant has been adopted automatically. Actual execution still needs: explicit private owner enrollment; a complete CVM/system/data disk/snapshot and external storage inventory; fixed worker route binding; dedicated operator keys; a scoped Tencent credential; review of in-flight unknown operations; and real provider revocation for any existing bot channels. These missing inputs are operational blockers, not simulated successful deletion.

## Validation results

Initial C suite: 28 injected-provider/operator tests + 6 actual tenant ASGI tests passed; combined existing journal/control/worker/gateway/relay suite was 120 passed. Follow-up review added 3 drain regressions (queued withdrawal, admitted start response loss, explicit stop readback), with C suite 37 passed. No cloud call or real account mutation occurred.

Final frozen C regression: `uv run pytest -q tests/test_account_deletion_operator.py tests/test_account_deletion_tenant.py tests/test_account_deletion.py tests/test_account_deletion_control.py tests/test_tenant_worker.py tests/test_deletion_gateway.py tests/test_device_relay.py` → **123 passed, 0 skipped, 2 upstream deprecation warnings, 14.52s**. The C-specific split is **28 operator/provider + 9 tenant ASGI tests**. `git diff --check` passed for the touched integration files. Source freeze handed to root after this result.
