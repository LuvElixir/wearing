# Public privacy/support publication — 2026-10-10

The approved three-file control gateway overlay is installed: `cloud/public_pages.py`, `cloud/auth_pages.py`, `cloud/gateway.py`. Final source hashes, protected file/configuration checks and service metadata passed the fixed manifest guard. Only the gateway restarted; registration, identity and the disabled activation worker retained their original PIDs/state. No account registration, authenticated acceptance or database change was performed by this release.

Public URLs are [Privacy](https://pajio.luckyloading.com/privacy) and [Support](https://pajio.luckyloading.com/support). Final anonymous HTTP checks returned 200 for both and `/join`, 401 for `/auth/session` and `/auth/provisioning`, and 303 from `/` to `/join`. Responses include `no-store`, with no `public`, `max-age` or `s-maxage` caching directive. The independent `/privacy` observation recorded 11 consecutive 200 responses across 100.98 seconds.

The original 80-request switch observation is retained: 24 × 200, 1 × 502 and 55 × 429. The synthetic `/join` probe reused one cookie binding every two seconds and reached the existing 24-per-600-second admission limit. These were GET observations, not failed user registration attempts. Future availability probes should use static public information or health endpoints.

The activation command initially reported an unknown result because its readiness assertion compared `Cache-Control` to the exact string `no-store`; middleware correctly returned merged `private, no-store`. A separate read-only reconciliation verified directive semantics, exact deployed source hashes, the new gateway process and all protected state. The original activation unknown/intent remains intact; activation was not replayed and the gateway was not restarted a second time.

Private evidence: `public-pages-release-20261010/deployment-final-proof.json`, SHA-256 `791c0a5b6254d305d303dcc031b4c5deaa8d207be24cc5712a7a02977cec4de8`; fixed manifest `069f77eb63a424016599c4ea19196378627e66059d85fd7ed6b8393c9441a09e`. These information pages disclose the reviewed service chain; publication alone does not implement explicit third-party AI consent.
