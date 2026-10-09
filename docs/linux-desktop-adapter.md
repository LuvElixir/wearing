# Linux desktop adapter

This is an independently implemented X11/AT-SPI backend for Pajio's existing
computer MCP and connector. It is not a general shell tool, a VM provisioner,
or a replacement for DeviceGateway, DesktopFrames, or the private media host.

## Runtime contract

- `LinuxComputerBackend(environment=...).dispatch(args)` returns a JSON string.
  Reuse one backend instance per MCP session.
- `status()` returns a readiness dictionary. Successful module import alone does
  not establish readiness: X11, its user session bus, dependencies and AT-SPI must
  be available.
- `set_approval_callback(callback)` is supplied by `DesktopFrames` for one input.
  The input consumes the most recent capture even when validation or execution
  fails. A new observation and approval are required to try again.
- Dispatch actions are `status`, `list_apps`, `list_windows`, `capture`, `click`,
  `set_value`, `type`, `key`, and `scroll`. There is no URL, shell, arbitrary
  subprocess, coordinate-click, or foreground-switch action.
- `app` is the exact `WM_CLASS` returned by discovery, not a guessed display name.
  Multiple matching windows require `window_id` **and** `pid` in capture args.
  Only the selected foreground window is admitted.
- Capture returns `app`, `window_id`, `pid`, `window_title`, `target`, `origin`,
  `width`, `height`, `elements`, `accessibility_text`, `snapshot_id`, and
  `screenshot: {mime_type: "image/png", data: "<base64>"}`. The MCP wrapper must
  remove `screenshot` from the text block and emit it as image content. Never
  put it in logs, command arguments, or ordinary diagnostics.
- PNG size is the selected window's client rectangle in X11 pixels. Element
  bounds are `[x, y, width, height]` relative to that same rectangle; `origin`
  gives its desktop offset. There is no device-pixel-ratio conversion or resizing.

The helper process uses `/usr/bin/python3`, which has Ubuntu's GI/AT-SPI modules.
The managed model environment does not need those modules. Inputs are JSON on
stdin; typed text is sent to `xdotool` on stdin. Neither the typed text nor native
stderr is returned by input results. Helper exceptions return fixed error codes.
Timeout/cancellation kills and reaps the whole helper process group before its
caller releases the native-action lock.

## Required ownership composition

The trusted computer proxy must resolve the persisted `computer_id` from
`connector-id.json`, using the existing legacy ID only where that legacy binding
already applies. The same ID must be used by the relay, private media host and
DeviceGateway.

For every native dispatch:

```python
permit = gateway.permit_agent(resource_id)
with gateway.native_lock(resource_id):
    gateway.validate_agent(permit)
    result = backend.dispatch(args)
    gateway.validate_agent(permit)
    return result
```

The helper must not reacquire that lock. If the second validation fails, discard
the result, including screenshots. A pending human takeover fences further
actions and does not expose private media before the existing action drains.
`DesktopFrames` remains outside dispatch to enforce lease epoch, capture age,
element identity, approved parameter hash and one-use approval. The native helper
additionally binds its current AT-SPI view to window ID, PID, origin, size and
title, and checks the foreground again immediately before input.

## Ubuntu 24.04 Xfce host

Provision a separate desktop user and X11 session for each isolated device VM.
The initial integration target is `pajio-desktop`, `DISPLAY=:10`. These are
deployment choices, not hard-coded identities in the backend.

Packages required by the backend:

```text
python3-pyatspi python3-gi at-spi2-core xdotool imagemagick x11-utils dbus-x11
```

The desktop session itself also needs Xfce/X11 and the desired applications.
Supply the session's `DISPLAY`, `XAUTHORITY`, `DBUS_SESSION_BUS_ADDRESS`,
`XDG_RUNTIME_DIR`, and `XDG_SESSION_TYPE=x11` to the connector and managed proxy.
The bus and display must belong to the same user. Do not connect the agent to the
Proxmox host desktop or another tenant's display. For Chromium, enable renderer
accessibility with `--force-renderer-accessibility`; the actual resulting tree
must still pass a live test. GTK applications must have their accessibility bridge
enabled. Readiness checks do not assert every application's accessibility support.

Wayland is explicitly unsupported in this adapter. Missing or ambiguous AT-SPI
targets fail closed instead of returning a successful empty UI tree. Capture or
input with a focused AT-SPI password field asks for private human handoff. Other
password fields have their accessible label and value redacted. This detects
standard accessible password roles; it is not a generic detector for every
custom-drawn sensitive screen or a password-manager implementation.

Clicks use the selected node's AT-SPI action. Edits use EditableText. Keyboard
input uses XTEST on the verified foreground, because many apps discard
XSendEvent. Scroll moves the pointer to the captured window center before sending
the bounded wheel event. Actions report native submission; only the next observed
application state establishes the result. No automatic input retry is performed.

## User service lifecycle

Once pairing is complete, use the existing connector command:

```text
python -m wearing.cli connector service install --root /absolute/connector/root
python -m wearing.cli connector service status --root /absolute/connector/root
python -m wearing.cli connector service stop --root /absolute/connector/root
python -m wearing.cli connector service start --root /absolute/connector/root
python -m wearing.cli connector service uninstall --root /absolute/connector/root
```

The Linux implementation writes a private unit under
`~/.config/systemd/user/com.wearing.connector.<root-hash>.service`, then enables it
with `systemctl --user`. It must be installed from the intended desktop user's
session, with that user's systemd bus available. It does not elevate privileges,
enable lingering, install packages or start a desktop. Provision the user bus and
desktop startup separately if this VM must remain available without an SSH login.

Only an allowlist of session environment variables is saved. Pairing credentials
remain in the existing private connector directory. Standard output/error are not
persisted in the journal; use structured connector `status.json` and action
receipts for diagnosis. Unit argument quoting preserves spaces and literal `%`/
`$`, and rejects control characters. There is no shell command in `ExecStart`.

Definition hashes, effective FragmentPath and absence of drop-ins are checked
before lifecycle changes. Existing or changed units are not overwritten. An
interrupted registration retains a private pending manifest so `install` can
finish the same owned definition. Explicit stopped intent survives installation
and restart. Stop lets the current action and receipt finish. Uninstall refuses
to kill a busy runner and retains pairing, local data and action history.

## Reproducible desktop VM provisioning

The files in `deploy/on-prem/` provide the separate host/session layer:

1. Install the listed Ubuntu packages plus `xvfb xauth xfce4 fonts-noto-cjk
   locales ibus ibus-libpinyin` inside the dedicated desktop VM.
2. Stage `setup-linux-desktop.sh`, `start-x11.sh`, `wait-x11.sh`,
   `start-desktop-session.sh`, both `pajio-x11.service` and
   `pajio-desktop-session.service`, and the two Python adapter files together.
   Run the setup script as the VM administrator. It creates a non-login desktop
   account without privileged groups and enables its user service manager at boot.
3. `install-mozilla-firefox.sh` validates Mozilla's published signing-key
   fingerprint, installs a scoped APT repository/pin, and installs official Firefox
   plus Chinese localization. It does not disable package verification. If a
   repository transfer fails, a package fetched from the same official URL can be
   transferred through the existing admin channel after its SHA-256 matches the
   VM's signed APT metadata, then installed through APT's cache.
4. Stage `enable-linux-browser.sh`, `pajio-browser.service` and
   `pajio-firefox.user.js` together. Run the enabling script to seed a fresh profile
   (existing profile preferences are preserved) and start Firefox with a blank tab.
5. Deploy the Pajio native Python environment and connector separately. Model keys
   and a tenant's general-purpose Agent process do not belong in this account.

Xvfb is `:10`, 1280×800, 24-bit; TCP listening is disabled and the fresh per-start
MIT-MAGIC-COOKIE goes only through stdin into the private Xauthority file.
Xfce runs under `dbus-run-session` using the distribution session-bus policy with
one stable Unix socket. For the first account (UID 1001), native drivers and media
hosts receive:

```text
HOME=/home/pajio-desktop
DISPLAY=:10
XAUTHORITY=/run/user/1001/pajio-x11/Xauthority
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/pajio-desktop-bus
XDG_RUNTIME_DIR=/run/user/1001
XDG_SESSION_TYPE=x11
```

Service-management commands must instead address the standard **user manager**
bus, `unix:path=/run/user/1001/bus`. `ConnectorService.systemd()` explicitly uses
that bus while retaining the desktop bus in the connector's native environment.
The UID comes from the provisioned account, not from a tenant-supplied request.

`linux-native-probe.html` and `probe-linux-native.py` are synthetic host acceptance
fixtures, not product screens. Open the local fixture in the dedicated Firefox
window, then run the probe as the desktop user with the above environment and a
private `--output` directory. It refuses other window titles and exercises native
read/edit/keyboard/click/scroll through the real helper. Its local one-use callback
is limited to this provisioning test and does not establish end-to-end relay
approval, ownership, or private-media acceptance.

## Acceptance evidence

Automated tests exercise real adapter logic with controlled native/AT-SPI
responses: window ambiguity/PID, coordinate agreement, mid-capture movement,
stale text/geometry/focus, password redaction, input approval consumption,
DesktopFrames epoch invalidation, key injection refusal, stdin-only typing, user
unit ownership/tampering, stopped intent, graceful drain and registration retry.
A POSIX subprocess test verifies a timed-out helper cannot leave a native child
to perform a later action.

Before production readiness, the provisioning owner must also verify on the VM:
live Xfce application discovery; an actual PNG and matching AT-SPI bounds; one
approved edit reflected in a subsequent read; human takeover with no Agent
screen/input access; network reconnection; and service start after reboot. The
unit tests do not claim that those host-level checks have already passed.

Implementation references, not copied code:
[systemd service syntax](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml),
[systemd environment syntax](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml),
[xdotool XTEST/XSendEvent notes](https://github.com/jordansissel/xdotool/blob/master/xdotool.pod).
