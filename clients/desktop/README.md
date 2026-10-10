# Pajio Desktop

Mac technical preview of Pajio. The client has its own window, native menu/tray, quick-entry action and official account entry. Calendar, tasks, notes, capture media and conversations remain in the same Pajio service; closing this client does not stop the core.

The first launch offers **使用邀请码** (`https://pajio.luckyloading.com/join`) and **已有账号登录** (`/auth/login`). Invitation redemption and OIDC happen on the official gateway. The native command accepts one of these fixed intents, never a caller-supplied URL or invitation code. The official IdP allowlist and local-only native IPC boundary are unchanged. Returning users with a saved official connection open the official homepage; its gateway determines whether they need to sign in.

Production builds do not show or accept custom server addresses. A valid legacy custom URL is replaced locally with the official origin, without contacting that URL; the user is asked to log in again. No cookies, tokens or records are copied between origins. Invalid settings remain on disk for recovery and are not used to connect. The native settings file only contains a URL.

See [implementation and platform boundaries](../../docs/native-clients.md), [acceptance](../../docs/evidence/native-desktop-2026-10-04.md) and [design](../../docs/design-native-desktop.md).

```sh
npm ci --ignore-scripts
npm run build -- --debug --bundles app
npm test
```

`npm run dev` explicitly enables `development-endpoints`. The custom connection form and native command require **both** that Cargo feature and a debug build; enabling the feature in a release build does not unlock custom endpoints. `npm run build -- --debug` alone also keeps them disabled. To test a local development endpoint, use `npm run dev` or an explicitly labelled debug build with `--features development-endpoints`. This is independent of the Web app's local developer form, which requires a local deployment, loopback page host and `?development=1`; cloud users never see that form.

`npm test` runs the actual account-entry JavaScript handlers and Rust URL, migration, IPC origin and HTTP-probe tests. These checks do not establish real invitation redemption, signed-in desktop UI acceptance, distribution signing or notarization.

Rust 1.90+, platform toolchain and a running Pajio service are required. The current artifact targets Apple Silicon macOS, is a local developer preview, and has no notarized public installer or auto-update. Windows installer configuration exists, but has not been built/tested on Windows. Background global-hotkey delivery, microphones/cameras and system calendars remain unverified; foreground menu accelerator and media file selection passed.

Dependency versions and checksums are locked. Upstream license texts included in the Mac build are in src-tauri/notices; a platform-specific license audit is required before public distribution. No personal record database, API key, Python/Hermes runtime or device driver is in the bundle.
