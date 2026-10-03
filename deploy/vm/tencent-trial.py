"""Operator trial runner. Official tccli owns signatures; no tenant web access.

prepare creates only a dedicated VPC/subnet/security group/public SSH key.
preflight explicitly uses DryRun=true. create is a paid operator action, with a
fresh quote ceiling and durable ClientToken. Never blindly retry an ambiguous
resource write. This is first-VM tooling, not the SaaS provisioning service.
"""

import argparse
from decimal import Decimal
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from filelock import FileLock

from wearing.cloud.tencent import TencentCLI, TencentError, TencentQuoteRequest, inspect_account, quote
from wearing.config import write_private_json


VERSIONS = {"vpc": "2017-03-12", "cvm": "2017-03-12", "tat": "2020-10-28", "cbs": "2017-03-12"}
READS = {"DescribeVpcs", "DescribeSubnets", "DescribeSecurityGroupPolicies", "DescribeKeyPairs",
         "DescribeInstances", "DescribeInstancesStatus", "DescribeDisks", "DescribeAddresses",
         "DescribeAutomationAgentStatus", "DescribeInvocations", "DescribeInvocationTasks"}


class Trial:
    def __init__(self, root, request, profile):
        self.root = root.absolute()
        if self.root.is_symlink():
            raise TencentError("部署目录不能是符号链接。")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.path = self.root / "deployment.json"
        self.request = request
        if request.selection.billing != "on-demand":
            raise TencentError("本试验工具仅允许一台按量 VM。")
        self.client = TencentCLI(profile, request.selection.region)
        account = inspect_account(self.client)
        if self.path.exists():
            if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
                raise TencentError("部署状态必须私有保存。")
            self.state = json.loads(self.path.read_text())
            if self.state["request"] != request.model_dump(mode="json") or self.state["account_fingerprint"] != account["account_fingerprint"]:
                raise TencentError("已有部署属于另一配置或云账户。")
        else:
            self.state = {"schema_version": 1, "deployment_id": uuid.uuid4().hex,
                          "account_fingerprint": account["account_fingerprint"],
                          "request": request.model_dump(mode="json"), "operations": {}, "resources": {}}
            self.save()

    def save(self):
        write_private_json(self.path, self.state)

    def read(self, service, action, params):
        if action not in READS:
            raise TencentError("未允许的读取接口。")
        return self.client._invoke(service, action, params, version=VERSIONS[service])

    def write(self, name, service, action, params):
        digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        previous = self.state["operations"].get(name)
        if previous:
            if previous["parameters_sha256"] != digest:
                raise TencentError("已有操作不能换参数后重试。")
            if previous["state"] != "complete":
                raise TencentError("上次云写入结果需要核对；不重复发送。")
            return json.loads((self.root / (name + "-response.json")).read_text())
        self.state["operations"][name] = {"state": "submitted", "service": service,
                                         "action": action, "parameters_sha256": digest}
        write_private_json(self.root / (name + "-request.json"), params)
        self.save()  # durable before request; a killed caller cannot buy twice.
        response = self.client._invoke(service, action, params, version=VERSIONS[service])
        write_private_json(self.root / (name + "-response.json"), response)
        self.state["operations"][name]["state"] = "complete"
        self.save()
        return response

    def prepare(self, admin_cidr):
        network = ipaddress.ip_network(admin_cidr, strict=True)
        if network.version != 4 or network.prefixlen != 32 or not network.network_address.is_global:
            raise TencentError("试验 SSH 入口只允许一个真实公网 IPv4 /32。")
        stored = self.state.get("admin_cidr")
        if stored and stored != admin_cidr:
            raise TencentError("原管理地址不能隐式改变。")
        self.state["admin_cidr"] = admin_cidr
        self.save()
        suffix = self.state["deployment_id"][:12]
        tags = [{"Key": "wearing-deployment", "Value": self.state["deployment_id"]},
                {"Key": "wearing-tenant", "Value": self.request.selection.tenant_id}]
        resources = self.state["resources"]
        vpc = self.write("network", "vpc", "CreateVpc", {
            "VpcName": "wearing-trial-" + suffix, "CidrBlock": "10.12.0.0/16", "Tags": tags})["Vpc"]
        resources["vpc_id"] = vpc["VpcId"]
        self.save()
        subnet = self.write("subnet", "vpc", "CreateSubnet", {
            "VpcId": vpc["VpcId"], "SubnetName": "wearing-trial-" + suffix,
            "CidrBlock": "10.12.1.0/24", "Zone": self.request.zone, "Tags": tags})["Subnet"]
        resources["subnet_id"] = subnet["SubnetId"]
        self.save()
        group = self.write("security-group", "vpc", "CreateSecurityGroup", {
            "GroupName": "wearing-trial-" + suffix, "GroupDescription": "Wearing isolated operator trial",
            "ProjectId": "0", "Tags": tags})["SecurityGroup"]
        resources["security_group_id"] = group["SecurityGroupId"]
        self.save()
        egress = [{"Protocol": "ALL", "CidrBlock": cidr, "Action": "DROP",
                   "PolicyDescription": "No private tenant destinations"}
                  for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
        egress.extend({"Protocol": protocol, "Port": ports, "CidrBlock": "0.0.0.0/0", "Action": "ACCEPT",
                       "PolicyDescription": "Trial downloads and DNS"}
                      for protocol, ports in (("TCP", "80"), ("TCP", "443"), ("UDP", "53"), ("TCP", "53")))
        # This API accepts only one direction per request, and ALL has no Port.
        self.write("security-ingress", "vpc", "CreateSecurityGroupPolicies", {
            "SecurityGroupId": resources["security_group_id"], "SecurityGroupPolicySet": {
                "Ingress": [{"Protocol": "TCP", "Port": "22", "CidrBlock": admin_cidr, "Action": "ACCEPT",
                             "PolicyDescription": "Operator SSH only"}]}})
        self.write("security-egress", "vpc", "CreateSecurityGroupPolicies", {
            "SecurityGroupId": resources["security_group_id"], "SecurityGroupPolicySet": {"Egress": egress}})
        key = self.root / "ssh-key"
        if not key.exists():
            if self.state["operations"].get("ssh-key"):
                raise TencentError("原管理密钥缺失；不生成另一把代替。")
            subprocess.run(["ssh-keygen", "-q", "-t", "rsa", "-b", "3072", "-N", "", "-C", "wearing-trial-" + suffix,
                            "-f", str(key)], check=True, capture_output=True)
        if key.is_symlink() or key.stat().st_mode & 0o077:
            raise TencentError("SSH 私钥必须私有保存。")
        response = self.write("ssh-key", "cvm", "ImportKeyPair", {
            "KeyName": "wearing_" + suffix, "ProjectId": 0, "PublicKey": key.with_suffix(".pub").read_text().strip(),
            "TagSpecification": [{"ResourceType": "keypair", "Tags": tags}]})
        resources["key_id"] = response["KeyId"]
        self.state["phase"] = "network_ready"
        self.save()

    def params(self):
        r = self.state["resources"]
        if any(not r.get(k) for k in ("vpc_id", "subnet_id", "security_group_id", "key_id")):
            raise TencentError("专用网络/密钥尚未准备完成。")
        tags = [{"Key": "wearing-deployment", "Value": self.state["deployment_id"]},
                {"Key": "wearing-tenant", "Value": self.request.selection.tenant_id}]
        return {**self.request.inquiry_params(),
                "VirtualPrivateCloud": {"VpcId": r["vpc_id"], "SubnetId": r["subnet_id"]},
                "SecurityGroupIds": [r["security_group_id"]], "LoginSettings": {"KeyIds": [r["key_id"]]},
                "InstanceName": "wearing-trial-" + self.state["deployment_id"][:12],
                "ClientToken": "wearing-" + self.state["deployment_id"],
                "TagSpecification": [{"ResourceType": "instance", "Tags": tags}],
                "EnhancedService": {"AutomationService": {"Enabled": True},
                                    "MonitorService": {"Enabled": True}, "SecurityService": {"Enabled": True}}}

    def preflight(self):
        response = self.client._invoke("cvm", "RunInstances", {**self.params(), "DryRun": True})
        if response.get("InstanceIdSet"):
            raise TencentError("预检意外返回实例，必须核对，不能继续创建。")
        self.state["preflight_request_id"] = response.get("RequestId")
        self.state["phase"] = "preflight_passed"
        self.save()

    def create(self, hourly_ceiling):
        if self.state["resources"].get("instance_id"):
            return  # already created, do not repurchase after a successful retry.
        if self.state.get("phase") != "preflight_passed":
            raise TencentError("创建前必须完成最终网络配置预检。")
        price = quote(self.client, self.request)
        rates = [Decimal(r) for r in price["compute_and_disks"]["hourly_tiers"]]
        limit = Decimal(hourly_ceiling)
        if not limit.is_finite() or limit <= 0 or max(rates) > limit:
            raise TencentError("当前每小时报价高于操作者接受的单价；没有下单。")
        write_private_json(self.root / "accepted-quote.json", price)
        result = self.write("vm-create", "cvm", "RunInstances", {**self.params(), "DryRun": False})
        ids = result.get("InstanceIdSet", [])
        if len(ids) != 1:
            raise TencentError("创建没有返回唯一实例；核对原请求，不重复购买。")
        self.state["resources"]["instance_id"] = ids[0]
        self.state["phase"] = "created_unverified"
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "preflight", "create", "status"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--admin-cidr")
    parser.add_argument("--accept-hourly-cny")
    args = parser.parse_args()
    try:
        if args.request.stat().st_size > 65536:
            raise TencentError("配置文件过大。")
        request = TencentQuoteRequest.model_validate_json(args.request.read_text())
        args.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with FileLock(args.root / "operator.lock", timeout=2):
            trial = Trial(args.root, request, args.profile)
            if args.action == "prepare":
                if not args.admin_cidr: raise TencentError("准备网络需要操作者 /32 管理地址。")
                trial.prepare(args.admin_cidr)
            elif args.action == "preflight": trial.preflight()
            elif args.action == "create":
                if not args.accept_hourly_cny: raise TencentError("创建即开始付费，需要明确接受每小时单价。")
                trial.create(args.accept_hourly_cny)
            print(json.dumps({"phase": trial.state.get("phase", "initialized"),
                              "resource_kinds": list(trial.state["resources"]),
                              "paid_instance_created": bool(trial.state["resources"].get("instance_id")),
                              "hardware_isolation_verified": False}, ensure_ascii=False))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, TencentError) else "操作未完成；检查私有状态与原云请求，不要盲目重试。"
        parser.error(message)


if __name__ == "__main__":
    main()
