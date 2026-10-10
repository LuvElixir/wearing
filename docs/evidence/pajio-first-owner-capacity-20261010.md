# First-owner capacity evidence — 2026-10-10

The current admission policy permits one complete user bundle with a 1-vCPU / 2-GiB Core, 2-vCPU / 4-GiB Linux desktop, and 2-vCPU / 4-GiB Android phone. This is a **configuration admission limit, not a measured hardware maximum**. Two such bundles, the 1-vCPU control VM, and the 2-core host reserve would commit 13 vCPUs against 12 physical cores. The host exposes 20 logical CPUs; committed vCPUs do not equal actual CPU use. The policy was not relaxed for these results.

## Single-pair measurements

Two independent synthetic Linux-and-Android pairs each completed a 150-second session: 30 seconds of warmup followed by a 120-second measurement window. Each guest had 2 vCPUs and 4 GiB RAM. The receiver was an aiortc test client using H.264 and RTX through TURN; actual selected relay candidates were verified. One Core ran in the background. These samples did **not** exercise simultaneous Core/model tasks, heavyweight third-party Android apps, or the native iPhone receiver.

| Run | Device | FPS / cap | Tap ACK p95 | Scroll ACK p95 | Largest observed decoded-frame gap | Guest CPU p95 |
|---|---|---:|---:|---:|---:|---:|
| Single 1 | Linux | 14.70 / 15 | 188 ms | 142 ms | **2,844 ms** | 61.54% |
| Single 1 | Android | 22.42 / 24 | 257 ms | 515 ms | 511 ms | 65.84% |
| Single 2 | Linux | 14.68 / 15 | 179 ms | 145 ms | **2,162 ms** | 61.42% |
| Single 2 | Android | 22.47 / 24 | 252 ms | 520 ms | 535 ms | 64.36% |

Android scroll ACK includes the requested 250-ms gesture. Every successful session verified actual synthetic UI progress for 20 taps and 10 scroll requests; an ACK alone was insufficient. Guest CPU percentages are normalized to each guest's two vCPUs.

Linux's multi-second decoded-frame gaps remain an experience limitation. Passing the unchanged 3-second video watchdog and achieving near-cap average FPS do not establish consistently smooth control. The longest Linux gap contained fresh metadata updates, but the evidence does not identify a definitive network or decoder root cause.

Host CPU p95 was 13.52% and 13.03% across its 20 logical CPUs; minimum available memory was 12.04 and 11.51 GiB. Host CPU, memory, and I/O PSI `avg10` remained zero, while guest CPU PSI `avg10` maxima ranged from 32.79% to 40.66%. Host headroom does not erase guest pressure or visible stalls.

## Dual-pair failure and capacity boundary

The dual-pair attempt failed before either Linux peer returned its first answer. The shared stop signal cancelled both Android peers before input. There was no valid simultaneous steady-state media window, so this attempt supports **no two-user performance conclusion**. The early failure was retained under a fixed error code; its root cause remains unconfirmed.

The failed raw report's zero FPS and **120,000-ms gap are missing-frame sentinels**, not observations of a 120-second playback stall. All peer process groups and synthetic workloads were subsequently confirmed stopped. Failed receipts were preserved; no uncertain operation was replayed or watchdog threshold relaxed.

First-owner acceptance still requires actual invitation redemption, independently owned devices, and native iPhone takeover/return. A second-user claim requires two independent Cores and both device pairs under concurrent realistic task and UI workloads, followed by a reviewed admission decision. These synthetic samples do not establish the hardware's maximum user count.

## Fixture cleanup and retained services

The four identity-free fixture VMs, their disks, dedicated bridges, and resource reservations were removed under the reviewed cleanup. Independent verification found only the control VM, personal Core, and clean template remaining. Personal Core and relay service PIDs, ten checked Core source hashes, and the private activation-network rules were preserved; the authenticated runtime health probe returned HTTP 200 with owned/reachable status.

At the cleanup snapshot, remaining commitments were 2 vCPUs and 5 GiB RAM, with no Linux or Android device slots reserved. This snapshot precedes subsequent first-owner provisioning. Two successful shutdowns initially had unknown confirmation receipts; exact read-only task/configuration reconciliation preserved those originals without repeating shutdown. A separate verifier's incorrect global firewall-rule count was corrected to check one rule in each of the two intended tables; no network mutation was needed for that correction.

Retained evidence digests (raw receipts remain private and are not shipped with this document):

- Measurement summary SHA-256: `4dffc73e14bdf945effc101400bf64bc617079b94c791f349ec23d01ec8d2bf4`.
- Final independent cleanup verification SHA-256: `7661bc43b0f99baa5ccee2d853a64756d8e5e35188d556f1947fe60e55e3e30c`.
