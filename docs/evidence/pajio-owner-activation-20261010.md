# First owner activation and recovery — 2026-10-10

The owner completed native invitation registration on the physical iPhone. The
control database confirmed the intended member, ownership, bundle and activation.
This is an actual account, not a QA account or fabricated onboarding completion.
The password and invitation stay outside the repository.

The first activation exposed two operational problems before device acceptance:

- Linux first boot had actually succeeded, but its activation entered review.
  The running VM, exact owner, full configuration and retained `boot_sent`
  journal were verified before a compare-and-swap returned the same activation
  to inspection. No clone or start was replayed. The precise original exception
  was not retained by the worker's sanitized log, so its cause is not confirmed.
- Installing the cold Ubuntu desktop dependencies took 1,423.69 seconds.
  Cloud-init eventually reported `done` with no errors. The subsequent runtime
  installer spent a long time downloading Firefox and entered review at 22:09:40
  Asia/Shanghai. The original failure and partial download were retained.

The exact Firefox 157.0.1 build 1 AMD64 and Chinese language packages were fetched
from Mozilla's official repository through the Mac, compared with SHA-256 and
sizes from the guest's signed APT index, transferred through the existing trusted
SSH route and verified again on the same guest. They were placed in the APT cache;
no repository signature check or host-key check was disabled. The two downloads
took 11.2 and 1.8 seconds locally. The runtime had already exited; no running
installer or package manager was killed.

Before returning this second failure to the existing worker, recovery verified
the exact VM configuration, owner, unpaired state, artifact journal, available
installation lock, cached package hashes and lease-free activation preimage. The
CAS changed only that activation back to inspection. The original runtime
artifact and device allocation remain unchanged. A recovery receipt is not a
claim that Linux, Android or remote control is ready.

## Operational changes

The host's stale test-VM monitoring and backup allowlist was replaced with one
private, root-owned configuration fingerprint scope. Monitoring checks the
current full guest identity before running service probes. Scope changes reset
the continuous-health interval while preserving earlier failures. Tests cover
changed owners, disks, VM reuse, unexpected locks, malformed scope files and
missed health samples.

The daily backup job initially covers the running control service and owner Core.
The Linux guest is monitored while provisioning but is not yet included in that
backup job. The Android guest will be added only after verified provisioning.
The first control snapshot completed at 22:05:41; the owner Core snapshot
completed at 22:16:41. Both use the storage reserve and archive privacy hook.
The 3,822,477,593-byte control archive and 2,296,441,775-byte Core archive passed
`zstd -t`; root ownership, private directory/archive modes and SHA-256 were
recorded privately. These local snapshots are not offsite disaster recovery or
a restore drill.

## Mobile follow-up

Build 3 keeps reading successful provisioning status while the app is in the
foreground, at no faster than 15-second intervals. It still pauses in the
background, fences account changes, stops on terminal status and stops after
three failed reads. It does not replay registration or provisioning mutations.
The original bounded polling behavior remains for registration.

Mobile validation: 896 tests, typecheck and focused lint passed. Host scope and
backup validation: 16 tests passed. The initial staged native build encountered
missing staged extension files and then a copied absolute compiler-cache path;
all 398 tracked mobile files were staged, native files regenerated, and a clean
derived-data build succeeded. Build 3 strict signature verification passed.
On October 11 the reconnected physical iPhone initially needed its existing
pairing refreshed. Build 3 then installed and launched successfully, preserving
the owner's authenticated session. Device Hub showed Core and Linux ready and
Android needing review; a manual status refresh after recovery resumed the live
preparation display. Archive and App Store export also succeeded. Upload and
full remote-control acceptance remain separate steps.

Linux finished runtime installation, enrollment and readiness verification after
the cache recovery. Android subsequently reached the same `boot_sent` review
condition even though its VM was running and cloud-init finished without errors.
On October 11, an owner/configuration-bound CAS returned that lease-free event
to inspection. No start or clone was repeated. Android runtime and enrollment
are still being verified at this checkpoint.

## Release consequence

Cold installation during a user's first signup is too slow for the intended
experience. Additional invitations must wait for a prepared, identity-clean
dependency image/cache and measured activation time, plus complete device and
remote-takeover acceptance. Do not derive additional capacity from this single
owner's registration or label a recovery, build, upload or service health check
as external-test readiness.
