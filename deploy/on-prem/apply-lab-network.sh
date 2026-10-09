#!/bin/sh
# Atomic update; do not flush unrelated Proxmox firewall tables.
set -eu
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
nft --check --file "$transaction"
nft --file "$transaction"
