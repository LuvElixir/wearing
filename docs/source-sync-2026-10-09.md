# Pajio source sync — 2026-10-09

This update collects the current App, web, desktop, agent runtime, deployment
scripts, tests, documentation, and required design assets into one source version.
`SOURCE-SNAPSHOT.json` remains the historical October 3 inventory; Git identifies
this version and its contents.

## Validation before publication

- Python: **1,641 passed, 31 skipped**. Environment-dependent checks retain their
  existing skip conditions; three upstream deprecation warnings remain.
- Mobile: TypeScript and source ESLint passed; **740 source tests** and **4 native
  configuration plugin tests** passed.
- Web JavaScript: **226 tests passed**.
- Mobile and desktop package locks, local imports, native configuration, bundled
  icons, character assets, and license notices were checked for inclusion.
- Gitleaks v8.30.1 scanned the staged source tree. Its 16 findings were reviewed:
  five source hashes, three synthetic QA request keys, one synthetic fixture key,
  and seven other test values. No confirmed live credential was found.

The two regression failures encountered during preparation were fixture errors:
the browser VM lacked `window`, and a loopback bridge test selected cloud mode.
The latter now checks both local access and cloud rejection without a trusted
owner, including forged scope headers. Production authentication was not relaxed.

## Publication boundaries

Local credentials, databases, pairing material, runtime logs, browser sessions,
generated previews, device acceptance captures, and research screenshots are
excluded. Required product artwork, synthetic test fixtures, and third-party
license notices are retained. A development account name was anonymized in the
public acceptance record.

This is a source sync. It does not establish production deployment, external App
distribution, or fresh native-build acceptance. Current delivery gaps are recorded
in [the public-readiness audit](evidence/pajio-public-readiness-20261009/product-gap-audit.md).
