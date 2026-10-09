#!/bin/sh
# Install under /etc/letsencrypt/renewal-hooks/deploy/ on the public gateway.
set -eu
if [ "${RENEWED_LINEAGE:-}" = /etc/letsencrypt/live/pajio.luckyloading.com ]; then
    /usr/sbin/nginx -t
    /usr/bin/systemctl reload nginx
fi
