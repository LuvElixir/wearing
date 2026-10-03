"""Operator-only Tencent discovery and quotes through the official tccli.

No purchase, IAM, network mutation, or secret copying. The first adapter uses
the China API endpoints and CNY pricing; international-site is not validated.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .commands import Record
from .placement import Location, VMSelection


class TencentError(ValueError):
    """Safe error text, never raw tccli stdout/stderr or SDK messages."""


READ_ACTIONS = {
    "sts": {"GetCallerIdentity"},
    "cvm": {"DescribeRegions", "DescribeZones", "DescribeImages",
            "DescribeZoneInstanceConfigInfos", "DescribeAccountQuota", "InquiryPriceRunInstances"},
    "cbs": {"DescribeDiskConfigQuota", "InquiryPriceCreateDisks"},
}
API_VERSIONS = {"sts": "2018-08-13", "cvm": "2017-03-12", "cbs": "2017-03-12"}


class TencentCLI:
    def __init__(self, profile="default", region="ap-hongkong"):
        # Profiles are operator input, never supplied by a tenant web request.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile):
            raise TencentError("CLI profile 格式无效。")
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", region):
            raise TencentError("区域格式无效。")
        self.executable = shutil.which("tccli")
        if not self.executable:
            raise TencentError("未找到腾讯云 tccli；请先安装并在本机配置凭据。")
        self.profile, self.region = profile, region

    def call(self, service, action, params=None):
        if action not in READ_ACTIONS.get(service, set()):
            raise TencentError("此入口仅允许已列出的查询接口。")
        return self._invoke(service, action, params)

    def _invoke(self, service, action, params=None, *, version=None):
        # Shared transport for separately scoped operator deployment tooling.
        # tccli requires file://, not inline JSON. TemporaryDirectory is private;
        # no shell, credential flags, debug output, or automatic purchase retries.
        with tempfile.TemporaryDirectory(prefix="wearing-tencent-") as directory:
            request = Path(directory) / "request.json"
            request.write_text(json.dumps(params or {}), encoding="utf-8")
            request.chmod(0o600)
            command = [self.executable, service, action, "--profile", self.profile,
                       "--region", self.region, "--version", version or API_VERSIONS[service],
                       "--endpoint", service + ".tencentcloudapi.com", "--timeout", "20",
                       "--cli-input-json", request.as_uri()]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise TencentError("腾讯云查询未完成；没有创建资源，请检查 CLI 或网络。") from error
        try:
            body = json.loads(result.stdout)
            body = body.get("Response", body)
            if not isinstance(body, dict):
                raise ValueError("Unexpected envelope")
        except (ValueError, AttributeError) as error:
            # tccli 3.1.125 writes official SDK failures to stderr, not JSON.
            match = re.search(r"\[TencentCloudSDKException\] code:([A-Za-z0-9_.]{1,128}) message:", result.stderr)
            if match:
                raise TencentError("腾讯云查询失败：" + match.group(1)) from None
            raise TencentError("腾讯云 CLI 未返回有效 JSON；请检查本机认证和 CLI 配置。") from error
        if result.returncode or "Error" in body:
            failure = body.get("Error")
            code = failure.get("Code", "UnknownError") if isinstance(failure, dict) else "UnknownError"
            if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_.]{1,128}", code):
                code = "UnknownError"
            raise TencentError("腾讯云查询失败：" + code)
        return body


class TencentQuoteRequest(Record):
    selection: VMSelection
    zone: Location
    instance_type: Annotated[str, Field(strict=True, pattern=r"^(S[2-9]|SA[2-9])\.[A-Z0-9]+$")]
    image_id: Annotated[str, Field(strict=True, pattern=r"^img-[a-z0-9]{8,32}$")]
    disk_type: Literal["CLOUD_PREMIUM", "CLOUD_SSD", "CLOUD_BSSD"] = "CLOUD_PREMIUM"
    outbound_mbps: int = Field(default=5, strict=True, ge=1, le=20)

    @model_validator(mode="after")
    def checked_provider(self):
        if self.selection.provider_id != "tencent" or self.selection.account_scope != "china-site":
            raise ValueError("首轮腾讯适配器仅验收中国站账户和人民币报价。")
        if not re.fullmatch(re.escape(self.selection.region) + r"-[1-9][0-9]*", self.zone):
            raise ValueError("可用区必须属于所选区域。")
        if self.selection.data_disk_gib % 10:
            raise ValueError("首轮数据盘规格按 10 GiB 步长选择。")
        return self

    def inquiry_params(self):
        params = {
            "Placement": {"Zone": self.zone}, "ImageId": self.image_id,
            "InstanceType": self.instance_type,
            "InstanceChargeType": "PREPAID" if self.selection.billing == "monthly" else "POSTPAID_BY_HOUR",
            "InstanceCount": 1,
            "SystemDisk": {"DiskType": self.disk_type, "DiskSize": self.selection.system_disk_gib},
            "DataDisks": [{"DiskType": self.disk_type, "DiskSize": self.selection.data_disk_gib,
                           "DeleteWithInstance": False}],
            "InternetAccessible": {"InternetChargeType": "TRAFFIC_POSTPAID_BY_HOUR",
                                   "InternetMaxBandwidthOut": self.outbound_mbps, "PublicIpAssigned": True},
        }
        if self.selection.billing == "monthly":
            params["InstanceChargePrepaid"] = {"Period": 1, "RenewFlag": "NOTIFY_AND_MANUAL_RENEW"}
        return params


def _amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TencentError("价格字段缺失或无效；不能将未知价格当成零。")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise TencentError("价格字段无效。") from error
    if not amount.is_finite() or amount < 0:
        raise TencentError("价格字段无效。")
    return amount


def _rate(item, suffix=""):
    value = item.get("UnitPriceDiscount" + suffix)
    return _amount(item.get("UnitPrice" + suffix) if value is None else value)


def _hourly_rates(item):
    if item.get("ChargeUnit") != "HOUR":
        raise TencentError("查询未返回按小时价格。")
    rates = [_rate(item)]
    for suffix in ("SecondStep", "ThirdStep"):
        # SDKs also represent an unused time tier with two zero fields.
        original, discounted = item.get("UnitPrice" + suffix), item.get("UnitPriceDiscount" + suffix)
        if original in (None, 0) and discounted in (None, 0):
            rates.append(rates[-1])
        else:
            rates.append(_rate(item, suffix))
    return rates


def _estimate(rates, hours):
    return rates[0] * min(hours, 96) + rates[1] * min(max(hours - 96, 0), 264) + rates[2] * max(hours - 360, 0)


def _fields(row, names):
    return {name: row.get(name) for name in names}


def inspect_account(client):
    identity = client.call("sts", "GetCallerIdentity")
    if not identity.get("AccountId") or not identity.get("Type"):
        raise TencentError("未取得调用账户身份。")
    return {"credential_verified": True, "identity_type": identity["Type"],
            "account_fingerprint": hashlib.sha256(str(identity["AccountId"]).encode()).hexdigest(),
            "region": client.region, "endpoint_scope": "china-api", "creates_resources": False}


def discover(client):
    account = inspect_account(client)
    regions = client.call("cvm", "DescribeRegions").get("RegionSet", [])
    zones = client.call("cvm", "DescribeZones").get("ZoneSet", [])
    types = client.call("cvm", "DescribeZoneInstanceConfigInfos", {
        "Filters": [{"Name": "instance-charge-type", "Values": ["POSTPAID_BY_HOUR"]}],
    }).get("InstanceTypeQuotaSet", [])
    images = client.call("cvm", "DescribeImages", {
        "Filters": [{"Name": "image-type", "Values": ["PUBLIC_IMAGE"]},
                    {"Name": "platform", "Values": ["Ubuntu"]}], "Limit": 100,
    }).get("ImageSet", [])
    candidates = [r for r in types if r.get("Status") == "SELL" and r.get("Cpu") == 2
                  and r.get("Memory") == 4 and re.fullmatch(r"(S[2-9]|SA[2-9])", r.get("InstanceFamily", ""))]
    return {"mode": "tencent_discovery", **account, "ready_to_provision": False,
            "regions": [_fields(r, ("Region", "RegionName", "RegionState")) for r in regions],
            "zones": [_fields(r, ("Zone", "ZoneName", "ZoneState")) for r in zones],
            "candidates": [_fields(r, ("Zone", "InstanceType", "Cpu", "Memory", "Status", "StatusCategory", "CpuType"))
                           for r in candidates],
            "images": [_fields(r, ("ImageId", "ImageName", "Architecture", "ImageSize")) for r in images
                       if r.get("Architecture") == "x86_64" and r.get("ImageState") == "NORMAL"
                       and r.get("ImageName", "").startswith("Ubuntu Server 24.04")],
            "inventory_checked_at": datetime.now(timezone.utc).isoformat()}


def quote(client, request: TencentQuoteRequest):
    if client.region != request.selection.region:
        raise TencentError("CLI 区域和报价请求不一致。")
    account = inspect_account(client)
    monthly = request.selection.billing == "monthly"
    types = client.call("cvm", "DescribeZoneInstanceConfigInfos", {"Filters": [
        {"Name": "zone", "Values": [request.zone]},
        {"Name": "instance-type", "Values": [request.instance_type]},
        {"Name": "instance-charge-type", "Values": ["PREPAID" if monthly else "POSTPAID_BY_HOUR"]},
    ]}).get("InstanceTypeQuotaSet", [])
    if not any(r.get("Zone") == request.zone and r.get("InstanceType") == request.instance_type
               and r.get("Status") == "SELL" and r.get("Cpu") == request.selection.vcpu
               and r.get("Memory") == request.selection.memory_gib for r in types):
        raise TencentError("所选机型当前不可售，或与 CPU/内存要求不符。")
    images = client.call("cvm", "DescribeImages", {
        "ImageIds": [request.image_id], "InstanceType": request.instance_type,
    }).get("ImageSet", [])
    if not any(r.get("ImageId") == request.image_id and r.get("Architecture") == "x86_64"
               and r.get("ImageType") == "PUBLIC_IMAGE" and r.get("ImageState") == "NORMAL"
               and r.get("ImageName", "").startswith("Ubuntu Server 24.04")
               and r.get("ImageSize", 1000000) <= request.selection.system_disk_gib for r in images):
        raise TencentError("镜像不是当前机型可用的官方 Ubuntu 24.04 x86_64 镜像。")
    quota = client.call("cvm", "DescribeAccountQuota").get("AccountQuotaOverview", {}).get("AccountQuota", {})
    remaining = next((r.get("RemainingQuota") for r in quota.get("PrePaidQuotaSet" if monthly else "PostPaidQuotaSet", [])
                      if r.get("Zone") == request.zone), None)
    if not isinstance(remaining, int) or isinstance(remaining, bool) or remaining < 1:
        raise TencentError("该可用区没有已确认的所选计费方式实例配额。")
    response = client.call("cvm", "InquiryPriceRunInstances", request.inquiry_params())
    prices = response.get("Price", {})
    instance = prices.get("InstancePrice", {})
    if monthly:
        value = instance.get("DiscountPrice")
        upfront = _amount(instance.get("OriginalPrice") if value is None else value)
        compute = {"includes_system_and_data_disks": True, "billing": "monthly", "period_months": 1,
                   "upfront_cny": str(upfront), "automatic_renewal": False}
    else:
        rates = _hourly_rates(instance)
        compute = {"includes_system_and_data_disks": True, "billing": "on-demand",
                   "hourly_tiers": [str(r) for r in rates],
                   "estimate_24_hours": str(_estimate(rates, 24)),
                   "estimate_720_hours": str(_estimate(rates, 720))}
    bandwidth = prices.get("BandwidthPrice", {})
    if bandwidth.get("ChargeUnit") != "GB":
        raise TencentError("公网未返回按 GB 流量价格。")
    canonical = json.dumps({"request": request.model_dump(mode="json"), "account": account["account_fingerprint"]},
                           sort_keys=True, separators=(",", ":"))
    return {"mode": "tencent_live_quote", **account, "request": request.model_dump(mode="json"),
            "configuration_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "quoted_at": datetime.now(timezone.utc).isoformat(), "price_request_id": response.get("RequestId"),
            "remaining_instance_quota": remaining, "currency": "CNY", "instance_count": 1,
            "compute_and_disks": compute,
            "outbound_cny_per_gb": str(_rate(bandwidth)),
            "not_included": ["快照实际占用容量", "公网 IP 保有费（依绑定和账户条件）", "模型费用",
                             "另行选择的控制面/数据库/沙盒及其他付费服务"],
            "ready_to_provision": False, "hardware_isolation_verified": False,
            "checks_remaining": ["实际独立 VPC/子网/安全组与管理登录方式", "最终创建参数 DryRun 与费用授权",
                                 "安装、隔离、私有数据、备份恢复和真实账单验收"],
            "note": "这是账户当时的一台 VM 报价；库存与折扣可变。磁盘已含在 InstancePrice 中，不另加 CBS 询价。"}
