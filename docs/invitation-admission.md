# Invitation-only admission

An invitation admits an authenticated OIDC subject to one new personal space. It is not a password, a user session or a reusable shared account. Existing active members keep the ordinary login path and do not consume another invitation.

## Operator preparation

The operator must first provision and verify a **new isolated tenant instance**, using the existing capacity and ownership workflow. Invitations do not create VMs or prove service readiness. Never assign a new person to the existing acceptance A/B spaces.

1. `wearing gateway invite reserve --root <gateway-root> --tenant-id <new-tenant>` creates only an empty control record. Existing or inactive membership and ownership records reject reservation.
2. `wearing gateway route --root <gateway-root> --tenant-root <new-private-instance> --url <verified-internal-url>` uses the existing immutable route and private credential flow.
3. `wearing gateway invite issue --root <gateway-root> --tenant-id <new-tenant> --output <private-directory/invite.json> --expires-in 604800` saves the code in a new mode-0600 file inside an owner-only directory before committing its hash to the database. Standard output contains only an issuance receipt. The same command and output path reconcile the same issuance after a failed/unknown database response; they never generate a replacement code. The expiry range is 60 seconds to 30 days.
4. `wearing gateway invite status --root <gateway-root> --invitation-id <receipt-id>` checks issuance. `... revoke ...` permanently disables further use. Revoking a consumed invitation does not silently remove its user's existing membership; use the separate explicit member revocation flow.

A tenant has at most one retained invitation. Expired/revoked registrations are not automatically reset or reassigned. A membership/route change after checking a code invalidates admission; no fallback assigns an existing space.

## Application contract

`InvitationStore(control_store)` exposes:

- `check(code, issuer=...)` returns `{eligible: false}` on any invalid code or `{eligible: true, code_hash: ...}` on success. `check_code(...)` is the equivalent exception-based API returning only the hash. Checking does not reserve or consume the invitation.
- `redeem_hash(hash, issuer=..., subject=...)` runs **after verified OIDC authentication**, returning `{status: admitted|already_member, user_id, tenant_id}`. The gateway then uses the existing `ControlStore.login` to issue its session. All claim failures are `InvitationError(code='invitation_unavailable')`; do not expose whether a code was used by another person.

The gateway retains only the hash in its private, expiring, one-use OIDC continuation. It must not put the plaintext code or hash in URLs, signed browser cookies, telemetry or HTML after submission. Request-size limits, same-origin form/CSRF protection, rate limits and OIDC state/nonce/PKCE remain gateway responsibilities. Knowing a code cannot bypass identity authentication.

Redemption atomically writes the new user (when necessary), active membership, verified single-owner record and redemption receipt. Repeated callbacks from the same admitted subject return the existing membership. Another subject cannot reuse the code. A later membership revoke or account-deletion fence is never undone by retrying the consumed code.

## Restricted self-registration broker

The identity provider's global self-registration stays disabled. A separate broker may create a new identity only after invitation validation; it must not hold general realm administration authority in the gateway process.

Construct its database store with `ControlStore(registration_database_url, registration=True)`. This login has only the `wearing_registration` NOLOGIN privilege group. It must not inherit `wearing_web`, `wearing_operator` or the migration owner. `InvitationStore` provides these broker-only operations:

- `reserve_registration(hash, issuer=..., registration_id=<uuid hex>, username_hash=<SHA256 of broker-canonical username>)` atomically fixes the intent and username hash. A retry for the same username returns the **original** registration ID, even if the caller proposes a different ID. A different username fails closed while an intent is reserved.
- `get_registration(hash, issuer=...)` returns the current fixed `{registration_id, username_hash, subject, expires_at}`.
- `bind_registration_subject(hash, issuer=..., registration_id=..., subject=...)` records the actual IdP subject only after the broker verifies successful creation or looks it up by the exact original intent. The subject is immutable. An invitation with a registration intent cannot be redeemed until this subject is bound, and then only by that authenticated subject.
- `release_registration(hash, issuer=..., registration_id=...)` is permitted only for the exact **unbound** intent. The broker may call it after a definitive IdP conflict that proves no identity was created, retaining that failed intent in its private journal. A timeout, disconnect, 5xx or unknown outcome must never release it. A late bind from a released intent cannot attach to a later intent.

Before any IdP create call, the broker durably records the fixed intent. After an uncertain response it queries that exact username and registration marker, without replaying a create under a different ID. Passwords never enter this control database. Invitation expiry/revocation can leave an unused IdP account, but cannot admit it; cleanup requires a separate verified operator action.

## PostgreSQL migration and boundary

Apply `deploy/control/postgres-roles.sql` with the existing DBA procedure to add the non-login `wearing_registration` and `wearing_cleanup` groups, then run the independent migration owner through `wearing gateway database upgrade`. Revision `wearing_control_0003` adds the invitation table, six fixed invitation `SECURITY DEFINER` functions and one fixed expired-state cleanup function, with a fixed `pg_catalog,wearing_control` search path. The migration is transactional and repeatable, and preserves existing users, memberships and sessions. It has no destructive automatic downgrade.

The web role still cannot directly insert or update membership, route, ownership or invitation rows. The registration role has no platform-table read/write access and cannot create login sessions or redeem an invitation. PostgreSQL startup checks function bodies, owner, grants, search path and owner-only RLS policies. `PUBLIC` has no execution grant. The migration owner remains separate from all runtime roles. Shared transaction locking orders invitation redemption with operator membership changes and deletion admission.

SQLite is a development-only equivalent with `BEGIN IMMEDIATE` and explicit application-role checks; it does not claim PostgreSQL's database privilege isolation.

## Broker process and state maintenance

`deploy/control/pajio-registration.service` runs as a separate non-login OS user. Its config, journal and provider-key copy are owner-private. Only the permissioned Unix socket is shared with the gateway group. The listener creates an exact mode-0660 socket inside an owner-controlled mode-0750 directory, holds a process lock for its entire serving lifetime, and refuses to replace an active socket. It has no public TCP listener.

Passwords are validated as 12–128 Unicode code points; C0/C1 controls, DEL and lone surrogate code points are rejected. Oversized request bodies retain their 413 response. The journal is fsynced before creation and stores only a keyed request fingerprint and immutable intent/subject metadata. After an unknown outcome, retries inspect the original IdP intent. A reservation whose local receipt is absent also inspects only: missing local evidence cannot justify another create request.

`pajio-expired-states.timer` invokes a separate maintenance OS/database identity every ten minutes. That login belongs only to `wearing_cleanup` and has no platform-table or invitation-function access. It can execute only `delete_expired_states()`, which accepts no arguments, uses the database timestamp and removes at most 5,000 expired OIDC-state rows per call. The expiry index bounds scanning; locked rows are skipped. Unexpired form/OIDC state, sessions, invitations and all identity accounts remain outside this cleanup operation. The web role's existing scoped DELETE/INSERT grants are unchanged.

Before migration, a source rollback may return to 0002. After migration, an old `ControlStore`/PostgreSQL boundary cannot run against 0003. Recovery must retain the 0003-compatible metadata layer or use a separately reviewed database snapshot restore with ingress closed and all subsequent admissions accounted for; no automated downgrade discards receipts.

## Verification boundary

Local tests use a newly initialized disposable PostgreSQL 18.6 cluster with separate web, operator, registration, cleanup and migration logins, plus SQLite development fixtures. They cover real SQL privileges/RLS, fresh migration and upgrade from the previous schema, concurrent redemption, retry, revocation, immutable registration intent, release/late-bind races, private ownership, transaction rollback, real unprivileged JoinFlow rendering/one-use state and concurrent rate limiting, bounded cleanup, and native Unix socket behavior. This does not by itself establish live IdP registration, a new customer's VM provisioning, production migration or client acceptance; those require the gateway and broker integration evidence.
