#!/bin/bash
# Run only inside the dedicated Ubuntu desktop VM, as its provisioning admin.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root inside the desktop VM.' >&2; exit 1; }
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || { echo 'Ubuntu 24.04 required.' >&2; exit 1; }
systemd-detect-virt --vm --quiet || { echo 'A dedicated execution VM is required.' >&2; exit 1; }
if [[ -d /etc/pve || -d /var/lib/wearing/instance ]]; then
    echo 'Refusing to install a desktop on a hypervisor or Agent core VM.' >&2
    exit 1
fi
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
desktop_user=pajio-desktop
desktop_home=/home/pajio-desktop
if ! id "$desktop_user" >/dev/null 2>&1; then
    useradd --create-home --user-group --shell /usr/sbin/nologin "$desktop_user"
fi
[[ $(getent passwd "$desktop_user" | cut -d: -f6) == "$desktop_home" ]] || exit 1
[[ $(getent passwd "$desktop_user" | cut -d: -f7) == /usr/sbin/nologin ]] || { echo 'Desktop account must not have an interactive login shell.' >&2; exit 1; }
desktop_uid=$(id -u "$desktop_user")
[[ $desktop_uid -ge 1000 ]] || exit 1
if id -nG "$desktop_user" | tr ' ' '\n' | grep -Eq '^(sudo|docker|lxd|libvirt)$'; then
    echo 'Desktop account has an unexpected privileged group.' >&2
    exit 1
fi
chmod 0700 "$desktop_home"
install -d -m 0755 /opt/pajio-native /etc/pajio-native
for item in start-x11.sh wait-x11.sh start-desktop-session.sh; do
    install -m 0755 "$source_dir/$item" "/opt/pajio-native/$item"
done
for item in linux_computer.py linux_computer_helper.py; do
    [[ ! -f "$source_dir/$item" ]] || install -m 0644 "$source_dir/$item" "/opt/pajio-native/$item"
done
# Preserve distribution D-Bus session policies and service directories. Only the
# Unix listen address is fixed so native service environments survive restarts.
python3 - "$desktop_uid" <<'PY'
from pathlib import Path
import sys, xml.etree.ElementTree as ET
uid = int(sys.argv[1])
root = ET.fromstring(Path('/usr/share/dbus-1/session.conf').read_text())
for item in list(root.findall('listen')):
    root.remove(item)
ET.SubElement(root, 'listen').text = f'unix:path=/run/user/{uid}/pajio-desktop-bus'
Path('/etc/pajio-native/session-bus.conf').write_text(ET.tostring(root, encoding='unicode')+'\n')
PY
install -d -m 0700 -o "$desktop_user" -g "$desktop_user" "$desktop_home/.config" "$desktop_home/.config/systemd" "$desktop_home/.config/systemd/user"
for item in pajio-x11.service pajio-desktop-session.service; do
    install -m 0600 -o "$desktop_user" -g "$desktop_user" "$source_dir/$item" "$desktop_home/.config/systemd/user/$item"
done
locale-gen zh_CN.UTF-8 >/dev/null
loginctl enable-linger "$desktop_user"
systemctl start "user@$desktop_uid.service"
runuser -u "$desktop_user" -- env XDG_RUNTIME_DIR="/run/user/$desktop_uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$desktop_uid/bus" systemctl --user daemon-reload
runuser -u "$desktop_user" -- env XDG_RUNTIME_DIR="/run/user/$desktop_uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$desktop_uid/bus" systemctl --user enable --now pajio-x11.service pajio-desktop-session.service
printf 'desktop_user=%s\nDISPLAY=:10\nXAUTHORITY=/run/user/%s/pajio-x11/Xauthority\nDBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%s/pajio-desktop-bus\nXDG_RUNTIME_DIR=/run/user/%s\nXDG_SESSION_TYPE=x11\n' "$desktop_user" "$desktop_uid" "$desktop_uid" "$desktop_uid"
