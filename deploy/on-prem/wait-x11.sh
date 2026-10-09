#!/bin/sh
set -eu
attempt=0
while ! /usr/bin/xdpyinfo -display :10 >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 60 ] || exit 1
    sleep 1
done
