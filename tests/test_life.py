from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json

import httpx
import pytest
from pydantic import ValidationError

from wearing.app import create_app
from wearing.config import Settings
from wearing.life import LifeBook, LifeDraft, LifeError
from wearing.life_proxy import dispatch
from wearing.profile import prepare_profile
from wearing.store import Store


@pytest.fixture
def book(tmp_path):
    return LifeBook(Store(tmp_path / "wearing.sqlite3"))


def note(title="一个念头"):
    return LifeDraft(kind="note", title=title, content="尚未成形也先留下")


def test_durable_shared_records_and_identity_scope(book):
    identity = book.store.save_identity("海外")["id"]
    item = book.create("daily", note(), "capture-1")
    other = book.create(identity, note("另一个身份"), "capture-1")
    reopened = LifeBook(Store(book.store.path))
    assert reopened.get("daily", item["id"]) == item
    assert reopened.snapshot(identity)["items"] == [other]
    with pytest.raises(LifeError) as error:
        reopened.get(identity, item["id"])
    assert error.value.status == 404
    with pytest.raises(LifeError):
        reopened.update(identity, item["id"], 1, {"title": "不能跨身份"})


def test_concurrent_upload_retries_create_one_record(book):
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(lambda _: book.create("daily", note(), "same-upload"), range(4)))
    assert len({i["id"] for i in items}) == 1
    assert len(book.snapshot("daily")["items"]) == 1
    assert book.snapshot("daily")["version"] == 1
    with pytest.raises(LifeError):
        book.create("daily", note("不同内容"), "same-upload")


def test_late_agent_write_cannot_overwrite_user_edit(book):
    item = book.create("daily", note(), "one")
    current = book.update("daily", item["id"], 1, {"title": "用户自己改过"})
    with pytest.raises(LifeError):
        dispatch(book, "daily", "life_change", {"record_id": item["id"], "revision": 1, "action": "edit", "patch": {"title": "晚到的整理"}})
    assert book.get("daily", item["id"])["title"] == current["title"]
    with book.store.connection() as db:
        assert db.execute("SELECT count(*) FROM life_changes").fetchone()[0] == 2


def test_concurrent_edits_only_one_can_use_revision(book):
    item = book.create("daily", note(), "one")
    def edit(title):
        try:
            return book.update("daily", item["id"], 1, {"title": title})
        except LifeError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["编辑 A", "编辑 B"]))
    assert sum(r is not None for r in results) == 1
    assert book.get("daily", item["id"])["revision"] == 2


def test_archive_restore_and_incremental_clock(book):
    item = book.create("daily", note(), "one")
    old_clock = book.snapshot("daily")["version"]
    assert book.snapshot("daily", old_clock) == {"version": old_clock, "unchanged": True}
    archived = book.update("daily", item["id"], 1, action="archive")
    assert not book.snapshot("daily")["items"]
    assert book.snapshot("daily", old_clock)["unchanged"] is False
    with pytest.raises(LifeError):
        book.update("daily", item["id"], archived["revision"], {"title": "不能编辑移除记录"})
    restored = book.update("daily", item["id"], archived["revision"], action="restore")
    assert not restored["deleted_at"]
    assert restored["revision"] == 3
    assert book.snapshot("daily")["items"] == [restored]


def test_agent_and_ui_use_same_book_and_audit_source(book):
    created = dispatch(book, "daily", "life_create", {"record": {"kind": "task", "title": "带雨伞", "list_name": "出门"}, "request_key": "agent-one"})
    original, = book.snapshot("daily")["items"]
    assert original["id"] == created["id"]
    assert all(original[key] == value for key, value in created.items())
    assert set(original) - set(created) == {"start_at", "end_at", "all_day"}
    done = dispatch(book, "daily", "life_change", {"record_id": created["id"], "revision": 1, "action": "edit", "patch": {"completed": True}})
    assert done["completed"] is True
    with book.store.connection() as db:
        assert {r[0] for r in db.execute("SELECT actor FROM life_changes")} == {"agent"}


def test_event_timezone_and_all_day_semantics():
    event = LifeDraft(kind="event", title="散步", start_at="2026-10-04T18:00:00+08:00", end_at="2026-10-04T19:00:00+08:00")
    assert event.start_at == "2026-10-04T10:00:00+00:00"
    all_day = LifeDraft(kind="event", title="休息", all_day=True, start_at="2026-10-04", end_at="2026-10-05")
    assert all_day.end_at == "2026-10-05"


@pytest.mark.parametrize("fields", [
    {"kind":"note", "title":"  "},
    {"kind":"note", "title":"有效", "timezone":"../bad"},
    {"kind":"event", "title":"有效", "start_at":"2026-10-04T18:00", "end_at":"2026-10-04T19:00"},
    {"kind":"event", "title":"有效", "start_at":"2026-10-04T18:00+08:00", "end_at":"2026-10-04T17:00+08:00"},
    {"kind":"note", "title":"有效", "completed":True},
    {"kind":"task", "title":"有效", "start_at":"2026-10-04"},
    {"kind":"note", "title":"有效", "identity_id":"other"},
])
def test_invalid_records_fail_before_writing(fields):
    with pytest.raises(ValidationError):
        LifeDraft.model_validate(fields)


def test_invalid_patch_rolls_back_entire_write(book):
    item = book.create("daily", note(), "one")
    with pytest.raises(ValidationError):
        book.update("daily", item["id"], 1, {"completed": True})
    assert book.get("daily", item["id"]) == item
    with pytest.raises(LifeError):
        book.update("daily", item["id"], 1, {"kind": "task"})


def test_record_reference_and_message_commit_together(book):
    import sqlite3
    item = book.create("daily", note(), "message-note")
    with book.store.connection() as db:
        db.execute("CREATE TRIGGER fixture_context_failure BEFORE INSERT ON life_message_context BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        book.create_message("daily", "继续聊这条", item["id"], 1)
    assert book.store.conversation("daily") == []
    assert book.store.list() == []


@pytest.mark.asyncio
async def test_api_auth_scope_conflict_and_persisted_feed(tmp_path):
    app = create_app(Settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        payload = {"record": {"kind":"note", "title":"API 记录"}, "request_key":"api-one"}
        assert (await client.post("/api/life", json=payload)).status_code == 403
        client.headers["X-Wearing-Token"] = (await client.get("/api/bootstrap")).json()["token"]
        assert (await client.post("/api/life", json=payload, headers={"Origin":"https://elsewhere.example"})).status_code == 403
        item = (await client.post("/api/life", json=payload)).json()
        change = {"revision":1,"patch":{"title":"新版"}}
        assert (await client.patch("/api/life/"+item["id"],json=change)).status_code == 200
        assert (await client.patch("/api/life/"+item["id"],json=change)).status_code == 409
        bad = {"revision":2,"patch":{"owner":"其他人"}}
        assert (await client.patch("/api/life/"+item["id"],json=bad)).status_code == 422
        other = app.state.store.save_identity("另一个身份")["id"]
        client.headers["X-Wearing-Identity"] = other
        assert (await client.get("/api/life/"+item["id"])).status_code == 404
        assert (await client.get("/api/life")).json()["items"] == []
        assert (await client.patch("/api/life/"+item["id"],json=change)).status_code == 404
    await app.state.service.hermes.close()


def test_profile_exposes_life_tools_preserving_model_config(tmp_path):
    source = tmp_path / "source"
    (source / "hermes_cli").mkdir(parents=True)
    (source / "hermes_cli/default_soul.py").write_text('DEFAULT_SOUL_MD = "Upstream"')
    home = tmp_path / "home"; home.mkdir()
    (home / "config.yaml").write_text('model:\n  provider: keep-me\n')
    connector = {"command":"python", "args":["life_proxy.py", "root", "daily"]}
    profile = prepare_profile(home, source, life=connector)
    assert "wearing_life" in profile["toolsets"]
    import yaml
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert config["model"]["provider"] == "keep-me"
    assert config["mcp_servers"]["wearing_life"] == connector


@pytest.mark.asyncio
async def test_natural_chat_keeps_record_reference_internal_and_scoped(tmp_path):
    app = create_app(Settings(tmp_path))
    item = app.state.life.create("daily", note(), "selected-note")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        client.headers["X-Wearing-Token"] = (await client.get("/api/bootstrap")).json()["token"]
        body = {"content":"我们一起看看这条笔记。", "life_record_id":item["id"], "life_revision":item["revision"]}
        response = await client.post("/api/conversation", json=body)
        assert response.status_code == 201
        task = app.state.store.get(response.json()["task"]["id"])
        assert task["prompt"] == body["content"]
        assert item["id"] in app.state.service.context_provider(task)
        assert (await client.post("/api/conversation", json={"content":"继续聊", "life_record_id":item["id"]})).status_code == 422
        other = app.state.store.save_identity("另一个身份")["id"]
        client.headers["X-Wearing-Identity"] = other
        assert (await client.post("/api/conversation", json=body)).status_code == 404
        assert app.state.store.conversation(other) == []
    await app.state.service.hermes.close()
