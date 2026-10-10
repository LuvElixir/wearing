# Native account and environment readiness

The native invitation flow verifies/registers through the control gateway. A completed registration is not a logged-in App session: the existing one-use handoff must still return a valid mobile session receipt. The new readiness page is a separate step after that session is stored.

## Read-only recovery

- A retained registration with an unknown result or `pending` state is queried only through the original operation's `status` request. Polling never resubmits the invitation, username/password, registration request, or handoff exchange.
- Registration checks run only in the foreground, respect the server retry delay, and stop after 12 reads or three consecutive transport failures. An explicit refresh resets the read budget. Completion found by polling presents the existing explicit entry action.
- Backgrounding aborts the outstanding read and discards its late UI result. The private recovery proof remains available; no password or invitation is persisted.

## Environment gate

Every authenticated public-cloud activation first requests `GET /auth/provisioning` at the fixed official origin. It sends the existing bearer and expected-tenant header, omits cookies, refuses redirects, and does not bootstrap Core. Explicit local/development connections retain their existing behavior.

The control contract is `{state,members:{core,linux,android},updated_at,reason,retry_after}`. Overall states are `reserved`, `preparing`, `installing`, `pairing`, `ready`, and `needs_review`; member states are `pending`, `preparing`, `ready`, and `needs_review`. `updated_at` is integer Unix seconds and `retry_after` is 3–30 seconds. Error details are not rendered.

Only an authoritative overall `ready` receipt with all three members present and ready releases the in-memory activation gate. Individual ready members do not imply overall readiness. Missing/legacy records (404), malformed responses, partial member lists, network failures, and pending states remain gated. No readiness flag is persisted. Switching credentials, accounts, or activating another connection resets the gate.

Before this gate opens, the production `Mobile.synchronize` handler cannot bootstrap Core or flush existing queues. Native synchronization/action sessions, device viewers, onboarding, and the conversation WebView are mounted after the preparation-page branch. Existing account-deletion recovery remains higher priority.

The preparation page makes at most 20 foreground reads per budget, stops at `needs_review`, and backs off network failures (6 then 12 seconds; stop after the third failure). Refresh only performs another GET. It has no provisioning retry/create mutation. Opening account options pauses polling before login/logout; a 401 prompts reauthentication. Backgrounding, leaving the panel, and account deletion abort and fence late results.

## Logout while Core is unavailable

The random installation ID is not a notification-registration flag. A new session-bound local receipt is saved only after a validated notification registration acknowledgement; it contains the installation and credential identifiers, never a push token. The key uses the existing account-scoped cleanup namespace and aggregates identities within that one credential.

Logout checks this receipt. With none, it makes no notification/Core request. A matching registered installation receives a cancellable two-second best-effort disable attempt. Failure/timeout cannot block the separate control-plane session revocation. Only successful revocation or the existing unauthorized-session response permits clearing local credentials; an unknown logout response retains them. If notification disable was unconfirmed, the signed-out screen says so and points to system notification settings. It does not claim successful notification cancellation.

## Validation and remaining acceptance

The implementation is covered by executable fetch, polling, enrollment, notification and production shell-handler tests. These verify unknown registration recovery without replay, late/background response rejection, cross-activation readiness isolation, zero bootstrap/queue flush before ready, receipt-bound logout, offline Core, abort-ignoring transports, and control-revocation failure.

At the initial source-only checkpoint, this change had not been built or installed. The subsequent 0.2.0 build 2 passed strict code-signature verification, was installed and launched on the owner's physical iPhone, and displayed the updated invitation welcome screen; see [native invitation acceptance](../../../docs/evidence/pajio-native-invitation-acceptance-20261010.md). This proves build, installation and entry-screen rendering only. Real invitation redemption, account creation, the preparing-to-ready transition, and access to the independent Core, Linux computer and Android phone remain unverified. No account or grant was fabricated to complete this check, and it does not establish external-test availability.
