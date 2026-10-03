import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from wearing.cloud.tencent import TencentCLI, TencentError, TencentQuoteRequest, quote


def request():
    return TencentQuoteRequest.model_validate_json(
        (Path(__file__).parents[1] / "deploy/vm/tencent-quote-example.json").read_text())


class Cloud:
    region = "ap-hongkong"

    def __init__(self):
        self.calls = []
        self.responses = {
            "GetCallerIdentity": {"AccountId": "account-one", "Type": "CAMUser"},
            "DescribeZoneInstanceConfigInfos": {"InstanceTypeQuotaSet": [
                {"Zone": "ap-hongkong-2", "InstanceType": "SA2.MEDIUM4", "Cpu": 2, "Memory": 4, "Status": "SELL"}]},
            "DescribeImages": {"ImageSet": [{"ImageId": "img-mmytdhbn", "ImageName": "Ubuntu Server 24.04 LTS 64位",
                                            "Architecture": "x86_64", "ImageType": "PUBLIC_IMAGE",
                                            "ImageState": "NORMAL", "ImageSize": 20}]},
            "DescribeAccountQuota": {"AccountQuotaOverview": {"AccountQuota": {"PostPaidQuotaSet": [
                {"Zone": "ap-hongkong-2", "RemainingQuota": 60}]}}},
            "InquiryPriceRunInstances": {"RequestId": "test-request", "Price": {
                "InstancePrice": {"ChargeUnit": "HOUR", "UnitPrice": 0.36, "UnitPriceDiscount": 0.29},
                "BandwidthPrice": {"ChargeUnit": "GB", "UnitPrice": 1, "UnitPriceDiscount": 0.6666}}},
        }

    def call(self, service, action, params=None):
        self.calls.append((service, action, params))
        return copy.deepcopy(self.responses[action])


def test_quote_includes_disks_once_and_separates_variable_traffic_and_missing_costs():
    cloud = Cloud()
    result = quote(cloud, request())
    assert result["compute_and_disks"]["estimate_24_hours"] == "6.96"
    assert result["compute_and_disks"]["estimate_720_hours"] == "208.80"
    assert result["outbound_cny_per_gb"] == "0.6666"
    assert result["ready_to_provision"] is False and result["creates_resources"] is False
    assert result["hardware_isolation_verified"] is False
    assert "account-one" not in json.dumps(result)
    assert not any(action in {"RunInstances", "InquiryPriceCreateDisks"} for _, action, _ in cloud.calls)
    payload = cloud.calls[-1][2]
    assert payload["DataDisks"][0]["DeleteWithInstance"] is False
    assert payload["InstanceCount"] == 1


def test_monthly_estimate_respects_time_tiers_instead_of_multiplying_first_rate():
    cloud = Cloud()
    cloud.responses["InquiryPriceRunInstances"]["Price"]["InstancePrice"].update(
        UnitPriceDiscountSecondStep=0.2, UnitPriceDiscountThirdStep=0.1)
    cost = quote(cloud, request())["compute_and_disks"]
    assert cost["estimate_24_hours"] == "6.96"
    assert cost["estimate_720_hours"] == "116.64"


def test_unused_zero_tiers_do_not_make_later_hours_free():
    cloud = Cloud()
    cloud.responses["InquiryPriceRunInstances"]["Price"]["InstancePrice"].update(
        UnitPriceSecondStep=0, UnitPriceDiscountSecondStep=0,
        UnitPriceThirdStep=0, UnitPriceDiscountThirdStep=0)
    assert quote(cloud, request())["compute_and_disks"]["estimate_720_hours"] == "208.80"


def test_monthly_quote_is_prepaid_one_month_without_auto_renewal_or_hourly_estimate():
    cloud = Cloud()
    cloud.responses["DescribeAccountQuota"]["AccountQuotaOverview"]["AccountQuota"]["PrePaidQuotaSet"] = [
        {"Zone": "ap-hongkong-2", "RemainingQuota": 300}]
    cloud.responses["InquiryPriceRunInstances"]["Price"]["InstancePrice"] = {
        "OriginalPrice": 194.0, "DiscountPrice": 155.82}
    data = request().model_dump()
    data["selection"]["billing"] = "monthly"
    monthly = TencentQuoteRequest.model_validate(data)
    result = quote(cloud, monthly)
    assert result["compute_and_disks"]["upfront_cny"] == "155.82"
    assert "estimate_720_hours" not in result["compute_and_disks"]
    assert result["compute_and_disks"]["automatic_renewal"] is False
    assert cloud.calls[-1][2]["InstanceChargePrepaid"] == {"Period": 1, "RenewFlag": "NOTIFY_AND_MANUAL_RENEW"}
    assert cloud.calls[-1][2]["InstanceChargeType"] == "PREPAID"


def test_quote_fingerprint_changes_if_profile_resolves_to_a_different_cloud_account():
    cloud = Cloud()
    first = quote(cloud, request())
    cloud.responses["GetCallerIdentity"]["AccountId"] = "account-two"
    second = quote(cloud, request())
    assert first["configuration_sha256"] != second["configuration_sha256"]
    assert first["account_fingerprint"] != second["account_fingerprint"]


@pytest.mark.parametrize("price", [None, True, -1, "NaN", "Infinity", "unknown"])
def test_invalid_price_never_becomes_zero_or_an_approved_quote(price):
    cloud = Cloud()
    cloud.responses["InquiryPriceRunInstances"]["Price"]["InstancePrice"] = {
        "ChargeUnit": "HOUR", "UnitPriceDiscount": price}
    with pytest.raises(TencentError):
        quote(cloud, request())


@pytest.mark.parametrize("kind", ["sold-out", "wrong-cpu", "foreign-zone", "wrong-image", "arm", "wrong-os", "no-quota"])
def test_live_inventory_image_and_account_quota_gate_quote(kind):
    cloud = Cloud()
    row = cloud.responses["DescribeZoneInstanceConfigInfos"]["InstanceTypeQuotaSet"][0]
    image = cloud.responses["DescribeImages"]["ImageSet"][0]
    if kind == "sold-out": row["Status"] = "SOLD_OUT"
    if kind == "wrong-cpu": row["Cpu"] = 4
    if kind == "foreign-zone": row["Zone"] = "ap-singapore-1"
    if kind == "wrong-image": image["ImageId"] = "img-foreign1"
    if kind == "arm": image["Architecture"] = "arm64"
    if kind == "wrong-os": image["ImageName"] = "Hermes Agent on Ubuntu24.04"
    if kind == "no-quota": cloud.responses["DescribeAccountQuota"] = {}
    with pytest.raises(TencentError):
        quote(cloud, request())
    assert not any(action == "InquiryPriceRunInstances" for _, action, _ in cloud.calls)


def test_unvalidated_account_environment_and_zone_mismatch_rejected():
    data = request().model_dump()
    data["selection"]["account_scope"] = "international-site"
    with pytest.raises(ValueError): TencentQuoteRequest.model_validate(data)
    data = request().model_dump()
    data["zone"] = "ap-singapore-1"
    with pytest.raises(ValueError): TencentQuoteRequest.model_validate(data)


def test_cli_client_will_not_dispatch_purchase_or_other_mutations(monkeypatch):
    monkeypatch.setattr("wearing.cloud.tencent.shutil.which", lambda _: "/some/tccli")
    monkeypatch.setattr("wearing.cloud.tencent.subprocess.run", lambda *a, **k: pytest.fail("must not dispatch"))
    client = TencentCLI()
    for action in ("RunInstances", "StopInstances", "TerminateInstances", "CreateDisks"):
        with pytest.raises(TencentError): client.call("cvm", action, {"DryRun": True})


def test_cli_invocation_uses_private_file_and_no_shell_and_does_not_leak_errors(monkeypatch):
    monkeypatch.setattr("wearing.cloud.tencent.shutil.which", lambda _: "/some/tccli")
    def run(command, **kwargs):
        assert kwargs.get("shell") is not True
        assert not any(flag in command for flag in ("--secretId", "--secretKey", "--token", "--warning"))
        arg = command[command.index("--cli-input-json") + 1]
        path = Path(arg.removeprefix("file://"))
        assert path.stat().st_mode & 0o077 == 0
        assert json.loads(path.read_text()) == {}
        return subprocess.CompletedProcess(command, 1, json.dumps({"Error": {
            "Code": "AuthFailure.SignatureFailure", "Message": "secret-do-not-log"}}), "secret-do-not-log")
    monkeypatch.setattr("wearing.cloud.tencent.subprocess.run", run)
    with pytest.raises(TencentError) as failure:
        TencentCLI().call("sts", "GetCallerIdentity")
    assert "SignatureFailure" in str(failure.value)
    assert "secret-do-not-log" not in str(failure.value)


def test_invalid_request_cli_does_not_echo_secret_or_load_tccli(tmp_path):
    path = tmp_path / "request.json"
    path.write_text(json.dumps({**request().model_dump(), "secretKey": "test-secret-do-not-log"}))
    result = subprocess.run([sys.executable, "-m", "wearing.cli", "cloud", "tencent", "quote", "--request", str(path)],
                            capture_output=True, text=True)
    assert result.returncode != 0 and "test-secret-do-not-log" not in result.stdout + result.stderr


def test_official_tccli_sdk_error_on_stderr_reports_only_code(monkeypatch):
    monkeypatch.setattr("wearing.cloud.tencent.shutil.which", lambda _: "/some/tccli")
    monkeypatch.setattr("wearing.cloud.tencent.subprocess.run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 255, "", "[TencentCloudSDKException] code:InvalidParameterValue.Port "
                                    "message:test-secret-do-not-log requestId:request-one"))
    with pytest.raises(TencentError) as failure:
        TencentCLI().call("sts", "GetCallerIdentity")
    assert "InvalidParameterValue.Port" in str(failure.value)
    assert "test-secret-do-not-log" not in str(failure.value)
