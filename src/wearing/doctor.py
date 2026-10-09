"""Portable read-only device inventory; never installs software or pairs a device."""

import platform
import shutil
import subprocess
from datetime import datetime, timezone


def parse_adb_devices(output: str) -> list[dict]:
    devices = []
    for line in output.splitlines():
        fields = line.strip().split()
        if len(fields) < 2 or fields[0] in {"List", "*", "adb:"}:
            continue
        if fields[1] not in {"device", "offline", "unauthorized", "recovery", "sideload"}:
            continue
        attributes = dict(x.split(":", 1) for x in fields[2:] if ":" in x)
        devices.append({"serial": fields[0], "state": fields[1], "model": attributes.get("model", "Android")})
    return devices


def run_readonly(args: list[str], timeout: int = 5):
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return completed.returncode, completed.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


def inspect_host(include_android: bool = False) -> dict:
    commands = {name: bool(shutil.which(name)) for name in ("hermes", "adb", "scrcpy", "node", "npx", "ssh")}
    result = {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "scope": "machine_running_this_command",
        "system": platform.system(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "commands": commands,
        "phones": [],
        "phone_check": "not_requested",
        "desktop_control": "not_tested",
    }
    if include_android:
        if not commands["adb"]:
            result["phone_check"] = "adb_missing"
        else:
            code, output = run_readonly([shutil.which("adb"), "devices", "-l"])
            result["phone_check"] = "checked" if code == 0 else "adb_failed"
            if code == 0:
                result["phones"] = parse_adb_devices(output)
                for phone in result["phones"]:
                    if phone["state"] == "device":
                        for prop, key in [("ro.build.version.release", "android_version"), ("ro.build.version.sdk", "sdk_level")]:
                            _, value = run_readonly([shutil.which("adb"), "-s", phone["serial"], "shell", "getprop", prop])
                            phone[key] = value or None
    return result


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Pajio 设备检测；仅检查运行命令的电脑与 USB 手机")
    parser.add_argument("--android", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    content = json.dumps(inspect_host(args.android), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(content + "\n", encoding="utf-8")
    else:
        print(content)
