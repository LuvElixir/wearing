# Pajio bear / wardrobe verification — 2026-10-07

## Native App delivered locally

Release simulator build: `artifacts/pajio-20261007/ios-bear-motion/Pajio.app`.
Source + bundled motion hashes: adjacent `source-sha256.json`.
Installed over the existing App on iPhone Air / iOS 27 simulator. Kept bundle/storage identity, connection and saved outfit. No real-device distribution or store release in this task.

- Removed the alternate symbol companion option and migrated its read behavior to bear without rewriting saved outfit or old records.
- Registered eight original drawings by measured alpha bounds, shared baseline and center. They are all resident/preloaded on the wardrobe stage.
- Enlarged the top bear to a legible 48px head/shoulder portrait. Removed the extra flex spacer so the progress subtitle has room.
- Hypit-generated blue greeting: muted articulated blink/head/paw movement; plays once with quiet intervals. Not a whole-image transform. Other outfits retain their own matching static asset.
- Blue/cream reversible video transition: about 2.8 seconds plus 220ms handoff to the final illustration. Other pairs use a short dressing curtain.
- Preview remains local until explicit apply. Rapidly switching cream → blue → peach settled on peach. Returning without apply preserved blue. Day/night and restoration to system mode checked through the actual native UI.
- Discovered and fixed a real `expo-video` teardown crash: calling `pause` in cleanup after `useVideoPlayer` released its native shared object. Final build allows the owning hook to dispose it. Repeated chat → settings → wardrobe navigation and finished/interrupted film transitions then passed.

Checks: TypeScript passed, scoped ESLint passed (0 errors/warnings), 196 tests passed, Xcode Release simulator build succeeded. Test log: `/tmp/pajio-bear-mobile-tests-final-20261007.log`; build log: `/tmp/pajio-bear-native-build-20261007.log`.

Screenshots in this directory are actual Device Hub/Pajio window captures through CUA. `desktop-regression.png` records a failed desktop review, not an accepted outcome: the prior Web inline style implementation was blocked by the server's `style-src 'self'` CSP. ZCode was asked to fix its CSS without weakening the security policy and to reverify the actual running desktop app.

## Design status

Two Hypit jobs completed; source/build IDs and estimated credit use are recorded in `design/motion/pajio-bear-20261007/PROGRESS.md`. Only blue idle and blue/cream garment pair have articulated footage, not all eight outfits.

The user selected C (quilt bear). Built-in image_gen isolated a production master, saved with its exact prompt at `design/brand/pajio/app-icon-c.prompt.txt`. 1024px opaque export plus size variants generated mechanically. Existing SVG wordmark preserved. The Release simulator build now contains C; installed and actual home-screen icon/name verified in `ios-icon-c-home.png`. Android source assets/config updated, Android runtime not tested. Desktop C package and favicon were updated by ZCode; root verified its strict code signature and the real Pajio window. `desktop-final.png` confirms the enlarged bear, correct progress layout and Pajio window title after the WKWebView correction below.

## Desktop verification follow-up

The first C build still rendered an empty progress circle in the actual WKWebView, despite the Chromium preview passing. ZCode corrected video framing to the App fixed portrait frame and kept the poster permanently beneath a video layer that becomes visible only when a frame is ready. It now restores the poster on pause/error/visibility/reduced-motion transitions. Root reopened the real Pajio package after preview-process restart and verified the bear pixels were present (`desktop-final.png`). Web UI suite: root reran all 107 tests successfully (`/tmp/pajio-web-final-20261007.log`) and independently verified the desktop bundle signature. Root also opened actual desktop appearance (symbol option absent), played blue-to-cream and verified the final cream outfit without applying it (`desktop-wardrobe-final.png`). User data and services were not reset.

C icon production master: `design/brand/pajio/app-icon.png`. The iOS source asset has the same SHA-256 (`4afacec34b2dfaadfebff17cd8f5e9dbda1c7215bca66925b74a72b0b7fb1b16`). The native package launched successfully after in-place install.
