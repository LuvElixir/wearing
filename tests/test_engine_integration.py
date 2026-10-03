"""No-LLM contract test against an installed, pinned Hermes interpreter."""

import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
import yaml

import httpx
import pytest

from wearing.engine_runner import ALLOWED_ROUTES
from wearing.profile import prepare_profile
from wearing.runtime import HermesRuntime, stop_owned_process
from wearing.filesystem import configuration as filesystem_configuration
from wearing.mobile import configuration as phone_configuration


@pytest.mark.parametrize("connectors,computer,disabled_memory", [(False, False, False), (True, False, False), (False, True, False), (False, False, True)])
def test_real_adapter_exposes_only_personal_engine_routes(tmp_path, connectors, computer, disabled_memory):
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
    phone = phone_configuration(runtime.root, runtime.python) if connectors else None
    if connectors and (not files or not phone):
        pytest.skip("Prepare and bind connectors for the combined discovery contract")
    prepare_profile(home, runtime.source, files, phone, computer)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    key = secrets.token_urlsafe(36)
    env = runtime.env()
    env.update(HERMES_HOME=str(home), API_SERVER_PORT=str(port), API_SERVER_KEY=key)
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
                assert caps["features"]["runs_idempotency"]["durable"]
                assert caps["features"]["session_chat"] is False
                assert caps["features"]["browser_extension_control"] is False
                assert len(caps["wearing"]["file_tools"]) == (6 if connectors else 0)
                assert len(caps["wearing"]["phone_tools"]) == (11 if connectors else 0)
                assert caps["wearing"]["computer_tools"] == (["computer_use"] if computer else [])
                assert caps["wearing"]["memory_tools"] == (["session_search"] if disabled_memory else ["memory", "session_search"])
                memory = client.get("/v1/wearing/memory").json()
                assert memory["targets"]["user"]["entries"] == ["喜欢简短结论", "测试偏好"]
                assert memory["targets"]["memory"]["entries"] == ["测试经验"]
                assert memory["targets"]["user"]["enabled"] is not disabled_memory
                assert client.post("/v1/wearing/memory", json={}).status_code == 405
                assert (home / "memories/USER.md").read_text() == "喜欢简短结论\n§\n测试偏好\n"
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
