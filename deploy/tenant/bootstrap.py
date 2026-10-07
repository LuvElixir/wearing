"""Run as root in a fresh trial Linux VM, with a verified uploaded release.

The operator supplies the *new* cloud data disk ID; the guest must independently
match its serial before formatting. Refuse existing filesystems/volumes and
unrelated installations. Model credentials and user data are not included.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def serial(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--service", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or not Path("/etc/os-release").read_text().startswith("PRETTY_NAME=\"Ubuntu 24.04"):
        raise RuntimeError("Bootstrap requires the new Ubuntu 24.04 VM and root.")
    context = json.loads(args.context.read_text())
    if set(context) != {"deployment_id", "tenant_id", "origin", "data_disk_id", "data_disk_gib", "wheel_sha256"}:
        raise RuntimeError("Unexpected deployment context")
    if not re.fullmatch(r"[0-9a-f]{32}", context["deployment_id"]) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}", context["tenant_id"]):
        raise RuntimeError("Invalid fixed deployment identity")
    if hashlib.sha256(args.wheel.read_bytes()).hexdigest() != context["wheel_sha256"]:
        raise RuntimeError("Release checksum mismatch")
    state = Path("/etc/wearing/trial-context.json")
    if state.exists():
        if json.loads(state.read_text()) != context:
            raise RuntimeError("Existing VM belongs to a different deployment")
        if Path("/var/lib/wearing/instance/instance.json").exists():
            raise RuntimeError("Already provisioned: inspect service/data, do not replay bootstrap")
    else:
        if Path("/opt/wearing/venv").exists() or Path("/var/lib/wearing").exists():
            raise RuntimeError("Refusing to adopt an unrelated existing installation")
        state.parent.mkdir(mode=0o700, exist_ok=True)
        state.write_text(json.dumps(context, indent=2)); state.chmod(0o600)
    status = Path("/etc/wearing/bootstrap-status.json")
    def phase(name, **fields):
        status.write_text(json.dumps({"phase": name, **fields}, indent=2)); status.chmod(0o600)
    phase("validating_data_volume")
    disks = json.loads(run("lsblk", "-J", "-b", "-o", "NAME,TYPE,SIZE,SERIAL,MOUNTPOINTS"))["blockdevices"]
    matches = [d for d in disks if d["type"] == "disk" and serial(d.get("serial")) == serial(context["data_disk_id"])]
    if len(matches) != 1:
        raise RuntimeError("Cloud disk ID must match exactly one guest disk serial")
    disk = matches[0]; device = "/dev/" + disk["name"]
    if int(disk["size"]) != context["data_disk_gib"] * 1024 ** 3 or disk.get("children") or any(disk.get("mountpoints") or []):
        raise RuntimeError("Data volume is not the expected empty whole disk")
    probe = subprocess.run(["blkid", "-p", device], capture_output=True, text=True)
    if probe.returncode != 2 or probe.stdout.strip():
        raise RuntimeError("Refusing to format an existing or ambiguous filesystem")
    run("mkfs.ext4", "-q", "-m", "0", "-L", "wearing" + context["deployment_id"][:8], device)
    fsuuid = run("blkid", "-s", "UUID", "-o", "value", device)
    home = Path("/var/lib/wearing"); home.mkdir(mode=0o700)
    fstab = Path("/etc/fstab")
    if any("/var/lib/wearing" in line and not line.lstrip().startswith("#") for line in fstab.read_text().splitlines()):
        raise RuntimeError("Existing mount configuration must be inspected")
    with fstab.open("a") as stream:
        stream.write("\nUUID=" + fsuuid + " /var/lib/wearing ext4 defaults,nodev,nosuid 0 2\n")
    run("mount", "/var/lib/wearing")
    if run("findmnt", "-n", "-o", "UUID", "--target", str(home)) != fsuuid:
        raise RuntimeError("Mounted volume does not match data filesystem")
    phase("installing_wearing", data_volume_mounted=True)
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get", "update", "-qq")
    run("apt-get", "install", "-y", "-qq", "python3-venv", "ca-certificates", "curl", "git")
    try: user = pwd.getpwnam("wearing")
    except KeyError:
        run("useradd", "--system", "--home-dir", str(home), "--shell", "/usr/sbin/nologin", "wearing")
        user = pwd.getpwnam("wearing")
    if user.pw_dir != str(home): raise RuntimeError("Existing service user has an unrelated home")
    os.chown(home, user.pw_uid, user.pw_gid); home.chmod(0o700)
    run("python3", "-m", "venv", "/opt/wearing/venv")
    python = "/opt/wearing/venv/bin/python"
    run(python, "-m", "pip", "install", "--disable-pip-version-check", str(args.wheel.resolve()))
    # Bootstrap runs with umask 077. Code remains root-owned, but the service
    # group needs to traverse/read the venv and execute its entry points.
    run("chgrp", "-R", "wearing", "/opt/wearing/venv")
    run("chmod", "-R", "g+rX", "/opt/wearing/venv")
    cli = "/opt/wearing/venv/bin/wearing"
    run("runuser", "-u", "wearing", "--", cli, "tenant", "init", "--root", str(home / "instance"),
        "--tenant-id", context["tenant_id"], "--origin", context["origin"])
    shutil.copyfile(args.service, "/etc/systemd/system/wearing-tenant.service")
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", "--now", "wearing-tenant.service")
    phase("installing_hermes", data_volume_mounted=True, wearing_service_active=True)
    run("runuser", "-u", "wearing", "--", cli, "engine", "install", "--data-dir", str(home / "instance/data"))
    phase("installing_file_tools", data_volume_mounted=True, wearing_service_active=True)
    run("runuser", "-u", "wearing", "--", python, "-c",
        "import asyncio; from pathlib import Path; from wearing.runtime import HermesRuntime; "
        "r=HermesRuntime(Path('/var/lib/wearing/instance/data'),local_devices=False); "
        "asyncio.run(r.install_filesystem()); assert r.files_phase=='ready',r.files_error")
    run("systemctl", "restart", "wearing-tenant.service")
    phase("installed_needs_model", data_volume_mounted=True, wearing_service_active=True,
          model_credentials_copied=False, hardware_isolation_verified=False)
    print(json.dumps({"phase": "installed_needs_model", "data_volume_mounted": True,
                      "wearing_service_active": run("systemctl", "is-active", "wearing-tenant.service") == "active"}))


if __name__ == "__main__":
    try: main()
    except Exception:
        # Detailed diagnostic stays in a root-owned log. No automatic formatting
        # retries or cleanup after a partial failure; inspect the recorded stage.
        import traceback
        Path('/etc/wearing').mkdir(mode=0o700, exist_ok=True)
        with Path("/etc/wearing/bootstrap-error.log").open("a") as log: traceback.print_exc(file=log)
        Path("/etc/wearing/bootstrap-error.log").chmod(0o600)
        raise SystemExit("Bootstrap stopped. Inspect private status/error; do not rerun formatting.")
