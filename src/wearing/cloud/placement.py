"""Offline cloud selection, not a cloud client or permission to spend money."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .commands import Identifier, Record


Location = Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9-]{1,62}$")]


class Provider(Record):
    id: Identifier
    name: str
    service: str
    phase: Literal["first_validation", "core_coverage", "later_coverage"]
    account_scopes: tuple[str, ...]
    provider_plugin: str | None
    create_api: str
    stop_note: str
    sources: tuple[str, ...]


class Catalog(Record):
    schema_version: Literal[1]
    reviewed_on: str
    providers: tuple[Provider, ...]


def catalog():
    return Catalog.model_validate_json(Path(__file__).with_name("providers.json").read_text())


def provider(provider_id):
    for item in catalog().providers:
        if item.id == provider_id:
            return item
    raise ValueError("未知云服务商。")


class VMSelection(Record):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    provider_id: Identifier
    # These are logical references, not cloud keys, login profiles or authority.
    account_ref: Identifier
    ownership: Literal["customer", "wearing"]
    account_scope: str
    region: Location
    vcpu: int = Field(default=2, strict=True, ge=1, le=128)
    memory_gib: int = Field(default=4, strict=True, ge=1, le=512)
    system_disk_gib: int = Field(default=40, strict=True, ge=20, le=2048)
    data_disk_gib: int = Field(default=40, strict=True, ge=20, le=16384)
    architecture: Literal["x86_64"] = "x86_64"
    os: Literal["ubuntu-24.04"] = "ubuntu-24.04"
    isolation: Literal["vm"] = "vm"
    billing: Literal["on-demand", "monthly"] = "on-demand"

    @model_validator(mode="after")
    def scope_matches(self):
        item = provider(self.provider_id)
        if self.billing == "monthly" and item.id != "tencent":
            raise ValueError("包月配置目前仅在腾讯云首轮适配中提供；其他厂商需分别验收。")
        if self.account_scope not in item.account_scopes:
            raise ValueError("云账户环境与服务商不匹配。")
        if item.id == "aws" and (self.region.startswith("cn-") != (self.account_scope == "aws-cn")):
            raise ValueError("AWS 中国区与全球区需要分别选择账户分区。")
        if item.id == "azure" and (self.region.startswith("china") != (self.account_scope == "china")):
            raise ValueError("Azure 中国与公共环境需分别选择。")
        return self


def preview(selection: VMSelection):
    item = provider(selection.provider_id)
    canonical = json.dumps(selection.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return {
        "mode": "offline_selection",
        "request": selection.model_dump(mode="json"),
        "configuration_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "provider": item.model_dump(mode="json"),
        "implementation_status": "planned",
        "adapter_installed": False,
        "credentials_checked": False,
        "quote": None,
        "ready_to_provision": False,
        "hardware_isolation_verified": False,
        "creates_resources": False,
        "persistent_data": {"private_volume_required": True, "delete_with_vm": False, "backup_verified": False},
        "checks_remaining": [
            "账户授权、凭据保管与最小权限",
            "区域/可用区、实际镜像、规格、库存与配额",
            "按量计算、磁盘、快照、公网地址和流量的完整报价与支出授权",
            "受版本锁定的提供商插件与部署模板验收",
            "独立 VM/数据卷与拒绝跨租户网络访问",
            "安装 Pajio、健康检查与真实用户绑定",
            "排空运行、备份、停止、重新启动及恢复到新实例",
            "账单核对、孤儿资源回收和用户退出流程"
        ],
    }
