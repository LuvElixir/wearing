# Core AI consent release — 2026-10-10

The personal Core's explicit DeepSeek consent enforcement is deployed. No account was granted consent by this release, no real registration/consent interaction was performed, and no provider request was sent. The API contract is [pajio-ai-consent.md](../../contracts/pajio-ai-consent.md).

The reviewed overlay updated exactly 11 modules: `ai_consent.py`, `ai_consent_api.py`, `usage_guard.py`, `runtime.py`, `engine_runner.py`, `app.py`, `service.py`, `capture.py`, `capture_api.py`, `capture_worker.py`, and `capture_bridge.py`. Only `wearing-tenant.service` restarted, once; its managed Hermes engine returned `wearing.ai_consent_guard = deepseek-v1`. Core PID changed from 4778 to 7288. Relay PID 5295, nginx PID 4603, 286 other source/static files, and 16 configuration references remained unchanged.

Local validation passed 240 targeted Core tests and 6 release/probe tests. An independent review reran the 8 consent tests, including the installed SDK. The real post-release probe matched the installed managed interpreter to the running Core's `engine_runner` child process, then verified that an unconsented request through its real OpenAI SDK raised `ConsentError` before any dispatch. The probe used synthetic content and a raising `MockTransport`; it created no task, owner binding, grant, or usage reservation. Core readiness independently reported zero model calls, missing-private-owner HTTP 403, and anonymous HTTP 401.

The first read-only SDK probe failed an incorrect local assumption that Hermes installs its environment under `data/runtime`. The actual official environment is under `data/hermes/installs`. Its original script and failure receipt were preserved. The second probe verified the actual process interpreter and passed; there was no second service restart or model retry.

Availability observations preserve the switch window:

| Observation | Result |
| --- | --- |
| Private Core readiness, 37 samples | 35 HTTP 200 and 2 connection errors during restart |
| Final consecutive private readiness | 28 reachable samples spanning 81.09 seconds |
| Public `/privacy`, 114.19-second window | 23 HTTP 200 |
| Public `/auth/provisioning`, same window | 23 HTTP 401, expected without a session |

The public checks do not prove authenticated Core or App behavior. Real user acceptance, withdrawal through App settings, and third-party processing after explicit acceptance remain separate acceptance steps. The deployment retained the default-denied state.

The original installed wheel and this overlay must be recorded together as the running Core version. Activation plans, control services, device runtime wheels, SSH command pins, and account/invitation data were not modified. The existing activation `CORE_PROBE` still checks the same scoped bootstrap and reachable engine without generating model output.

Private evidence is under `.wearing/on-prem/20261009/ai-consent-core-20261010/`:

- Overlay manifest SHA-256: `d3ce5d7f3ff477f7513ad843d09c87fbf29b98d3926fbdd90698643b339c9a13`.
- Source/test/contract manifest SHA-256: `5e34adbe1efceea9ee23896e99b4c2708c9366c84fdace32381c1c0d36b38f84`.
- `deployment-final-proof.json` SHA-256: `a85a4e5d8cd36e62ef5ee097f1d82ab0ef374eaeb21863c85c597195e7cc5e9f`; it links exact installed source hashes, preserved service/configuration state, original failure and successful SDK receipts, and all availability samples.

Rollback was prepared and tested locally but not executed. It requires separate approval and refuses to remove enforcement once a real consent owner or personal task exists; original receipts and user data are retained.
