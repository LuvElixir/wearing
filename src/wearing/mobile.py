"""A bound phone resource; control is supplied by upstream Mobile MCP."""

import json
import hashlib
import os
from pathlib import Path

VERSION = "1.0.7"
PACKAGE = Path(__file__).parent / "connectors/mobile"
TOOLS = ("mobile_get_screen_size", "mobile_list_apps", "mobile_list_elements_on_screen",
         "mobile_take_screenshot", "mobile_click_on_screen_at_coordinates", "mobile_swipe_on_screen",
         "mobile_type_keys", "mobile_press_button", "mobile_launch_app")
EXTRA_TOOLS = ("mobile_list_devices", "mobile_set_text")
ALL_TOOLS = TOOLS + EXTRA_TOOLS
U2_VERSION = "3.7.0"
U2_PACKAGE = Path(__file__).parent / "connectors/android-u2"


def resource_id(serial):
    return "phone_" + hashlib.sha256(serial.encode()).hexdigest()[:20]


def installed(root):
    try:
        data = json.loads((root / "mobile/installed.json").read_text())
        if data["version"] == VERSION and Path(data["node"]).is_file() and (root / "mobile/node_modules/@mobilenext/mobile-mcp/lib/index.js").is_file():
            return data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


class RegistryError(ValueError):
    pass


def registry(data_dir):
    path = data_dir / "phone.json"
    if path.is_symlink():
        raise RegistryError("手机配置不能使用符号链接。")
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError()
        if value.get("schema_version") == 2:
            records = value["devices"]
            if not isinstance(records, dict):
                raise ValueError()
            for key, record in records.items():
                if not isinstance(record, dict) or not isinstance(record.get("serial"), str) or not record["serial"] or key != resource_id(record["serial"]) or record.get("resource_id") != key or not isinstance(record.get("enabled"), bool):
                    raise ValueError()
            if value.get("selected") is not None and value["selected"] not in records:
                raise ValueError()
            return value
        if isinstance(value.get("serial"), str) and isinstance(value.get("enabled"), bool):
            rid = resource_id(value["serial"])
            record = {**value, "resource_id": rid, "platform": "android"}
            return {"schema_version": 2, "selected": rid, "devices": {rid: record}}
        raise ValueError()
    except FileNotFoundError:
        return {"schema_version": 2, "selected": None, "devices": {}}
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise RegistryError("手机配置无法读取，原记录已保留。") from error


def binding(data_dir):
    data = registry(data_dir)
    return data["devices"].get(data["selected"])


def u2_python(root):
    return root / "android-u2" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def u2_installed(root):
    try:
        marker = json.loads((root / "android-u2/installed.json").read_text())
        return u2_python(root).is_file() and marker["requirements_sha256"] == hashlib.sha256((U2_PACKAGE / "requirements.txt").read_bytes()).hexdigest()
    except (OSError, ValueError, KeyError):
        return False


def read_capabilities(data_dir, rid):
    try:
        return json.loads((data_dir / "runtime/mobile" / rid / "capabilities.json").read_text())
    except (OSError, ValueError):
        return {}


def configuration(root, python):
    if not installed(root) or not registry(root.parent)["devices"]:
        return None
    return {"command": str(python), "args": [str(Path(__file__).with_name("phone_proxy.py")), str(root.parent)],
            "tools": {"include": list(ALL_TOOLS), "resources": False, "prompts": False}}
