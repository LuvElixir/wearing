# Pajio identity theme

Extends the pinned Keycloak 26.7.4 `keycloak.v2` theme. No authentication templates, action URLs, validation, password logic or MFA protocols are overridden. Custom CSS and a local input-focus script present the same Pajio bear used by the native app and invitation portal. The script never reads or stores password values. Reduced-motion preference removes pose transitions. No external fonts, trackers or image hosts.

Install this directory under the distribution's `themes/pajio` directory and set only the `pajio` realm's `loginTheme` to `pajio`. Back up the previous realm theme field and deployed file hashes before activation; verify discovery and actual rendered login HTML afterwards. Restoring the prior `loginTheme` rolls back the presentation. Keep `directAccessGrantsEnabled=false` for `pajio-app`.

Shared presentation sources: `src/wearing/web/auth/auth.css`, `auth.js`, `bear-resting.png`, `bear-privacy.png`; copies here must remain byte-identical. Static image masters were generated with the built-in image tool from the approved Pajio character, then exported at 672px for the UI.
