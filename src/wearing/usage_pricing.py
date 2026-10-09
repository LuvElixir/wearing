"""Operator-authored estimates, never a supplier bill or automatic price feed.

All amounts use currency micros. Rates are decimal currency units per million
tokens; one final upward rounding prevents fractional-micro under-reservation.
"""
from decimal import Decimal, InvalidOperation
import re

MICROS = 1_000_000
MAX_MONEY = 9_000_000_000_000_000  # Also exactly representable in the App's JS.


def money(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,10}(?:\.\d{1,6})?", value):
        raise ValueError("Money must be a nonnegative decimal string, at most six places")
    try:
        result = int(Decimal(value) * MICROS)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid money") from None
    if result > MAX_MONEY:
        raise ValueError("Money exceeds supported range")
    return result


def configuration(value):
    """Normalize a private operator JSON. Exact provider hostname/model matching."""
    if not isinstance(value, dict) or set(value) != {"version", "currency", "budget", "models"}:
        raise ValueError("Invalid pricing configuration fields")
    version, currency = value["version"], value["currency"]
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", version):
        raise ValueError("Invalid price version")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Currency must be a three-letter code")
    models = value["models"]
    if not isinstance(models, list) or not 1 <= len(models) <= 100:
        raise ValueError("Provide between one and 100 model rates")
    normalized, seen = [], set()
    fields = {"provider", "model", "input_per_million", "cached_input_per_million", "output_per_million", "max_input_tokens", "max_output_tokens"}
    for item in models:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("Invalid model price fields")
        provider, model = item["provider"], item["model"]
        if not isinstance(provider, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,99}", provider):
            raise ValueError("Provider must be a lowercase hostname")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", model):
            raise ValueError("Invalid model name")
        if (provider, model) in seen:
            raise ValueError("Duplicate model rate")
        seen.add((provider, model))
        for key in ("max_input_tokens", "max_output_tokens"):
            if type(item[key]) is not int or not 0 <= item[key] <= 1_000_000_000:
                raise ValueError("Invalid token bound")
        if not item["max_input_tokens"]:
            raise ValueError("Input context bound must be positive")
        rates = {key: money(item[key]) for key in ("input_per_million", "cached_input_per_million", "output_per_million")}
        row = {"provider": provider, "model": model, **rates,
               "max_input_tokens": item["max_input_tokens"], "max_output_tokens": item["max_output_tokens"]}
        if estimate(row, row["max_input_tokens"], row["max_output_tokens"]) > MAX_MONEY:
            raise ValueError("Reservation exceeds supported range")
        normalized.append(row)
    return {"version": version, "currency": currency, "budget_micros": money(value["budget"]),
            "models": sorted(normalized, key=lambda item: (item["provider"], item["model"]))}


def estimate(rate, input_tokens, output_tokens, cached_input_tokens=None):
    """Unknown cache split uses the dearer rate; never assume a cache hit."""
    if cached_input_tokens is None:
        input_cost = input_tokens * max(rate["input_per_million"], rate["cached_input_per_million"])
    else:
        input_cost = ((input_tokens - cached_input_tokens) * rate["input_per_million"]
                      + cached_input_tokens * rate["cached_input_per_million"])
    return (input_cost + output_tokens * rate["output_per_million"] + MICROS - 1) // MICROS
