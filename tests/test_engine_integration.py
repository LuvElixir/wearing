"""No-LLM contract test against an installed, pinned Hermes interpreter."""

import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import yaml

import httpx
import pytest

from wearing.engine_runner import ALLOWED_ROUTES, expected_life_tool_names
from wearing.cloud_apps_contract import NAMES as CLOUD_NAMES
from wearing.native_actions_contract import NAMES as NATIVE_NAMES
from wearing.profile import PROFILE_VERSION, prepare_profile
from wearing.store import Store
from wearing.runtime import HermesRuntime, stop_owned_process
from wearing.filesystem import configuration as filesystem_configuration
from wearing.mobile import configuration as phone_configuration
from wearing import mobile
from wearing.config import write_private_json


def test_life_registration_matches_engine_startup_contract_without_installed_engine():
    from wearing.life_proxy import TOOLS
    registered = {tool.name for tool in TOOLS}
    assert {"chat_import_search", "chat_import_read"} <= registered
    assert registered == expected_life_tool_names()


@pytest.mark.parametrize("connectors,computer,disabled_memory,life", [(False, False, False, False), (True, False, False, False), (False, True, False, False), (False, False, True, False), (False, False, False, True)])
def test_real_adapter_exposes_only_personal_engine_routes(tmp_path, connectors, computer, disabled_memory, life):
    runtime = HermesRuntime(Path(__file__).resolve().parents[1] / ".wearing")
    if not runtime.python.is_file():
        pytest.skip("Install the pinned local engine to run its integration contract")
    home = tmp_path / "home"
    home.mkdir()
    if disabled_memory:
        (home / "config.yaml").write_text(yaml.safe_dump({"memory": {"memory_enabled": False, "user_profile_enabled": False}}))
    (home / "memories").mkdir()
    (home / "memories/USER.md").write_text("喜欢简短结论\n§\n测试偏好\n", encoding="utf-8")
    (home / "memories/MEMORY.md").write_text("测试经验", encoding="utf-8")
    files = filesystem_configuration(runtime.root, runtime.workspace) if connectors else None
    phone = None
    adb_blocked = None
    if connectors:
        package = mobile.installed(runtime.root)
        if package:
            # Discover the real pinned driver with synthetic enrollment only.
            # Never share the live phone registry or a usable adb binary.
            phone_root = tmp_path / "phone"
            directory = phone_root / "runtime/mobile"
            directory.mkdir(parents=True)
            (directory / "node_modules").symlink_to(runtime.root / "mobile/node_modules", target_is_directory=True)
            write_private_json(directory / "installed.json", package)
            write_private_json(phone_root / "phone.json", {"serial": "synthetic-discovery-only", "enabled": False})
            adb = phone_root / "runtime/android/platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
            adb.parent.mkdir(parents=True)
            adb.write_text('#!/bin/sh\n: > "$0.invoked"\nexit 88\n')
            adb.chmod(0o700)
            adb_blocked = adb.with_name(adb.name + '.invoked')
            phone = phone_configuration(phone_root / "runtime", runtime.python)
    if connectors and (not files or not phone):
        pytest.skip("Prepare and bind connectors for the combined discovery contract")
    life_connector = None
    if life:
        life_root = tmp_path / "life"
        Store(life_root / "wearing.sqlite3")
        life_connector = {"command": sys.executable, "args": [str(Path(__file__).resolve().parents[1] / "src/wearing/life_proxy.py"), str(life_root), "daily"]}
    prepare_profile(home, runtime.source, files, phone, computer, life=life_connector)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    key = secrets.token_urlsafe(36)
    env = runtime.env()
    guard_root = tmp_path / "guard"
    Store(guard_root / "wearing.sqlite3")
    env.update(HERMES_HOME=str(home), API_SERVER_PORT=str(port), API_SERVER_KEY=key,
               PAJIO_CONFIRMATION_DATA_DIR=str(guard_root), PAJIO_CONFIRMATION_IDENTITY="daily",
               PAJIO_RECALL_DATA_DIR=str(guard_root), PAJIO_RECALL_IDENTITY="daily", PAJIO_RECALL_LOCAL="1",
               PAJIO_USAGE_DATA_DIR=str(guard_root), PAJIO_USAGE_IDENTITY="daily", PAJIO_TRIAL_LIMITS="1")
    runner = Path(__file__).resolve().parents[1] / "src/wearing/engine_runner.py"
    with (tmp_path / "engine.log").open("w") as log:
        process = subprocess.Popen([str(runtime.python), str(runner), str(runtime.source)],
                                   env=env, cwd=tmp_path, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2) as client:
                for _ in range(300):
                    assert process.poll() is None, "Engine exited before readiness"
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("Engine readiness timed out: " + (tmp_path / "engine.log").read_text()[-2000:])
                assert client.get("/v1/capabilities").status_code == 401
                assert client.get("/v1/wearing/memory").status_code == 401
                client.headers["Authorization"] = f"Bearer {key}"
                caps = client.get("/v1/capabilities").json()
                assert caps["runtime"]["mode"] == "wearing-personal"
                assert caps["wearing"]["profile_version"] == PROFILE_VERSION
                assert caps["wearing"]["identity"] == "Pajio"
                assert caps["wearing"]["web_tools"] == ["web_search", "web_extract"]
                assert caps["wearing"]["planning_tools"] == ["todo_list"]
                assert caps["wearing"]["skill_tools"] == ["skill_manage", "skill_view", "skills_list"]
                assert set(caps["wearing"]["media_tools"]) <= {"vision_analyze"}
                assert caps["wearing"]["research_receipts"] is True
                assert caps["wearing"]["app_observation_receipts"] is True
                assert caps["wearing"]["confirmation_guard"] == "durable-v1"
                assert caps["wearing"]["session_recall_guard"] == "sources-v1"
                assert set(caps["wearing"]["life_tools"]) == ({"mcp__wearing_life__" + name for name in ("request_confirmation", "life_records", "life_create", "life_change", "task_lists", "task_list_change", "calendar_series", "goal_list", "goal_create", "goal_change", "schedule_list", "schedule_create", "schedule_change", "artifact_list", "artifact_read", "artifact_publish", "artifact_design_guide", "chat_import_search", "chat_import_read")} | {"mcp__wearing_life__" + name for name in CLOUD_NAMES | NATIVE_NAMES} if life else set())
                if life:
                    from wearing.life_proxy import TOOLS
                    assert set(caps["wearing"]["life_tools"]) == {"mcp__wearing_life__" + tool.name for tool in TOOLS}
                assert caps["features"]["runs_idempotency"]["durable"]
                assert caps["features"]["session_chat"] is False
                assert caps["features"]["browser_extension_control"] is False
                assert len(caps["wearing"]["file_tools"]) == (6 if connectors else 0)
                assert len(caps["wearing"]["phone_tools"]) == (11 if connectors else 0)
                if adb_blocked is not None:
                    assert not adb_blocked.exists(), "Discovery attempted forbidden device enumeration"
                assert caps["wearing"]["computer_tools"] == (["computer_use"] if computer else [])
                assert caps["wearing"]["memory_tools"] == (["session_search"] if disabled_memory else ["memory", "session_search"])
                memory = client.get("/v1/wearing/memory").json()
                assert memory["targets"]["user"]["entries"] == ["喜欢简短结论", "测试偏好"]
                assert memory["targets"]["memory"]["entries"] == ["测试经验"]
                assert memory["targets"]["user"]["enabled"] is not disabled_memory
                assert client.post("/v1/wearing/memory", json={}).status_code == 405
                assert (home / "memories/USER.md").read_text() == "喜欢简短结论\n§\n测试偏好\n"
                edit = {"target": "user", "revision": memory["targets"]["user"]["revision"], "action": "replace", "index": 0, "content": "喜欢准确简短结论"}
                changed = client.patch("/v1/wearing/memory", json=edit)
                if disabled_memory:
                    assert changed.status_code == 409
                else:
                    assert changed.status_code == 200, changed.text
                    updated = changed.json()["targets"]["user"]
                    assert updated["entries"] == ["喜欢准确简短结论", "测试偏好"]
                    assert client.patch("/v1/wearing/memory", json=edit).status_code == 409
                    removed = client.patch("/v1/wearing/memory", json={"target": "user", "revision": updated["revision"], "action": "remove", "index": 1})
                    assert removed.status_code == 200, removed.text
                    assert removed.json()["targets"]["user"]["entries"] == ["喜欢准确简短结论"]
                    assert '测试偏好' not in (home / "memories/USER.md").read_text()
                latest = client.get("/v1/wearing/memory").json()["targets"]["user"]
                original_entries = latest["entries"]
                toggled = client.patch("/v1/wearing/memory", json={"target": "user", "action": "set_enabled", "enabled": not latest["enabled"], "revision": latest["revision"], "settings_revision": latest["settings_revision"]})
                assert toggled.status_code == 200, toggled.text
                assert toggled.json()["targets"]["user"]["entries"] == original_entries
                assert toggled.json()["targets"]["user"]["enabled"] is not latest["enabled"]
                stale = client.patch("/v1/wearing/memory", json={"target": "user", "action": "set_enabled", "enabled": latest["enabled"], "revision": latest["revision"], "settings_revision": latest["settings_revision"]})
                assert stale.status_code == 409
                assert "memory" in client.get("/v1/capabilities").json()["wearing"]["memory_tools"]
                if not connectors and not computer and not disabled_memory:
                    (home / "memories/USER.md").unlink()
                    (home / "memories/USER.md").symlink_to(home / "SOUL.md")
                    assert client.get("/v1/wearing/memory").status_code == 503
                assert "mcp__wearing_phone__mobile_get_foreground_app" not in caps["wearing"]["phone_tools"]
                assert all((v["method"], v["path"]) in ALLOWED_ROUTES for v in caps["endpoints"].values())
                for path in ("/api/jobs", "/api/sessions", "/v1/skills", "/api/model/options", "/p/default/v1/capabilities"):
                    assert client.get(path).status_code == 404
                assert client.post("/v1/runs", json={}).status_code == 400  # routed, validated; no model call
                assert client.post("/api/jobs", json={}).status_code == 404
        finally:
            stop_owned_process(process)
        assert process.poll() is not None
