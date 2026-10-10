# Invitation bundle activation — control revision 0004

This change creates controller metadata and an outbox. It never allocates a VM,
grants provider access, releases reserved capacity, or fabricates an AccountProof.
Host reservation verification and a healthy Core are prerequisites enforced by
the separately reviewed operator adapter.

## Immutable binding and redemption

`control.bundles` (`wearing_bundles`) contains `id`, `tenant_id`, `instance_id`,
`host`, `reservation_sha256`, `worker_plan_sha256`, `members_json`,
`reservation_expires_at`, and `created_at`. IDs are 32 lowercase hex. SHA values
are 64 lowercase hex. Members are an object with exactly `core`, `linux`, and
`android`; each has `vmid`, `request_id`, `vcpus`, `memory_mib`, `disk_mib`,
`image_sha256`, and `core_reservation_sha256` (non-null only for Core).

The operator calls `InvitationStore.bind_bundle(...)` with freshly verified host
facts and the private worker plan path. The plan is read with no-follow,
owner/mode/regular-file/single-link checks; only its SHA is saved. Rebinding any
field of an existing bundle is refused. New PostgreSQL invitations require a
unique bundle binding and reservation expiry at least 900 seconds after invite
expiry. `issue` and `issue_to_file` take `bundle_id` and `worker_plan_path` and
verify the file against the frozen plan SHA. The CLI accepts `--bundle-id` and
`--worker-plan`; these flags do not substitute for live host verification.
Existing null-bundle invitations can remain readable for legacy compatibility;
new PostgreSQL INSERTs without a bundle are rejected by a trigger.

A successful authenticated redemption creates membership, private ownership,
consumes the invitation and inserts exactly one `wearing_bundle_activations`
event in the same transaction. Invitation and bundle IDs are individually
unique. An insertion failure rolls back all four effects. A same-subject retry
returns the same activation ID; an already-admitted user does not consume a
second invitation. SQLite follows this transaction contract; its old unbundled
fixtures remain supported.

## SQL API and authority

All functions return JSONB or SQL NULL. NULL means the operation did not obtain
valid authority; it is not proof that a provider action failed or can be retried.

| Function | Arguments |
| --- | --- |
| `bundle_activation_status` | tenant TEXT |
| `activation_claim` | worker TEXT, lease seconds INT |
| `activation_heartbeat` | event TEXT, worker TEXT, generation INT, lease seconds INT |
| `activation_update` | event TEXT, worker TEXT, generation INT, state TEXT, step TEXT, receipt SHA TEXT, reason TEXT, members JSONB |
| `activation_release` | event TEXT, worker TEXT, generation INT |

`ControlStore(..., activation=True)` is exclusive of operator and registration.
Its LOGIN may inherit only `wearing_activation`, a restricted NOLOGIN role. It
has no direct platform table or column access, route/membership/session writes,
or user creation ability. It can execute only the four lease functions. The web
role can execute owner status and existing admission functions. Registration
retains only its original fixed functions. Startup verifies exact function
bodies, grants, owner, search_path, FORCE RLS and immutable-scope triggers.

Owner status takes trusted gateway `wearing.user_id` and `wearing.tenant_id`
transaction scope after current-session validation. It rechecks active private
ownership, exact sole member, revision, membership digest, route and deletion
fences. It returns only `state`, `members`, `updated_at`, `reason`, `retry_after`;
no host, VMID, reservation/receipt hash, credential, or identity subject.

Worker claim returns the complete immutable event plus `bundle`. Claims advance
generation. Heartbeat/update/release require the current worker, generation and
unexpired lease, and recheck current ownership. Lease expiry permits a later
worker to **observe the same operation**; it does not authorize replaying an
unknown provider mutation. Release clears only the worker lease. Pending,
expired and unknown reservations continue to count in the provider ledger.

States: `reserved`, `preparing`, `installing`, `pairing`, `ready`, `needs_review`.
Progress is exactly `{core:{state},linux:{state},android:{state}}`; member states
are `pending`, `preparing`, `ready`, `needs_review`. Ready requires all three
ready plus a nonempty 64-hex receipt SHA. Overall state cannot regress; terminal
states cannot be claimed or rewritten by the worker. Public reason is null or
`provisioning_requires_review`. Private books retain detailed failure evidence.
Lease bounds: 30–300 seconds (worker default 120; heartbeat 20).

## Local verification before deployment

75 tests passed using an isolated, explicitly `qa_only` real PostgreSQL database
plus SQLite, existing invitation/registration/native-enrollment regressions and
worker tests. Tests include atomic rollback on outbox failure, concurrent redeem,
exactly one event, safe status scope, role isolation, lease takeover fencing,
owner change rejection, readiness prerequisites and immutable scope. These are
synthetic identities in a disposable local database, not a real-user provider
or device acceptance claim.

## Production migration boundary

1. Independently back up the control database and record source/config/role
   preimages. Keep dumps and credentials private. Stage exact reviewed bytes.
2. Create the restricted activation group and distinct LOGIN/OS service account;
   keep its password solely in the root-owned mode-0600 environment file. Keep
   activation disabled until private fixed plans and provider access are reviewed.
3. Bound the gateway/broker write window. Use the existing distinct non-admin
   migration owner for transactional `0003 → 0004`; no runtime role can migrate.
4. Check all runtime boundaries using their real credentials, then restore
   gateway/broker and record public probe failures as well as recovery.

A failed migration transaction leaves 0003 and allows old source restoration.
A committed 0004 cannot be rolled back by restoring only old `postgres.py`, whose
startup requires 0003. Once writes resume, an old database snapshot must not be
restored over new sessions or redemptions. Keep the compatible 0004 controller
and disable activation while repairing. Whole-database rollback requires an
independently reviewed no-new-writes window. No automatic destructive downgrade
or unknown-phase replay is provided.

## Production deployment — 2026-10-10

The reviewed `wearing_control_0004` migration and compatible controller modules
were deployed on 2026-10-10 (Asia/Shanghai). Real web, registration, operator and
activation PostgreSQL role checks passed, including the separate non-root
activation service account. The activation unit remains disabled and inactive;
this deployment did not issue an invitation or provision a user's devices.

The bounded gateway/broker restart produced two observed HTTP 502 responses in
one sampling round; the subsequent 162.81 seconds of public probes were stable.
See the [deployment evidence](../evidence/pajio-bundle-activation-schema-20261010.md)
for the frozen release digest, role checks and exact verification boundaries.
The local test results above remain local evidence and do not claim completed
real-user registration or device readiness.
