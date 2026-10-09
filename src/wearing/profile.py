"""Versioned Pajio product profile, separate from the pinned upstream source."""

import ast
import hashlib
import json
import os
from pathlib import Path

import yaml

from .config import private_directory, write_private_json

PROFILE_VERSION = 24
ENGINE_MODE = "wearing-personal"
IDENTITY_PATH = Path(__file__).with_name("identity.md")


class ProfileError(Exception):
    pass


def identity_text():
    return IDENTITY_PATH.read_text(encoding="utf-8").strip()


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_private_text(path, text):
    private_directory(path.parent)
    temp = path.with_name(path.name + ".wearing-tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    temp.replace(path)


def upstream_default_identity(source):
    """Read a literal from the pinned source without importing third-party code."""
    path = source / "hermes_cli" / "default_soul.py"
    if not path.is_file():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DEFAULT_SOUL_MD" for t in node.targets):
            return ast.literal_eval(node.value).strip()
    return None


def prepare_profile(home: Path, source: Path, filesystem=None, phone=None, computer=False, remote=None, life=None):
    """Migrate only owned product fields, preserving credentials and custom config.

    Existing custom SOUL files are never silently replaced. Backups contain private
    user config and inherit private permissions; they are not evidence artifacts.
    """
    private_directory(home)
    config_path, soul_path, manifest_path = (home / n for n in ("config.yaml", "SOUL.md", "wearing-profile.json"))
    for path in (config_path, soul_path, manifest_path):
        if path.is_symlink():
            raise ProfileError("Pajio 配置不能指向其他目录；原配置未改动。")
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else "{}"
    try:
        config = yaml.safe_load(original) or {}
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if not isinstance(config, dict) or not isinstance(manifest, dict):
            raise ValueError()
    except (ValueError, yaml.YAMLError) as error:
        raise ProfileError("本地配置格式无法读取；请先检查配置，原文件已保留。") from error
    soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
    wanted = identity_text() + "\n"
    owned = not soul.strip() or soul.strip() in (identity_text(), upstream_default_identity(source)) or digest(soul) == manifest.get("identity_sha256")
    if not owned:
        raise ProfileError("发现你自定义的 SOUL.md，未覆盖。请先合并 Pajio 身份设定后再启动。")

    # These fields belong to this product release, not to provider/model setup.
    toolsets = ["memory", "session_search", "web", "todo", "skills", "vision"] + (["wearing_files"] if filesystem else []) + (["wearing_phone"] if phone else []) + (["computer_use"] if computer else []) + (["wearing_devices"] if remote else []) + (["wearing_life"] if life else [])
    changes = {
        "platform_toolsets": {"api_server": toolsets or ["no_mcp"], "cli": ["no_mcp"]},
        "auxiliary": {"background_review": {"enabled": False}, "title_generation": {"enabled": False, "model_upgrade_enabled": False}},
        "curator": {"enabled": False},
        "skills": {"project_discovery": False, "external_dirs": [], "auto_load": []},
        "sessions": {"auto_prune": False},
        "gateway": {"api_server": {"max_concurrent_runs": 1}},
    }
    if computer:
        # A local personal desktop keeps upstream's standard approval boundary.
        changes["computer_use"] = {"permission_mode": "standard", "capture_after_mode": "ax", "cua_telemetry": False}
        changes["approvals"] = {"mode": "manual"}

    def merge(dst, patch):
        for key, value in patch.items():
            if isinstance(value, dict):
                if key not in dst:
                    dst[key] = {}
                if not isinstance(dst[key], dict):
                    raise ProfileError(f"配置字段 {key} 格式不正确；原文件已保留。")
                merge(dst[key], value)
            else:
                dst[key] = value

    # A new installation starts on the upstream anonymous tier. Preserve an
    # explicitly selected provider, tier or key configuration on migration.
    if "web" not in config:
        config["web"] = {"backend": "exa", "provider_tier": {"exa": "free"}}
    merge(config, changes)
    if filesystem or phone or remote or life:
        servers = config.setdefault("mcp_servers", {})
        if not isinstance(servers, dict):
            raise ProfileError("文件连接器配置格式不正确，原配置已保留。")
        if filesystem:
            servers["wearing_files"] = filesystem
        if phone:
            servers["wearing_phone"] = phone
        if remote:
            servers["wearing_devices"] = remote
        if life:
            servers["wearing_life"] = {**life, "timeout": 360,
                                       "elicitation": {"enabled": True, "timeout": 300}}
    if not remote and isinstance(config.get("mcp_servers"), dict):
        config["mcp_servers"].pop("wearing_devices", None)
    rendered = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    backup_dir = home / "wearing-backups"
    for path, before, after in ((config_path, original, rendered), (soul_path, soul, wanted)):
        if before != after:
            if path.exists():
                backup = backup_dir / f"{path.name}.{digest(before)[:16]}"
                if not backup.exists():
                    write_private_text(backup, before)
            write_private_text(path, after)
    result = {"version": PROFILE_VERSION, "mode": ENGINE_MODE, "identity_sha256": digest(wanted), "toolsets": toolsets,
              "background_review": False, "messaging_gateway": False, "scheduler": False}
    write_private_json(manifest_path, result)
    return result
