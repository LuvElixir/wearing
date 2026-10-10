# Dedicated compute capacity preparation — 2026-10-10

This checkpoint records completed cleanup and infrastructure preparation. It does **not** certify a two-person capacity limit or production performance.

## Completed and preserved

- The explicitly authorized QA A/B/C environments were removed: three QA Core VMs, four QA desktop/phone VMs, and three restore-test VMs. Their 20 owned volumes and the exact QA backup set were removed. QA controller routes, memberships, sessions, ownership, invitations and dedicated network bridges were cleared.
- The production controller, the clean Ubuntu template and shared infrastructure were preserved. The original personal Core 1401 reservation and its unknown-operation evidence are unchanged; no Core 1401 VM exists and the old create operation has not been replayed.
- Cleanup completed all 29 recorded phases. The private final proof has SHA-256 `df6ebed2299707b82a1be1b1e56ed5fcbc3b4dbe77784dbf775d04a8bd6ac47b`.

## Capacity accounting now implemented

Root-owned preclaim reservations account for future Core, Linux and Android resources before assignment. Reserved, stopped and unknown outcomes continue to consume capacity. Expiry does not silently release capacity. Existing Core promises are deduplicated, and a durable device claim continues to block duplicate tenant/kind, request or resource bindings even if the VM has not appeared or the local provisioning ledger is missing.

Assignment still requires the existing real account ownership proof. These infrastructure changes do not create a user, membership, pairing, invitation, or automatic redemption worker. Release requires exact evidence that the owned machines and volumes are absent; unrelated promises remain intact.

The reservation/provisioning/transport/power regression selection passed **81 tests**, including independent review and the missing-ledger duplicate-binding reproduction. The repository network startup script also sets `umask 077` so newly created lock files stay private. That script change has not yet been activated on the host.

## Benchmark state at this checkpoint

Four identity-free temporary fixtures were created within the approved resource limit:

| Fixture | Count | Per-machine allocation |
| --- | ---: | --- |
| Linux desktop | 2 | 1 vCPU, 4 GiB RAM, 32 GiB disk |
| Android execution VM | 2 | 2 vCPU, 4 GiB RAM, 32 GiB disk |

All four completed Ubuntu 24.04 cloud-init without reported errors. Required packages, signed official repository responses, and denial of management/private and non-allowlisted egress were checked. Repository addresses were resolved from the actual hypervisor and validated as public addresses; local proxy synthetic DNS addresses were rejected.

A fixed-file runtime cache and clean fixture installers were reviewed. Their tests cover actual HTTP path/method/range rejection, startup readiness, partial activation recovery, exact network rollback, directory ownership/symlink checks and expiry at installation time (**26 tests**). Public runtime asset transfer is in progress. Temporary cache access is limited to the four test bridges; closure must restore the original network before fixture destruction.

## Not yet established

- Single-pair versus two-pair simultaneous desktop/Android frame rate, input acknowledgement latency, CPU/RAM pressure and stability have not yet been measured.
- Synthetic browser/WebView workloads will not by themselves prove compatibility or latency for third-party heavy apps, or simultaneous Core/model task performance.
- The maximum user count remains unverified. No capacity-backed user invitations have been issued, and the personal Core 1401 recovery has not run.
- The redemption-to-provisioning outbox/worker path remains a separate engineering step. No temporary QA account or fixture is being reassigned to the user.

Private operational journals and artifacts stay outside Git. The protected pre-existing personal-compute delivery plan was not changed for this checkpoint.
