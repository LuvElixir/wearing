#!/bin/bash
set -euo pipefail
[[ $EUID -eq 0 && -x /usr/bin/firefox ]] || exit 1
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
desktop_uid=$(id -u pajio-desktop)
profile=/home/pajio-desktop/.mozilla/pajio
install -d -m 0700 -o pajio-desktop -g pajio-desktop /home/pajio-desktop/.mozilla "$profile"
if [[ ! -e "$profile/prefs.js" && ! -e "$profile/user.js" ]]; then
    install -m 0600 -o pajio-desktop -g pajio-desktop "$source_dir/pajio-firefox.user.js" "$profile/user.js"
fi
install -m 0600 -o pajio-desktop -g pajio-desktop "$source_dir/pajio-browser.service" /home/pajio-desktop/.config/systemd/user/pajio-browser.service
runuser -u pajio-desktop -- env XDG_RUNTIME_DIR="/run/user/$desktop_uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$desktop_uid/bus" systemctl --user daemon-reload
runuser -u pajio-desktop -- env XDG_RUNTIME_DIR="/run/user/$desktop_uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$desktop_uid/bus" systemctl --user enable --now pajio-browser.service
