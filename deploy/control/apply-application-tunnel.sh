#!/bin/sh
set -eu
config=/etc/pajio/control-tunnel.nft
if /usr/sbin/nft list table inet pajio_control_tunnel >/dev/null 2>&1; then
  { echo 'delete table inet pajio_control_tunnel'; cat "$config"; } | /usr/sbin/nft -f -
else
  /usr/sbin/nft -f "$config"
fi
