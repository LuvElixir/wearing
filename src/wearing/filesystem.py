"""Pinned upstream filesystem connector configuration, kept out of the agent loop."""

import json
from pathlib import Path

VERSION = "2026.8.31"
TOOLS = ("read_text_file", "write_file", "create_directory", "list_directory", "get_file_info", "list_allowed_directories")
PACKAGE = Path(__file__).parent / "connectors" / "filesystem"


def configuration(root: Path, workspace: Path):
    marker = root / "filesystem" / "installed.json"
    try:
        info = json.loads(marker.read_text())
        node = Path(info["node"])
        entry = root / "filesystem/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
        if info["version"] != VERSION or not node.is_file() or not entry.is_file() or workspace.is_symlink():
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {"command": str(node), "args": [str(entry), str(workspace)],
            "tools": {"include": list(TOOLS), "resources": False, "prompts": False}}
