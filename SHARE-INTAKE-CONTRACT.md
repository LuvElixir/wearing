# Pajio system share intake — 2026-10-08

Status: App modules, native extension/config plugin and business receiver implemented. Root still owns `Mobile.tsx`/Router/VoiceComposer integration and real signed-device acceptance. Web/Desktop are not modified. No actual system share, network provider upload or user-content import was performed by these tests.

## Build requirements

- Existing Expo SDK 57 dependencies are sufficient: expo-sharing 57.0.22, expo-file-system 57.0.7, expo-crypto 57.0.3. No package added.
- `app.json` replaces the plain `expo-sharing` plugin with `./plugins/share-intake.cjs`.
- iOS plugin reuses Expo's share target/entitlement generation, then replaces `ShareIntoViewController.swift` with `extensions/share-intake/ShareIntoViewController.swift`. Native target: `expo-sharing-extension`, extension bundle: `io.luckyloading.wearing.mobile.share`, App Group: `group.io.luckyloading.wearing.mobile.share`.
- Main app and extension require that App Group in their signed provisioning profiles. The extension shares only content copies/manifests, never keychain, tokens, sessions or identity credentials. The existing product bundle ID is preserved.
- **Prebuild and a native rebuild are required.** An OTA JavaScript bundle does not add an extension/Android intent filters. Expo Go is not an acceptance target. Older iOS binaries safely report the missing share entry rather than assuming availability.
- iOS uses a standard share ViewController: Save → durable local copy → Done. It does not use Expo's experimental responder-chain auto-open technique. The user returns to Pajio to preview; foreground/cold-start intake consumes the queue.
- Android declares SEND/SEND_MULTIPLE for explicit supported MIME types. The config plugin normalizes text/plain intents with EXTRA_STREAM before Expo's lifecycle hooks, because SDK 57 otherwise silently drops text-file streams. It preserves the URI grants and provider's actual MIME type. Both cold `onCreate` and warm `onNewIntent` are covered, with strict Kotlin template guards/idempotence. There is no edit to `node_modules` or committed generated native directories.

Official documentation/source checked against installed SDK:

- [Expo 57 sharing](https://docs.expo.dev/versions/v57.0.0/sdk/sharing/): incoming raw payload API, plugin, Router redirect and experimental iOS auto-open caveat.
- [App extensions](https://docs.expo.dev/build-reference/app-extensions/).
- Installed Expo 57 `SharingModule`, `SimpleShareIntentDataParser`, `SharingReactActivityLifecycleListener`, `FileMode`, `Paths.appleSharedContainers`, and config plugin sources.

## Root integration

1. Mount `useShareIntake(connection)` at the connected App shell (not only when the inbox is visible). It exposes `{items,error,loading,refresh,available}` and listens to foreground/Linking events. Use pending count for a visible “分享收件箱” entry. Do not auto-dispatch `items`.
2. Add a route/view for `ShareIntakePanel`. It takes:

   ```ts
   {
     connection: Connection;
     identityName?: string;
     onChooseIdentity?: () => void;
     onCapture: ShareHandler;
     onDraft: ShareHandler;
     onChanged?: () => void;
   }
   ```

   The panel previews text, thumbnails and file metadata, names the selected identity, and requires a separate explicit import / chat-draft action. `onChooseIdentity` should open the real identity selector. The identity and action become immutable once a request begins; uncertain results must be retried in that same scope. Scoped panel keys include account/credential generation so stale callbacks cannot update a new identity's UI.

3. In existing `src/app/+native-intent.tsx`, preserve native sign-in handling and intercept exactly `pajio://expo-sharing` (optional legacy wearing scheme if desired) to an existing App view such as `/?view=share-intake`. Do not feed it to auth error handling. iOS standard extension does not deep-link or launch the host app.
4. Capture receiver:

   ```ts
   const onCapture = createShareCaptureHandler(connection, {
     store: storage,
     outbox, // the shared existing Outbox instance
     readFile: async uri => new File(uri),
     fetcher: serviceFetch,
     isCurrent: () => /* original endpoint/account/identity/credential still current */,
   });
   ```

   It uploads **every attachment through `uploadWorkspace`**, never image/audio capture upload. Per-file request key is `share-<UUID>-file-<index>`; each exact `imports/<key>/<normalized-name>`/size receipt is validated and persisted immediately. Retry resumes after the last confirmed file. File uploads themselves also use the server's request-key/digest idempotency. A late receipt is retained in its original identity and no next file/note is dispatched after identity change.

   After all files are confirmed, it enqueues `share-<UUID>` as a **text-only note** containing the full original text plus verified workspace paths, `media=[]`, `organize=false`. No model/task/automatic execution is started. Full composed length (12,000) and filenames (server 180-byte limit) are checked before the first upload; text is never silently truncated. Keep the ordinary existing outbox sync/attention UI.

   The receiver calls `outbox.enqueue(entry, [shareDeliveryKey, completedReceipt])`: existing Outbox commits both through one Store.batch transaction. The independent durable completion receipt therefore exists before any outbox flush can remove the item. Restart/retry after sync does not recreate the note. Do not replace this with “queue length is zero, so create again”.

5. Chat receiver remains root-owned. Contract:

   ```ts
   type ShareSubmission = {
     requestId: string; scope: string; text: string;
     files: {id:string; path:string; name:string; mime:string; size:number; uri:string}[];
   };
   type ShareHandler = (input: ShareSubmission) =>
     Promise<{requestId:string; scope:string}>;
   ```

   `onDraft` is offered only for text/URL shares. Persist a separate scope-bound chat-draft item with this stable request ID and a durable completion receipt before returning. Let the user explicitly bring it into VoiceComposer without overwriting their existing draft. Never send a message automatically. The panel says “已保存为聊天草稿” only after an exact receipt. Returning a receipt after merely changing a React state variable violates the contract.

## Queue and safety semantics

- iOS extension reads only the item providers explicitly supplied by the system share sheet. Save writes in a staging directory, bounds streams, writes manifest, then atomically renames to `<AppGroup>/pajio-share-inbox/<UUID>`. Cancel checks task cancellation before publication. Abandoned staging directories older than 24 hours are cleaned; ready shares are never auto-expired. Live ready/staging slots are capped at eight.
- App ingestion copies into private `Documents/share-intake/<UUID>`, verifies actual byte count, then writes the SQLite index. App Group content is deleted only after private queue persistence. Interrupted private copy is retried from the same native UUID. Only this queue's own copies are deleted on dismissal/completion; source files are not touched.
- Android reads raw `getSharedPayloads()` and granted `content://` streams. Arbitrary incoming `file://`, HTML/executable MIME, unsupported URL schemes and credentials in parsed web URLs are rejected. `text`-typed content URIs are correctly treated as files. No URL metadata/network resolution is invoked. Files are streamed in 64 KiB blocks, yielding between reads.
- Android's persisted journal gives intake retries the same UUID until the raw intent is cleared. If the private copy is already committed, recovery does not reopen an expired content-provider URI. A deliberate subsequent share after clear receives a new UUID. SDK's raw API has no per-intent native event identifier: two identical rapid intents arriving while the first copy is still in flight can be coalesced. Do not claim each such event is distinguishable.
- Limits: 4 files, 15 MiB per file, 30 MiB total, 12,000 UTF-16 text units, 8 active private shares. Supported content: text/http(s) URL, JPEG/PNG/GIF/HEIC/WebP/PDF/plain text/Markdown. Native iOS provider support determines available text-file representations; unsupported representation fails explicitly.
- Each private request is pending → bound (scope/action written before dispatch) → completed. Failures stay bound; no automatic downstream retry/action on foreground. Tombstones prevent cancel/completion from being resurrected. The capture receiver's partial workspace imports remain visible in the original identity if later steps fail.
- A malformed native inbox manifest is retained with a visible error rather than deleted automatically. Such a corrupt source may require a future explicit cleanup flow; it is not considered a successful import. Raw Android unsupported content similarly remains pending until replaced/cleared. Do not present these as imported.

## Verification

Executed on synthetic content and fresh temp directories only:

```sh
cd clients/mobile
node node_modules/tsx/dist/cli.mjs --test src/share-intake-model.test.ts src/share-intake-native.test.ts src/share-intake-delivery.test.ts plugins/share-intake.test.cjs
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js src/share-intake-model.ts src/share-intake-native.ts src/share-intake-delivery.ts src/ShareIntakePanel.tsx src/share-intake-model.test.ts src/share-intake-native.test.ts src/share-intake-delivery.test.ts
xcrun swiftc -typecheck -sdk /Applications/Xcode.app/Contents/Developer/Platforms/iPhoneSimulator.platform/Developer/SDKs/iPhoneSimulator27.0.sdk -target arm64-apple-ios16.4-simulator extensions/share-intake/ShareIntoViewController.swift
```

At module handoff: 28 tests passed; full App TypeScript check passed; Swift typecheck passed. Tests cover actual temp file copies/size mismatch/path validation/native staging consumption/restart, Android URI/clear journal, plugin-generated Swift/plist/entitlements, Android activity injection, exact identity/action binding, cancellation tombstones, uncertain receipts, workspace multi-file partial progress, atomic outbox receipt and post-flush replay prevention.

Remaining acceptance owned by root: generated native target build and signed provisioning, actual iOS Safari text/URL + Photos + Files/PDF shares (cold/warm start, cancel and force-close), Android grant-backed text/PDF/multiple-file shares, account switch during upload, App inbox discoverability/identity selector/chat draft preservation, network-off/retry flow. Unit/type checks are not a claim of real-device acceptance.
