"""Official Android Platform Tools installer and read-only USB/ADB discovery."""

import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import stat
import subprocess
import urllib.request
import zipfile

VERSION = "37.0.1"
# Published Google repository2-1.xml checksums, verified 2026-10-02.
ARCHIVES = {
    "Darwin": ("darwin", "6ae73f4de6452dc57e62ec02b68eed92a4c21661"),
    "Windows": ("win", "e03e78b1d80b396f1c3358e31251cb31740e1110"),
    "Linux": ("linux", "477254aa5f903c15cf51001717bdf347fb6b53e0"),
}


def adb_path(root):
    local = root / "android/platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
    return str(local) if local.is_file() else shutil.which("adb")


def install(root):
    host, expected = ARCHIVES[platform.system()]
    directory = root / "android"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f"platform-tools_r{VERSION}-{host}.zip"
    url = "https://dl.google.com/android/repository/" + archive.name
    if not archive.is_file() or hashlib.sha1(archive.read_bytes()).hexdigest() != expected:
        partial = archive.with_suffix(".download")
        with urllib.request.urlopen(url, timeout=40) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        if hashlib.sha1(partial.read_bytes()).hexdigest() != expected:
            raise ValueError("Android 工具下载校验失败。")
        partial.replace(archive)
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            target = directory / entry.filename
            if not target.resolve().is_relative_to(directory.resolve()) or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Android 工具包包含不支持的路径。")
        bundle.extractall(directory)
    executable = directory / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
    if os.name != "nt":
        executable.chmod(0o755)
    (directory / "installed.json").write_text(json.dumps({"version": VERSION, "url": url,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "adb": str(executable)}))
    return executable


def usb_inventory():
    if platform.system() != "Darwin":
        return []
    try:
        value = subprocess.run(["/usr/sbin/ioreg", "-r", "-c", "IOUSBHostDevice", "-a"],
                               capture_output=True, timeout=5, check=True)
        # Don't return serial numbers or unrelated kernel diagnostics.
        return [{"name": row.get("USB Product Name", "USB device"), "vendor": row.get("USB Vendor Name", ""),
                 "vendor_id": row.get("idVendor")} for row in plistlib.loads(value.stdout)
                if row.get("USB Vendor Name") and row.get("USB Vendor Name") != "Apple Inc."]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def devices(root):
    # Portable parser is shared with the downloadable doctor.
    from .doctor import parse_adb_devices, run_readonly
    adb = adb_path(root)
    if not adb:
        return {"state": "adb_missing", "devices": [], "usb": usb_inventory()}
    code, output = run_readonly([adb, "devices", "-l"], timeout=10)
    if code:
        return {"state": "adb_failed", "devices": [], "usb": usb_inventory()}
    phones = parse_adb_devices(output)
    for phone in phones:
        if phone["state"] == "device":
            for prop, key in (("ro.product.model", "model"), ("ro.build.version.release", "android_version"), ("ro.build.version.sdk", "sdk_level")):
                _, value = run_readonly([adb, "-s", phone["serial"], "shell", "getprop", prop])
                phone[key] = value or phone.get(key)
    return {"state": "checked", "devices": phones, "usb": usb_inventory() if not phones else []}
