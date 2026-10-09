#!/bin/bash
# Official Mozilla DEB repository; verify the published primary signing key.
set -euo pipefail
[[ $EUID -eq 0 ]] || exit 1
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || exit 1
temp_key=$(mktemp)
trap 'rm -f "$temp_key"' EXIT
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    --connect-timeout 20 --max-time 120 --retry 2 \
    https://packages.mozilla.org/apt/repo-signing-key.gpg -o "$temp_key"
fingerprint=$(gpg --batch --show-keys --with-colons "$temp_key" 2>/dev/null | awk -F: '$1=="fpr" {print $10;exit}')
[[ $fingerprint == 35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3 ]] || { echo 'Mozilla key fingerprint mismatch.' >&2; exit 1; }
install -d -m 0755 /etc/apt/keyrings
install -m 0644 "$temp_key" /etc/apt/keyrings/packages.mozilla.org.asc
cat >/etc/apt/sources.list.d/pajio-mozilla.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main
EOF
cat >/etc/apt/preferences.d/pajio-mozilla <<'EOF'
Package: firefox firefox-*
Pin: origin packages.mozilla.org
Pin-Priority: 1000

Package: firefox
Pin: release o=Ubuntu
Pin-Priority: -1
EOF
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends firefox firefox-l10n-zh-cn
apt-cache policy firefox
