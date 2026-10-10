# Host monitoring and backup scope

Both host jobs read the same root-owned, mode 0600
`/etc/pajio-operations-scope.json`. It is a private deployment artifact; do not
commit the real guest bindings. Install `operations_scope.py` beside
`health-watch.py` in `/usr/local/lib/pajio/` and the backup hook at its existing
`/usr/local/sbin/pajio-check-backup-space` path.

The version 1 JSON object contains a nonempty `guests` map, keyed by VM ID. Each
entry contains `config_sha256` and a nonempty `services` array. The fingerprint
binds the complete trusted Proxmox guest config, including owner descriptions,
disks, network, OS identity, and startup policy. Only provider `digest` and the
temporary backup `lock` are excluded from the hash. A lock other than `backup`
still rejects the guest. A reused VM ID or a changed owner cannot inherit the
previous guest's healthy state or backup eligibility.

Generate a scope only after comparing the live host configs with the approved
provisioning plan and receipts. Retain the exact previous scope, scripts and
backup job in a private deployment receipt. Review planned guest changes before
updating this file; monitoring must report the mismatch rather than silently
refreshing its own approval. Changing the health scope starts a new continuity
window while retaining earlier failures. A missing, invalid or unreadable scope
records a failed sample.

The backup job's VM list must match the intended ready guests in this scope.
The backup hook checks the current guest binding and full virtual disk size
before starting, retains 16 GiB of host free space, and protects dump directories
and archives. A scheduled job is not proof that an archive was produced or
restorable. Local archives on the same physical disk are also not an offsite
disaster-recovery copy.

Validation: `tests/test_operations_scope.py`, `tests/test_backup_space_guard.py`
and `tests/test_health_watch.py` cover scope failures, identity changes, backup
locks, storage bounds and honest continuity reporting. These unit checks do not
constitute a live backup/restore or application acceptance result.
