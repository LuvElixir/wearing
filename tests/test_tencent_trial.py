"""Operator purchase boundaries; no real Tencent requests."""

import importlib.util
import json
from pathlib import Path

import pytest

from wearing.cloud.tencent import TencentError, TencentQuoteRequest


spec = importlib.util.spec_from_file_location("tencent_trial", Path(__file__).parents[1] / "deploy/vm/tencent-trial.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


def make_trial(tmp_path, monkeypatch):
    class Client:
        calls = []

        def __init__(self, *args): pass

        def _invoke(self, service, action, params, **kwargs):
            self.calls.append((service, action, params))
            raise TencentError("Transport outcome unknown")

    monkeypatch.setattr(trial, "TencentCLI", Client)
    monkeypatch.setattr(trial, "inspect_account", lambda _: {"account_fingerprint": "test-account"})
    request = TencentQuoteRequest.model_validate_json(
        (Path(__file__).parents[1] / "deploy/vm/tencent-quote-example.json").read_text())
    return trial.Trial(tmp_path / "private", request, "default")


def test_ambiguous_write_is_durable_and_not_repeated_after_operator_restart(tmp_path, monkeypatch):
    first = make_trial(tmp_path, monkeypatch)
    params = {"InstanceCount": 1, "ClientToken": "fixed-test-token"}
    with pytest.raises(TencentError, match="unknown"):
        first.write("vm-create", "cvm", "RunInstances", params)
    state = json.loads(first.path.read_text())
    assert state["operations"]["vm-create"]["state"] == "submitted"
    assert first.path.stat().st_mode & 0o077 == 0
    second = trial.Trial(first.root, first.request, "default")
    with pytest.raises(TencentError, match="不重复"):
        second.write("vm-create", "cvm", "RunInstances", params)
    assert len(first.client.calls) == 1


def test_fresh_price_increase_does_not_purchase(tmp_path, monkeypatch):
    current = make_trial(tmp_path, monkeypatch)
    current.state["phase"] = "preflight_passed"
    monkeypatch.setattr(trial, "quote", lambda *_: {
        "compute_and_disks": {"hourly_tiers": ["0.29", "0.30", "0.29"]}})
    with pytest.raises(TencentError, match="没有下单"):
        current.create("0.29")
    assert current.client.calls == []
    assert "vm-create" not in current.state["operations"]


def test_successful_create_retry_does_not_buy_again(tmp_path, monkeypatch):
    current = make_trial(tmp_path, monkeypatch)
    current.state["resources"]["instance_id"] = "ins-trial"
    monkeypatch.setattr(trial, "quote", lambda *_: pytest.fail("already created"))
    current.create("0.29")
    assert current.client.calls == []
