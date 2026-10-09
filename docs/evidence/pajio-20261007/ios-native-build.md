# Pajio iOS simulator native build — 2026-10-07

> Runtime correction: the originally built app crashed on both GUI launches on iOS 27 because it had not adopted UIScene. This artifact is superseded; follow `ios-scene-lifecycle.md` for the official configuration fix and rebuilt package. Build success did not establish launch success.

Final result: **BUILD SUCCEEDED**, exit **0**. Pajio 0.2.0 is packaged as a standalone arm64 iOS Simulator application with an embedded Hermes bundle. This is a simulator artifact, not a device-signed IPA or App Store release. Simulator installation, launch and visual/interaction acceptance remain pending because macOS is locked.

## Deliverables

- App: `/Users/archieliew/Documents/facet/artifacts/pajio-20261007/ios-simulator/Pajio.app`
- Archive: `/Users/archieliew/Documents/facet/artifacts/pajio-20261007/ios-simulator/Pajio-ios-simulator-arm64.zip`
- Archive size: 26,586,403 bytes.
- Archive SHA-256: `4af8b6b7e3e9674eced8593d77133e32037c470c646cb54f21ac5f25c802bbf9`
- App copy: 92 file hashes match the original build output; archive passed `unzip -t`.
- Embedded Hermes bytecode: version 98, 6,871,136 bytes, SHA-256 `160ae0e92872b4b7cc68b8f260a1136b2d40848ffb3b261b061beba9a7a6d8ba`.
- App executable: Mach-O arm64; SHA-256 `48beb97914f8a6bba76450425d03d68fb2c2238d3365e7ca7fdb4538b4b9f50c`.
- Full metadata/source hashes: `ios-native-build.json`; copied file hashes: `artifacts/pajio-20261007/ios-simulator/app-file-manifest.json`.

## Final source

Only these two runtime files were refreshed after the successful first native build, as confirmed by the source owner:

- `src/Mobile.tsx`: `df3aac6f27416cb0a5ca8c104e62018da36200fd8d1d260d49354f619dd541dc`
- `src/mobile-sync-feedback.ts`: `8ce4e710e3ea2c22b3d3026bb13b19657381b1861dc84a9f771216b6669e2927`

No web/desktop source was included or changed. Newly added regression tests were not copied into the candidate; the source owner runs the full suite. Candidate TypeScript and direct local ESLint passed again after the final sync.

## Isolated toolchain

- Candidate: `/var/folders/32/vzdw9zp96ps4lgrqy7rz55cw0000gn/T/pajio-native-candidate-veejd0vv`
- Xcode 27.0 (27A266a), iOS 27 SDK; Expo 57.0.26, React Native 0.86.3, Node 24.16.0.
- macOS system Ruby 2.6.10; candidate-local Bundler 2.4.22, CocoaPods 1.16.2, 42 locked gems from rubygems.org.
- No sudo, system Ruby/gem update, global package installation, cloud build, provisioning or release.
- The original shared `node_modules` symlink was preserved as `.node_modules-original-symlink`. An independent APFS clone prevents dependency generation from writing back into the active mobile workspace.
- `pod install` passed: 113 declared dependencies and 115 Pods. React Native/Hermes artifacts downloaded from their configured official distribution sources.
- Ruby 2.6 lacks `Array#filter_map`; Expo's precompiled module discovery reported warnings and automatically built those modules from source. The resulting native build succeeded.
- `CODE_SIGNING_ALLOWED=NO`; the linker applies an ad-hoc simulator signature. No Apple team or provisioning profile is embedded.
- Native build uses `-jobs 2`; final Metro bundling uses `--max-workers 2`.

Rebuild within the retained candidate:

```sh
.pajio-toolchain/run-pod install --project-directory=ios
.pajio-toolchain/build-ios-simulator
```

The build script runs `xcodebuild -workspace ios/Pajio.xcworkspace -scheme Pajio -configuration Release -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' -derivedDataPath ios-simulator-derived-data -jobs 2 ARCHS=arm64 ONLY_ACTIVE_ARCH=YES CODE_SIGNING_ALLOWED=NO build`.

## Validation and limits

- Initial full native build: exit 0. Final incremental native build: exit 0.
- `node node_modules/typescript/bin/tsc --noEmit`: passed.
- `node node_modules/eslint/bin/eslint.js src`: passed.
- Standard `npm run lint` initially failed in the existing global npx wrapper because `npm/bin/package.json` has `type: module`; the local ESLint binary passed. No global npm files were changed.
- Generated configuration audit: Pajio display name; legacy bundle identifier `io.luckyloading.wearing.mobile`; schemes `pajio`, `wearing`, and the bundle ID; opaque 1024×1024 icon; 72/144/216 px light and dark splash assets. All confirmed in the final app's plist/resource presence checks.
- 356 native/Pods reference files and symlinks had no reference back to active mobile source.
- Final app declares `DTPlatformName=iphonesimulator`, `MinimumOSVersion=16.4`; `Assets.car`, `SplashScreen.storyboardc`, and `main.jsbundle` are present.
- Compiler emitted upstream deprecation and Hermes static-global warnings; there were no build errors.
- Runtime connection, bright/dark appearance, deep-link behavior and user flows require later simulator/device acceptance. File/build success alone does not prove those behaviors.

Logs and locks are preserved under `/Users/archieliew/Documents/facet/artifacts/pajio-20261007/ios-simulator/logs` and `/Users/archieliew/Documents/facet/artifacts/pajio-20261007/ios-simulator/toolchain`; their scripts record the isolated setup and are intended to run from the retained candidate.

## Official references

- https://guides.cocoapods.org/using/getting-started.html
- https://rubygems.org/gems/cocoapods/versions/1.16.2
- https://docs.expo.dev/versions/v57.0.0/
- https://docs.expo.dev/guides/local-app-development/
