import asyncio
import hashlib
import io
import json
import subprocess
import sys
import tarfile

import httpx
import pytest
from filelock import FileLock

from wearing.app import create_app
from wearing.config import Settings
from wearing.runtime import HermesRuntime, RuntimeError, stop_owned_process, unpack_source


def test_source_must_match_digest_before_extraction(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    archive.write_bytes(b"not the official archive")
    with pytest.raises(RuntimeError, match="校验失败"):
        unpack_source(archive, tmp_path / "source")
    assert not (tmp_path / "source").exists()


@pytest.mark.parametrize("name,kind", [("../escaped", "file"), ("source/link", "link")])
def test_unpack_rejects_traversal_and_links(tmp_path, monkeypatch, name, kind):
    archive = tmp_path / "input.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        item = tarfile.TarInfo(name)
        if kind == "link":
            item.type, item.linkname = tarfile.SYMTYPE, "../../escaped"
            output.addfile(item)
        else:
            item.size = 1
            output.addfile(item, io.BytesIO(b"x"))
    monkeypatch.setattr("wearing.runtime.SOURCE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(RuntimeError, match="不支持的路径"):
        unpack_source(archive, tmp_path / "source")
    assert not (tmp_path / "escaped").exists()


def test_model_configuration_survives_runtime_preparation(tmp_path):
    runtime = HermesRuntime(tmp_path)
    runtime.prepare_home()
    config = runtime.home / "config.yaml"
    assert json.loads(config.read_text())["platform_toolsets"]["api_server"] == []
    config.write_text("model:\n  provider: user-selected\n")
    runtime.prepare_home()
    assert "user-selected" in config.read_text()
    assert "key" not in runtime.status()


async def test_concurrent_install_is_rejected_and_network_error_is_safe(tmp_path, monkeypatch):
    runtime = HermesRuntime(tmp_path)
    runtime.prepare_home()
    with FileLock(runtime.root / "install.lock"):
        assert "另一个进程" in (await runtime.install())["error"]
    def fail(_):
        raise OSError("sensitive-debug-token")
    monkeypatch.setattr("wearing.runtime.fetch_source", fail)
    status = await runtime.install()
    assert status["phase"] == "failed"
    assert "sensitive-debug-token" not in str(status)
    assert not runtime.lock.locked()


async def test_model_login_is_required_before_launching_gateway(tmp_path, monkeypatch):
    runtime = HermesRuntime(tmp_path)
    runtime.prepare_home()
    interpreter = runtime.home / "installs" / "test" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    from wearing.runtime import HERMES_REVISION
    (runtime.root / "installed.json").write_text(json.dumps({"revision": HERMES_REVISION, "python": str(interpreter)}))
    async def missing_model(force=False):
        return {"state": "needs_login", "provider": None}
    monkeypatch.setattr(runtime, "inspect_model", missing_model)
    with pytest.raises(RuntimeError, match="完成登录"):
        await runtime.start()
    assert runtime.process is None


def test_stopping_owned_process_exits_and_does_not_touch_unrelated_process():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        stop_owned_process(child)
        assert child.poll() is not None
        assert unrelated.poll() is None
        stop_owned_process(child)  # idempotent, no stale PID signaling
    finally:
        stop_owned_process(unrelated)


def test_local_auth_namespace_survives_process_restart(tmp_path):
    first = HermesRuntime(tmp_path)
    first.prepare_home()
    key = first.connection_key()
    second = HermesRuntime(tmp_path)
    assert second.connection_key() == key
    assert key not in json.dumps(second.status())
    credentials = first.root / "api-credential.json"
    credentials.write_text('{"key":"damaged"}')
    with pytest.raises(RuntimeError, match="原记录已保留"):
        second.connection_key()
    assert credentials.read_text() == '{"key":"damaged"}'


async def test_runtime_connection_secret_stays_server_side_and_active_run_blocks_switch(tmp_path, monkeypatch):
    app = create_app(Settings(tmp_path))
    runtime = app.state.runtime
    async def start():
        return {"url": "http://127.0.0.1:8888", "key": "private-gateway-key"}
    monkeypatch.setattr(runtime, "start", start)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.post("/api/runtime/start")).status_code == 403
        token = (await client.get("/api/bootstrap")).json()["token"]
        client.headers["X-Wearing-Token"] = token
        response = await client.post("/api/runtime/start")
        assert response.status_code == 200
        assert "private-gateway-key" not in response.text
        assert json.loads((tmp_path / "connection.json").read_text())["key"] == "private-gateway-key"
        task = app.state.store.create("still running", "computer")
        app.state.store.update(task["id"], status="running", run_id="run-existing")
        assert (await client.post("/api/runtime/start")).status_code == 409
        assert (await client.post("/api/runtime/stop")).status_code == 409
    await app.state.service.hermes.close()
    await runtime.close()
