"""Immutable, operator-created tenant instance state, not a VM provisioner."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlparse
import uuid

from filelock import FileLock
from pydantic import AwareDatetime, Field, field_validator

from .commands import Identifier, Record
from ..config import private_directory, write_private_json
from ..profile import write_private_text
from ..runtime import HERMES_REVISION


class InstanceError(ValueError):
    pass


class TenantInstance(Record):
    schema_version: int = Field(default=1, ge=1, le=1, strict=True)
    tenant_id: Identifier
    instance_id: Identifier
    public_origin: str
    hermes_revision: str = HERMES_REVISION
    created_at: AwareDatetime

    @field_validator("public_origin")
    @classmethod
    def origin(cls, value):
        url = urlparse(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                or url.path not in {"", "/"} or url.query or url.fragment or "*" in url.netloc
                or any(ord(c) < 33 or ord(c) > 126 for c in value)):
            raise ValueError("Use a single browser origin without credentials or path")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("Invalid origin port")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Public browser origin must use HTTPS")
        return value.rstrip("/")

    @field_validator("hermes_revision")
    @classmethod
    def pinned_engine(cls, value):
        if value != HERMES_REVISION:
            raise ValueError("This instance requires a different engine release")
        return value


def checked_root(root: Path):
    root = root.expanduser().absolute()
    if root.is_symlink():
        raise InstanceError("实例目录不能是符号链接。")
    return root.resolve()


def read_private(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise InstanceError("实例配置缺失或不安全；原数据未改动。")
    if os.name != "nt" and (path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid()):
        raise InstanceError("实例配置必须由当前用户私有保存。")
    return path.read_text(encoding="utf-8")


def load_instance(root: Path):
    root = checked_root(root)
    try:
        instance = TenantInstance.model_validate_json(read_private(root / "instance.json"))
        key = read_private(root / "gateway.key").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{64}", key):
            raise ValueError("Invalid internal credential")
        data = root / "data"
        if data.is_symlink() or not data.is_dir():
            raise ValueError("Invalid private data directory")
        if os.name != "nt" and (data.stat().st_mode & 0o077 or data.stat().st_uid != os.getuid()):
            raise ValueError("Private data directory permissions")
        owner = json.loads(read_private(data / "instance-owner.json"))
        if owner != {"tenant_id": instance.tenant_id, "instance_id": instance.instance_id}:
            raise ValueError("Data volume belongs to a different instance")
    except (OSError, ValueError) as error:
        raise InstanceError("实例配置或私有卷归属校验失败；没有启动或改写数据。") from error
    return instance


def initialize_instance(root: Path, tenant_id: str, public_origin: str):
    root = checked_root(root)
    try:
        desired = TenantInstance(tenant_id=tenant_id, instance_id="instance_" + uuid.uuid4().hex,
                                 public_origin=public_origin, created_at=datetime.now(timezone.utc))
    except ValueError as error:
        raise InstanceError("租户编号或网页来源格式不正确。") from error
    root.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(root.parent / ("." + root.name + ".wearing-init.lock"), timeout=5):
        if root.exists() and any(root.iterdir()):
            current = load_instance(root)
            if current.tenant_id != desired.tenant_id or current.public_origin != desired.public_origin:
                raise InstanceError("已有实例不能改成另一个租户或网页来源；请使用独立新目录。")
            return current
        private_directory(root)
        private_directory(root / "data")
        write_private_text(root / "gateway.key", secrets.token_urlsafe(48) + "\n")
        write_private_json(root / "data/instance-owner.json", {"tenant_id": desired.tenant_id, "instance_id": desired.instance_id})
        write_private_json(root / "instance.json", desired.model_dump(mode="json"))
        return desired


def instance_status(root: Path):
    instance = load_instance(root)
    return {"tenant_id": instance.tenant_id, "instance_id": instance.instance_id,
            "public_origin": instance.public_origin, "hermes_revision": instance.hermes_revision,
            "mode": "tenant-worker", "hardware_isolation_verified": False,
            "note": "实例归属已固定；VM/microVM 与网络隔离需要提供商实测。"}
