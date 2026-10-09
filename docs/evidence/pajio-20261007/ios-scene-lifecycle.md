# Pajio iOS 27 scene lifecycle repair — 2026-10-07

Status: official scene configuration added; two clean generations validated; scene-only intermediate Release simulator build succeeded (exit 0). Final delivery also awaits the requested pajama-bear app icon. Scene-only runtime acceptance: the root agent clicked the home-screen Pajio icon through CUA and observed the standalone chat, real existing history, five navigation entries and no Expo Go gear. The scene lifecycle startup repair passed this simulator observation. Final branding integration remains pending.

## Observed failure

Root GUI acceptance launched the installed app twice; both launches exited. Crash report: `/Users/archieliew/Library/Logs/DiagnosticReports/Pajio-2026-10-07-192143.ips`, incident `085BB2CE-7E99-4648-80E3-A1E750980B3C`. Exception `EXC_BREAKPOINT / SIGTRAP`; first frame `___UIApplicationEvaluateRuntimeIssueForNoSceneLifecycleAdoption_block_invoke`.

The generated AppDelegate used `UIWindow(frame:)` and started React Native from `didFinishLaunchingWithOptions`; Info.plist lacked `UIApplicationSceneManifest`. Apple requires scene lifecycle for apps built with the iOS 27 SDK. Expo 57.0.26 already includes the official scene delegate, but SDK 57 requires explicit opt-in.

## Change

- Installed SDK-compatible `expo-build-properties ~57.0.22` via `node node_modules/expo/bin/cli install expo-build-properties --npm`.
- Configured `expo-build-properties` with `{ "ios": { "enableSceneSupport": true } }` in `clients/mobile/app.json`.
- Package lock adds only `node_modules/expo-build-properties`; no dependency upgrades/removals.
- No handwritten SceneDelegate, private flag, SDK downgrade or Mobile.tsx change.

## Repeatable generation

Two independent `CI=1 node node_modules/expo/bin/cli prebuild --platform ios --no-install` runs produced identical SHA-256 for AppDelegate.swift, Info.plist, Podfile and Podfile.properties.json.

Generated Info.plist declares `UIApplicationSceneManifest` with `EXExpoAppSceneDelegate`, single scene. AppDelegate conforms to `ExpoReactNativeFactoryProvider`, retains the React factory initialization and removes the legacy window/startReactNative block. The official Expo delegate starts React in the connected scene and handles both cold and warm URL delivery.

Active-source typecheck and local ESLint passed after plugin installation. Build and runtime acceptance are tracked separately.

## Official references

- https://docs.expo.dev/versions/v57.0.0/sdk/build-properties/#pluginconfigtypeios
- https://expo.dev/changelog/sdk-57
- https://developer.apple.com/documentation/technotes/tn3187-migrating-to-the-uikit-scene-based-life-cycle

Scene-only verification app: `/Users/archieliew/Documents/facet/artifacts/pajio-20261007/ios-scene-verification/Pajio.app`. Final Info.plist contains the scene manifest. This is an intermediate package with the previous icon, for startup verification only. The build agent has not installed/launched it.

## Runtime observation after scene repair

The root agent installed and launched the scene-only intermediate package through the simulator home screen. It reached the independent Pajio chat with existing history and five navigation entries, without Expo Go chrome. This establishes startup success for the scene-only package on the iOS 27 simulator. Deep-link cold/warm routing, light/dark transitions and final replacement icon/wordmark require their own acceptance.
