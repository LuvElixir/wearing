# Pajio backend profile regression · 2026-10-07

The backend command recorded in `docs/pajio-zcode-delivery-2026-10-07.md:37`
now passes all **131 tests**. The earlier failure was an outdated test expectation
for the life connector's confirmation settings. Only `tests/test_life.py` was
changed; `src/wearing/profile.py`, live configuration, services and mobile sources
were not changed by this correction.

## Reproduction and root cause

Working directory: `/Users/archieliew/Documents/facet`.

```sh
uv run pytest -q tests/test_life.py::test_profile_exposes_life_tools_preserving_model_config
```

Before the correction: **1 failed in 0.37s**. The assertion at the former
`tests/test_life.py:175` required the generated `mcp_servers.wearing_life` mapping
to exactly equal the input connector. The actual mapping additionally contained:

```python
{"timeout": 360, "elicitation": {"enabled": True, "timeout": 300}}
```

These are intentional owned profile fields in `src/wearing/profile.py:118–119`.
`src/wearing/life_proxy.py` exposes `request_confirmation` through the same MCP
connector. `docs/confirmation-cards.md` specifies the existing 300-second decision
window; the 360-second tool timeout allows that window to complete. Removing
these fields to satisfy the old assertion would weaken the confirmation path.

The updated assertion still compares the complete generated mapping, now with
the two required fields explicitly included. A separate assertion also proves
that preparing the profile does not mutate the input connector. The existing
model-provider preservation assertion remains intact.

This failure did not demonstrate a defect in Pajio's runtime behavior: it was the
test rejecting the intended configuration. The correction changes test coverage
only; it does not change production behavior or claim live service acceptance.

## Focused verification

```sh
uv run pytest -q tests/test_life.py::test_profile_exposes_life_tools_preserving_model_config tests/test_profile.py tests/test_confirmations.py::test_mcp_awaits_actual_decision tests/test_confirmations.py::test_timeout_does_not_approve
```

Result: **14 passed in 0.38s**. This includes the corrected regression, all profile
tests, accepted/declined/cancelled decisions and confirmation timeout behavior.
Fixtures use temporary profile/data directories and mocked confirmation sessions.

## Exact ZCode command rerun

The command below was copied from the delivery report; its file selection was not
inferred or expanded:

```sh
uv run python -m pytest tests/test_api.py tests/test_dev_mobile.py tests/test_gateway.py tests/test_tenant_worker.py tests/test_life.py tests/test_activity.py
```

Environment reported by pytest: Darwin, Python 3.12.13, pytest 9.1.1,
pytest-asyncio 1.4.0, anyio 4.15.1; configuration `pyproject.toml`.

Result: **131 passed, 1 warning in 2.95s**; process exit code **0**.

| Test file | Passed |
| --- | ---: |
| `tests/test_api.py` | 15 |
| `tests/test_dev_mobile.py` | 28 |
| `tests/test_gateway.py` | 15 |
| `tests/test_tenant_worker.py` | 16 |
| `tests/test_life.py` | 19 |
| `tests/test_activity.py` | 38 |
| Total | 131 |

The warning is Authlib's `AuthlibDeprecationWarning` from
`authlib/integrations/httpx_client/assertion_client.py`: its HTTPX integration is
deprecated in favor of `httpx2`. It is not a failed test and no dependency upgrade
was included in this correction.

The selected tests use temporary directories, in-process ASGI transports and
mocked upstream transports; worker startup tests replace the engine starter with
test doubles. No live service was restarted or live business record changed.
The separate iOS launch investigation is outside this backend result.

## File fingerprints

SHA-256 at verification:

- Updated `tests/test_life.py`:
  `06786b8db5a0bfceaa3d13932f74f6dffdd8af04b0476199a7e3c64c41659cda`
- Observed, unchanged `src/wearing/profile.py`:
  `4bd59a354f4d194fb28ac1d56b27d720e0cab32741601142d21d66bb1ef6a874`
