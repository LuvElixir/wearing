# Third-party notices

## croniter

Wearing's time-triggered intentions use unmodified **croniter 6.2.4** (MIT) for calendar recurrence calculation. It is a normal Python dependency; its license remains in the installed distribution and version/integrity hashes are recorded in `uv.lock`. Wearing supplies identity-scoped records and dispatches through its existing Hermes run adapter. Source: [pallets-eco/croniter](https://github.com/pallets-eco/croniter).

## FullCalendar

The built-in calendar integrates unmodified FullCalendar **7.1.0** standard browser bundles and the Monarch theme, licensed MIT. No Premium/Scheduler bundle is included. The upstream license is shipped at `wearing/web/vendor/fullcalendar/LICENSE.md`; the downloaded source URLs and SHA-256 hashes are recorded in `wearing/web/vendor/fullcalendar/manifest.json`. Assets are served locally with Wearing and require no runtime CDN requests. Sources: [FullCalendar vanilla JavaScript documentation](https://fullcalendar.io/docs/vanilla-js), [FullCalendar licensing](https://fullcalendar.io/license).

Wearing applies its own scoped styles and record adapter without modifying these bundles. The normal Python `tzdata` dependency supplies IANA timezone data on systems without a system database; installed dependency notices remain in its distribution, with versions and hashes in `uv.lock`.

## Login and platform metadata dependencies

The OIDC entry integrates unmodified Authlib 1.8.0 (BSD-3-Clause), itsdangerous 2.2.0 (BSD-3-Clause) and SQLAlchemy 2.0.54 (MIT). They are normal Python dependencies, not vendored source. Their notices remain in their installed distributions; reproducible package versions and integrity hashes are recorded in `uv.lock`. Authlib uses its JOSE dependencies for signature and claim verification. Sources: [Authlib](https://github.com/authlib/authlib), [itsdangerous](https://github.com/pallets/itsdangerous), [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy).

The optional `cloud` extra installs unmodified Psycopg 3.3.6 and its binary distribution for PostgreSQL integration (upstream LGPL-3.0-only). It is not included in the Wearing wheel as embedded code. Upstream notices and binary dependency licenses remain in the installed package. Source: [Psycopg](https://github.com/psycopg/psycopg).

Versioned platform migrations use unmodified Alembic 1.20.0 (MIT), a normal Python dependency with its installed notices and integrity hashes in `uv.lock`. Source: [Alembic](https://github.com/sqlalchemy/alembic).

Local acceptance used PostgreSQL 18.6 built from checksum-verified official source under the private QA directory. PostgreSQL is not bundled or installed as a system service by Wearing; its upstream COPYRIGHT remains in the private source distribution. Production database/TLS configuration is separate from the local test setup. Source and license: [PostgreSQL source](https://ftp.postgresql.org/pub/source/v18.6/), [PostgreSQL License](https://www.postgresql.org/about/licence/).

## Wearing wordmark / Fredoka

The outlined Wearing wordmark in `wearing/web/wordmark.svg` is derived from Fredoka, with word spacing and a cobalt terminal treatment. Copyright 2016 The Fredoka Project Authors (https://github.com/hafontia/Fredoka-One). Fredoka is licensed under SIL Open Font License 1.1; the full license is distributed at `wearing/web/fonts/Fredoka-OFL.txt`. The wordmark contains vector outlines and does not require loading the font. The illustrated avatar is generated Wearing artwork and is supplied as a transparent PNG.

Wearing integrates [Hermes Agent](https://github.com/NousResearch/hermes-agent), pinned to commit `367441274c48a03d12ee9f8d3d9ccd9bc1585392`. Its source is downloaded unchanged; Wearing provides a separate host adapter and product configuration.

## Hermes Agent

MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Filesystem MCP

The optional file connector uses the unmodified official `@modelcontextprotocol/server-filesystem` package, pinned to `2026.8.31` (npm source commit `a40bc270fb5ece62673f8a1196f57116d885c5eb`). Transitive npm dependencies and integrity hashes are locked in `src/wearing/connectors/filesystem/package-lock.json`; packages are installed on demand with lifecycle scripts disabled.

Source: https://github.com/modelcontextprotocol/servers/tree/a40bc270fb5ece62673f8a1196f57116d885c5eb/src/filesystem

The upstream license text from that commit is included at `wearing/connectors/filesystem/LICENSE.upstream` in the distribution (`src/wearing/connectors/filesystem/LICENSE.upstream` in source). It describes the project's MIT/Apache-2.0 transition and CC-BY-4.0 documentation terms; Wearing does not relabel the project under a single license. Dependency notices remain in their installed packages.

## Mobile MCP and Android Platform Tools

The optional Android connector uses unmodified `@mobilenext/mobile-mcp@1.0.7` (npm gitHead `ef371e8c6fd7fee066d773b98a0ce6b57a73b42d`), licensed Apache-2.0. The upstream license is included at `wearing/connectors/mobile/LICENSE.upstream`. Dependencies and integrity hashes are locked in `connectors/mobile/package-lock.json`; lifecycle scripts are disabled. Source: https://github.com/mobile-next/mobile-mcp

Wearing supplies a separate device-binding and pause proxy; it does not claim authorship of the mobile control implementation. The Android 9 route uses upstream legacy ADB mode with telemetry disabled. The legacy driver does not provide Unicode input; Wearing integrates the separate native-field adapter below. Not every tool or input surface is supported; see the acceptance record.

Android SDK Platform Tools 37.0.1 are downloaded on demand from Google's official distribution, with repository metadata checksums verified. They are not bundled into the Wearing wheel. Google terms and bundled notices apply: https://developer.android.com/tools/releases/platform-tools

## UiAutomator2

Optional native Android input uses unmodified `openatx/uiautomator2==3.7.0` (MIT), in a separate Python environment. Source: https://github.com/openatx/uiautomator2/tree/3.7.0

The upstream MIT notice is included in `wearing/connectors/android-u2/LICENSE.upstream`. All Python dependencies and distribution hashes are locked in `connectors/android-u2/requirements.txt`; their notices remain in installed distributions. The upstream bundled `u2.jar` is pushed to the authorized Android device and run via ADB on demand. Wearing does not install an input-method APK or enable root.

The adapter uses this pinned release's single-attempt JSON-RPC transport for `setText`, with before/after checks and a short-lived device service. Updating the dependency requires revalidating this private API and device behavior.


## Cua Driver

The optional computer connector reuses Hermes' built-in `computer_use` tool and its on-disk human/agent control lease. Hermes PM installs its pinned, checksum-verified Cua Driver **0.21.0** package on demand; no driver binary is bundled in Wearing's wheel. Source: https://github.com/trycua/cua

Cua Driver is MIT-licensed according to the upstream licensing map: https://github.com/trycua/cua/blob/main/LICENSING.md . Other Cua products have separate terms; this integration does not install Cua Spaces or imply that the entire monorepo has one license. Driver notices remain upstream-owned. Wearing preserves standard permission mode, disables driver telemetry, and uses upstream environment sanitization for driver processes.


## Capture input adapters

Image validation uses unmodified Pillow 12.3.0 (MIT-CMU); its full license remains in the installed Python distribution. Source: https://github.com/python-pillow/Pillow . Mac text recognition calls Apple Vision through a small Wearing Swift adapter; the platform framework is not bundled. Documentation: https://developer.apple.com/documentation/vision/recognizing-text-in-images .

Optional speech transcription uses the Doubao Seed-ASR 2.0 hosted API under the provider's service terms. Wearing's adapter implements the documented WebSocket envelope independently; no vendor sample source is executed or bundled. Documentation: https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-automatic-speech-recognition-websocket?lang=zh .

Audio decoding uses unmodified PyAV 16.1.0 (BSD-3-Clause), and transport uses websockets 16.1.1 (BSD-3-Clause). Locked versions/hashes are in uv.lock, with original notices in installed distributions. PyAV wheel codecs/FFmpeg have their own bundled upstream terms; Wearing does not relabel these dependencies under MIT. Sources: https://github.com/PyAV-Org/PyAV and https://github.com/python-websockets/websockets .

The former faster-whisper/Whisper Small integration and Hugging Face weight downloader were removed on 2026-10-07. Historical test evidence refers to that retired implementation; those dependencies and weights are no longer required or bundled.

## Desktop client

The optional desktop client reuses unmodified Tauri 2.12.1, tauri-plugin-global-shortcut 2.4.0 and tauri-plugin-single-instance 2.5.2, each MIT OR Apache-2.0. The build CLI is pinned to @tauri-apps/cli 2.12.1; npm integrity hashes and Rust source checksums are locked in clients/desktop/package-lock.json and src-tauri/Cargo.lock. Sources: https://github.com/tauri-apps/tauri and https://github.com/tauri-apps/plugins-workspace .

Upstream notices from the registry dependencies resolved on the Mac build host are included in clients/desktop/src-tauri/notices/DEPENDENCIES.txt and bundled as resources. This is a local technical preview; a platform-specific license audit, signing and distribution checks precede a public installer. No Hermes, Python, Cua Driver, ADB, model weights or user secrets are included in the desktop bundle.

## Mobile client

The optional mobile client uses unmodified Expo 57.0.26 modules, React 19.2.3, React Native 0.86.3, React Native Paper 5.15.3, react-native-webview 13.16.1, react-native-svg 15.15.4, the community datetime picker 9.1.0, safe-area-context 5.7.0, react-native-web 0.21.2 and idb 8.0.3 (MIT), plus lucide-react-native 1.52.0 (ISC). Exact resolved versions and integrity hashes are in clients/mobile/package-lock.json. Registry-supplied direct dependency notices are retained in clients/mobile/notices/DEPENDENCIES.txt. Sources: https://github.com/expo/expo , https://github.com/facebook/react-native , https://github.com/callstack/react-native-paper , https://github.com/lucide-icons/lucide .

The approved Wearing avatar and wordmark are reused unchanged. Expo Go 57.0.9 is an official development host installed separately on the test Android device; it is not a Wearing APK. Native binary distribution, signing, transitive notices and vulnerability remediation remain release gates. Model weights, Hermes, private records and credentials are not included in client exports.
