# Product source review — 2026-10-07

This private review snapshot contains the current working-tree product implementation, including untracked mobile and desktop source. It is broader than the 2026-10-03 source snapshot currently referenced in the older README.

## Read first

- `PRODUCT.md` and `docs/plans/product-brand-ux-strategy-2026-10-07.md`: product definition and current proposed brand/UX direction. Proposals are not all implemented or market validated.
- `clients/mobile/src/Mobile.tsx`: native navigation shell and primary state wiring.
- `clients/mobile/src/Conversation.tsx`, `RetainedConversation.tsx`, `src/wearing/web/mobile-host.js`: native/retained WebView conversation bridge.
- `clients/mobile/src/VoiceComposer.tsx`, `useVoiceInput.ts`, `voice-stream.ts`, `src/wearing/speech.py`: voice interaction and ASR integration.
- `clients/mobile/src/TodayPanel.tsx`, `AgentTaskList.tsx`, `ActivityReview.tsx`: briefings, tasks and return/progress experience.
- `clients/mobile/src/PersonalPanels.tsx`, `PersonalHub.tsx`, `NativeConnections.tsx`: memories, connections and settings.
- `clients/mobile/src/appearance.ts`, `app-theme.tsx`, `navigation-icons.tsx`, `PajamaBear.tsx`: current visual system; bear is implemented, optional/hide behavior is only proposed.
- `src/wearing/web/`: full web and App-hosted conversation UI, shared server-rendered behavior.
- `src/wearing/activity.py`, `service.py`, `store.py`, `goals.py`, `artifacts.py`, `confirmations.py`: truth boundaries for accepted work, progress, result and user decision.
- `clients/desktop/`: Tauri client frontend and Rust shell.
- `tests/` and `clients/mobile/src/*.test.ts`: synthetic regression tests.

## Review questions

Design for a mature, welcoming personal execution assistant. Review actual code rather than assuming every roadmap promise exists. The primary success criterion is that a user can give an instruction, leave confidently, and immediately understand what happened on return. Challenge excessive decoration, the brown/cream palette, mascot dominance, unclear actions, duplicate progress, and chat friction. A single four-point star is the user's preferred symbol; avoid multi-sparkle magic icons. Evaluate naming and mascot necessity independently from founder taste. Distinguish public market evidence, hypotheses and real validation still needed. Recommend precise IA, interaction, typography, spacing, day/night tokens and phased changes. Do not invent supported integrations, paid membership, completed work or user data.

## Completeness and privacy

This contains application and backend code, dependency manifests/locks, included UI assets, tests, deployment source and selected product contracts. Runtime state, real connection settings, keys, databases, user recordings, private QA screenshots, build outputs and installed dependencies are excluded. Existing development state and Git index are untouched. `SOURCE-REVIEW-MANIFEST.json` records per-file source and export hashes, coverage and limitations. One architecture-document example name is replaced with a synthetic label only in this export.

Use the existing PRIVATE repository. Access through an authenticated GitHub connector or attach the prepared review bundles; a bare private URL may not be readable by a separate model session. Do not make the repository public to resolve access.

No application behavior or build has been changed by this export. No source snapshot test result should be inferred from the application's prior local test reports.
