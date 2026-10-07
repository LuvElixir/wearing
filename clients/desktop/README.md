# Wearing Desktop

First Mac technical preview of Wearing, connected to the existing personal-agent service. The client has its own window, native menu/tray, quick-entry action and recoverable connection page. Calendar, tasks, notes, capture media and conversations remain in the same Wearing service; closing this client does not stop the core.

See [implementation and platform boundaries](../../docs/native-clients.md), [acceptance](../../docs/evidence/native-desktop-2026-10-04.md) and [design](../../docs/design-native-desktop.md).

```sh
npm ci --ignore-scripts
npm run build -- --debug --bundles app
npm test
```

Rust 1.90+, platform toolchain and a running Wearing service are required. The current artifact targets Apple Silicon macOS, is a local developer preview, and has no notarized public installer or auto-update. Windows installer configuration exists, but has not been built/tested on Windows. Background global-hotkey delivery, microphones/cameras and system calendars remain unverified; foreground menu accelerator and media file selection passed.

Dependency versions and checksums are locked. Upstream license texts included in the Mac build are in src-tauri/notices; a platform-specific license audit is required before public distribution. No personal record database, API key, Python/Hermes runtime or device driver is in the bundle.
