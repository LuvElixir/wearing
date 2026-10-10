# Paused private-session return: source, builds and Core activation

Date: 2026-10-10. This record separates source/build checks from native UI acceptance.

## Change and safety boundary

A device paused after a private remote session cannot use the ordinary device-resume endpoint. The existing relay rejects that request with `human_session_requires_explicit_return`; the user must inspect the screen and explicitly return the device through the remote-session flow.

The App now offers “查看并交还” for this state. Opening that entry only navigates to the existing remote-session page. An ordinary resume first fetches the current access state; missing, changed or pending state does not send a resume. Backgrounding or leaving the page suppresses a late continuation. The relay's explicit-return and device-ACK requirements are unchanged.

Core maps the existing rejection code to an actionable Chinese message rather than the generic device-settings failure. No permission or control-state logic changed in this Core overlay.

## Local verification and packages

- App tests: 818 passed, zero failures or skips.
- Focused Core HTTP/relay tests: 15 passed, including rejection without mutation for a paused private session and ordinary resume under its existing generation check.
- TypeScript, repository-local `eslint src`, and `git diff --check` passed. `expo lint` itself could not start because the host's global `npx-cli.js` was configured as an ES module; the local ESLint command completed with the project's configuration.
- Both Release builds completed under the existing toolchains. The candidates contained the two changed runtime source files and the new test; no native project regeneration or dependency update occurred. All 14 recorded native configuration hashes remained unchanged.
- The iOS simulator app retains the existing application identifier, App Group and simulator entitlements, with native Xcode ad-hoc signing. It is not an iPhone distribution package.
- The Android APK contains only `arm64-v8a`, retains the existing Android Debug test certificate, and passes v2 signature verification, 16 KB zip alignment and 16 KB ELF alignment for 25 native libraries. It is not distribution-signed.
- Source-map checks matched the packaged code to the recorded source hashes. The previous packages were preserved unchanged. This build task did not install either package.

| Build artifact | SHA-256 |
| --- | --- |
| `Pajio-0.2.0-20261010-control-return-fix-arm64-test.apk` | `32a525399d5d40fb0ae588f24cbfb4e75009e3f50f01282bb2b153521edaf478` |
| `control-return-fix-simulator-manifest.json` | `0a7d9e3753b0ad2933154383d7bb84d452c3c488727eacc1bd9a4df7586be732` |

The simulator manifest describes the complete `.app` tree; its digest is not a single-file application digest. Build logs, commands, source manifests and `control-return-fix-build-proof.json` are retained locally alongside the packages in `Downloads/Pajio-test-20261010`.

## Core single-file deployment and availability

The operator read each live `app.py` and compared it locally with the candidate. Both exact diffs contained only the fixed rejection-message mapping. The deployment order was **B, then A**. Each live preimage was backed up privately with its hash before replacement; the operation kept a one-shot intent and remote activation receipt. An uncertain result must be queried, not redispatched.

| Scope | Before SHA-256 | After SHA-256 |
| --- | --- | --- |
| A and B `app.py` | `dfe035e84138cf4ad082ea7c5d5bffadce71e2a116a4159415f88a3aaaa0ff5d` | `2c825a17a664e2d105ef2ece3472d802d174ecaa3136eb7ac89a3919972f0175` |

Only `wearing-tenant.service` was restarted on each tenant. Each new Core PID remained stable and passed five consecutive authenticated public `/api/status` checks with HTTP 200 and Hermes `reachable` before proceeding. The relay PID, start timestamp and restart count were identical before and after. The operation did not restart media services, change instance data directly, or send a resume command to a real device.

The continuous public probe observed **68 requests during the 39.961-second deployment window**:

| Tenant | HTTP 200 | HTTP 502 |
| --- | ---: | ---: |
| B | 30 | 4 |
| A | 31 | 3 |

The seven transient 502 responses occurred during the respective Core restarts. This was not a zero-downtime deployment. Both tenants recovered and passed the separate consecutive-ready checks described above.

Sanitized deployment receipts, exact source diffs, backup references and the bounded probe snapshot are retained in the ignored local directory `.wearing/on-prem/20261009/personal-compute/control-return-core-20261010/`, with `summary.json` as the entry point. Credentials and raw device screens are not included in this record.

## Native UI acceptance boundary

At 12:22 China Standard Time, the operator checked the installed `control-return-fix` build on the dedicated **Pajio Acceptance iPhone Air simulator**; the existing test-A sign-in was retained. The device page showed the Linux device's existing private-session pause and the button “查看并交还 专属Linux电脑”, with no ordinary resume button for that state.

Opening this entry displayed “设备保持暂停” and “重新接管”. Navigation did not release the Agent pause. The operator then explicitly requested takeover and received the device ACK and a real remote picture. The local, ignored screenshot `docs/evidence/pajio-device-files-ui-20261010/app-explicit-return-entry.png` records the corrected entry.

Between 12:33 and 12:37 China Standard Time, after the Linux pointer fix, the same simulator completed the remote-control and return flow against the synthetic Linux fixture. Repeated clicks at the same Save button position advanced its visible counter from `Saved 3` to `Saved 4` and `Saved 5`. The operator entered the Chinese test text `好梦42` and used the down-arrow control to scroll. These observations establish the tested click, text and keyboard paths; they do not establish touch scrolling or exact emoji rendering.

The operator then selected both return confirmations and pressed the confirmation button. The UI displayed “设备已确认交还” following the actual device ACK. The local, ignored screenshot `docs/evidence/pajio-device-files-ui-20261010/app-linux-return-confirmed.jpg` records this final state. The earlier media interruption remains documented separately in the Linux input-stall and deployment evidence; its failed captures `app-linux-control.png` and `desktop-linux-save.png` are not passing input evidence.

This verifies the pause-aware entry, the stated Linux interactions and explicit return on an iOS simulator. It is not physical-iPhone or Android-App acceptance, and it does not by itself prove native file transfer or long-duration remote-session stability.
