# Device file channel

This is a bounded data-transfer capability for an already paired Linux desktop or Android phone. It does not create a device, run a shell, open an application, install an APK, or select an arbitrary device path.

## API contract

Every route is under `/api/devices/{resource_id}/files`, behind the existing tenant/session/identity boundary. A foreign identity receives 404. Existing grants do not gain file access automatically.

- `GET /`: `{supported,available,reason,max_bytes,inbox_label,outbox_label}`. Labels are `Pajio/Inbox` and `Pajio/Outbox`. `files_permission_required` means the separate file grant has not been enabled.
- `POST /workspace-source` with `{path}`: safely snapshots one current Core workspace file into private staging. Returns Source `{file_id,name,size,sha256}`. Later changes to the original do not change this source.
- `POST /transfers` with `{request_id,direction,source?}`. `request_id` is 32 lowercase hex; direction is `to_device`, `from_device`, or `list`. `list` has no source. A fetch source must have appeared in a completed list for this exact identity and device. Same ID and same payload return the same command; a changed payload is rejected.
- `GET /transfers/{request_id}` reads a stable receipt. `GET /transfers` returns the latest 50 in `{transfers}`.

Transfer has `request_id,resource_id,direction,state,bytes_completed`, plus `source` for either transfer direction. State is `queued|executing|completed|failed|unknown`. Completed lists include `files,truncated`; completed fetches include `workspace_file:{path,size,modified}`. Bytes are zero until completion; the API does not invent percentage progress. Fetch results use the existing workspace download endpoint. Errors are fixed codes, never input contents or tracebacks.

Public proxy errors, including 4xx, do not prove that an upstream command was never accepted. The App preserves its original request ID and queries it after any ambiguous response. Neither a missing receipt nor an unknown command automatically issues a second command. Unknown native outcomes require explicit inspection/review; the Inbox filename includes the original request ID for that inspection. Existing command review never changes a failed/unknown action into a fabricated success.

Files must contain 1 byte through 20 MiB (20,971,520 bytes), inclusive. Names are NFC, at most 180 UTF-8 bytes, have no leading dot, surrounding whitespace, control characters or path separator. Empty files are intentionally unsupported in this first version. Workspace import remains data-only and mode 0600; a `.sh` or `.apk` is not executed or installed.

## Transport and ownership

Separate `files.send`, `files.list`, and `files.fetch` methods are added to a locally verified capability inventory. Existing `computer.input` grants remain unchanged. An operator can use the existing two-sided revision-fenced permission flow with `mode:files,file_access:true,delivery:connector`; prepare/download alone does not grant access. The connector must independently have the native binding installed and available before accepting that local ceiling.

Command envelopes contain only references, hashes and sizes. Authenticated `/v1/files/download` and `/v1/files/upload` move at most 1 MiB of raw bytes per request (base64 in bounded JSON). Each chunk verifies the original connector, identity, current connection, exact executing command, method, lease epoch, human-access state and maintenance fence. The normal connector journal commits intent before claim and never reexecutes an unknown ID. Native hash verification occurs before publishing a received file; fetched snapshots are hash-verified again before Core import.

Linux uses `/home/pajio-desktop/Pajio/Inbox` and `Outbox`. Android uses the dedicated phone's backing `/var/lib/pajio-phone/data/media/0/Download/Pajio`, visible inside that phone as `/storage/emulated/0/Download/Pajio`. Only these fixed folders are exposed. Android access is a dedicated root Unix-socket service; the connector never receives Docker, sudo or arbitrary-path access. Both client and broker check Linux `SO_PEERCRED`. The broker accepts only the configured `pajio-phone` UID and exact resource ID; the client requires UID 0 at the fixed socket.

Filesystem traversal opens every component with directory descriptors and `O_NOFOLLOW`; directories, symlinks, hardlinks, pipes and oversized files are not exported. Received files are fully written and fsynced before atomic no-overwrite publication, named `{request_id}-{original_name}`. No destination overwrite is permitted. Android files are owned by Android's media UID/GID 1023, never made executable. Linux native I/O holds the DeviceGateway action lock, with permit checks before and after. Cancellation waits for an in-flight filesystem worker before releasing that lock. Android's broker independently holds the same fixed phone action lock and checks its existing gateway database read-only before and after each data operation, so a client timeout cannot release a still-running write. Active private takeover and epoch changes reject file I/O and discard returns.

The first successful fetch import is idempotent. Subsequent status reads verify the original workspace import instead of recreating a user-deleted file or overwriting edits. Changed/missing workspace results report `file_workspace_import_pending` as an unknown result requiring inspection.

## Enablement and current limits

1. Deploy the reviewed Python modules to Core, relay and the matching native connector. No permission migration is implicit.
2. On the bound dedicated execution VM, run `deploy/on-prem/install-device-files.py` with the installed Python environment. It checks the root device-owner marker against the actual local connector scope. It writes nonsecret root-owned `/etc/pajio-device-files.json`; for Android it installs and starts only `pajio-device-files.service`. It does not restart core, connector, media, Android or a VM.
3. Apply the explicit two-sided file permission update, preserving all existing observation/input methods. The connector reconnects for the new policy revision through the existing permission lifecycle.
4. Verify synthetic Linux and Android round trips, exact 20 MiB, both SHA values, foreign identity denial, takeover denial, same-ID recovery and no executable/installation effects. Test Android Unix credentials and independent broker lock on Linux, since macOS cannot supply Linux `SO_PEERCRED`/procfs.

Staging is currently limited to 200 MiB and 1,000 source/fetch reservations per identity; there is no automatic staging garbage collection in this P0 release. At quota the API refuses new data rather than silently deleting it. Outbox listing considers at most 200 entries, returns at most 50 files, and hashes at most approximately 100 MiB plus one bounded file; `truncated` is explicit. Subdirectories are not traversed. Results still live in the existing single-host backup model; this feature does not change off-site recovery, retention or capacity policy. No public self-service VM API is introduced.

## Personal account isolation and operator registration

This channel is only enabled for an operator-verified **private personal tenant**. `ControlStore.private_owner_scope` uses the authoritative ownership registry's owner, full membership count and digest, and the current instance route. It does not count the web database role's RLS-filtered memberships. Private mismatches deny every proxied HTTP API, body/upload/download wait and live voice WebSocket, so another member cannot bypass the file history gate through the existing workspace or Agent APIs. Existing shared/unknown/unregistered tenants keep their previous general API behavior, but receive no file authority.

The gateway alone adds `X-Pajio-Private-Owner-Scope`, derived from the authenticated account and tenant; caller-supplied versions are never forwarded. The worker strips that internal header after authenticating the gateway and verifies it against `X-Pajio-Storage-Scope`. File APIs accept only the resulting trusted ASGI scope. There is no client-supplied owner field.

A second independent resource anchor binds exact identity, resource, connector and personal actor. Before enabling file grants, the operator obtains a fresh `AccountProof` with `TrustedSSHAdmission.check` from the existing private control/tenant metadata targets. Within 60 seconds, pipe that proof over the already trusted SSH connection to the tenant service account's Python:

```text
<tenant-python> -m wearing.cloud.device_files bind-owner \
  --instance-root <exact-tenant-private-root> --resource-id <paired-resource-id>
```

The proof JSON is read from stdin, not an environment variable or command argument. The entry verifies its tenant and instance against the actual private volume and its identity/resource against the existing paired connector. It never creates a pairing or changes an existing owner. The same binding is idempotent; a changed account, identity or connector is refused and needs a separately reviewed migration. Do not fabricate a proof, use a historical cached proof, or infer the owner from the first caller or a human takeover session.

All new source/transfer rows carry the actor. An additive SQLite migration leaves older unowned rows with an empty actor; these are inaccessible, not automatically adopted. Authenticated connector chunks also verify that their original transfer actor still matches the bound resource. This ledger contains no new public binding or provisioning endpoint.

The explicit permission request uses the current `permission_revision` from `GET /api/devices`:

```json
{"request_id":"<fresh 32-hex ID>","resource_id":"<paired-resource-id>","revision":"<current 64-hex permission_revision>","mode":"files","file_access":true,"delivery":"connector"}
```

Send it through the existing authenticated `POST /api/devices/permissions`. Poll `GET /api/devices/permissions/{request_id}` until applied, then verify a fresh connector lease and file capabilities. `delivery:connector` uses the existing two-sided automatic permission delivery; do not manually mutate grant rows or replace connector config. A lost response is checked using the original permission request ID. Setting `file_access:false` explicitly removes only file methods.

### Exact deployment roles

Use a reviewed source manifest and live preimages for each rollout. On 2026-10-10, the backend roles below were deployed to the A/B acceptance environment and its four execution devices. The [deployment evidence](evidence/pajio-device-files-2026-10-10.md) preserves the initial A native installer failures and rollback, the separate successful installer-v2 attempts, and the observed activation-window HTTP 502 responses; deployment was not interruption-free.

| Role | Python paths under `src/wearing/` | Activation |
| --- | --- | --- |
| Control/public gateway | `cloud/control.py`, `cloud/gateway.py`, `cloud/voice.py` | Restart only public gateway; registry schema already exists, no PostgreSQL migration |
| A/B tenant Core and relay | `app.py`, `workspace_upload.py`, `device_files_io.py`, `cloud/device_files.py`, `cloud/device_setup.py`, `cloud/device_permissions.py`, `cloud/relay.py`, `cloud/worker.py` | Restart both Core **and** long-running relay; first initialization adds actor/file tables under existing SQLite transaction |
| Linux/Android native connectors | `device_files_io.py`, `device_files_native.py`, `device_files_broker.py`, `connectors/remote/adapter.py`, `connectors/remote/client.py`, `connectors/remote/permissions.py`, `cloud/device_permissions.py`, `cloud/device_setup.py` | Run reviewed `deploy/on-prem/install-device-files.py` with `/opt/pajio-native/venv/bin/python` as root; restart only matching connector to load capability code; Android installer starts the separate broker |

Unchanged dependencies such as DeviceGateway, commands, journal, admission metadata verifier and native runner must already be the verified current build. The native installer carries its own bounded metadata reader and atomic no-overwrite writer; it does not depend on the enrollment module being installed on previously adopted VMs. No media, Android container, desktop session, VM or host restart is needed. Do not enable file permissions until both tenant and native code, trusted ownership registry and per-resource anchor are in place. Keep old permissions until all synthetic checks pass. Core and relay both import the new module; updating only Core is insufficient.

### P0 capacity and recovery limits

The 200 MiB/1,000 limit is **cumulative staging reservations**, including failed/unknown fetch reservations. Deleting a workspace result does not release it. There is currently no garbage collection or cleanup endpoint; quota exhaustion requires a separately designed safe retention/cleanup operation. It must not be described as unlimited ongoing storage. Installer metadata uses same-directory temporary files, file fsync, atomic no-overwrite publication and directory fsync. Interrupted temporary writes are not published. A pre-existing differing, unsafe or partial metadata file still fails closed and requires operator inspection instead of automatic deletion/replacement. Native single-transfer receipts and first workspace import are atomic and do not replay unknown effects.


### Installer v2 compatibility correction

The first installer reused `cloud.device_enrollment_remote.read/write_exact`. Older manually adopted execution VMs do not necessarily contain that module, so import failed before enablement. Installer v2 removes this dependency without installing enrollment or changing a grant. Its local helpers pin each path component with `O_NOFOLLOW`, bound metadata to 128 KiB, check inode type/link count/owner/mode, and use atomic no-overwrite publication with file and directory fsync. Same existing bytes with exact ownership/mode are idempotent; changed or unsafe files are refused. A process crash in the narrow interval after publishing the hard link and before removing its temporary name can leave link count two; retry deliberately refuses this inode until the operator inspects it. This is not a guarantee of automatic recovery from every crash point. Tests simulate an absent enrollment module, interrupted writes, racing creators, symlinks/hardlinks/FIFO, wrong owners and oversized files using ordinary temporary directories.

The original frozen manifest remains unchanged. At the installer-v2 freeze, `source-manifest-v2.json` recorded only the installer, this document's then-current revision and the additional installer test as changes; all 16 production Python module hashes remained the original frozen versions. Later documentation updates do not alter that historical manifest. A rollout attempt that already rolled back must retain that evidence and use a separate reviewed attempt for v2.

## Verified use and remaining acceptance boundaries

The deployed API/connector/filesystem path completed synthetic 96 KiB send, list and fetch on all four A/B Linux and Android devices, with matching device and downloaded-workspace SHA-256 values. The two B devices additionally passed the exact 20 MiB boundary. Cross-account reads and file operations during acknowledged private takeover were checked separately; details and limits are in the [backend evidence](evidence/pajio-device-files-2026-10-10.md).

The dedicated **Pajio Acceptance iPhone Air simulator running the Release native App** then completed the actual file UI flow for A's `daily` identity on both Linux and Android: choose a known 96 KiB workspace fixture, send it, read Outbox, and fetch the fixture back. The operator initiated these actions in the App. An independent read-only check subsequently fetched the original three receipts per device and downloaded only the known synthetic result: each receipt was `completed`, and both downloads matched the fixture's 98,304 bytes and SHA-256. See the [Linux App receipts](evidence/pajio-device-files-ui-20261010/linux-receipts.json) and [Android App receipts](evidence/pajio-device-files-ui-20261010/receipts.json). UI observation times and workspace modification times are not transfer-duration measurements.

This is actual simulator App-to-service acceptance, not physical iPhone or Android APK manual acceptance. The 20 MiB and private-takeover boundary checks above are API/device checks, not claimed as repeats through the App UI. Ambiguous-response recovery, original-ID lookup and no replay are covered by unit/handler tests; no real App network-disconnection or accepted-command/lost-response fault was injected in this round. Transfer completion does not prove that an Agent or third-party application has opened or used the file.
