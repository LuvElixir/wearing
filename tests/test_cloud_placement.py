import json
from pathlib import Path
import subprocess
import sys

import pytest

from wearing.cloud.placement import VMSelection, preview


def selection(**changes):
    return VMSelection(tenant_id="tenant_A", provider_id="aws", account_ref="account_example",
                       ownership="customer", account_scope="aws", region="ap-southeast-1", **changes)


@pytest.mark.parametrize("provider_id,scope,region", [
    ("aws", "aws", "cn-north-1"),
    ("aws", "aws-cn", "ap-southeast-1"),
    ("azure", "public", "chinaeast3"),
    ("azure", "china", "eastasia"),
    ("gcp", "china", "asia-east1"),
    ("unknown", "global", "region-one"),
])
def test_wrong_account_partition_and_unknown_provider_are_rejected(provider_id, scope, region):
    with pytest.raises(ValueError):
        VMSelection(tenant_id="tenant_A", provider_id=provider_id, account_ref="example",
                    ownership="customer", account_scope=scope, region=region)


@pytest.mark.parametrize("changes", [
    {"access_key": "secret"}, {"password": "secret"}, {"user_data": "model keys"},
    {"isolation": "container"}, {"billing": "spot"}, {"vcpu": True}, {"memory_gib": 0},
])
def test_preview_does_not_accept_credentials_or_change_isolation(changes):
    data = selection().model_dump()
    with pytest.raises(ValueError):
        VMSelection.model_validate({**data, **changes})


def test_configuration_changes_cannot_be_treated_as_same_deployment():
    request = selection()
    first = preview(request)
    assert preview(request)["configuration_sha256"] == first["configuration_sha256"]
    second = preview(VMSelection.model_validate({**request.model_dump(), "tenant_id": "tenant_B"}))
    third = preview(VMSelection.model_validate({**request.model_dump(), "account_ref": "other_account"}))
    assert len({r["configuration_sha256"] for r in (first, second, third)}) == 3
    assert first["creates_resources"] is False and first["ready_to_provision"] is False
    assert first["quote"] is None and first["hardware_isolation_verified"] is False
    assert first["adapter_installed"] is False and first["credentials_checked"] is False


def test_cli_preview_is_offline_and_never_echoes_invalid_secret_payload(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(selection().model_dump_json())
    before = set(tmp_path.iterdir())
    result = subprocess.run([sys.executable, "-m", "wearing.cli", "cloud", "plan", "--request", str(request)], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["mode"] == "offline_selection"
    assert set(tmp_path.iterdir()) == before
    request.write_text(json.dumps({**selection().model_dump(), "access_key": "test-secret-do-not-log"}))
    failed = subprocess.run([sys.executable, "-m", "wearing.cli", "cloud", "plan", "--request", str(request)], capture_output=True, text=True)
    assert failed.returncode != 0 and "test-secret-do-not-log" not in failed.stdout + failed.stderr


def test_release_catalog_is_available_from_cli_without_cloud_credentials():
    result = subprocess.run([sys.executable, "-m", "wearing.cli", "cloud", "providers"], capture_output=True, text=True)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["cloud_verified"] is False and data["implementation_status"] == "planned"
    assert {p["id"] for p in data["providers"]} == {"aws", "azure", "gcp", "aliyun", "tencent", "huawei", "volcengine", "baidu", "oci"}
