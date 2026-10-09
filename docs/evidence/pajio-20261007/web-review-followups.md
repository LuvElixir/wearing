# Pajio Web independent review — 2026-10-07 19:01

Review of the served Web UI while ZCode was implementing Desktop. These findings are not a rejection of the unfinished whole delivery. After the Mac became accessible again, all four findings were sent to the existing ZCode task through its UI at approximately 19:20; the task visibly started a new working turn.

## Fix before accepting the Web/Desktop handoff

1. **Persistent navigation and progress access.** At 1280×720, opening the real existing chat auto-scrolls to the latest message. `.app-header` is `position: relative`, with bounding box top `-1433.5`, bottom `-1346.5`; all five navigation controls, search/settings and the progress entry are outside the viewport. `app.js:scrollToLatest()` scrolls the whole window. Keep navigation and one compact progress entry reachable while reading/typing long conversations, with correct clearance for content and composer; verify both desktop and narrow layouts. Do not add a second progress block inside messages or change the mobile host layout. Screenshot: `web-review-header-offscreen.jpg`.

2. **Wordmark CSS.** The actual `.wordmark .pajio-wordmark` has computed `width:20px`, `height:20px`, `fill:none`. Legacy generic SVG styling overrides the provided width/height/fill attributes. The result is a tiny, hairline wordmark. Add a appropriately scoped rule for the real outlined-path wordmark: stable readable dimensions, filled paths, no inherited functional-icon stroke. The asset is already converted to vector outlines; “outlined” does not mean drawing only the contours. Preserve `html.mobile-host`. Screenshot: `web-review-today.jpg`.

3. **Delegation copy.** The served chat still says `和 Pajio 说说`, `想到哪儿，聊到哪儿。`, `我在，接着说。` and `用「日常」，想做些什么？`. Align the active composer/empty-state guidance with the App's `说一声，我来做…` and concrete task handoff. Historical messages should remain unchanged.

4. **Desktop bundle signing evidence.** ZCode's delivery says the local candidate is ad-hoc signed. Independent `codesign --verify --deep --strict clients/desktop/src-tauri/target/release/bundle/macos/Pajio.app` reports `code has no resources but signature indicates they must be present`. The inner arm64 executable's linker signature does not establish a valid app-bundle signature. Produce and verify a complete local ad-hoc bundle (no Developer ID, notarization or deployment requested), or explicitly describe it as unsigned/unverified. The Pajio display name and preserved `io.luckyloading.wearing.desktop` identifier were independently confirmed.

## Observations that passed

- The actual Today page reads current live activity (`18:59`), with one genuine saved-but-unstarted item and real returned content. No fake auto-generated brief is presented.
- No console errors/warnings in this browser session.
- Day palette, card separation and five-entry navigation are present when the viewport is at the top.
- Night appearance and the eight outfit assets render. The original system theme was restored through UI and `aria-checked=true` confirmed. No outfit was saved by the independent review.

ZCode's first delivery report is now present at `docs/pajio-zcode-delivery-2026-10-07.md`. Its declaration of completion does not close the findings above. A follow-up implementation and independent verification are pending.

No product business message/task was sent during review. The engineering follow-up was delivered to ZCode; this document does not yet establish that the findings are fixed.
