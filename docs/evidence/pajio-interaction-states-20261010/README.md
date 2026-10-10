# Pajio Web / desktop interaction states — 2026-10-10

Candidate only; no deployment or account operation in this verification.

The canonical palette is `design/brand/pajio/interaction-tokens.json`, from the user's selected second design. Web main product and the desktop connection shell use its exact day/night values. The mobile-host WebView remains outside every Pajio selector. Auth pages and native App are owned by the parallel implementation.

## Coverage

- Primary navigation, review navigation and calendar views: strong selected ink and a 20 × 2 px indicator, with no selected white card.
- Appearance, wardrobe preview, initial preferences, import author choice, record kind, repeat weekdays and schedule kind: subtle selected surface with visible check/radio/checkbox.
- Current identity and current note retain explicit text/check semantics. Task-completed checks use the shared indicator token.
- FullCalendar selected/hover/pressed/focus color bridge is mapped without editing the vendor.
- Keyboard focus is a separate 2 px ring, 2 px offset. Pressed and disabled controls have semantic surfaces/ink. Reduced motion suppresses transforms and transitions.
- Wardrobe now uses `role=radio` + `aria-checked`, one Tab stop, arrow/Home/End selection; preview remains distinct from acknowledged save. Appearance has radiogroup semantics, keyboard navigation and focus restoration after repaint. Calendar unselected buttons explicitly expose `aria-pressed=false`.

## Verification

`node --test tests/pajio-interaction.test.cjs tests/pajio-web-ui.test.cjs tests/onboarding-ui.test.cjs tests/test_web_motion.cjs tests/development-connection-ui.test.cjs` — 49 passed.

A real Chromium instance rendered a **static interaction fixture**, using all product stylesheets in their actual order. These are stylesheet screenshots, not an authenticated product session or fictional service results. Day and night screenshot files are in this directory.

Computed verification:

- Navigation background transparent; selected text day `rgb(49,77,89)`, night `rgb(208,225,230)`; indicator 20 × 2 px.
- Selected choice background day `rgb(231,236,238)`, night `rgb(41,59,67)`.
- Disabled choice opacity is 1 and uses the contract's disabled ink/surface; the old double fade was removed.
- Focused unselected choice remains `aria-pressed=false`, with a 2 px outline and 2 px offset.
- Widths 1120 px and 390 px have no horizontal overflow in the fixture.
- Adding `mobile-host` leaves the new `--selection-surface` unset, confirming style exclusion.
- The actual desktop connection HTML was loaded locally in Chromium at 720 px and checked in both OS color schemes; canvas/ink/disabled colors match the contract and no horizontal overflow occurs. No Tauri login was invoked.

Limitations: a logged-in full product smoke, real desktop WKWebView and native App acceptance belong to the release check. The fixture does not establish service functionality. No backend authorization or business state machine was changed.
