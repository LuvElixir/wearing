"""Document import contracts through the real ASGI app and temporary private data."""
import asyncio
import hashlib
import os
from pathlib import Path
import sqlite3

import httpx
import pytest

from wearing.app import create_app
from wearing.cloud.worker import TenantBoundary
from wearing.config import Settings
from wearing.workspace_upload import MAX_IMPORT_BYTES


KEY = "document-import-001"
FILE = "会议材料.pdf"
BODY = b"%PDF-1.7\nsynthetic meeting material\n%%EOF"


@pytest.fixture
async def upload_app(tmp_path):
    app = create_app(Settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        bootstrap = (await client.get("/api/bootstrap")).json()
        client.headers.update({"X-Wearing-Token": bootstrap["token"], "X-Wearing-Identity": "daily"})
        yield app, client, app.state.runtime.workspace
    await app.state.service.hermes.close()


async def upload(client, data=BODY, *, key=KEY, name=FILE, headers=None, identity=None):
    params = {"name": name, "request_key": key}
    if identity is not None:
        params["identity"] = identity
    return await client.post("/api/workspace/import", params=params, content=data, headers=headers)


def imports(app):
    with app.state.store.connection() as db:
        return [dict(row) for row in db.execute("SELECT * FROM workspace_imports")]


async def test_import_requires_session_token_and_rejects_foreign_origin_before_write(upload_app):
    app, client, root = upload_app
    for headers in ({"X-Wearing-Token": ""}, {"X-Wearing-Token": "stale-token"}, {"Origin": "https://unrelated.example"}):
        response = await upload(client, headers=headers)
        assert response.status_code == 403
    assert not imports(app)
    assert not root.exists()
    assert (await upload(client, headers={"Origin": "http://testserver"})).status_code == 201


async def test_tenant_boundary_requires_correct_instance_auth_and_tenant(tmp_path):
    app = create_app(Settings(tmp_path))
    app.add_middleware(TenantBoundary, tenant_id="tenant_test", gateway_key="instance-test-key")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await upload(client)).status_code == 401
        client.headers["Authorization"] = "Bearer instance-test-key"
        assert (await upload(client)).status_code == 403
        client.headers["X-Wearing-Tenant"] = "tenant_other"
        assert (await upload(client)).status_code == 403
        client.headers["X-Wearing-Tenant"] = "tenant_test"
        token = (await client.get("/api/bootstrap")).json()["token"]
        assert (await upload(client)).status_code == 403  # Auth does not waive CSRF.
        client.headers["X-Wearing-Token"] = token
        assert (await upload(client)).status_code == 201
        client.headers["Authorization"] = "Bearer wrong-key"
        assert (await upload(client)).status_code == 401
        assert len(imports(app)) == 1
    await app.state.service.hermes.close()


async def test_import_is_private_data_and_download_does_not_execute_html_or_script(upload_app, tmp_path):
    app, client, root = upload_app
    canary = tmp_path / "should-never-exist"
    content = f"#!/bin/sh\ntouch '{canary}'\n<script>globalThis.executed=true</script>".encode()
    response = await upload(client, data=content, name="material.html")
    assert response.status_code == 201
    receipt = response.json()
    assert receipt["request_key"] == KEY
    assert receipt["sha256"] == hashlib.sha256(content).hexdigest()
    assert receipt["replayed"] is False
    path = root / receipt["file"]["path"]
    assert path.read_bytes() == content
    assert path.stat().st_mode & 0o777 == 0o600
    assert not canary.exists()
    downloaded = await client.get("/api/workspace/file", params={"path": receipt["file"]["path"]})
    assert downloaded.content == content
    assert downloaded.headers["content-type"] == "application/octet-stream"
    assert "attachment" in downloaded.headers["content-disposition"]
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert not canary.exists()
    assert app.state.store.list() == []  # Importing cannot create or execute an Agent task.


async def test_identity_boundaries_include_reused_request_keys_and_download(upload_app):
    app, client, root = upload_app
    response = await upload(client)
    path = response.json()["file"]["path"]
    other = app.state.store.save_identity("另一测试身份")["id"]
    client.headers["X-Wearing-Identity"] = other
    assert (await client.get("/api/workspace/file", params={"path": path})).status_code == 404
    assert (await upload(client, identity="daily")).status_code == 409
    assert (await upload(client, data=b"other-identity-only")).status_code == 201
    assert (await client.get("/api/workspace/file", params={"path": path})).content == b"other-identity-only"
    assert (root / path).read_bytes() == BODY
    assert {row["identity_id"] for row in imports(app)} == {"daily", other}
    client.headers["X-Wearing-Identity"] = "unknown-identity"
    assert (await upload(client)).status_code == 404
    assert len(imports(app)) == 2


async def test_same_key_same_bytes_recovers_receipt_without_rewriting_file(upload_app):
    app, client, root = upload_app
    first = (await upload(client)).json()
    path = root / first["file"]["path"]
    before = path.stat()
    second = await upload(client)
    assert second.status_code == 201
    assert second.json() == {**first, "replayed": True}
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert path.stat().st_ino == before.st_ino
    assert len(imports(app)) == 1


async def test_concurrent_duplicate_requests_commit_one_file_and_one_receipt(upload_app):
    app, client, root = upload_app
    results = await asyncio.gather(*(upload(client) for _ in range(6)))
    assert all(result.status_code == 201 for result in results)
    assert sum(result.json()["replayed"] is False for result in results) == 1
    assert len({result.json()["file"]["path"] for result in results}) == 1
    assert len(imports(app)) == 1
    assert len([path for path in root.rglob("*") if path.is_file()]) == 1


@pytest.mark.parametrize("change", ["body", "filename"])
async def test_same_key_changed_payload_rejected_without_overwriting_original(upload_app, change):
    app, client, root = upload_app
    path = (await upload(client)).json()["file"]["path"]
    response = await upload(client, data=BODY if change == "filename" else b"different", name="new.pdf" if change == "filename" else FILE)
    assert response.status_code == 409
    assert (root / path).read_bytes() == BODY
    assert len(imports(app)) == 1
    assert not (root / "imports" / KEY / "new.pdf").exists()


async def test_existing_different_file_and_changed_receipted_file_never_overwritten(upload_app):
    app, client, root = upload_app
    file = root / "imports" / KEY / FILE
    file.parent.mkdir(parents=True)
    file.write_bytes(b"existing unrelated bytes")
    assert (await upload(client)).status_code == 409
    assert file.read_bytes() == b"existing unrelated bytes"
    assert not imports(app)
    file.unlink()
    assert (await upload(client)).status_code == 201
    file.write_bytes(b"edited by another process")
    assert (await upload(client)).status_code == 409
    assert file.read_bytes() == b"edited by another process"
    assert len(imports(app)) == 1


async def test_retry_adopts_identical_orphan_after_database_commit_failure(upload_app):
    app, client, root = upload_app
    with app.state.store.connection() as db:
        db.execute("CREATE TRIGGER import_test_failure BEFORE INSERT ON workspace_imports BEGIN SELECT RAISE(ABORT,'test save failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        await upload(client)
    path = root / "imports" / KEY / FILE
    assert path.read_bytes() == BODY
    inode = path.stat().st_ino
    assert not imports(app)
    with app.state.store.connection() as db:
        db.execute("DROP TRIGGER import_test_failure")
    response = await upload(client)
    assert response.status_code == 201
    assert path.stat().st_ino == inode
    assert len(imports(app)) == 1


@pytest.mark.parametrize("name", ["../escape.txt", "..\\escape.txt", "/tmp/escape.txt", "folder/file.txt", ".", "..", ".env", "bad\x00name", "bad\nname", " ", "熊" * 61])
async def test_invalid_filenames_rejected_before_filesystem_changes(upload_app, name):
    app, client, root = upload_app
    assert (await upload(client, name=name)).status_code == 422
    assert not imports(app)
    assert not root.exists()


@pytest.mark.parametrize("key", ["short", "../outside/import-key", "a" * 81, "valid-import-key/other"])
async def test_invalid_request_keys_rejected_before_filesystem_changes(upload_app, key):
    app, client, root = upload_app
    assert (await upload(client, key=key)).status_code == 422
    assert not imports(app)
    assert not root.exists()


@pytest.mark.parametrize("component", ["root", "imports", "key", "file"])
async def test_symlink_at_each_destination_component_is_rejected(upload_app, tmp_path, component):
    app, client, root = upload_app
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "private.pdf"
    canary.write_bytes(b"private-canary")
    destination = {"root": root, "imports": root / "imports", "key": root / "imports" / KEY, "file": root / "imports" / KEY / FILE}[component]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(canary if component == "file" else outside, target_is_directory=component != "file")
    assert (await upload(client)).status_code == 409
    assert canary.read_bytes() == b"private-canary"
    assert sorted(path.name for path in outside.iterdir()) == ["private.pdf"]
    assert not imports(app)


async def test_existing_directory_is_not_read_or_replaced_as_a_file(upload_app):
    app, client, root = upload_app
    directory = root / "imports" / KEY / FILE
    directory.mkdir(parents=True)
    assert (await upload(client)).status_code == 409
    assert directory.is_dir()
    assert not imports(app)


async def test_fifo_cannot_block_import_and_hold_database_write_lock(upload_app):
    app, client, root = upload_app
    fifo = root / "imports" / KEY / FILE
    fifo.parent.mkdir(parents=True)
    os.mkfifo(fifo)
    request = asyncio.create_task(upload(client))
    done, _ = await asyncio.wait({request}, timeout=1.0)
    if not done:
        # Release an implementation with blocking open so a failed regression
        # cannot leak a thread/write transaction into the rest of the suite.
        writer = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.close(writer)
        await request
    assert done, "An existing FIFO blocked the request before fstat and retained the DB write lock"
    assert request.result().status_code == 409
    assert not imports(app)


async def test_empty_and_oversized_stream_rejected_and_exact_limit_accepted(upload_app):
    app, client, root = upload_app
    assert (await upload(client, data=b"")).status_code == 413
    consumed = []

    async def chunks():
        for chunk in (b"x" * MAX_IMPORT_BYTES, b"y", b"must-not-be-read"):
            consumed.append(len(chunk))
            yield chunk

    response = await upload(client, data=chunks())
    assert response.status_code == 413
    assert consumed == [MAX_IMPORT_BYTES, 1]
    assert not root.exists()
    assert not imports(app)
    response = await upload(client, data=b"x" * MAX_IMPORT_BYTES)
    assert response.status_code == 201
    assert response.json()["file"]["size"] == MAX_IMPORT_BYTES
    assert (root / response.json()["file"]["path"]).stat().st_size == MAX_IMPORT_BYTES


async def test_unicode_normalization_makes_equivalent_filename_retry_idempotent(upload_app):
    app, client, root = upload_app
    first = await upload(client, name="cafe\u0301.txt")
    second = await upload(client, name="caf\u00e9.txt")
    assert first.status_code == second.status_code == 201
    assert second.json()["replayed"] is True
    assert first.json()["file"]["path"] == second.json()["file"]["path"]
    assert len(imports(app)) == 1
