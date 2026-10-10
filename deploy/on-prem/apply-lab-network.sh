#!/bin/sh
# Atomic update; do not flush unrelated Proxmox firewall tables.
set -eu
# Keep newly created runtime locks private after a host restart as well.
umask 077
exec 9>/run/lock/pajio-device-network.lock
flock -n 9 || { echo 'Another device network update is in progress.' >&2; exit 1; }
rules=/etc/pajio/lab-network.nft
transaction=$(mktemp)
trap 'rm -f "$transaction"' EXIT HUP INT TERM
for pair in 'inet pajio_lab_guard' 'ip pajio_lab_nat'; do
    # The words below are fixed table identifiers, never user input.
    if nft list table $pair >/dev/null 2>&1; then
        printf 'delete table %s\n' "$pair" >> "$transaction"
    fi
done
cat "$rules" >> "$transaction"
# Regenerate the fixed-rule fragments on EVERY apply/reboot. An owner mismatch
# rejects the whole atomic transaction; never silently drop a device's isolation.
/usr/bin/python3 /usr/local/libexec/pajio-render-device-network.py >> "$transaction"
nft --check --file "$transaction"
nft --file "$transaction"
