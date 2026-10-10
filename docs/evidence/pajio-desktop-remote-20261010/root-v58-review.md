# Desktop control entry v58: independent review and correction

2026-10-10. ZCode completed its final in-flight task at v57. The user then assigned future Web/Desktop work to Codex; no further ZCode implementation was requested.

Root found remaining mutable-data and evidence problems in v57: the ordinary resume POST still read `button.dataset` after awaiting access, the purported real-handler regression built a hand-written handler instead of registering production source, and a direct-pause async continuation did not recheck the active identity. These were corrected before deployment.

v58 freezes resource, generation, pause/pending state, device kind/name and identity/epoch. Both device-list and chat controls share one dispatcher. It checks the current inventory again after the async decision, uses the frozen request fields, opens the correct Android/Linux panel for explicit private return, and preserves ordinary resume only for an explicitly unsupported legacy connector or verified agent-ready state. Unknown access support/generation stays blocked. No server permission, lease, frame or ACK threshold changed.

The regression harness now executes the actual production event registration and generates button datasets from the real device-row renderer. Tests cover normal pause, private return, legacy resume, pending state, malformed access, in-flight identity/device changes, mutable button datasets and the real chat handler. Fifteen entry tests and the full selected Web suite passed: **256 tests, zero failures/skips**. `git diff --check` passed.

| Asset | Frozen SHA-256 |
| --- | --- |
| app.js v58 | fec56f2e069916c21e38febdbb0cf621ad59d8964b52deaa7a1367f640f084c4 |
| index.html | 132e683a5b98b33ff6457eed4e5baced1a03159b56848e61f13b17e79e32a53b |
| remote-device.js v6, unchanged | 9086adb692f09632f4021ece682d714c09a3227aad50cad6bcc0b1bacf127874 |
| pajio.css v22, unchanged | dd5c280cc115c405b3fa657373c00e31d444283139fd6a2bcbbf23106288cdac |

Source verification does not establish deployment or actual UI acceptance. Those are recorded separately in `web-static-deployment.md` and the client acceptance record after activation.
