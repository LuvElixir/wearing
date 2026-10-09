# Comfort implementation record · 2026-10-05

This is an existing-world refinement, extracted from the effective source cascade. It is not a concept seed or a new quality card. `DESIGN.md` owns reusable tokens; this file keeps contextual geometry and supersession evidence. No new browser/device acceptance is claimed by this documentation pass.

## Authority and scope

- `.impeccable/surfaces/comfort.md` records delegated selection of comp A, the later one-primary-action correction, and the explicit folded-W selection.
- `comfort.css` is loaded after `style.css`, `life.css` and `capture.css`; its effective rules supersede their old layout descriptions.
- `comfort.js` owns interruptible motion, disclosure and selected-kind label synchronization. `Mobile.tsx` implements equivalent disclosure with native state.
- The established 3D character is the sole in-product IP for greetings, conversations and feedback. The later user decision supersedes earlier avatar guidance: the portrait master is `design/character/3d-20261005/companion-portrait-master.png`, faithfully generated from `src/wearing/web/character-poster.png`. The runtime copies are identical 512px transparent PNGs at `src/wearing/web/companion-portrait.png`, `clients/mobile/assets/companion-portrait.png` and `clients/desktop/frontend/companion-portrait.png`. Existing motion files are unchanged. Retired runtime flat avatars are archived in `.wearing/qa/comfort-20261004/retired-2d/`; historical design assets and examples remain preserved. `design/icons/folded-w/wearing-symbol.svg` is the approved application identifier; its README defines wrappers, masking, safe area and variants.

## Current layout and component geometry

| Surface | Current implementation |
| --- | --- |
| Web ≥1000px | 220px fixed left rail; five destinations, content max 1120px, fluid 24–64px horizontal padding; editor column 330px. |
| Web 641–999px | Top navigation; 28px content padding; editor column 300px. Existing ≤700px editor stacking and day-column behavior still apply. |
| Web ≤640px | Fixed five-item bottom navigation; 57px targets plus safe-area padding; page bottom reserve 84px plus safe area; 20px content padding. |
| Web capture | 28px radius, 23px 24px 16px inset; phone 24px radius, 19px 18px 14px inset; 16px input at 1.8 line height; auto-height capped at 240px. |
| Web daily groups | 24px radius and 12px 23px 18px inset; phone 22px radius and 10px 18px 16px inset. These group day/tasks/notes, not every record. |
| Native mobile | Four destinations; 58-unit bottom targets. At 840 units: 190-unit rail, 48-unit navigation targets, content max 980. |
| Native capture | 24-unit radius, 20-unit inset, 17/28 input, 104–240-unit input height. Plus target 44; save target at least 48. |
| Native record | 16/25 title, 12/20 metadata, 14/23 excerpt; 8-unit target radius and 52-unit minimum target height. |
| Desktop connection | Same platform reading stack; 28px heading stays contextual to this entry page; field 52px minimum height and button 48px, both 16px radius. |

The former always-visible media toolbar and record-kind segment are superseded by plus disclosure. Save is the sole filled primary capture action. Default kind is note. Changing kind closes optional choices unless recording; a live recording must keep its stop control visible. Web restoration updates the small kind label from actual `aria-pressed` state via a mutation observer. The placeholder uses the existing muted token.

## Reuse evidence and classification

| Value / role | Evidence | Classification |
| --- | --- | --- |
| Cobalt, paper, ink, muted, light blue | Existing web root tokens, native theme and desktop connection tokens | Incumbent palette, preserved. |
| Rail cool gray | Web wide app header and native rail share `#f3f4f8` | Reused neutral token `rail`. |
| Group edge | Web today/recent sections and native section share `#ebedf2` | Reused neutral token `section-line`. |
| Focus border | Existing web composer/goal input, Comfort capture and desktop connection use `#91a2e3` | Existing focus material `focus-border`, not a new accent. |
| Repeated heading ramp | Web life heading applies across today/calendar/tasks/notes: clamp(28px, 2.5vw, 34px), with 27px phone override | Update `life-heading`; system UI reading typography is incumbent in this product. |
| 8px record target corner | Web record and note targets; native `recordBody` | Reused `record-target` geometry; does not make every panel small-radius. |
| 28/24px capture, 24/22px groups | Repeated writing/group surfaces across breakpoints and native composer/sections | Role-specific radius relationships, reusing existing 28/24 and adding the repeated 22 step. |
| Fold pale blue | Two master SVG fold paths and generated app wrappers | Approved brand asset material `symbol-fold`, not UI emphasis. |
| Other nearby border grays, 7px check corner, 15px nav corner, asymmetric sheet corners | Individual CSS contexts | Keep literal in component/surface evidence; no extra global token. |
| Desktop 28px connection heading | One connection screen | Contextual geometry; not a new display token. |

## Motion and depth

Web controls respond in 140ms with a 0.98 press scale. Entry uses 240ms and 7px translation; dialog exit uses 160ms and 8px translation. Existing animation is canceled before replacement. Native page entry uses 240ms cubic-out. Reduced motion skips spatial transitions, press scaling and backdrop blur. Native press feedback remains opacity 0.65.

Writing surfaces use very light ambient shadow; focused writing gains a low-opacity cobalt halo. The settings sheet has a stronger environmental shadow. Daily record groups and native capture remain primarily tonal/bordered. Focus rings and raw/organized/local/server state labels remain functional feedback.

## Deliberately not generalized

No invented display face, new decorative accent, arbitrary one-off gray, exact greeting placement, OS mask geometry or historical prototype logo is promoted to a house rule. The documented system-font titles are established daily reading roles; the independent WearingGreeting and outlined wordmark still own the brand display roles. Remaining implementation discrepancies must be assessed as defects or local geometry, not converted into tokens merely to silence the design hook.
