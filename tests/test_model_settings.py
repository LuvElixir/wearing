import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

from wearing import model_bridge
from wearing.runtime import HermesRuntime, RuntimeError


def fake_upstream(monkeypatch, tmp_path, *, apply_fails=False, validation_fails=False):
    (tmp_path / "config.yaml").write_text("model: original\n")
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=original-test-value\n")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(model_bridge, "provider_rows", lambda: [{"id": "deepseek", "configured": True, "env": "DEEPSEEK_API_KEY"}])
    monkeypatch.setattr(model_bridge, "inspect", lambda: {"provider": "deepseek", "model": "test-model"})
    def save_env(name, value):
        (tmp_path / ".env").write_text(f"{name}={value}\n")
    def validate(*_):
        if validation_fails:
            raise ValueError("provider error with new-secret")
        return ("", object())
    def apply(*_, **__):
        (tmp_path / "config.yaml").write_text("model: changed\n")
        if apply_fails:
            raise OSError("disk-error-new-secret")
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.config", types.SimpleNamespace(read_raw_config=lambda: {}, save_env_value=save_env))
    monkeypatch.setitem(sys.modules, "hermes_cli.web_server_config", types.SimpleNamespace(_prepare_main_assignment=validate, _apply_main_assignment_sync=apply))


@pytest.mark.parametrize("key", ["", "new-secret"])
def test_model_save_preserves_or_replaces_key_without_echo(tmp_path, monkeypatch, key):
    fake_upstream(monkeypatch, tmp_path)
    before = (tmp_path / ".env").read_bytes()
    result = model_bridge.configure({"provider": "deepseek", "model": "test-model", "key": key})
    assert "error" not in result
    assert "new-secret" not in json.dumps(result)
    if not key:
        assert (tmp_path / ".env").read_bytes() == before
    else:
        assert (tmp_path / ".env").read_text() == "DEEPSEEK_API_KEY=new-secret\n"


@pytest.mark.parametrize("stage", ["validation", "apply"])
def test_model_failures_preserve_config_and_hide_secrets(tmp_path, monkeypatch, stage):
    fake_upstream(monkeypatch, tmp_path, validation_fails=stage == "validation", apply_fails=stage == "apply")
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    result = model_bridge.configure({"provider": "deepseek", "model": "test-model", "key": "new-secret"})
    assert "error" in result
    assert "new-secret" not in json.dumps(result)
    assert all(p.read_bytes() == value for p, value in before.items())


async def test_bridge_uses_stdin_not_argv_and_suppresses_subprocess_diagnostics(tmp_path, monkeypatch):
    runtime = HermesRuntime(tmp_path)
    runtime.prepare_home()
    interpreter = runtime.home / "installs/test/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    monkeypatch.setattr(HermesRuntime, "python", property(lambda _: interpreter))
    def run(command, **kwargs):
        assert "new-secret" not in str(command)
        assert json.loads(kwargs["input"])["key"] == "new-secret"
        raise subprocess.CalledProcessError(1, command, stderr="diagnostic-new-secret")
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError) as error:
        await runtime.model_settings({"action": "configure", "key": "new-secret"})
    assert "new-secret" not in str(error.value)
