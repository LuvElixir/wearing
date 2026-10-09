#!/bin/sh
set -eu
transaction=$(mktemp)
trap 'rm -f "$transaction"' EXIT HUP INT TERM
if nft list table inet pajio_host_guard >/dev/null 2>&1; then
    printf 'delete table inet pajio_host_guard\n' > "$transaction"
fi
cat /etc/pajio/host-management.nft >> "$transaction"
nft --check --file "$transaction"
nft --file "$transaction"
