# Pajio login and interaction states — visual acceptance

Date: 2026-10-10. Scope: the user's selected second login direction, implemented native entry, public invitation/identity pages, and shared selection-state presentation. This is visual acceptance, not a claim of completed account provisioning or server capacity.

## Evidence and normalization

- Source visual truth: `docs/evidence/pajio-auth-design-20261010/selected-direction-2.png`, copied byte-for-byte from the selected generated result `exec-d5ecd0d7-0a10-4401-a9df-0eff9f92f199.png` (853 × 1844 pixels).
- Full-view combined comparisons: `http://127.0.0.1:8891/compare` (source + actual invitation HTML) and `http://127.0.0.1:8891/compare?target=native` (source + actual NativeEnrollmentPanel compiled for the browser). Both were captured and inspected together through CUA in this task, including a final post-fix comparison. These browser captures are recorded in the task, not falsely represented as saved PNGs.
- Each comparison panel is 390 × 844 CSS pixels; outer comparison viewport is 860 × 930, deviceScaleFactor 1. The source is scaled into that same panel. It contains no device bezel or recreated system chrome. State: day, logged out, invitation selected, empty field, no focus. Source raster antialiasing is not used as a font-geometry requirement.
- Actual installed iPhone screenshots: `docs/evidence/pajio-auth-design-20261010/iphone-night-login-final.png` and `iphone-oidc-night.png`, each 1260 × 2736 device pixels. Device: physical iPhone Air, iOS 27.0. Native system bars and the system authentication sheet are retained. These night captures verify runtime presentation; they are not treated as a same-theme pixel comparison against the day source.
- Installation/signature/source hashes and verification limits: `docs/evidence/pajio-auth-design-20261010/iphone-install.json`.
- Additional rendered states: local native harness `http://127.0.0.1:8919/`, `?mode=night`, `?screen=states`; embedded stylesheet fixture `/embedded.html?mode=night` and day; actual public `/join`; actual Keycloak OIDC page reached via the public entry and from the installed iPhone. Fixture content is explicitly synthetic and does not stand for an authenticated product session.
- Focused inspection covered wordmark/header, tab baseline and underline, field/focus/error borders, field-to-button alignment and the identity language row. At the normalized scale all labels were readable; the full comparison and separate control-state captures exposed these regions without requiring an image crop.

## Findings and comparison history

1. **P2 — wordmark and vertical rhythm drift (resolved).** Initial render enlarged the wordmark and placed the form too low. Corrected the wordmark to 56 × 24 and the header/navigation gaps. Reopened the combined source/implementation comparison at 390 × 844; hierarchy and left alignment now follow the chosen direction.
2. **P2 — heading scale (resolved).** Initial 28 px title weakened the source hierarchy. Corrected the standard title to 32 px bold, with a deliberate smaller narrow-screen fallback. Post-fix combined comparison shows equivalent title emphasis and wrapping.
3. **P2 — focus remained after entry switch (resolved).** On the physical iPhone, focusing the invitation field then switching to existing-account and back retained a focus ring on a departed input. Added focus reset on entry/state transitions, rebuilt the signed Release, reinstalled and repeated the exact interaction. The returning invitation field is neutral until focused again. Final screenshot and the separate focus-delta hash record the corrected build.
4. **P2 — inherited identity-provider layout (resolved).** The actual OIDC page retained a blue header rule, normal-weight heading, oversized language layout and a wider primary button. Scoped theme overrides removed that rule, restored 700/32 typography, made the language selector secondary, and aligned field/button widths at 360 px in the inspected desktop view. The public gzip cache entry was refreshed after a hash-checked stylesheet replacement; a fresh browser and physical iPhone loaded the corrected page. Authentication templates and security behavior were not replaced.
5. **P2 — embedded night surfaces (resolved in source).** The review switcher parent and schedule form inherited light surfaces. Corrected semantic surfaces and verified both themes using the actual stylesheets. A separate preview issue (missing native canvas beneath a transparent WebView) was fixed only in the fixture. The product's native AppBackdrop provides the canvas. This remote-served CSS is not included in the authentication deployment and awaits the Core surface release.

No actionable P0/P1/P2 visual finding remains in the inspected login or shared state presentation. The pending Core deployment is tracked as a release boundary, not hidden as completed work.

## Required fidelity surfaces

| Surface | Result |
| --- | --- |
| Fonts / typography | System sans with native Chinese fallback, bold title, quieter supporting copy and distinct label hierarchy. Normalized comparisons preserve title wrapping. Real iPhone labels remain legible. |
| Spacing / rhythm | Flat canvas, left wordmark/title/form alignment, generous upper spacing, short selected underline and no enclosing hero card. Main fields/buttons use 52 pt for touch comfort; the resulting small downward shift versus the raster's approximately 48 px controls is intentional. |
| Colors / tokens | Canonical values in `design/brand/pajio/interaction-tokens.json`: warm off-white day and graphite night, muted blue-gray action/selection. Selected, pressed, focus and disabled remain distinct. Recorded day text/muted/action contrast: 13.82/4.90/7.55; night: 14.65/8.95/8.66. |
| Image / asset quality | Reuses the existing approved Pajio SVG wordmark, as expressly requested in the prior brand work. No generated hero asset is required by the selected design. No raster screenshot is used as a form, background or recreated device chrome. |
| Copy / content | Keeps the selected welcome and supporting message. Native placeholder permits typing as well as paste. Helper accurately says verification precedes account creation. The generated reference's legal acceptance footer was not adopted as approved legal text; public footer is neutral, native footer omitted. |

## Interaction acceptance

- Native: invitation/existing-account entry state, independent focus, empty-field inline validation, official system authentication window, and cancellation back to the App were visually exercised on the installed iPhone.
- Synthetic harness: invitation and account fields, pending/error/recovery presentations, password visibility control, and shared choice/tab/switch states were exercised without creating a real account.
- Web/desktop source: radio/checkbox/tab semantics, keyboard navigation, reduced-motion rules, current selection and focus use the shared contract. Test fixtures verify style behavior at narrow and wide widths; they do not establish live authenticated Core behavior.
- Build/typecheck/lint and targeted/full suite evidence is recorded separately in the source and release evidence. These checks supplement, rather than replace, the visual comparison.
- Console review separated old harness errors from the final run: the early RN-Web fixture lacked its `global` compatibility alias and forwarded a native-only `accessible` prop; the fixture was corrected. No error entry was recorded after 09:45 UTC in the inspected tab, including the final public page visit. Public `/join` was also checked at an observed 390 × 844 viewport, DPR 1, without horizontal overflow.

## Remaining acceptance boundaries

- No real invitation redemption or new personal account was completed. Provisioning a full Core + Linux + Android bundle and deciding invite capacity remain separate outstanding work.
- A software-keyboard layout run on the physical iPhone is not recorded as passed; Device Hub used a hardware keyboard path. No real password was entered.
- Shared Web/desktop and mobile-host source styles still require their own Core release and authenticated product-page smoke. Only the native installed build and authentication service release are established here.
- P3 follow-up: repeat larger accessibility text sizes and the on-device software keyboard before wider distribution.

## Implementation checklist

- [x] Selected reference resolved and both implementations rendered alongside it at equal dimensions.
- [x] Wordmark, typography, spacing and token drift corrected and recaptured.
- [x] Focus transition fixed and verified on the reinstalled iPhone build.
- [x] Actual identity-provider theme checked on the physical iPhone.
- [x] Release evidence distinguishes preview, installed UI, deployed authentication and unverified full registration.

final result: passed
