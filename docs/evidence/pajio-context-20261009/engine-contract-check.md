# Chat import engine contract verification — 2026-10-09

The final review found one startup blocker: `wearing_life` registered `chat_import_search` and `chat_import_read`, but `engine_runner.py` compared discovered names against an older exact allowlist. A fresh engine therefore rejected its own tool registration before readiness. The allowlist now includes both tools. A fast regression compares the actual `life_proxy.TOOLS` registry against the same startup contract without requiring an installed Hermes engine; the existing subprocess integration test also compares the discovered capability names with that registry.

Only `src/wearing/engine_runner.py` and `tests/test_engine_integration.py` changed for this repair. Existing unrelated dirty changes in those files were preserved. App source and the previously built APK were unchanged.

## Commands and results

All commands ran from `/Users/archieliew/Documents/facet` with the installed pinned Hermes interpreter. Commands below are the commands actually executed, not proposed reruns.

### Initial broad check: 31 passed, 1 failed

```sh
uv run pytest -q tests/test_engine_integration.py tests/test_chat_imports.py tests/test_context_routes_integration.py
```

Exit code 1; 47.06 seconds. The `life=True` subprocess scenario passed. The only failed parameter was `[True-False-False-False]` (`connectors=True`, `life=False`): the pre-existing `wearing_phone` MCP connection closed on all three discovery attempts, and the engine exited before readiness with `RuntimeError: Pajio phone connector did not expose the expected tools`. This was not the corrected life-tool allowlist failure. The phone branch was not rerun or repaired in this check.

- Full captured pytest output: [initial-31-pass-1-fail-pytest.log](engine-contract-logs/initial-31-pass-1-fail-pytest.log).
- Verbatim failure subprocess output: [initial-phone-connection-failed-engine.log](engine-contract-logs/initial-phone-connection-failed-engine.log).
- Initial passing life subprocess: [initial-life-engine.log](engine-contract-logs/initial-life-engine.log).
- Other initial subprocess logs are retained in `engine-contract-logs/initial-*-engine.log`.

### Scoped backend and real life subprocess check: 67 passed

```sh
uv run pytest -q 'tests/test_engine_integration.py::test_real_adapter_exposes_only_personal_engine_routes[False-False-False-True]' tests/test_chat_imports.py tests/test_context_routes_integration.py tests/test_identity_export_documents.py tests/test_account_deletion_tenant.py
```

Exit code 0; 17.33 seconds. Covers the real life MCP subprocess, engine readiness, authenticated capability listing, synthetic chat imports, source/owner isolation, deletion and replay, real application routes, export, and tenant deletion boundaries. This run occurred after adding the two tool names, before extracting the unchanged allowlist into `expected_life_tool_names()` and adding the fast registry regression below.

- Full captured pytest output: [scoped-67-pytest.log](engine-contract-logs/scoped-67-pytest.log).
- Verbatim life subprocess output, including `WEARING_ENGINE_READY`: [scoped-67-life-engine.log](engine-contract-logs/scoped-67-life-engine.log).

### Final registry and real life subprocess check: 2 passed

```sh
uv run pytest -q tests/test_engine_integration.py::test_life_registration_matches_engine_startup_contract_without_installed_engine 'tests/test_engine_integration.py::test_real_adapter_exposes_only_personal_engine_routes[False-False-False-True]'
```

Exit code 0; 8.97 seconds. Ran against the final helper and regression. The first test requires exact equality between the actual MCP registry and the startup allowlist, with both chat-import tools present. The second launches the actual `life_proxy.py` MCP subprocess through Hermes discovery, waits for engine readiness, and verifies `/v1/capabilities` against the registered names. This is more than an import-only or mocked registration test.

- Full captured pytest output: [final-2-pytest.log](engine-contract-logs/final-2-pytest.log).
- Verbatim life subprocess output: [final-2-life-engine.log](engine-contract-logs/final-2-life-engine.log).

## Evidence provenance and scope

The three pytest logs are transcripts of the complete terminal-tool output from those runs, saved after the runs; they were not captured using `tee` at execution time. The initial progress output arrived in two tool chunks and was joined in its original order. The subprocess `engine.log` files were copied byte-for-byte from pytest's retained temporary directories. Their source paths, sizes, and SHA-256 values are recorded in [copied-engine-log-manifest.json](engine-contract-logs/copied-engine-log-manifest.json). No failed output was replaced with a later passing run. This archival task did not rerun tests.

The tests used temporary databases, synthetic messages and memory, generated local test credentials, and ephemeral loopback API ports. No real account login or user chat was accessed, no real phone action was executed, no model request was submitted, and no production service was restarted. The initial connector scenario attempted tool discovery only; its failed connection is not physical-phone acceptance. The scoped and final scenarios do not enable the phone connector. All test subprocesses were stopped by the integration test's cleanup.

The source deletion tests establish removal from chat-import detail/search/export and retained request-key tombstones. Previously generated answers, historical tool results, and independently saved memory are explicitly outside this source-only deletion promise. These tests do not establish live WeChat sharing, physical remote-login behavior, or a deployed engine upgrade.

## Follow-up: isolated phone startup failure resolved

After the initial archival task, a separate authorized follow-up diagnosed the phone startup failure without physical device access. The initial failure records above remain unchanged.

The failure was a new dependency-boundary regression: `phone_proxy.py` imports `device_gateway.py`; the latter had introduced a top-level `filelock` dependency. The separately managed Hermes interpreter has no `filelock`. Starting the actual `phone_proxy.py` script with an empty temporary data directory reproduced `ModuleNotFoundError: No module named 'filelock'` before the driver or registry could be loaded. The earlier broad test had suppressed this child stderr and surfaced only `Connection closed`.

The diagnostic command used `uv run python` to resolve `HermesRuntime(Path('.wearing')).python`, create `tempfile.TemporaryDirectory(prefix='pajio-phone-import-')`, and execute:

```python
subprocess.run(
    [str(runtime.python), str(Path('src/wearing/phone_proxy.py').resolve()), temporary],
    capture_output=True, text=True, timeout=20,
)
```

The captured traceback is archived in [phone-managed-import-before-fix.log](engine-contract-logs/phone-managed-import-before-fix.log). This is a terminal-output transcript; the temporary path was intentionally not a live data directory.

The minimal repair removes `filelock` from `device_gateway.py` and uses the same nonblocking OS advisory lock as the existing phone controller: `fcntl.flock` on POSIX, or one-byte `msvcrt.locking` on Windows, imported only on the applicable platform. The path remains `action_lock_path(resource_id)` under `.wearing/phone-locks`; the local proxy and the remote adapter's `phone_proxy.py` child therefore use the same lock. Closing the descriptor releases the lock even when the operation raises. The lock file is not unlinked, avoiding concurrent contenders opening different inodes. No dependency was installed into Hermes.

The connector integration fixture now uses only a temporary, paused synthetic phone registry. It references the existing pinned driver's static package, not the live registry, and supplies a temporary `adb` stub that exits with code 88 and records any attempted call. The test asserts that this stub was never invoked. It performs MCP initialize/list-tools discovery only; it does not call `mobile_list_devices` or any phone operation.

Initial bounded repair regression:

```sh
uv run pytest -q tests/test_device_access_gateway.py 'tests/test_engine_integration.py::test_real_adapter_exposes_only_personal_engine_routes[True-False-False-False]'
```

Result: 28 passed in 4.68 seconds. An additional regression was then added that starts the gateway with Python `-S`, proving that startup and locking do not require site-packages.

Final regression command:

```sh
uv run pytest -q tests/test_device_access_gateway.py tests/test_engine_integration.py::test_life_registration_matches_engine_startup_contract_without_installed_engine 'tests/test_engine_integration.py::test_real_adapter_exposes_only_personal_engine_routes[True-False-False-False]' 'tests/test_engine_integration.py::test_real_adapter_exposes_only_personal_engine_routes[False-False-False-True]'
```

Result: **31 passed in 7.35 seconds, exit code 0**. The command's stdout and stderr were captured directly to [phone-startup-fixed-pytest.log](engine-contract-logs/phone-startup-fixed-pytest.log) by a Python `subprocess.run` wrapper. Coverage includes:

- Real pinned phone MCP subprocess and upstream driver discovery, exact 11-tool capability count, and engine readiness.
- Real life MCP startup and registry contract, retaining the earlier fix.
- A separate process holding the established `filelock` lock blocks gateway takeover; while the gateway holds the lock, a separate process using the actual `phone_proxy.DeviceLock` reports busy. After an injected exception it can acquire the lock again.
- Gateway module startup and locking with site-packages disabled.
- Existing synthetic privacy takeover, expiry, scope, late-frame discard, and return tests.

The managed-interpreter post-fix import probe succeeded while reporting `filelock_available: false`; see [phone-managed-import-after-fix.log](engine-contract-logs/phone-managed-import-after-fix.log). This confirms the environment was not patched to hide the issue.

The final phone and life subprocess outputs were copied verbatim to [phone-startup-fixed-engine.log](engine-contract-logs/phone-startup-fixed-engine.log) and [phone-startup-fixed-life-engine.log](engine-contract-logs/phone-startup-fixed-life-engine.log). Their source paths, hashes, synthetic registry, and unused ADB-stub check are in [phone-startup-fixed-manifest.json](engine-contract-logs/phone-startup-fixed-manifest.json).

This follow-up changed only `src/wearing/device_gateway.py`, `tests/test_device_access_gateway.py`, and the isolated fixture in `tests/test_engine_integration.py`, plus these evidence files. It did not modify App code, install dependencies, restart production, access real account content, enumerate real devices, or perform real phone actions. These checks ran on macOS; the Windows locking branch is implemented but was not executed here.
