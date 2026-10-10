# Personal invitation test: AI consent release, 2026-10-10

The personal Core now enforces explicit DeepSeek consent before new model requests. This release retained the default-denied state: it did not grant consent, create an account, or run a real user registration or native consent flow. The [API contract](../contracts/pajio-ai-consent.md) describes the decision and withdrawal protocol.

## Deployed scope

The reviewed overlay changed exactly 11 Core modules: `ai_consent.py`, `ai_consent_api.py`, `usage_guard.py`, `runtime.py`, `engine_runner.py`, `app.py`, `service.py`, `capture.py`, `capture_api.py`, `capture_worker.py`, and `capture_bridge.py`.

Only `wearing-tenant.service` restarted, once. Its PID changed from **4778 to 7288**, and the managed Hermes engine reported the capability **`wearing.ai_consent_guard = deepseek-v1`**. Relay PID 5295 and nginx PID 4603 stayed unchanged; post-release checks matched 286 protected source/static files and 16 configuration references to their preimages. Control services, activation plans, device runtime artifacts, SSH command pins, and account/invitation data were outside this overlay.

The installed base wheel and this overlay together identify the running Core. The old wheel hash alone does not prove the current source version.

## Enforcement evidence

Local validation passed 240 targeted Core tests and 6 release/probe tests. Independent review reran the 8 consent tests, including the installed SDK path.

The post-release probe matched the actual managed Python interpreter to the running Core's `engine_runner` child process. With synthetic input and a raising `MockTransport`, its real OpenAI SDK raised `ConsentError` before dispatch: **zero network dispatches, zero provider requests**, and no owner binding, grant, task, or usage reservation. Independent Core readiness reported a reachable engine, zero model calls, HTTP 403 when the trusted private-owner scope was absent, and HTTP 401 for anonymous access.

The initial read-only probe used an incorrect assumed Hermes environment path and failed. That failure was preserved. The corrected probe verified the real process interpreter and passed; no second service restart or model retry was performed.

## Availability observations

| Observation | Result |
| --- | --- |
| Private Core readiness, 37 samples across activation | 35 HTTP 200; 2 connection errors during the single restart |
| Final consecutive private readiness | 28 reachable samples over **81.09 seconds** |
| Public `/privacy`, 114.19-second observation window | 23 HTTP 200 |
| Public `/auth/provisioning`, same window | 23 HTTP 401, expected for unauthenticated requests |

The separately deployed [privacy](https://pajio.luckyloading.com/privacy) and [support](https://pajio.luckyloading.com/support) pages were also verified publicly accessible with HTTP 200. Their deployment and probe limitations are recorded in [public-pages-release.md](pajio-auth-design-20261010/public-pages-release.md). Public page availability and expected anonymous rejection do not prove authenticated provisioning or native App acceptance.

## Evidence boundary

Real user acceptance, withdrawal from App settings, subsequent permitted model processing, and the invitation-to-native-App flow remain separate acceptance steps. No real consent was supplied by an operator or synthesized for this deployment. Already dispatched content cannot be recalled; the guard blocks future requests after withdrawal.

The private evidence set retains the original preimages, exact installed hashes, activation receipt, failed and successful probe receipts, and all availability samples. Its `deployment-final-proof.json` SHA-256 is `a85a4e5d8cd36e62ef5ee097f1d82ab0ef374eaeb21863c85c597195e7cc5e9f`. This document intentionally omits credentials, account identifiers, and the full private deployment manifest.

Rollback was prepared and tested locally but was not executed. It requires separate approval and refuses to remove enforcement after a real consent owner or personal task exists.
