import json

import httpx
import pytest
import yaml

from wearing.app import create_app
from wearing.computer import enroll, enrolled
from wearing.config import Settings
from wearing.profile import prepare_profile
from wearing.runtime import HermesRuntime, RuntimeError


def test_computer_is_opt_in_and_corrupt_registry_fails_closed(tmp_path):
    assert not enrolled(tmp_path)
    (tmp_path / "computer.json").write_text("{broken")
    assert not enrolled(tmp_path)
    enroll(tmp_path)
    assert enrolled(tmp_path)


def test_computer_profile_keeps_only_selected_capabilities(tmp_path):
    source, home = tmp_path / "source", tmp_path / "home"
    source.mkdir()
    profile = prepare_profile(home, source, computer=True)
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert profile["toolsets"] == ["memory", "session_search", "web", "todo", "skills", "vision", "computer_use"]
    assert config["approvals"]["mode"] == "manual"
    assert config["computer_use"]["permission_mode"] == "standard"
    assert config["computer_use"]["cua_telemetry"] is False
    assert config["platform_toolsets"]["cli"] == ["no_mcp"]
    assert prepare_profile(home, source)["toolsets"] == ["memory", "session_search", "web", "todo", "skills", "vision"]


async def test_enrollment_requires_real_permission_probe_and_preserves_handoff(tmp_path, monkeypatch):
    runtime = HermesRuntime(tmp_path)
    async def unready(force=False):
        return {"installed": True, "ready": False}
    monkeypatch.setattr(runtime, "computer_status", unready)
    with pytest.raises(RuntimeError, match="权限尚未就绪"):
        await runtime.bind_computer()
    assert not enrolled(tmp_path)
    async def ready(force=False):
        return {"installed": True, "ready": True, "control": {"holder": "human"}}
    monkeypatch.setattr(runtime, "computer_status", ready)
    async def forbidden(*_):
        raise AssertionError("Enrollment must not silently release human control")
    monkeypatch.setattr(runtime, "computer_command", forbidden)
    await runtime.bind_computer()
    assert enrolled(tmp_path)


async def test_takeover_is_authenticated_and_available_during_active_run(tmp_path, monkeypatch):
    app = create_app(Settings(tmp_path))
    calls = []
    async def command(action, **kwargs):
        calls.append(action)
        return {"holder": "human" if action == "takeover" else "agent", "epoch": len(calls)}
    monkeypatch.setattr(app.state.runtime, "computer_command", command)
    task = app.state.store.create("active local test", "computer")
    app.state.store.update(task["id"], status="running", run_id="test-run")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.post("/api/computer/pause")).status_code == 403
        assert not calls
        client.headers["X-Wearing-Token"] = (await client.get("/api/bootstrap")).json()["token"]
        assert (await client.post("/api/computer/bind")).status_code == 409
        assert (await client.post("/api/computer/pause")).json()["holder"] == "human"
        assert (await client.post("/api/computer/resume")).json()["holder"] == "agent"
    assert calls == ["takeover", "resume"]
    await app.state.service.hermes.close()


async def test_probe_bridge_runs_under_managed_interpreter(tmp_path, monkeypatch):
    # Exercise argument expansion and JSON transport without invoking a desktop.
    runtime = HermesRuntime(tmp_path)
    import sys
    monkeypatch.setattr(HermesRuntime, "python", property(lambda _: __import__('pathlib').Path(sys.executable)))
    runtime.source.mkdir(parents=True)
    class Child:
        returncode = 0
        async def communicate(self):
            return b'{"holder":"human"}', b''
    async def spawn(*args, **kwargs):
        assert args[-1] == "control" and all(isinstance(a, str) for a in args)
        assert kwargs["env"]["HERMES_HOME"] == str(runtime.home)
        return Child()
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    assert await runtime.computer_command("control") == {"holder": "human"}


def test_real_upstream_takeover_blocks_observation_and_input_before_driver(tmp_path):
    from pathlib import Path
    import subprocess
    runtime = HermesRuntime(Path(__file__).resolve().parents[1] / ".wearing")
    if not runtime.python.is_file():
        pytest.skip("Requires the pinned local Hermes interpreter")
    env = runtime.env()
    env["HERMES_HOME"] = str(tmp_path / "isolated-home")
    script = '''
import json
from tools.bot_desktop import lease
from tools.computer_use.tool import handle_computer_use
lease.acquire("wearing-test-human")
blocked = [json.loads(handle_computer_use(args)) for args in (
    {"action":"capture","mode":"ax","app":"WearingProbe"},
    {"action":"type","text":"MUST NOT TYPE"})]
assert all(r.get("code")=="human_has_control" for r in blocked)
assert lease.release("wrong-viewer").holder == "human"
assert lease.release("wearing-test-human").holder == "agent"
print("blocked capture and input; stale handback refused; correct handback accepted")
'''
    result = subprocess.run([str(runtime.python), "-c", script], cwd=runtime.source,
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "blocked capture and input" in result.stdout
