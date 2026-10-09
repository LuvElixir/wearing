from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
import yaml

from wearing.skills_api import SkillLibrary, install_skill_routes
from wearing.store import Store


def skill(root, name="documents/letter", title="letter", extra=""):
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(f"---\nname: {title}\ndescription: Letter writing\n{extra}---\n\n# Guide\nRead the supplied document.")
    return path


def library(tmp_path):
    runtime = SimpleNamespace(home=tmp_path / "identity" / "hermes", source=tmp_path / "runtime")
    runtime.home.mkdir(parents=True)
    (runtime.home / "config.yaml").write_text("model:\n  api_key: private-canary\nskills:\n  auto_load: [custom]\n")
    return SkillLibrary(runtime, store=Store(tmp_path / "app.sqlite3"), identity="daily")


def test_list_detail_expose_skill_content_but_no_secrets_or_absolute_paths(tmp_path):
    lib = library(tmp_path)
    skill(lib.installed)
    skill(lib.catalog)
    listing = lib.list()
    assert listing["installed"][0]["enabled"]
    assert listing["catalog"][0]["installed"]
    assert "private-canary" not in str(listing)
    assert str(tmp_path) not in str(listing)
    detail = lib.detail("installed", "documents/letter")
    assert "# Guide" in detail["content"]


def test_enable_disable_changes_actual_runtime_config_preserving_other_fields(tmp_path):
    lib = library(tmp_path)
    skill(lib.installed)
    initial = lib.list()
    updated = lib.enabled("documents/letter", False, initial["revision"])
    assert not updated["installed"][0]["enabled"]
    config = yaml.safe_load(lib.config_path.read_text())
    assert config["skills"]["disabled"] == ["letter"]
    assert config["skills"]["auto_load"] == ["custom"]
    assert config["model"]["api_key"] == "private-canary"
    config["skills"]["platform_disabled"] = {"api_server": ["letter"], "telegram": ["letter"]}
    lib.config_path.write_text(yaml.safe_dump(config))
    enabled = lib.enabled("documents/letter", True, lib.list()["revision"])
    assert enabled["installed"][0]["enabled"]
    assert yaml.safe_load(lib.config_path.read_text())["skills"]["platform_disabled"]["telegram"] == ["letter"]
    assert lib.config_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(HTTPException) as error:
        lib.enabled("documents/letter", False, initial["revision"])
    assert error.value.status_code == 409


def test_install_is_atomic_copy_with_no_script_execution_and_never_overwrites(tmp_path):
    lib = library(tmp_path)
    package = skill(lib.catalog)
    (package / "scripts").mkdir()
    (package / "scripts" / "setup.py").write_text("raise Exception('MUST NOT RUN')")
    item = lib.list()["catalog"][0]
    installed = lib.install(item["id"], item["revision"])
    assert installed["installed"][0]["name"] == "letter"
    assert (lib.installed / item["id"] / "scripts" / "setup.py").exists()
    target = lib.installed / item["id"] / "SKILL.md"
    target.write_text(target.read_text() + "\nUser modification")
    lib.install(item["id"], item["revision"])
    assert "User modification" in target.read_text()
    assert not list(lib.installed.glob(".install-*"))


def test_traversal_symlinks_and_changed_packages_cannot_be_read_or_installed(tmp_path):
    lib = library(tmp_path)
    package = skill(lib.catalog)
    item = lib.list()["catalog"][0]
    for value in ("../private", "/tmp/private", "documents\\letter", "documents/../letter"):
        with pytest.raises(HTTPException):
            lib.detail("catalog", value)
    (package / "leak").symlink_to(lib.config_path)
    with pytest.raises(HTTPException):
        lib.install(item["id"], item["revision"])
    assert not (lib.installed / item["id"]).exists()
    (package / "leak").unlink()
    (package / "SKILL.md").write_text("# Updated")
    with pytest.raises(HTTPException) as error:
        lib.install(item["id"], item["revision"])
    assert error.value.status_code == 409


def test_invalid_config_and_essential_skill_never_silently_change(tmp_path):
    lib = library(tmp_path)
    skill(lib.installed, title="hermes-agent")
    before = lib.config_path.read_text()
    with pytest.raises(HTTPException):
        lib.enabled("documents/letter", False, lib.list()["revision"])
    assert lib.config_path.read_text() == before
    lib.config_path.write_text("skills: [invalid]")
    with pytest.raises(HTTPException):
        lib.list()
    assert lib.config_path.read_text() == "skills: [invalid]"


async def test_routes_use_request_identity_for_reads_and_mutations(tmp_path):
    runtimes = {key: SimpleNamespace(home=tmp_path / key / "hermes", source=tmp_path / "source") for key in ("one", "two")}
    for runtime in runtimes.values():
        runtime.home.mkdir(parents=True)
        skill(runtime.home / "skills")
    app = FastAPI()
    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.identity_id = request.headers.get("x-identity", "one")
        return await call_next(request)
    install_skill_routes(app, runtimes.__getitem__)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = (await client.get("/api/skills")).json()
        result = await client.patch("/api/skills/enabled", json={"id": "documents/letter", "enabled": False, "revision": result["revision"]})
        assert result.status_code == 200
        assert not result.json()["installed"][0]["enabled"]
        other = (await client.get("/api/skills", headers={"x-identity": "two"})).json()
        assert other["installed"][0]["enabled"]
        assert (await client.get("/api/skills/detail", params={"id": "../config"})).status_code == 422


def test_disabled_setting_is_read_by_actual_pinned_runtime_when_installed(tmp_path):
    import os
    import subprocess
    from wearing.runtime import HermesRuntime
    runtime = HermesRuntime(Path(__file__).resolve().parents[1] / ".wearing")
    if not runtime.python.is_file() or not runtime.source.is_dir():
        pytest.skip("Pinned runtime is not installed in this checkout")
    lib = library(tmp_path)
    skill(lib.installed)
    lib.enabled("documents/letter", False, lib.list()["revision"])
    code = "from agent.skill_utils import get_disabled_skill_names; assert 'letter' in get_disabled_skill_names('api_server')"
    process = subprocess.run([str(runtime.python), "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=15,
                             env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "HERMES_HOME": str(lib.home), "PYTHONPATH": str(runtime.source)})
    assert process.returncode == 0, "Pinned runtime did not recognize the disabled-skill configuration"


def remove(lib, preview):
    return lib.remove(preview["id"], preview["revision"], preview["package_revision"], preview["operation_id"])


def test_remove_moves_exact_package_to_recovery_and_keeps_catalog_config_and_other_files(tmp_path):
    lib = library(tmp_path)
    package = skill(lib.installed)
    original = skill(lib.catalog)
    extra = skill(lib.installed, "documents/other", "other")
    (package / "script.py").write_text("do not execute")
    config = lib.config_path.read_bytes()
    preview = lib.removal_preview("documents/letter")
    assert package.exists()  # Merely opening confirmation never removes.
    receipt = remove(lib, preview)
    assert receipt["removed"] and receipt["id"] == preview["id"]
    assert not package.exists() and original.exists() and extra.exists()
    assert lib.config_path.read_bytes() == config
    saved = lib.home / ".pajio-skill-recovery" / receipt["recovery_id"] / "package"
    assert (saved / "script.py").read_text() == "do not execute"
    assert receipt["snapshot"]["catalog"][0]["installed"] is False
    assert str(tmp_path) not in str(receipt)
    assert remove(lib, preview) == receipt  # Lost HTTP response is recoverable.
    lib.install("documents/letter", receipt["snapshot"]["catalog"][0]["revision"])
    with pytest.raises(HTTPException) as error:
        remove(lib, preview)
    assert error.value.status_code == 409
    fresh = lib.removal_preview("documents/letter")
    assert fresh["operation_id"] != preview["operation_id"]
    assert remove(lib, fresh)["removed"]


@pytest.mark.parametrize("change", ["script", "config", "nested", "symlink", "autoload", "essential"])
def test_remove_rejects_changed_protected_or_unsafe_packages(tmp_path, change):
    lib = library(tmp_path)
    package = skill(lib.installed)
    preview = lib.removal_preview("documents/letter")
    if change == "script":
        (package / "script.py").write_text("changed after preview")
    elif change == "config":
        lib.config_path.write_text(lib.config_path.read_text() + "changed: true\n")
    elif change == "nested":
        skill(package, "child", "nested")
    elif change == "symlink":
        (package / "linked-secret").symlink_to(lib.config_path)
    elif change == "autoload":
        lib.config_path.write_text("skills:\n  auto_load: [letter]\n")
    else:
        (package / "SKILL.md").write_text("---\nname: hermes-agent\n---\nEssential")
    with pytest.raises(HTTPException):
        remove(lib, preview)
    assert package.exists()


@pytest.mark.parametrize("state", ["starting", "running", "waiting_for_approval", "stopping", "connection_lost", "ambiguous", "queued"])
def test_remove_refuses_active_or_queued_work_but_allows_completed_work(tmp_path, state):
    lib = library(tmp_path)
    package = skill(lib.installed)
    preview = lib.removal_preview("documents/letter")
    if state == "queued":
        running = lib.store.create("synthetic active", "hermes")
        lib.store.update(running["id"], status="running")
        task, _ = lib.store.accept_message("synthetic queued", "daily", "synthetic-skill-remove", {"running"})
        lib.store.update(running["id"], status="completed_unverified")
    else:
        task = lib.store.create("synthetic active", "hermes")
        lib.store.update(task["id"], status=state)
    with pytest.raises(HTTPException) as error:
        remove(lib, preview)
    assert error.value.status_code == 423 and package.exists()
    lib.store.update(task["id"], status="completed_unverified")
    assert remove(lib, preview)["removed"]


def test_remove_rejects_catalog_alias_and_recovery_symlinks(tmp_path):
    lib = library(tmp_path)
    package = skill(lib.installed)
    preview = lib.removal_preview("documents/letter")
    recovery = lib.home / ".pajio-skill-recovery"
    recovery.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(HTTPException):
        remove(lib, preview)
    assert package.exists()
    recovery.unlink()
    lib.catalog = lib.installed
    with pytest.raises(HTTPException):
        lib.removal_preview("documents/letter")
    assert package.exists()


async def test_remove_real_http_identity_csrf_and_exact_recovery_receipt(tmp_path):
    from wearing.app import create_app
    from wearing.config import Settings
    app = create_app(Settings(tmp_path), engine_autostart=False)
    installed = tmp_path / "hermes" / "skills"
    package = skill(installed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        csrf = (await client.get("/api/bootstrap")).json()["token"]
        preview = (await client.get("/api/skills/removal", params={"id": "documents/letter"})).json()
        body = {k: v for k, v in preview.items() if k != "name"}
        assert (await client.post("/api/skills/remove", json=body)).status_code == 403
        headers = {"X-Wearing-Token": csrf}
        other = app.state.store.save_identity("Other")["id"]
        response = await client.post("/api/skills/remove", json=body, headers={**headers, "X-Wearing-Identity": other})
        assert response.status_code == 404 and package.exists()
        assert (await client.post("/api/skills/remove", json={**body, "source": "catalog"}, headers=headers)).status_code == 422
        response = await client.post("/api/skills/remove", json=body, headers=headers)
        assert response.status_code == 200 and response.json()["removed"] is True
        assert not package.exists()
        assert (await client.get("/api/skills")).json()["installed"] == []
        assert (await client.post("/api/skills/remove", json=body, headers=headers)).json() == response.json()
    await app.state.service.hermes.close()


def test_remove_recovers_after_move_but_before_http_snapshot(tmp_path, monkeypatch):
    lib = library(tmp_path)
    package = skill(lib.installed)
    preview = lib.removal_preview("documents/letter")
    listing = lib.list
    monkeypatch.setattr(lib, "list", lambda: (_ for _ in ()).throw(RuntimeError("synthetic response failure")))
    with pytest.raises(RuntimeError):
        remove(lib, preview)
    assert not package.exists()
    monkeypatch.setattr(lib, "list", listing)
    assert remove(lib, preview)["removed"] is True
    assert len(list((lib.home / ".pajio-skill-recovery").iterdir())) == 1


def test_remove_transaction_serializes_with_real_task_start(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    import threading
    from wearing.service import ACTIVE
    lib = library(tmp_path)
    package = skill(lib.installed)
    preview = lib.removal_preview("documents/letter")
    task = lib.store.create("synthetic new task", "hermes")
    entered, release, admission_started = threading.Event(), threading.Event(), threading.Event()
    rename = Path.rename
    def slow_rename(path, target):
        if path == package:
            entered.set()
            assert release.wait(5)
        return rename(path, target)
    monkeypatch.setattr(Path, "rename", slow_rename)
    def start():
        admission_started.set()
        return lib.store.reserve_start(task["id"], {}, "synthetic-start", ACTIVE)
    with ThreadPoolExecutor(max_workers=2) as pool:
        removal = pool.submit(remove, lib, preview)
        assert entered.wait(5)
        admission = pool.submit(start)
        assert admission_started.wait(5)
        try:
            with pytest.raises(TimeoutError):
                admission.result(timeout=0.05)
        finally:
            release.set()
        assert removal.result(timeout=5)["removed"]
        assert admission.result(timeout=5)
    assert lib.store.get(task["id"])["status"] == "starting" and not package.exists()


def test_removal_recovery_is_not_discovered_by_actual_pinned_runtime(tmp_path):
    import json
    import os
    import subprocess
    from wearing.runtime import HermesRuntime
    runtime = HermesRuntime(Path(__file__).resolve().parents[1] / ".wearing")
    if not runtime.python.is_file() or not runtime.source.is_dir():
        pytest.skip("Pinned runtime is not installed in this checkout")
    lib = library(tmp_path)
    skill(lib.installed)
    def names():
        code = "import json; from tools.skills_tool import _find_all_skills; print(json.dumps([s['name'] for s in _find_all_skills()]))"
        result = subprocess.run([str(runtime.python), "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=15,
                                env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "HERMES_HOME": str(lib.home), "PYTHONPATH": str(runtime.source)})
        assert result.returncode == 0, result.stderr[-500:]
        return json.loads(result.stdout.splitlines()[-1])
    assert "letter" in names()
    remove(lib, lib.removal_preview("documents/letter"))
    assert "letter" not in names()
