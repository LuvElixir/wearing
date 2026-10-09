# Pajio delivery evidence — 2026-10-07

Current status: the iOS 27 startup crash has been resolved and the `ios-scene-verification` standalone app was launched through the iPhone Air simulator home screen into the real Pajio chat. Final native packaging is paused until the App icon is selected again. The earlier `ios-simulator` ZIP and the desktop bundle containing the P-and-bear candidate icon are not final deliverables.

## Scope

User-approved Pajio name, original rounded pajama teddy with mouth, eight outfits, neutral day/night App, single filled four-point star and outlined wordmark. Native Android resources were regenerated in an isolated candidate and copied within a 39-file reviewed scope. iOS CNG candidate was generated separately, without creating a live ios tree. `expo-system-ui` was added at the SDK-matched version for Android automatic appearance; native resource/manifest evidence is `pajio-20261007/native-brand-sync.json`. Android build remains unavailable because this Mac lacks JDK/Android SDK. During resumed work, CocoaPods 1.16.2 was installed in an isolated temporary toolchain, 115 Pods installed successfully, and an initial iOS Simulator arm64 Release build passed. Its build/install checkpoint is recorded in `pajio-20261007/ios-native-build.md`; the subsequent startup failure and verified scene repair are recorded in `pajio-20261007/ios-scene-lifecycle.md`. This is a simulator app, not a signed physical-device IPA.

The name and artwork are product decisions; this delivery does not establish market validation or trademark clearance.

## Delivered App and runtime

- Pajio display name, permission explanations, connection UI and account wordmark; new icon/adaptive assets and light/dark single-star splash. Legacy wearing installation IDs, storage and protocol names retained, `pajio` deep-link scheme additive.
- Fresh identities default to mist-blue teddy; existing explicit companion/outfit preferences preserved. Eight outfits preview then save; failure does not silently replace current outfit.
- Non-chat pages use compact handoff/continue-draft entry. Composer and conversation stay mounted; connection/identity remain the state boundary.
- Expo Network drives offline send guard without treating LAN-only connectivity as offline. Voice remains editable before explicit send. Font scale is controlled in host CSS, not whole-page zoom.
- Chat progress, Today and Tasks share an in-memory snapshot per endpoint, identity and development credential. Polls/inflight reads deduplicate; background unsubscribes pause refresh, stale/error states retain the last valid read, and scope changes reject late responses. Task archive pagination keeps its own stable base.
- Task history supports complete paged reads, identity-scoped versioned cursors, explicit stale-page refresh and global counts separate from loaded rows.
- Selected memory content is carried into a correction draft. It is not automatically sent or silently rewritten.
- Backend product identity is Pajio, profile24 migration preserves user-modified config/SOUL; compatibility IDs remain.

## Checks

- Final full mobile tests: **196 passed, 0 failed**, including wardrobe/drafts/voice/scale/paging and the final synchronization/capture-lifecycle regressions.
- Mobile TypeScript and source ESLint: **pass** via local executables.
- Earlier iOS Hermes bundle export: **pass**, 3,811 modules and eight bear assets included; `/tmp/pajio-ios-final-20261007`. The later native Release checkpoints below include the subsequent source fixes; the old ZIP is not a final deliverable.
- Backend identity/profile/runtime tests: **158 passed** plus **one real pinned Hermes adapter test**.
- Backend activity/pagination tests: **87 passed**, including 53-item traversal, cross-identity cursor rejection and 409 on changed content.
- App-host initial HTML CSP issue fixed by moving the portrait radius into existing CSS; no CSP relaxation. Served browser console check had no errors/warnings.
- App-host UI structure tests: **7 passed**. Browser-host at 390×844: 200% body text (17→34px) reflows without horizontal overflow in both themes; search targets about 51–58px. Screenshots under `output/playwright/pajio-host-*.png`.
- Reading palette: 30 canonical text/background pairs passed 4.5:1, lowest 4.76:1. Numeric evidence: `pajio-20261007/contrast.json`; this excludes image overlays and does not establish full accessibility compliance.
- SVG wordmark/symbol/icon audit: no blocking issues, only coordinate precision/viewBox advisory. Wordmark uses bundled Nunito under copied OFL license and is outlined.
- Brand preview `http://127.0.0.1:8877/`: day/night toggle and outfit selector verified through browser UI. Approved bear images load.
- iPhone Air iOS27 simulator: Pajio account wordmark, dark appearance selection, eight outfit radios, cream-moon preview and explicit saved state observed. Screenshot `pajio-20261007/wardrobe-night.png` captured during local service restart, so it truthfully contains temporary connection feedback. This is simulator evidence, not physical iPhone proof.

## Local activation

Local backend was idle before graceful replacement. New server PID79991 serves Pajio/profile24; live read-only pagination walked nine records in page sizes 2,2,2,2,1 with no missing/duplicate IDs and unchanged aggregate counts. Existing four-hour phone pairing had expired before activation; renewed bridge PID80373 returned authenticated 200. Its private QR is `.wearing/mobile-dev/pajio-iphone-20261007T101304Z.png`, expires 22:13 Beijing; this does not imply the physical phone already reconnected. Runtime log is local private `.wearing/runtime/pajio-server-20261007T101048Z.log`.

## Design-tool findings

The brand preview's 13 automatic style advisories compare it against legacy root DESIGN.md, outside its intended scope: five current App palette colors, two intentional icon/pill radii, and six brand presentation heading sizes. They were reviewed as scope mismatches. The preview is a brand specimen, not the product reading UI; App palette authority is clients/mobile/DESIGN.md. No claim of blanket accessibility compliance follows from screenshots.

## Remaining evidence boundaries

The scene-verification standalone package passed a home-screen launch into the real Pajio chat on the iPhone Air iOS 27 simulator. The final icon and final native package remain pending selection and a later build; the startup crash is no longer the current blocker. Expo Go screenshots alone do not verify native resources. Physical-device interruption/real-network/system-font/overnight and push delivery were not retested by these checks. Market/user studies and subscription entitlements are not fabricated. Current-delegation attachment binding and cross-night notification/resilience remain separate engineering work; this brand/UX delivery does not silently mark them complete.

Web/Desktop are assigned to ZCode with `docs/pajio-zcode-handoff-2026-10-07.md`. Completion requires its implementation and evidence, not this handoff document.

## Resumed UI verification

The earlier Mac lock was resolved by the user. The simulator's original mist-blue/day preferences were restored through the App UI. ZCode received the final Pajio follow-up in its existing facet task and was visibly implementing Web/Desktop on 2026-10-07 around 18:43. Its delivery and independent review are still required before those surfaces can be called complete.

On the iPhone Air iOS 27 simulator, Today read the live task state and the compact entry returned to chat. A temporary, unsent text draft survived chat → Today → compact continue-draft entry → chat. It was then cleared through the UI; no message or task was sent. Clean Today screenshot: `pajio-20261007/app-today-day-resumed.png`.

A stale connection-error banner found during QA was fixed: complete synchronization clears only sync-owned feedback and preserves action-owned messages. Connected state is now committed after snapshot/local storage success. Final review also protected capture drafts while save/media/identity operations await completion and ensured local-read failures release the synchronization lock. The final mobile suite is **196/196**, with TypeScript and local source ESLint passing. See `pajio-20261007/connection-recovery.md` and `capture-lifecycle.md`; a real native outage/recovery cycle is not claimed by these unit checks.

The Mac locked again during resumed verification; the user was asked to unlock through the supported user-input tool. Native UI operation and sending the Web follow-up through ZCode were paused at that checkpoint; the later unlock and standalone launch verification are recorded below. Browser-based read-only/reversible QA continued: it found the Web header scrolling out of view and inherited 20px/no-fill wordmark styling. These findings were recorded in `pajio-20261007/web-review-followups.md`; the final ZCode delivery must address them before acceptance. The Web QA theme was restored to its original system preference.

## Archived pre-scene iOS simulator artifact — not final

- `artifacts/pajio-20261007/ios-simulator/Pajio.app` and `Pajio-ios-simulator-arm64.zip` (26,586,403 bytes).
- ZIP SHA-256: `4af8b6b7e3e9674eced8593d77133e32037c470c646cb54f21ac5f25c802bbf9`.
- Initial xcodebuild exit 0 / BUILD SUCCEEDED, 92 copied file hashes identical to the candidate, ZIP integrity passed. No developer certificate, device provisioning or App Store publication. This ZIP is retained as a build/install checkpoint and is superseded by the scene repair below.
- Installed successfully with `xcrun simctl install` on the existing iPhone Air simulator `FC25D76C-DF85-4CB5-A862-DB33E302BA07`; `get_app_container` confirmed a `Pajio.app` container. Its subsequent launch failed; only the later scene-verification package passed standalone startup.

## Recorded source checks

Final full mobile suite: 196/196, no skipped/failed; TypeScript and source ESLint pass after the final source changes. Mobile-host UI regression suite: 7/7 after the Web work so far. The archived simulator artifact and scene-verification package include `Mobile.tsx` SHA-256 `df3aac6f27416cb0a5ca8c104e62018da36200fd8d1d260d49354f619dd541dc` and `mobile-sync-feedback.ts` SHA-256 `8ce4e710e3ea2c22b3d3026bb13b19657381b1861dc84a9f771216b6669e2927`; use its manifest for the remaining files. Earlier Hermes export `entry-28b438534ca9b668e705d6d3838f11b0.hbc` predates these final fixes. Digital brand archive: `design/brand/pajio-brand-kit-20261007.zip`, SHA-256 `b49f9d55a7c0661838d2233a75c80c0e5c91614f7bf0ed434dad5cc337c73e91`.

## Independent native launch — scene repair verified

At about 19:20 the Mac became accessible again. The four Web/Desktop findings were sent to the existing ZCode task and a working turn was observed. The installed Pajio name and single-star icon were visible on the iPhone Air home screen (`pajio-20261007/ios-standalone-home.png`).

Launching the original independent simulator package exited before its first screen. System crash report `Pajio-2026-10-07-192143.ips` identifies `___UIApplicationEvaluateRuntimeIssueForNoSceneLifecycleAdoption_block_invoke` on iOS 27. The repair uses the official `expo-build-properties ~57.0.22` plugin with `ios.enableSceneSupport: true`; two CNG runs produced identical scene configuration, and the rebuilt Release package passed compilation.

The root agent then installed `artifacts/pajio-20261007/ios-scene-verification/Pajio.app` and clicked its home-screen icon through CUA on the iPhone Air simulator. It reached the independent Pajio chat with real existing history, five navigation entries and no Expo Go gear. This resolves the observed iOS 27 startup failure. Details and remaining acceptance limits are recorded in `pajio-20261007/ios-scene-lifecycle.md`.

The verified scene package is retained for startup evidence. Final native packaging remains paused while the App icon is reselected; the earlier `ios-simulator/Pajio-ios-simulator-arm64.zip` and the desktop bundle containing the P-and-bear candidate icon are **not final deliverables**. A selected icon, final rebuild and corresponding UI acceptance are still required before marking those packages delivered.
