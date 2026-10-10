# Bundle activation schema and service deployment

The reviewed control-plane migration to `wearing_control_0004` completed. The immutable bundle binding, atomic authenticated-redemption outbox and generation-fenced worker API are installed. This evidence covers deployment and permissions; it does not claim a new real user has received working devices.

- Frozen manifest SHA256: `549b47cc9aaab44edff43b3e8321c486c64e289efd85f8e68a9139670a9d26ed`.
- Independent database dump and old source/config preimages are retained under the root-private release backup.
- Actual production web, registration, operator and activation database logins passed boundary verification. The activation login was also verified while running as its dedicated non-root OS account.
- Gateway PID49550 and registration PID49548 remained active and unchanged at the final metadata check. Empty invalid requests were correctly rejected; unauthenticated provisioning returned401.
- Activation service is installed, inactive and disabled (PID0). No worker tick, provider keys, plans or resource mutation occurred in this release.
- 180-second public window:97 samples. `/auth/session`:84×401 and1×502. `/join`:11×200 and1×502. Both502 occurred in the stop/restart window; subsequent samples stayed normal for about163seconds. The window was not uninterrupted.

Validation: prior75-test database/auth/worker regression; final35-test database/worker/pipeline run including real disposable PostgreSQL; eight private release failure-path tests. Provider behavior in these tests is synthetic.

Unknown mutation outcomes are observed without replay. Before migration commit, exact old source rollback is supported. After0004 commits, old0003 source and destructive database restore are refused; only reviewed completion/forward repair is appropriate. The inactive activation principal is retained if precommit source rollback is needed.

Private detailed evidence: `.wearing/on-prem/20261009/bundle-activation-release-20261010/deployment-summary.json` and the hash-bound backup/apply/status receipts. No secrets or business rows are included in this public summary.

## Large-file delivery follow-up — 2026-10-10

The device delivery module now hashes uploads as streams on both the controller
and receiving guest, so the 873 MB Android image does not have to fit inside the
worker's memory limit. A single-module release was deployed after exact
preimage checks and private backup; the actual activation OS user verified its
import. The installed SHA256 is
`10bb8173ebfed567b7f655bfee52aeb8cbdaab40cfb5871ab38edcb17fe9fb87`.

Gateway and registration kept their original PIDs; no service restart occurred.
Activation stayed disabled and inactive. Eight release failure-path tests and
the real 873 MB bounded-memory hash proof passed. This follow-up did not install
the product runtime bundles or exercise a provider mutation. Private proof:
`.wearing/on-prem/20261009/delivery-streamhash-release-20261010/deployment-summary.json`.
