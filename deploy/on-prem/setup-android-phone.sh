#!/bin/bash
# Dedicated Ubuntu execution VM only. Never run on the hypervisor or core VM.
set -euo pipefail

# Read-only contract check before starting an already present container. The
# image name alone is not ownership: an identically labelled container could
# mount another user's data or share the execution host network/IPC namespace.
validate_existing_container() {
  python3 -c '
import json, re, sys

def verify():
    image, port = sys.argv[1:]
    rows = json.load(sys.stdin)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError()
    item = rows[0]
    config, host = item["Config"], item["HostConfig"]
    if item["Name"] != "/pajio-phone" or not re.fullmatch("[0-9a-f]{64}", item["Id"]):
        raise ValueError()
    if config["Labels"].get("io.pajio.role") != "tenant-android" or config["Image"] != image:
        raise ValueError()
    expected = {"5555/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]}
    if host["PortBindings"] != expected or host["PublishAllPorts"] is not False:
        raise ValueError()
    if host["NetworkMode"] not in ("default", "bridge") or set(item["NetworkSettings"]["Networks"]) != {"bridge"}:
        raise ValueError()
    if host["PidMode"] != "" or host["IpcMode"] != "private" or host["UTSMode"] != "":
        raise ValueError()
    mounts = item["Mounts"]
    if not isinstance(mounts, list) or len(mounts) != 1:
        raise ValueError()
    mount = mounts[0]
    if (mount["Type"] != "bind" or mount["Source"] != "/var/lib/pajio-phone/data"
            or mount["Destination"] != "/data" or mount["RW"] is not True
            or mount["Propagation"] != "rprivate"):
        raise ValueError()
    # These are the dedicated-VM resource limits below, not a multi-tenant
    # Docker security boundary. Privileged redroid stays inside its own VM.
    if (host["Privileged"] is not True or host["NanoCpus"] != 2000000000
            or host["Memory"] != 3221225472 or host["MemorySwap"] != 3221225472):
        raise ValueError()
    if host["RestartPolicy"] != {"Name": "unless-stopped", "MaximumRetryCount": 0}:
        raise ValueError()
    expected_cmd = ["androidboot.use_memfd=1", "androidboot.redroid_width=720",
                    "androidboot.redroid_height=1280", "androidboot.redroid_dpi=320",
                    "androidboot.redroid_fps=24", "androidboot.redroid_gpu_mode=guest",
                    "androidboot.redroid_net_ndns=2", "androidboot.redroid_net_dns1=223.5.5.5",
                    "androidboot.redroid_net_dns2=1.1.1.1"]
    if config["Cmd"] != expected_cmd:
        raise ValueError()

try:
    verify()
except (ValueError, KeyError, TypeError, AttributeError):
    print("Existing Android container binding changed; refusing reuse", file=sys.stderr)
    sys.exit(2)
' "$image" "$adb_port"
}
image=${1:?Pass a verified redroid image digest}
adb_port=${PAJIO_ANDROID_ADB_PORT:-5555}
case "$adb_port" in ''|*[!0-9]*) echo 'Invalid loopback ADB port' >&2; exit 2;; esac
if [ "$adb_port" -lt 1024 ] || [ "$adb_port" -gt 65535 ]; then echo 'Invalid loopback ADB port' >&2; exit 2; fi
adb_serial="127.0.0.1:$adb_port"
case "$image" in *@sha256:11d58a64bfbde2253d1cce81bff409ff58174980222d1bada232d9ef59181191) ;; *) echo 'Image digest is not the accepted Android 14 build' >&2; exit 2;; esac
if ! systemd-detect-virt --quiet; then echo 'A dedicated execution VM is required' >&2; exit 2; fi
if [ -d /etc/pve ] || [ -d /var/lib/wearing/instance ]; then echo 'Refusing to install a phone on a hypervisor or Agent core VM' >&2; exit 2; fi
if id pajio-phone >/dev/null 2>&1; then
  test "$(getent passwd pajio-phone | cut -d: -f6)" = /home/pajio-phone
  test "$(getent passwd pajio-phone | cut -d: -f7)" = /usr/sbin/nologin
  case " $(id -nG pajio-phone) " in *' sudo '*|*' docker '*|*' root '*) echo 'Existing phone account has unexpected privileges' >&2; exit 2;; esac
fi
id pajio-phone >/dev/null 2>&1 || useradd --create-home --shell /usr/sbin/nologin pajio-phone
chmod 700 /home/pajio-phone
if [ -L /var/lib/pajio-phone ]; then echo 'Unsafe Android data directory' >&2; exit 2; fi
install -d -m 700 /var/lib/pajio-phone
# Android owns /data mode and uid after first boot. Re-running install -d -m
# on that bind mount would remove shell traversal and break scrcpy/ADB uploads.
if [ -L /var/lib/pajio-phone/data ]; then echo 'Unsafe Android data directory' >&2; exit 2; fi
if [ ! -d /var/lib/pajio-phone/data ]; then mkdir -m 700 /var/lib/pajio-phone/data; fi
printf 'binder_linux\n' > /etc/modules-load.d/pajio-phone.conf
printf 'options binder_linux devices=binder,hwbinder,vndbinder\n' > /etc/modprobe.d/pajio-phone.conf
# Cloud images may run an older kernel than linux-modules-extra-generic.
# Install the module package for the running kernel; never silently reboot or
# replace a tenant's active kernel while preparing the native transport.
if ! modinfo binder_linux >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "linux-modules-extra-$(uname -r)"
fi
modprobe binder_linux devices=binder,hwbinder,vndbinder
systemctl enable --now docker
if docker container inspect pajio-phone >/dev/null 2>&1; then
  test "$(docker inspect --format '{{ index .Config.Labels "io.pajio.role" }}' pajio-phone)" = 'tenant-android'
  test "$(docker inspect --format '{{.Config.Image}}' pajio-phone)" = "$image"
  test "$(docker inspect --format '{{json (index .HostConfig.PortBindings "5555/tcp")}}' pajio-phone)" = "[{\"HostIp\":\"127.0.0.1\",\"HostPort\":\"$adb_port\"}]" || { echo 'Existing Android port binding changed; refusing migration' >&2; exit 2; }
  docker inspect pajio-phone | validate_existing_container
  docker start pajio-phone >/dev/null
else
  docker run -d --name pajio-phone --label io.pajio.role=tenant-android \
    --restart unless-stopped --privileged --cpus=2 --memory=3g --memory-swap=3g \
    --log-driver=local --log-opt max-size=5m --log-opt max-file=2 \
    -v /var/lib/pajio-phone/data:/data -p "$adb_serial:5555" "$image" \
    androidboot.use_memfd=1 androidboot.redroid_width=720 androidboot.redroid_height=1280 \
    androidboot.redroid_dpi=320 androidboot.redroid_fps=24 androidboot.redroid_gpu_mode=guest \
    androidboot.redroid_net_ndns=2 androidboot.redroid_net_dns1=223.5.5.5 androidboot.redroid_net_dns2=1.1.1.1 >/dev/null
fi
# This service account receives local ADB access, never Docker or sudo access.
install -d -m 755 /usr/local/libexec
cat > /usr/local/libexec/pajio-phone-transport <<'SCRIPT'
#!/bin/sh
# Reconnect after a delayed Android boot or container restart; never change
# device selection or automatically restart/wipe a user's Android instance.
set -eu
serial=${PAJIO_ANDROID_SERIAL:?Missing bound loopback Android serial}
while true; do
  if ! /usr/bin/timeout 8 /usr/bin/adb -s "$serial" get-state >/dev/null 2>&1; then
    /usr/bin/timeout 8 /usr/bin/adb connect "$serial" >/dev/null 2>&1 || true
  fi
  sleep 5
done
SCRIPT
chmod 755 /usr/local/libexec/pajio-phone-transport
printf 'PAJIO_ANDROID_SERIAL=%s\n' "$adb_serial" > /etc/pajio-phone-transport.env
chmod 600 /etc/pajio-phone-transport.env
cat > /etc/systemd/system/pajio-phone-adb.service <<'UNIT'
[Unit]
Description=Pajio local Android transport
After=docker.service
Requires=docker.service
[Service]
Type=simple
User=pajio-phone
Group=pajio-phone
Environment=HOME=/home/pajio-phone
EnvironmentFile=/etc/pajio-phone-transport.env
ExecStartPre=/usr/bin/adb start-server
ExecStart=/usr/local/libexec/pajio-phone-transport
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=yes
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now pajio-phone-adb
# Installation never selects this IME as the user's default. Private sessions
# select it temporarily after runtime verification and restore the old IME.
private_apk=/opt/pajio-native/pajio-private-input.apk
private_apk_sha=80960fcaa86936abdf20de79660ea63cbc10f024b3f43b3a6ee53e92c1037c27
test -f "$private_apk" && test ! -L "$private_apk"
printf '%s  %s\n' "$private_apk_sha" "$private_apk" | sha256sum --check --status
ready=0
for attempt in $(seq 1 30); do
  if runuser -u pajio-phone -- env HOME=/home/pajio-phone /usr/bin/adb -s "$adb_serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' | grep -qx 1; then
    ready=1
    break
  fi
  sleep 2
done
test "$ready" = 1 || { echo 'Android not booted; private IME installation was not attempted' >&2; exit 3; }
runuser -u pajio-phone -- env HOME=/home/pajio-phone /usr/bin/adb -s "$adb_serial" install -r "$private_apk" >/dev/null
printf 'Dedicated phone created; boot, app compatibility and media still need verification.\n'
