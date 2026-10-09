#!/bin/sh
set -eu
/usr/bin/dbus-update-activation-environment DISPLAY XAUTHORITY XDG_RUNTIME_DIR XDG_SESSION_TYPE NO_AT_BRIDGE GTK_MODULES LANG
/usr/bin/gsettings set org.gnome.desktop.interface toolkit-accessibility true
/usr/bin/xset s off
/usr/bin/xset -dpms || true
if [ -x /usr/bin/ibus-daemon ]; then
    /usr/bin/ibus-daemon --daemonize --xim
fi
exec /usr/bin/xfce4-session
