"""Local desktop enrollment; actual control uses Hermes + Cua Driver."""
import json
import sys
from pathlib import Path

from .config import write_private_json


def enrolled(data_dir: Path) -> bool:
    path = data_dir / "computer.json"
    try:
        value = json.loads(path.read_text())
        return isinstance(value, dict) and value.get("enrolled") is True
    except (OSError, ValueError):
        return False


def enroll(data_dir: Path):
    write_private_json(data_dir / "computer.json", {"enrolled": True, "resource_id": "computer_local", "backend": "linux-x11" if sys.platform.startswith('linux') else "hermes-cua"})
