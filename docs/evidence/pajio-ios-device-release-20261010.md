# Pajio iPhone Release preparation — 2026-10-10

## Physical-device result

The parent completed a signed `Release` build and installed and launched Pajio 0.2.0 on the owner's connected physical iPhone Air on 2026-10-10. Device Hub showed the live Pajio invitation entry, and tapping **使用邀请码加入** opened the production invitation page successfully. The public endpoint is supplied by the app; the owner is not asked to enter a server address.

Both main app and share extension passed strict code-signature verification. Both profiles include the registered physical device and the shared App Group; both bundles include their privacy manifests. The main app is an `iphoneos` artifact with a 7,017,260-byte bundled JavaScript file, and its signed plist retains the strict ATS configuration below. The personal artifact is retained in a private local Downloads directory and must not be published with device provisioning data.

Personal account activation, authenticated chat on that account, native sharing, and a disconnected mobile-data cold launch remain to be verified. This is a local development-signed Release installation, not a TestFlight or App Store release. WeatherKit and remote push are separate outstanding integrations.

## Preparation scope

The mobile release configuration is ready for the parent task's explicit-team, physical-device Release build. This audit generated an isolated iOS project and checked its actual PBX resources and plists. It did not create credentials, sign an app, install on a device, submit to Apple, change a server, or establish real-device acceptance.

The shortest route for the owner's own iPhone is a local, signed `Release` build installed over USB. It embeds the JavaScript bundle and uses the public HTTPS service. It does not require Metro or EAS account setup. TestFlight/App Store distribution is a separate later artifact and approval flow.

## Current configuration

| Item | Observed value / implication |
| --- | --- |
| Expo / React Native | Expo 57.0.26 / React Native 0.86.3; package and versioned Expo docs checked |
| Local toolchain | Node 24.16.0, Xcode 27.0; compatible with the Expo 57 requirements checked in the official docs |
| Display / version | Pajio / 0.2.0; legacy bundle identifiers intentionally preserved |
| Main bundle | `io.luckyloading.wearing.mobile` |
| Share extension | `io.luckyloading.wearing.mobile.share` |
| App Group | `group.io.luckyloading.wearing.mobile.share`, shared only between main app and share extension |
| Public API | `https://pajio.luckyloading.com/`; fresh production native installs do not ask for an endpoint |
| Login | System browser, PKCE/state, `pajio://auth`; old custom-origin credentials stay isolated |
| Native credential storage | SecureStore `WHEN_UNLOCKED_THIS_DEVICE_ONLY` |
| Developer endpoints | Require both `__DEV__ === true` and explicit build flag; Release cannot enable them merely by setting the flag |
| Transport | Explicit ATS: arbitrary loads false, local networking false, no exception domains |
| OTA / Metro | Existing native Expo configuration has updates disabled; signed Release output must include its bundled JS |
| Push | Notification module present, but no EAS project ID in source config. Remote push registration deliberately refuses to proceed without a matching configured project; this remains an independent feature gap |
| EAS profiles | `preview` is internal distribution, `production` is store. The `development` profile is not the standalone personal Release route |

No Team ID, signing certificate, private key, provisioning profile, account cookie, or password was added to source.

## Narrow release fixes

1. `clients/mobile/app.json`: define strict ATS explicitly. The older generated native plist allowed local networking; the new actual CNG output has no local exception.
2. `clients/mobile/extensions/share-intake/PrivacyInfo.xcprivacy`: declare the extension's actual required-reason file-metadata APIs. `C617.1` covers creation-date reads for cleanup inside the App Group staging directory; `3B52.1` covers size checks of files explicitly shared by the user. The extension itself has no networking or tracking.
3. `clients/mobile/plugins/share-intake.cjs`: copy the extension manifest and include it in the **extension** resources. Expo 57's generated extension resource phase is named `Embed Foundation Extensions`, so node-xcode's resource helper can silently select the main app's `Resources` phase. The plugin now resolves the resource phase from the extension target's phase UUIDs and fails closed if there is no unique target/phase or the file is not attached to it.
4. `clients/mobile/plugins/share-intake.test.cjs`: validate the declared reasons, correct target binding, idempotency, and rejection of an existing but unbound resource.

The main app's existing aggregated manifest covers its dependencies. An extension is a separate executable bundle; the main app's manifest alone does not replace the extension's declaration. The bundled manifests are not a substitute for the later App Store privacy questionnaire or a complete product-data policy review.

## Actual CNG checks

An isolated temporary project copied only the app configuration, package metadata, plugins, extensions and assets, with existing node_modules reused. It did not touch the parent's candidate or device. A clean CNG run completed successfully:

```sh
CI=1 EXPO_NO_DOTENV=1 EXPO_NO_TELEMETRY=1 node node_modules/expo/bin/cli prebuild --clean --platform ios --no-install
```

`--clean` above applied only to the disposable audit snapshot. In the parent's separate run, `prebuild --platform ios --no-install` also printed `Clearing ios` and removed its workspace/Pods; the parent is restoring Pods with its existing toolchain. Do not infer that `--no-install` preserves native dependencies. Always retain the candidate backup and verify workspace/Pods after generation.

Independent parsing of the generated `Pajio.xcodeproj/project.pbxproj`, following each native target's actual phase IDs, confirmed:

```json
{
  "extensionManifestReferenceInExtensionResources": 1,
  "extensionManifestReferenceInMainResources": 0,
  "manifestCopiedToExtensionDirectory": true,
  "reapplyingResourceHookChangesProject": false,
  "NSAppTransportSecurity": {
    "NSAllowsArbitraryLoads": false,
    "NSAllowsLocalNetworking": false,
    "NSExceptionDomains": {}
  }
}
```

An earlier draft passed CNG but failed this independent resource-target check. It was corrected before source freeze; native projects generated from the earlier draft must be regenerated from the final source and checked again.

## Source freeze

| File | SHA-256 |
| --- | --- |
| `clients/mobile/app.json` | `d04af081b852d699a3a2f6bb0b1ebb524827b80ace45f4836698347865b930e4` |
| `clients/mobile/plugins/share-intake.cjs` | `9ad2735b857fe844b366eeb52e8e7bd57763b889f34720adf537c51deffc5068` |
| `clients/mobile/plugins/share-intake.test.cjs` | `f4ce08415b5cbd85e594f3073f86179d0f4b890580342bfb9c7612a7cb07aaef` |
| `clients/mobile/extensions/share-intake/PrivacyInfo.xcprivacy` | `0a64987150d583ab275bac1fe55964eba361b05cd7bfda0bebe056b015529137` |

Validation after the final source change:

- `node --test plugins/share-intake.test.cjs`: 4/4 passed.
- `node node_modules/tsx/dist/cli.mjs --test src/connection-default.test.ts src/dev-connection.test.ts src/session-protocol.test.ts`: 25/25 passed.
- `node node_modules/typescript/bin/tsc --noEmit`: passed.
- `node node_modules/eslint/bin/eslint.js src`: passed.
- Scoped `git diff --check`: passed.

## Signing and artifact boundary

The parent owns the guarded runner at `.wearing/on-prem/20261009/iphone-personal-20261010/build-device.py`. It backs up and prepares the isolated candidate, records exact source hashes, and supplies the explicitly selected team and physical device. This audit does not duplicate that runner or alter its signing inputs.

The relevant build action is `xcodebuild` on the generated `Pajio.xcworkspace`, scheme `Pajio`, configuration `Release`, destination `id=<explicit device UDID>`, with explicit `DEVELOPMENT_TEAM`, automatic signing and the parent-authorized provisioning/device-registration flags. Both main and extension targets must resolve to the same team with profiles permitting the shared App Group. Push entitlement must agree with the selected signing profile; it should not be removed to make signing pass.

A successful local compile alone is not install acceptance. Before claiming the installed build is standalone, verify the resulting `.app` is `iphoneos` / arm64, contains its JS bundle and signed share `.appex`, and contains a privacy manifest in each relevant bundle. Then install, disconnect from Mac/Metro, cold-launch over mobile data, sign in through the system browser, and exercise chat and native sharing. The parent performs and records those real-device checks separately.

For later exported IPAs, Xcode 27 names the development export method `debugging` and internal Ad Hoc method `release-testing`; use explicit team/profile mapping and inspect the resulting profile entitlements. An IPA export is not an App Store upload.

## Official references checked

- [Expo SDK 57](https://docs.expo.dev/versions/v57.0.0/) and [Expo documentation index](https://docs.expo.dev/llms.txt)
- [Expo local production builds](https://docs.expo.dev/guides/local-app-production/)
- [Expo internal distribution](https://docs.expo.dev/build/internal-distribution/)
- [Expo Apple privacy manifests](https://docs.expo.dev/guides/apple-privacy/)
- [Apple required-reason APIs](https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api)
- [Apple approved API reasons](https://developer.apple.com/documentation/bundleresources/app-privacy-configuration/nsprivacyaccessedapitypes/nsprivacyaccessedapitypereasons)
- [Apple App Groups](https://developer.apple.com/documentation/xcode/configuring-app-groups)
- [Apple Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)
- [Apple testing a Release build](https://developer.apple.com/documentation/xcode/testing-a-release-build)
