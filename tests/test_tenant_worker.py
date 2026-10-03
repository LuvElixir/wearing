import json
import os
from pathlib import Path
import shutil

import httpx
import pytest

from wearing.cloud.instance import InstanceError, initialize_instance, instance_status, load_instance
from wearing.cloud.worker import create_tenant_app
from wearing.config import Settings, write_private_json
from wearing.hermes import HermesClient


ORIGIN = "https://wearing.example"


def initialize(path, tenant="tenant_A"):
    return initialize_instance(path, tenant, ORIGIN)


def headers(root, tenant="tenant_A"):
    return {"Authorization": "Bearer " + (root / "gateway.key").read_text().strip(), "X-Wearing-Tenant": tenant}


def test_initialized_instance_is_private_idempotent_and_cannot_change_owner(tmp_path):
    root = tmp_path / "instance"
    first = initialize(root)
    key = (root / "gateway.key").read_bytes()
    assert initialize(root) == first
    assert key == (root / "gateway.key").read_bytes()
    with pytest.raises(InstanceError):
        initialize(root, "tenant_B")
    with pytest.raises(InstanceError):
        initialize_instance(root, "tenant_A", "https://another.example")
    assert load_instance(root) == first
    status = instance_status(root)
    assert key.decode().strip() not in json.dumps(status)
    assert status["hardware_isolation_verified"] is False
    if os.name != "nt":
        assert not (root / "gateway.key").stat().st_mode & 0o077
        assert not (root / "data").stat().st_mode & 0o077


@pytest.mark.parametrize("tenant,origin", [("../escape", ORIGIN), ("tenant_A", "http://public.example"), ("tenant_A", "https://user:secret@example.com"), ("tenant_A", "https://example.com/path")])
def test_bad_binding_never_creates_instance(tmp_path, tenant, origin):
    with pytest.raises(InstanceError):
        initialize_instance(tmp_path / "instance", tenant, origin)
    assert not (tmp_path / "instance").exists()


def test_does_not_adopt_existing_local_user_data(tmp_path):
    root = tmp_path / "existing"
    root.mkdir()
    data = root / "wearing.sqlite3"
    data.write_bytes(b"original-user-data")
    with pytest.raises(InstanceError):
        initialize(root)
    assert data.read_bytes() == b"original-user-data"
    assert list(root.iterdir()) == [data]


def test_wrong_volume_and_symlinks_are_rejected_before_database_creation(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    initialize(a); initialize(b, "tenant_B")
    shutil.copyfile(a / "data/instance-owner.json", b / "data/instance-owner.json")
    with pytest.raises(InstanceError):
        create_tenant_app(b)
    assert not (b / "data/wearing.sqlite3").exists()
    (a / "gateway.key").unlink()
    (a / "gateway.key").symlink_to(b / "gateway.key")
    with pytest.raises(InstanceError):
        load_instance(a)


@pytest.mark.parametrize("saved", [{}, [], {"url": "http://127.0.0.1:9999", "key": 123}, {"url": "private-invalid-url", "key": "private-key"}])
async def test_bad_engine_connection_fails_before_database_and_releases_lock(tmp_path, saved):
    root = tmp_path / "instance"
    initialize(root)
    connection = root / "data/connection.json"
    write_private_json(connection, saved)
    with pytest.raises(InstanceError) as error:
        create_tenant_app(root, engine_autostart=False)
    assert "private-" not in str(error.value)
    assert not (root / "data/wearing.sqlite3").exists()
    connection.unlink()
    recovered = create_tenant_app(root, engine_autostart=False)
    async with recovered.router.lifespan_context(recovered):
        assert recovered.state.service.hermes.configured is False


async def test_every_route_requires_key_and_bound_tenant_and_origin(tmp_path):
    root = tmp_path / "instance"
    initialize(root)
    app = create_tenant_app(root, engine_autostart=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            for path in ("/", "/assets/app.js", "/api/bootstrap", "/api/conversation", "/api/workspace", "/api/memory", "/internal/runtime"):
                assert (await client.get(path)).status_code == 401
                assert (await client.get(path, headers=headers(root, "tenant_B"))).status_code == 403
            client.headers.update(headers(root))
            assert (await client.get("/api/bootstrap", headers={"Origin": "http://wearing.example"})).status_code == 403
            assert (await client.get("/api/bootstrap", headers={"Origin": "https://foreign.example"})).status_code == 403
            assert (await client.get("/api/bootstrap", headers={"Host": "evil.example"})).status_code == 400
            token = (await client.get("/api/bootstrap", headers={"Origin": ORIGIN})).json()["token"]
            assert (await client.post("/api/conversation", json={"content": "without CSRF"})).status_code == 403
            client.headers["X-Wearing-Token"] = token
            assert (await client.post("/api/conversation", json={"content": "保留在本租户"})).status_code == 201
            for path in ("/api/phone", "/api/computer", "/api/doctor", "/api/connection"):
                assert (await client.get(path)).status_code == 501
            assert app.state.runtime.local_devices is False
            status = (await client.get("/internal/runtime")).json()
            assert status["tenant_id"] == "tenant_A" and status["hardware_isolation_verified"] is False
            assert status["engine_state"] == "not_configured"
            duplicate = [("Authorization", headers(root)["Authorization"]), ("Authorization", headers(root)["Authorization"]), ("X-Wearing-Tenant", "tenant_A")]
            assert (await client.get("/api/bootstrap", headers=duplicate)).status_code == 401


async def test_private_records_files_and_restart_do_not_cross_tenants(tmp_path, monkeypatch):
    a, b = tmp_path / "A", tmp_path / "B"
    initialize(a); initialize(b, "tenant_B")
    monkeypatch.setenv("WEARING_DATA_DIR", str(a / "data"))
    monkeypatch.setenv("WEARING_HERMES_KEY", "do-not-inherit")
    first, second = create_tenant_app(a, engine_autostart=False), create_tenant_app(b, engine_autostart=False)
    async with first.router.lifespan_context(first), second.router.lifespan_context(second):
        with pytest.raises(InstanceError, match="已有运行实例"):
            create_tenant_app(a)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=first), base_url=ORIGIN, headers=headers(a)) as ca, httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url=ORIGIN, headers=headers(b, "tenant_B")) as cb:
            for client in (ca, cb):
                client.headers["X-Wearing-Token"] = (await client.get("/api/bootstrap")).json()["token"]
            task = (await ca.post("/api/conversation", json={"content": "A-only-message"})).json()
            assert "A-only-message" in (await ca.get("/api/conversation")).text
            assert (await cb.get("/api/conversation")).json() == []
            assert (await cb.get('/api/tasks/' + task['task']['id'])).status_code == 404
            assert first.state.service.hermes.configured is False and second.state.service.hermes.configured is False
            workspace = a / "data/workspace"
            workspace.mkdir()
            (workspace / "private.txt").write_text("A-only-file")
            assert (await ca.get("/api/workspace/file", params={"path": "private.txt"})).text == "A-only-file"
            assert (await cb.get("/api/workspace/file", params={"path": "private.txt"})).status_code == 404
            assert (await cb.get("/api/bootstrap", headers={"Authorization": headers(a)["Authorization"]})).status_code == 401
    restarted = create_tenant_app(a, engine_autostart=False)
    async with restarted.router.lifespan_context(restarted):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=ORIGIN, headers=headers(a)) as client:
            assert "A-only-message" in (await client.get("/api/conversation")).text
            assert (await client.get("/api/workspace/file", params={"path": "private.txt"})).text == "A-only-file"


async def test_managed_engine_is_started_on_boot_and_connection_is_server_only(tmp_path, monkeypatch):
    root = tmp_path / "instance"
    initialize(root)
    wire = HermesClient(Settings(root / "data", hermes_key="test"), httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    app = create_tenant_app(root, hermes=wire)
    engine = app.state.runtime
    started = []
    old_status = engine.status
    monkeypatch.setattr(engine, "status", lambda: {**old_status(), "installed": True})
    async def start():
        started.append(True)
        return {"url": "http://127.0.0.1:9999", "key": "private-engine-key"}
    monkeypatch.setattr(engine, "start", start)
    async with app.router.lifespan_context(app):
        assert started == [True]
        assert json.loads((root / "data/connection.json").read_text())["key"] == "private-engine-key"
        assert app.state.service.hermes.configured is True


async def test_missing_model_does_not_destroy_records_or_expose_private_error(tmp_path, monkeypatch, caplog):
    from wearing.runtime import RuntimeError
    root = tmp_path / "instance"
    initialize(root)
    app = create_tenant_app(root)
    engine = app.state.runtime
    old_status = engine.status
    monkeypatch.setattr(engine, "status", lambda: {**old_status(), "installed": True})
    async def fail():
        raise RuntimeError("private-provider-error")
    monkeypatch.setattr(engine, "start", fail)
    async with app.router.lifespan_context(app):
        assert app.state.service.hermes.configured is False
        assert (root / "data/wearing.sqlite3").is_file()
    assert "private-provider-error" not in caplog.text
