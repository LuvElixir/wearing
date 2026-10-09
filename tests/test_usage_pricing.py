"""Synthetic operator rates only. No test is a claim about a supplier price."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import asyncio
import json
import sqlite3

import pytest

from wearing.usage import UsageBook, UsageError, UsagePolicy
from wearing.usage_guard import _AsyncStream, _Stream, receipt
from wearing.usage_pricing import configuration


def prices(*, budget="10", version="fixture-v1"):
    return {"version": version, "currency": "CNY", "budget": budget, "models": [{
        "provider": "unit.invalid", "model": "fixture",
        "input_per_million": "2", "cached_input_per_million": "0.2", "output_per_million": "8",
        "max_input_tokens": 1_000_000, "max_output_tokens": 10_000,
    }]}


def book(tmp_path, **kwargs):
    return UsageBook(tmp_path, policy=UsagePolicy(model_concurrency=20), enabled=True, **kwargs)


def reserve(b, key="one", identity="daily", **kwargs):
    return b.reserve(identity, "model", key, provider="unit.invalid", model="fixture", **kwargs)


def test_budget_concurrency_shared_by_identity_and_released_only_after_receipt(tmp_path):
    b = book(tmp_path)
    b.configure_pricing(prices(budget="4.16"))  # Two full-context reservations.
    def attempt(i):
        try: return reserve(b, str(i), "daily" if i % 2 else "work")
        except UsageError as error: return error.code
    with ThreadPoolExecutor(max_workers=10) as pool:
        calls = list(pool.map(attempt, range(10)))
    active = [value for value in calls if value != "quota_budget"]
    assert len(active) == 2
    assert b.snapshot("daily")["cost"]["active_reserved_micros"] == 4_160_000
    b.settle(active[0], input_tokens=1_000, output_tokens=100, cached_input_tokens=500)
    cost = b.snapshot("daily")["cost"]
    assert cost["settled_estimate_micros"] == 1_900
    assert cost["remaining_micros"] == 2_078_100
    with pytest.raises(UsageError, match="预算"):
        reserve(b, "still-too-large")
    reserve(b, "smaller-output", reserve_output_tokens=0)
    assert b.snapshot("daily")["resources"]["model"]["calls"] == 3


def test_settlement_is_versioned_and_idempotent_not_supplier_bill(tmp_path):
    b = book(tmp_path)
    b.configure_pricing(prices())
    call = reserve(b)
    with pytest.raises(UsageError) as error:
        reserve(b)
    assert error.value.code == "quota_duplicate"
    newer = prices(version="fixture-v2")
    newer["models"][0]["input_per_million"] = "4"
    b.configure_pricing(newer)
    b.settle(call, input_tokens=1_000_000, output_tokens=100, cached_input_tokens=500_000)
    b.settle(call, input_tokens=0, output_tokens=0)
    cost = b.snapshot("work")["cost"]
    assert cost["settled_estimate_micros"] == 1_100_800  # Immutable v1 rate.
    assert cost["supplier_bill"] is False
    assert cost["scope"] == "runtime_model_calls"
    with sqlite3.connect(b.path) as db:
        assert db.execute("SELECT price_version FROM trial_calls").fetchone()[0] == "fixture-v1"
    again = reserve(b, "next")
    b.settle(again, input_tokens=0, output_tokens=0)
    assert b.snapshot("daily")["cost"]["active_reserved_micros"] == 0


@pytest.mark.parametrize("partial", [{}, {"input_tokens": 1_000}, {"output_tokens": 1_000}, {"input_tokens": 5, "output_tokens": 2, "uncertain": True}])
def test_missing_or_uncertain_receipt_keeps_full_reservation_across_restart(tmp_path, partial):
    b = book(tmp_path)
    b.configure_pricing(prices(budget="2.08"))
    call = reserve(b)
    b.settle(call, **partial)
    reopened = book(tmp_path)
    view = reopened.snapshot("daily")
    assert view["resources"]["model"]["active"] == 0
    assert view["resources"]["model"]["uncertain"] == 1
    assert view["cost"]["uncertain_reserved_micros"] == 2_080_000
    assert view["cost"]["settled_estimate_micros"] == 0
    reopened.settle(call, input_tokens=0, output_tokens=0)
    assert reopened.snapshot("daily")["cost"]["remaining_micros"] == 0
    with pytest.raises(UsageError, match="预算"):
        reserve(reopened, "repeat")


def test_dead_owner_does_not_refund_money_or_reset_budget(tmp_path):
    b = book(tmp_path)
    b.configure_pricing(prices(budget="2.08"))
    reserve(b)
    restarted = book(tmp_path, alive=lambda pid, stamp: False)
    cost = restarted.snapshot("daily")["cost"]
    assert cost["active_reserved_micros"] == 0
    assert cost["uncertain_reserved_micros"] == 2_080_000
    restarted.configure_pricing(prices(budget="3", version="fixture-v2"))
    assert restarted.snapshot("daily")["cost"]["remaining_micros"] == 920_000
    with pytest.raises(UsageError, match="预算"):
        reserve(restarted, "after-reboot")


def test_unpriced_models_keep_trial_caps_and_report_missing_cost(tmp_path):
    b = UsageBook(tmp_path, UsagePolicy(model_calls=1), enabled=True)
    call = reserve(b)
    b.settle(call, input_tokens=10, output_tokens=2)
    assert b.snapshot("daily")["cost"] is None
    b.configure_pricing(prices())
    cost = b.snapshot("daily")
    assert cost["cost_status"] == "partial"
    assert cost["cost"]["unpriced_calls"] == 1
    assert cost["cost"]["settled_estimate_micros"] == 0  # Explicitly incomplete.
    with pytest.raises(UsageError) as error:
        reserve(b, "two")
    assert error.value.code == "quota_exhausted"


def test_price_matching_uses_full_transport_model_not_truncated_audit_label(tmp_path):
    b = book(tmp_path)
    config = prices()
    config["models"][0]["model"] = "x" * 160
    b.configure_pricing(config)
    with pytest.raises(UsageError) as error:
        b.reserve("daily", "model", "unmatched", provider="unit.invalid", model="x" * 161)
    assert error.value.code == "quota_price_unavailable"
    cost = b.snapshot("daily")["cost"]
    assert cost["unpriced_calls"] == 0 and cost["active_reserved_micros"] == 0


def test_configured_budget_cannot_be_bypassed_by_an_unknown_provider_or_model(tmp_path):
    b = book(tmp_path)
    b.configure_pricing(prices(budget="0"))
    for provider, model in [("other.invalid", "fixture"), ("unit.invalid", "expensive-unknown")]:
        with pytest.raises(UsageError) as error:
            b.reserve("daily", "model", provider + model, provider=provider, model=model)
        assert error.value.code == "quota_price_unavailable"
    assert b.snapshot("daily")["resources"]["model"]["calls"] == 0


def test_unknown_cache_split_uses_conservative_rate_and_fractional_micros_round_up(tmp_path):
    b = book(tmp_path)
    cfg = prices()
    cfg["models"][0]["cached_input_per_million"] = "0.02"
    b.configure_pricing(cfg)
    one = reserve(b)
    b.settle(one, input_tokens=1, output_tokens=0)
    two = reserve(b, "two")
    b.settle(two, input_tokens=1, output_tokens=0, cached_input_tokens=1)
    cost = b.snapshot("daily")["cost"]
    assert cost["settled_estimate_micros"] == 3  # 2 + ceil(0.02).
    assert cost["upper_bound_calls"] == 1


def test_overrun_records_actual_receipt_and_blocks_that_version_until_operator_fixes_bound(tmp_path):
    b = book(tmp_path)
    b.configure_pricing(prices())
    call = reserve(b)
    b.settle(call, input_tokens=1_500_000, output_tokens=0, cached_input_tokens=0)
    cost = b.snapshot("daily")["cost"]
    assert cost["settled_estimate_micros"] == 3_000_000 and cost["overrun_calls"] == 1
    with pytest.raises(UsageError) as error:
        reserve(b, "unsafe-bound")
    assert error.value.code == "quota_price_bound"
    cfg = prices(version="fixed")
    cfg["models"][0]["max_input_tokens"] = 2_000_000
    b.configure_pricing(cfg)
    reserve(b, "corrected")


def test_price_version_currency_validation_and_budget_updates(tmp_path):
    b = book(tmp_path)
    b.configure_pricing(prices())
    b.configure_pricing(prices(budget="20"))
    changed = prices()
    changed["models"][0]["output_per_million"] = "9"
    with pytest.raises(ValueError, match="immutable"):
        b.configure_pricing(changed)
    changed = prices(version="different-currency")
    changed["currency"] = "USD"
    with pytest.raises(ValueError, match="currency"):
        b.configure_pricing(changed)
    for invalid in [True, -1, "NaN", "Infinity", "1e-2", "0.0000001", 0.02]:
        changed = prices()
        changed["models"][0]["input_per_million"] = invalid
        with pytest.raises(ValueError):
            b.configure_pricing(changed)
    cfg = prices()
    cfg["models"].append(deepcopy(cfg["models"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        configuration(cfg)
    assert b.snapshot("daily")["cost"]["budget_micros"] == 20_000_000


def test_concurrent_upgrade_of_old_ledger_preserves_calls(tmp_path):
    b = book(tmp_path)
    reserve(b)
    with sqlite3.connect(b.path) as db:
        for column in ("cached_input_tokens", "price_version", "currency", "price_snapshot", "reserved_input_tokens", "reserved_output_tokens", "reserved_cost_micros", "estimated_cost_micros", "cost_status", "reservation_overrun"):
            db.execute(f"ALTER TABLE trial_calls DROP COLUMN {column}")
    with ThreadPoolExecutor(max_workers=5) as pool:
        counts = list(pool.map(lambda _: book(tmp_path).snapshot("daily")["resources"]["model"]["calls"], range(5)))
    assert counts == [1] * 5


def test_cache_receipts_validate_counts_and_support_deepseek_and_responses():
    assert receipt({"usage": {"prompt_tokens": 10, "completion_tokens": 2, "prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 6}}) == {"input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 4}
    assert receipt({"response": {"usage": {"input_tokens": 10, "output_tokens": 2, "input_tokens_details": {"cached_tokens": 4}}}})["cached_input_tokens"] == 4
    for value in [True, -1, 11, "4"]:
        assert "cached_input_tokens" not in receipt({"usage": {"prompt_tokens": 10, "prompt_cache_hit_tokens": value}})
    assert "cached_input_tokens" not in receipt({"usage": {"prompt_tokens": 10, "prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 1}})
    assert receipt({"usage": {"prompt_tokens": 10, "prompt_cache_miss_tokens": 6}})["cached_input_tokens"] == 4


def test_closed_stream_with_partial_usage_keeps_reservation(tmp_path):
    b = book(tmp_path)
    b.configure_pricing(prices())
    class Inner:
        def __iter__(self):
            yield {"usage": {"prompt_tokens": 10, "completion_tokens": 1}}
            yield {}
        def close(self): pass
    stream = _Stream(Inner(), b, reserve(b))
    iterator = iter(stream)
    next(iterator)
    stream.close()
    iterator.close()
    assert b.snapshot("daily")["cost"]["uncertain_reserved_micros"] == 2_080_000


@pytest.mark.asyncio
async def test_async_cancellation_keeps_money_and_frees_only_concurrency(tmp_path):
    b = book(tmp_path)
    b.configure_pricing(prices())
    class Inner:
        async def __aiter__(self):
            yield {"usage": {"prompt_tokens": 10, "completion_tokens": 1}}
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        async for _ in _AsyncStream(Inner(), b, reserve(b)):
            pass
    cost = b.snapshot("daily")["cost"]
    assert cost["active_reserved_micros"] == 0
    assert cost["uncertain_reserved_micros"] == 2_080_000


def test_private_ledger_never_stores_payloads_or_credentials(tmp_path):
    b = book(tmp_path)
    b.configure_pricing(prices())
    reserve(b, "private-request-key")
    with sqlite3.connect(b.path) as db:
        dump = "\n".join(db.iterdump())
    assert "private-request-key" not in dump
    assert "api_key" not in dump and "messages" not in dump
