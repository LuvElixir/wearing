"""Pin an already initialized lab VM's NoCloud identity before editing userdata.

Run on the Proxmox host. Does not create a VM or inject a password. Metadata
snippets MUST travel with host configuration backups; vzdump alone does not
make this external snippet portable to another hypervisor.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess


def output(*args):
    return subprocess.check_output(args, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vmid", type=int, required=True)
    parser.add_argument("--hostname", required=True)
    args = parser.parse_args()
    if args.vmid < 100 or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", args.hostname):
        parser.error("Invalid VM ID or hostname")
    vmid = str(args.vmid)
    config = dict(line.split(": ", 1) for line in output("qm", "config", vmid).splitlines()
                  if ": " in line and not line.startswith("#"))
    if config.get("name") != args.hostname or config.get("template") == "1":
        raise RuntimeError("VM name must match; templates are not initialized guests")
    state = json.loads(output("qm", "guest", "exec", vmid, "--",
                              "cloud-init", "status", "--format", "json"))
    if state.get("exitcode") != 0 or json.loads(state["out-data"]).get("status") != "done":
        raise RuntimeError("Wait for successful cloud-init completion first")
    result = json.loads(output("qm", "guest", "exec", vmid, "--",
                               "cat", "/var/lib/cloud/data/instance-id"))
    if result.get("exitcode") != 0:
        raise RuntimeError("Could not read authenticated guest instance identity")
    instance = result["out-data"].strip()
    if not 8 < len(instance) < 128 or any(ord(c) < 32 for c in instance):
        raise RuntimeError("Unexpected guest instance identity")
    custom = dict(item.split("=", 1) for item in config.get("cicustom", "").split(",") if item)
    path = Path("/var/lib/vz/snippets") / f"pajio-{vmid}-meta.yaml"
    reference = "local:snippets/" + path.name
    if custom.get("meta", reference) != reference:
        raise RuntimeError("Refusing to replace another metadata provider")
    data = f"instance-id: {json.dumps(instance)}\nlocal-hostname: {args.hostname}\n"
    if path.exists() and path.read_text() != data:
        raise RuntimeError("Existing pinned identity differs; inspect before changing it")
    path.parent.mkdir(exist_ok=True)
    path.write_text(data)
    path.chmod(0o600)
    custom["meta"] = reference
    output("qm", "set", vmid, "--cicustom", ",".join(f"{k}={v}" for k, v in custom.items()))
    print(f"VM {vmid}: current cloud-init identity pinned; reboot and verify SSH identity")


if __name__ == "__main__":
    main()
