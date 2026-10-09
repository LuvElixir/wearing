# Dedicated device enrollment

This is an operator path for a **new, owned, runtime-verified** Linux or Android
guest. It is not an HTTP endpoint, an agent tool, or evidence that an existing VM
was cloned from a reviewed clean template.

## Inputs and integration

`wearing.cloud.device_enrollment` exposes:

```python
settings = EnrollmentSpec.model_validate_json(spec_file.read_text())
adapter = SSHEnrollmentAdapter(
    config=ssh_config,
    sources=operator_sources,
    allow_apply=True,
)
enrollment = EnrollmentBook(provision_book)
plan = enrollment.plan(request_id, settings, adapter)
# Operator reviews the fixed scope, targets, artifact and network binding.
result = enrollment.enroll(
    request_id, settings, adapter,
    reviewed_sha256=plan["plan_sha256"],
)
current = enrollment.inspect(request_id, adapter)
```

The provisioning ledger must contain a `staged` device and `network_staged`
bootstrap record, plus a fresh authoritative private-account proof. Owner
objects match exactly across the ledger, root-owned guest marker and bootstrap
manifest. The guest address and relay endpoint must match that same network
record. A caller cannot inject a different destination URL.

Enrollment settings contain `guest_ipv4`, `tenant_endpoint`, public
`relay_ca_pem`, and `artifact_sha256`. Operator sources contain tenant
`MetadataTarget` entries (`host`, `python`, `root`, `account`) and resource-keyed
`GuestTarget` entries (`host`; Python is fixed to the native venv). SSH uses strict
existing host-key trust. It never accepts a new host key on first use.

The main operator CLI owns argument parsing and the overall delivery state.
Its `enrollment-plan`, `enroll` and `enrollment-status` actions use these APIs.
For example, with reviewed private files and a previously reserved request:

```sh
python -m wearing.cloud.device_operator enrollment-plan \
  --root /private/operator-ledger --ssh-config /private/ssh-config \
  --host reviewed-proxmox --node pve01 \
  --admission-sources /private/admission-sources.json \
  --request-id REVIEWED_REQUEST_ID \
  --enrollment-spec /private/enrollment-spec.json \
  --enrollment-sources /private/enrollment-sources.json
```

After reviewing that output, use `enroll` with the same arguments and
`--plan-sha256 REVIEWED_PLAN_SHA256`. To inspect, use `enrollment-status` with the
same target/admission/request/source arguments; it reads the already-recorded
settings and does not require `--enrollment-spec`. Placeholder values above are
not generated device IDs and must be replaced with the real reviewed ledger
values. No additional device is admitted by this command.

There is no alternative ad-hoc deployment path in this module.
`python -m wearing.cloud.device_enrollment --remote` is only
the privileged, fixed SSH child entry point and reads its protocol from stdin.

## Prerequisites

- The operator has verified the guest SSH host key through the provisioned
  hypervisor/console. The reviewed runtime bundle includes both enrollment Python
  modules on guest and tenant.
- `/etc/pajio-native/device-owner.json` contains the exact owner record;
  `bootstrap-expected.json` and `bootstrap-installed.json` both equal
  `{version: 1, owner_sha256, artifact_sha256}`. The runtime installer owns the
  actual artifact verification; enrollment does not write these receipts.
- Native account, private home, user service manager, native drivers and live
  desktop/phone are present. The guest has no existing active connector/media
  service. Existing live A devices are intentionally excluded.
- Linux uses `pajio-desktop`, X11 `:10`, its private Xauthority and desktop bus.
  Android uses `pajio-phone`, loopback ADB port `20000 + VMID`, VMID at most 45535,
  and a resource ID derived from that serial. Existing port-5555 devices are not
  changed. Fleet operators must allocate unique VMIDs across any hosts sharing a
  resource namespace.
- Android has the pinned scrcpy server and verified private-input APK. Enrollment
  checks the installed APK SHA before enabling Unicode private input. It does not
  fall back to broadcasts, clipboard, or ASCII password input.
- The authenticated tenant relay is already reachable at its fixed TLS 8444
  address. The operator has seeded tenant-private
  `private-media-access.json` with `{version:1, enabled:true, hosts:{}, turn:...}`
  for a first device, or a verified existing configuration for another device.
  Enrollment never invents a TURN secret, copies it from another tenant, or
  sends it to the execution guest.

## Execution and recovery

Stages are `prepare → issue → configure → bind → activate`. The operator ledger
commits an in-flight state before each mutation. Secrets are generated once and
stored under the private operator ledger; neither plans nor status output
contain them.

- **Prepare** fixes a unique native resource, obtains the actual driver tool
  inventory, and probes native and private-video availability.
- **Issue** transactionally records the exact owner/inventory digest and one
  pairing code in the tenant relay DB. A repeated request recovers that same
  pairing. It never silently rotates an expired code or claims an already-bound
  resource.
- **Configure** consumes the pair using the pre-persisted connector token and
  installs exact-bound local media configuration, private TLS files and services.
  Differing existing files are refused.
- **Bind** adds only this resource's tenant media entry and independent client
  certificate. The relay must run the release which reads the private media
  enable flag per request; the helper verifies that release is loaded. It never
  restarts the tenant relay, including for the first device. Concurrent pairing
  or queued work cannot be disrupted by an enrollment restart.
- **Activate** starts the new guest's services. Connector installation is held in
  stopped intent until its private-media host is started.

A lost SSH response remains `unknown`. A retry performs authoritative readback
of that exact stage's owner, configuration, pairing or service state. It proceeds
only if the whole stage can be proven complete. Partially configured state is not
automatically replayed; the operator must inspect and explicitly repair it.
There is no destructive rollback, unpair, password rotation or automatic delete.

For the known Android base-image failure involving the nonexistent
`linux-modules-extra-generic` package, `device_bootstrap_repair.py` has a separate
operator-only recovery path. It accepts only that exact single cloud-init error,
checks the hypervisor and guest owner binding, and installs the extra-module
package matching the running kernel. It preserves the original cloud-init error
and records a root-private repair receipt. Every later attestation rechecks the
receipt, machine, artifact, package versions, and Binder module path/vermagic/hash.
The resulting `bootstrap_repair_verified` flag never rewrites
`cloud_init_ready=false` or labels the original cloud-init run successful.

`inspect` rechecks live service/source availability, current relay heartbeat,
matching scope and pinned mTLS reachability. It verifies that no-client-cert and
no-bearer probes are rejected. A probe sends no SDP, captures no screen and makes
no ownership transition. `enrollment_ready=true` therefore means the binding and
transport prerequisites are verified; it is **not a video, user-input or model
task acceptance result**. `product_ready` remains false in this module. The
delivery layer must additionally verify network isolation, unique OS identity,
terms state and actual remote-control/model acceptance before public readiness.

Each device gets a new CA and distinct server/client leaf keys. Only public CA
material is shared; the CA signing key is discarded. The server key goes only to
the guest, the client key only to the tenant, and the connector bearer is stored
on the guest (only its hash goes to the tenant enrollment helper). Leaf lifetime
is 89 days. This bootstrap is not a certificate-renewal implementation; renewal
and expiry monitoring remain an explicit operator lifecycle requirement.

## Existing A devices: safe adoption proposal

Do not insert an old VM into a fresh-clone record or manufacture a template SHA.
A separate, explicit `adopted_existing` origin is required. Before an adoption
mutation, collect an immutable review bundle containing:

1. Hypervisor VMID, actual CPU/RAM/disks, current configuration digest, current OS
   identity and SSH host-key evidence. Record the original legacy deployment
   provenance as unknown/manual where it cannot be established.
2. Fresh authoritative tenant/account/identity ownership, exact current connector
   ID and inventory, native gateway resource, current media scope and TLS chain.
   Verify every value agrees. No cross-tenant binding is inferred from a VM name.
3. Existing device pause/quiescence evidence, no active media/input/commands, and
   a recoverable backup with independent readback. Preserve current pairing keys,
   user app data and resource ID, including the existing Android 5555 serial.
4. A reviewed adoption digest binds all of the above to one new operator owner
   nonce. Install that exact marker on guest and hypervisor atomically enough that
   a partial result becomes `needs_operator`, never `ready`.
5. Only after readback agreement may the capacity ledger substitute this owned
   reservation for the corresponding external legacy slot; it must never count
   neither. The first maintenance freeze/sleep/wake uses the same live gate as a
   fresh device and is independently verified.

The enrollment helper deliberately refuses legacy A devices. Adoption is a
different operation implemented by `device_adoption.py` and
`device_adoption_ssh.py`, exposed as `adopt-plan`/`adopt`/`adoption-status` by the
same operator CLI. Its separately reviewed evidence is required before a live
sleep/wake trial. It must not be simulated by relaxing admission checks.

## Current verification boundary

Targeted automated tests cover scope/plan/material changes, account revocation,
lost-response reconciliation without replay, transactional pairing, unique
Android serial bounds, certificate usage/SAN separation, stdin-only transport,
key minimization, exact-file protection and media proxy boundaries. The generated
media service command is also parsed by the actual private-media CLI in tests;
checking two matching template strings is insufficient.

On 2026-10-10, a second synthetic tenant's Linux VM 1211 and Android VM 1212 were
actually provisioned on the office host through the operator ledger. The control
and tenant VMs were resized first, with before/after hypervisor evidence and
service recovery checks; existing A devices and host reserves remained in the
capacity calculation. Both new guests completed owner/artifact verification,
first pairing, tenant binding, authenticated relay connection and pinned mTLS
inspection. Their enrollment records are `verified`, with
`enrollment_ready=true` and `product_ready=false`.

The retained private evidence directory is
`.wearing/on-prem/20261009/personal-compute/`. It is not a public artifact folder
and contains separate private configuration files; only reviewed, redacted proof
records should be shared. Relevant acceptance records are:

| Evidence | What it establishes |
| --- | --- |
| `core-resize-proof.json`, `b-linux-enroll.json`, `b-android-enroll.json` | Actual capacity changes and first enrollment of the two new guests. The core resize included recorded transient 502/503 responses; it was not a zero-downtime operation. |
| `b-android-bootstrap-repair-proof.json` | The specific missing-package cloud-init failure was repaired against the running kernel. Original cloud-init status remains an error; subsequent attestations independently validate the immutable repair evidence and live package/module state. |
| `b-linux-media-cli-repair-proof.json`, `b-android-enrollment-cli-overlay-proof.json` | An invalid media CLI argument was corrected using exact preimage hashes. The Android overlay was recorded separately from its frozen base artifact. Pairing was not replayed. |
| `b-android-media-proof.json` | Authenticated public WebRTC with TURN-only candidates, a real 720×1280 frame, synthetic Unicode input acknowledged and observed on the device, and explicit return acknowledged by the device. Twelve cross-tenant access/control requests were rejected with 404; a stale offer was rejected with 409. |
| `b-android-adb-proxy-repair-proof.json`, `b-android-native-readonly-proof.json` | The new guest exposed an ADB path mismatch. The proxy now uses the same SDK-or-system ADB resolution as availability checks; actual native screen-size and app-list methods succeeded after the narrow repair. |
| `b-android-native-failure-reviews-proof.json` | Three earlier, confirmed read-only `device_error` receipts were reviewed through the existing authenticated revision-checked review API. Their original failures remain in history; no command was replayed or changed to completed. |
| `b-android-after-driver-media-proof.json` | A new takeover after connector restart produced a first frame in 0.992 seconds and a fresh device return acknowledgement. The sample decoded 23.6 fps while the source reported 12.67 capture fps; these are distinct measurements. |
| `b-agent-desktop-v4-proof.json` | The model actually called Linux status and window-list tools, with completed device receipts and successful tool events for that run. Earlier failed attempts remain separate evidence. |
| `b-agent-android-v2-proof.json` | The model actually called Android app-list and screen-size tools, with completed device receipts and successful events for run `run_603c1bd132454ba69d93363bc9ee934b`. The engine still had PID 7979, start ticks 347325 and its 04:15:28 Asia/Shanghai start time, preceding first phone enrollment. The stored process samples before the model checks and after this task match; they are not a fabricated pre-enrollment snapshot. Together with enrollment timing, this establishes discovery without a tenant core restart for the new phone. |
| `b-linux-post-backup-media-proof.json`, `b-android-post-backup-media-proof.json` | After state backup, connector recovery and the final core update, new TURN-only sessions produced Linux and Android first frames in 0.918 and 1.233 seconds. Explicit return obtained fresh device acknowledgements on both connections; old offers returned 409. No frames, SDP or input content were saved, and no additional model task was used. |
| `a-linux-post-backup-media-proof.json`, `a-android-post-backup-media-proof.json` | The existing A devices also needed fresh acknowledgements after backup recovery. New TURN-only sessions produced first frames in 1.165 and 1.501 seconds; explicit return restored `device_confirmed=true` on both current connections and old offers returned 409. Android Home was acknowledged; Linux received no input. These checks do not reclassify A's adopted provenance as a fresh clone. |

Read-only relay commands have device task IDs rather than a direct business-task
foreign key. The model checks correlate new command IDs, resource/method/params,
an exclusive test window, and the current run's SSE tool events. SSE does not
contain complete arguments; these records do not claim an exact task-ID join.
The task status `completed_unverified` alone is not the acceptance criterion.

This proves a controlled second-tenant supply and use path, not unrestricted
public readiness. B's media checks used an operator WebRTC client; they do not
replace native App or physical iPhone acceptance. Browser first-run setup and
third-party account authorization remain separate checks. The source fixes and
recorded overlays must be incorporated into the next reviewed runtime bundle.
Certificates still expire after 89 days without automatic renewal. Every new
device must pass current physical admission; historical proof does not create
capacity or permit a stale readiness result to bypass current checks.
