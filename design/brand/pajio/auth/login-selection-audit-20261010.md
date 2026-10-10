# Login redesign and product-wide interaction states

Status: user selected displayed mock 2 on 2026-10-10. Implementation is underway; production deployment and device acceptance are separate gates. The previous bear-over-form composition is rejected. Native enrollment, recovery, PKCE exchange and infrastructure work proceed independently.

## Scope

Pajio's native iPhone invitation and account creation, web invitation, standard OIDC account sign-in, and a common selection language for native App, web and desktop. Keep day and night themes, accessible contrast, 44-point targets and reduced-motion support. User entry must not ask for a server address. Registration remains invite-only.

Visual mock order is the order displayed in the conversation:

1. `exec-491b7ecc-3c82-45d7-9389-f91260323e97.png`
2. `exec-d5ecd0d7-0a10-4401-a9df-0eff9f92f199.png`
3. `exec-0326a5b1-ece4-4cc9-906e-112ec2c64f36.png`

Files are in `/Users/archieliew/.codex/generated_images/01a0ee05-4561-73e3-8587-49c9ac376cad/`. They are concepts, not functioning or approved screens. All three received the actual current login capture as context through image generation. The mock copy, legal wording and visual fidelity need implementation review; image-generated text is not an approved legal policy.

## Findings

Native App currently has at least six selection treatments: neutral fill, raised white segment, accent border plus tint, border only, text checkmark, and Material tonal button. The current accent is overloaded for links, primary actions, selection and focus. Some selections depend on extremely small neutral surface differences. Web has analogous inconsistency across stylesheet layers.

Selection must be persistent and recognizable without color alone. Focus is where input will go; pressed is transient; selected is a persistent choice; disabled means unavailable; saving or pending means the operation has not yet been confirmed. These states need separate tokens. Do not use the selected token to imply connection, permission or save success.

## Native migration inventory

Paths are relative to `clients/mobile/src`.

| Surface | Existing implementation | Required treatment |
| --- | --- | --- |
| Main navigation | `experience/BottomNavigation.tsx` | Shared selection tokens; preserve tab/selected and interruptible reduced-motion-aware transitions |
| Top-level sections, calendar modes, skills, bookmarks | `Mobile.tsx`, `CalendarPanel.tsx`, `SkillsPanel.tsx`, `BookmarksPanel.tsx` | Common segmented control and appropriate tab or radio semantics |
| Appearance | `AppearancePanel.tsx` | Shared choice row; retain persisted-state confirmation |
| Wardrobe | `WardrobePanel.tsx` | Choice indicator means preview; saved outfit remains an independent receipt |
| Onboarding and import | `OnboardingPanel.tsx`, `ChatImportPanel.tsx`, `ArtifactChoicePanel.tsx` | Single-choice radio and multiple-choice checkbox must differ semantically and visibly |
| Task lists and completion | `TaskListsPanel.tsx` | List selection separate from completion checkbox; preserve completion undo/state |
| Search, diagnostics, health | `NativeSearchPanel.tsx`, `NativeDiagnosticsPanel.tsx`, `HealthHistoryPanel.tsx` | Common chips; add group semantics where missing |
| Brief preferences | `BriefPreferencesPanel.tsx`, `BriefAutomationPanel.tsx` | Replace weak surface-only selection; add accessible selected/checked state for cadence and automatic brief options |
| Calendar sources and recurrence | `CalendarSourceFilter.tsx`, `NativeCalendarPanel.tsx`, `CalendarSeriesPanel.tsx`, `TaskManagementForm.tsx` | Scope/frequency/end controls currently miss state semantics; keep multi-select days distinct |
| Calendar grid | `MonthCalendar.tsx` | Selected date must remain distinct from today and dates containing events |
| Identity switcher | `Mobile.tsx` | Explicit current identity state; do not rely on Paper tonal styling alone |
| Remote shortcuts | `NativeRemoteDevicePanel.tsx`, `experience/primitives.tsx` | Toggle button pressed semantics, separate from action button |
| Permissions and running states | `NativeDevicePanel.tsx`, `NativeActionPanel.tsx`, `NativeRemoteDevicePanel.tsx`, `MemoryEditor.tsx`, `QuietHoursPanel.tsx` | Keep switch behavior; do not treat a user's confirmation as a server acknowledgement |

RN Web compatibility: the local primitive maps `aria-selected`, but the installed web adapter does not map `accessibilityState.checked`; explicit web checked mapping is required for preview parity. Native is not affected by that particular adapter issue.

## Web and desktop migration inventory

Paths are relative to `src/wearing/web` unless noted.

| Surface | Sources | Required treatment |
| --- | --- | --- |
| Cascade and tokens | `style.css`, `life.css`, `comfort.css`, `schedules.css`, `now.css`, `pajio.css` | One final semantic token layer; remove conflicting feature-specific selected colors |
| Main and Today navigation | `pajio.css`, `now.css` | Common state rule, appropriate `aria-current` or `aria-selected` |
| Life navigation and kinds | `life.css`, `comfort.css` | Remove hardcoded competing white/blue backgrounds |
| Appearance and wardrobe | `views.js`, `pajio.css` | Radio must use `aria-checked`, not `aria-pressed`; separate outfit preview and saved receipt |
| Onboarding and chat import | `.ob-choice`, `.ob-tick` | Shared choice tokens and visible radio/checkbox indicators |
| Recurrence and schedule kinds | `schedules.css`, `capture.css`, `life.css` | Harmonized checked state and keyboard focus |
| Identity and notes | `style.css` and view renderers | Current state cannot rely on text hue alone |
| Calendar library | FullCalendar bridge in `life.css` | Map library selected/hover/down tokens; do not modify vendored calendar code |
| Native web host | `mobile-host.css` | Match native tokens without global web cascade leaking into embedded App content |
| Desktop sign-in shell | desktop `connection.css` | Reuse auth state specification and preserve real service errors |

## Implementation contract after visual selection

Use shared `selection.surface`, `selection.ink`, `selection.border`, `selection.indicator`, `focus.ring`, `pressed.surface`, and disabled tokens for both themes. Final values follow the selected mock and contrast checks. Do not force all controls into one shape: navigation, radios, checkboxes, switches and toggles retain their proper interaction model while sharing the same color and motion language.

Introduce lightweight ChoiceRow, ChoiceChip(single/multiple), SegmentedControl and ToggleIconButton presentation primitives. They must not own network mutations, storage transactions or authorization state. Migration order: login and base primitives; navigation/identity/appearance/wardrobe; onboarding and preferences; calendar/lists/remote shortcuts; web/desktop parity. Each stage checks keyboard/VoiceOver semantics, light/dark, disabled/pressed/selected/focus composition, persistence failure and reduced motion.

## Functional baseline retained

Native enrollment is implemented independently of the superseded presentation: verify invite, create account, recover uncertain result without resubmitting passwords, cancel and exchange a one-time PKCE-bound session. Candidate tests passed: 65 backend synthetic cases, 9 disposable PostgreSQL cases; App 840 tests including 16 enrollment state tests, typecheck and direct ESLint. These are build-time/test evidence, not proof of deployment or actual iPhone acceptance of the new flow.
