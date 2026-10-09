"""Life-change intentions: real SQLite ledger and task lifecycle, synthetic engine."""
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import jsonschema
import pytest
from pydantic import ValidationError

from wearing.app import create_app
from wearing.capture import CaptureBook, CaptureDraft
from wearing.config import Settings
from wearing.life import LifeBook, LifeDraft
from wearing.life_proxy import TOOLS, dispatch
from wearing.schedules import ScheduleBook, ScheduleCoordinator, ScheduleDraft
from wearing.store import Store
from test_schedules import clock, rig, spec


def watch(**changes):
    return ScheduleDraft(title="留意新的想法", instruction="先读变化对应记录，判断有没有值得研究的想法，再给我反馈。", kind="life_change",
                         changes={"record_kinds": ["note"], "debounce_seconds": 15, "cooldown_minutes": 1, **changes})


def note(life, key="one", identity="daily", actor="user"):
    return life.create(identity, LifeDraft(kind="note", title=key, content="来自用户的新想法"), key, actor)


async def finish(service, coordinator, wire):
    wire.status, wire.output = "completed", "[SILENT]"
    await service.tick()
    await coordinator.tick()


@pytest.mark.parametrize("fields", [
    {"changes": None}, {"changes": {"record_kinds": []}}, {"changes": {"record_kinds": ["email"]}},
    {"changes": {"debounce_seconds": 0}}, {"changes": {"max_runs_per_day": 999}},
    {"changes": {}, "at": "2026-10-05T01:00:00+00:00"}, {"changes": {}, "kind": "cron", "cron": "* * * * *"},
])
def test_trigger_validation(fields):
    with pytest.raises(ValidationError):
        ScheduleDraft.model_validate({**watch().model_dump(), **fields})


@pytest.mark.parametrize("name", ["schedule_create", "schedule_change"])
def test_nested_mcp_schema_resolves_from_tool_root(name):
    tool = next(t for t in TOOLS if t.name == name)
    args = {"schedule": watch().model_dump()}
    args.update({"request_key": "one"} if name == "schedule_create" else {"schedule_id": "one", "revision": 1, "action": "edit"})
    jsonschema.validate(args, tool.inputSchema)


async def test_only_new_authorized_sources_and_identity_are_collected(rig):
    store, book, service, coordinator, wire, clock = rig
    life = LifeBook(store)
    note(life, "before")
    item = book.create("daily", watch(), "watch")
    other = store.save_identity("other")["id"]
    note(life, "other", identity=other)
    note(life, "automated", actor="agent")
    life.create("daily", LifeDraft(kind="task", title="unwatched"), "unwatched")
    await coordinator.tick()
    assert book.get("daily", item["id"])["next_run"] is None
    record = note(life)
    await coordinator.tick()
    assert not wire.runs
    clock[0] = "2026-10-05T00:00:15+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 1
    occurrence = book.get("daily", item["id"])["occurrences"][0]
    refs = book.events.context(occurrence["id"])
    assert refs["change_count"] == 1
    assert refs["records"][0]["record_id"] == record["id"]
    assert "life_change" in wire.runs[0]["instructions"]
    assert "before" not in json.dumps(refs)


async def test_burst_coalesces_and_restarts_do_not_replay(rig):
    store, book, service, coordinator, wire, clock = rig
    life = LifeBook(store)
    item = book.create("daily", watch(), "watch")
    record = note(life)
    await coordinator.tick()
    clock[0] = "2026-10-05T00:00:10+00:00"
    life.update("daily", record["id"], 1, {"content": "改过的想法"})
    await coordinator.tick()
    assert book.get("daily", item["id"])["next_run"] == "2026-10-05T00:00:25+00:00"
    clock[0] = "2026-10-05T00:00:25+00:00"
    reopened = ScheduleBook(Store(store.path))
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = list(pool.map(lambda _: reopened.claim(item["id"]), range(4)))
    assert sum(x is not None for x in claimed) == 1
    await ScheduleCoordinator(reopened, service).tick()
    await coordinator.tick()
    occurrence = book.get("daily", item["id"])["occurrences"][0]
    batch = book.events.context(occurrence["id"])
    assert batch["change_count"] == 2 and len(batch["records"]) == 1
    assert batch["records"][0]["revision"] == 2
    assert len(wire.runs) == 1
    await finish(service, coordinator, wire)
    await coordinator.tick()
    assert book.conversation("daily") == []
    assert book.get("daily", item["id"])["status"] == "active"
    assert book.get("daily", item["id"])["next_run"] is None


async def test_continuous_edits_have_maximum_merge_window(rig):
    store, book, service, coordinator, wire, clock = rig
    life = LifeBook(store)
    item = book.create("daily", watch(), "watch")
    record = note(life)
    await coordinator.tick()
    for revision, second in enumerate([10, 20, 30, 40], 1):
        clock[0] = f"2026-10-05T00:00:{second:02d}+00:00"
        life.update("daily", record["id"], revision, {"content": f"edit {second}"})
        await coordinator.tick()
    assert book.get("daily", item["id"])["next_run"] == "2026-10-05T00:00:45+00:00"
    clock[0] = "2026-10-05T00:00:45+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 1


async def test_inflight_context_frozen_new_changes_wait_and_limits_survive_edit(rig):
    store, book, service, coordinator, wire, clock = rig
    life = LifeBook(store)
    item = book.create("daily", watch(max_runs_per_day=1), "watch")
    first = note(life)
    await coordinator.tick()
    clock[0] = "2026-10-05T00:00:15+00:00"
    await coordinator.tick()
    first_context = book.context(store.list()[0])
    clock[0] = "2026-10-05T00:00:20+00:00"
    second = note(life, "second")
    await coordinator.tick()
    assert book.context(store.list()[0]) == first_context.replace('"current_time": "2026-10-05T00:00:15+00:00"', '"current_time": "2026-10-05T00:00:20+00:00"')
    assert second["id"] not in first_context
    assert book.get("daily", item["id"])["next_run"] == "2026-10-06T00:00:15+00:00"
    await finish(service, coordinator, wire)
    changed = book.change("daily", item["id"], 1, "edit", watch(max_runs_per_day=1))
    note(life, "third")
    await coordinator.tick()
    assert book.get("daily", item["id"])["next_run"] == "2026-10-06T00:00:15+00:00"
    clock[0] = "2026-10-06T00:00:15+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 2


async def test_pause_resume_discards_buffer_and_paused_history(rig):
    store, book, service, coordinator, wire, clock = rig
    life = LifeBook(store)
    item = book.create("daily", watch(), "watch")
    note(life)
    await coordinator.tick()
    paused = book.change("daily", item["id"], 1, "pause")
    note(life, "during-pause")
    book.change("daily", item["id"], paused["revision"], "resume")
    clock[0] = "2026-10-05T00:01:00+00:00"
    await coordinator.tick()
    assert not wire.runs
    assert book.get("daily", item["id"])["next_run"] is None
    record = note(life, "after-resume")
    await coordinator.tick()
    clock[0] = "2026-10-05T00:01:15+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 1 and record["id"] in wire.runs[0]["instructions"]


async def test_save_without_change_does_not_wake_or_bump_revision(rig):
    store, book, service, coordinator, wire, clock = rig
    life = LifeBook(store)
    record = note(life)
    item = book.create("daily", watch(), "watch")
    same = life.update("daily", record["id"], 1, {"title": record["title"]})
    await coordinator.tick()
    assert same["revision"] == 1
    assert book.get("daily", item["id"])["next_run"] is None
    assert not wire.runs


async def test_provenance_from_real_conversation_and_no_self_trigger(rig):
    store, book, service, coordinator, wire, clock = rig
    item = book.create("daily", watch(), "watch")
    life = LifeBook(store)
    message = store.create_message("帮我记个想法")
    store.update(message["id"], status="running")
    dispatch(life, "daily", "life_create", {"record": {"kind": "note", "title": "对话代记"}, "request_key": "conversation"})
    await coordinator.tick()
    store.update(message["id"], status="completed_unverified")
    clock[0] = "2026-10-05T00:00:15+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 1
    dispatch(life, "daily", "life_create", {"record": {"kind": "note", "title": "后台结果"}, "request_key": "background", "origin": "conversation"})
    await finish(service, coordinator, wire)
    clock[0] = "2026-10-05T00:02:00+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 1
    assert book.get("daily", item["id"])["next_run"] is None


async def test_deleted_record_latest_state_and_bounded_context(rig):
    store, book, service, coordinator, wire, clock = rig
    life = LifeBook(store)
    item = book.create("daily", watch(), "watch")
    records = [note(life, str(i)) for i in range(55)]
    last = records[-1]
    life.update("daily", last["id"], 1, action="archive")
    await coordinator.tick()
    clock[0] = "2026-10-05T00:00:15+00:00"
    await coordinator.tick()
    occurrence = book.get("daily", item["id"])["occurrences"][0]
    batch = book.events.context(occurrence["id"])
    assert batch["change_count"] == 50 and len(batch["records"]) == 50
    assert "来自用户的新想法" not in json.dumps(batch)
    await finish(service, coordinator, wire)
    clock[0] = "2026-10-05T00:01:15+00:00"
    await coordinator.tick()
    following = book.events.context(book.get("daily", item["id"])["occurrences"][0]["id"])
    assert following["change_count"] == 6 and len(following["records"]) == 5
    assert following["records"][-1]["deleted"]
    assert set(r["record_id"] for r in batch["records"] + following["records"]) == set(r["id"] for r in records)


async def test_uncertain_acceptance_never_reissued_on_further_changes(rig):
    store, book, service, coordinator, wire, clock = rig
    life = LifeBook(store)
    item = book.create("daily", watch(), "watch")
    note(life)
    await coordinator.tick()
    clock[0] = "2026-10-05T00:00:15+00:00"
    wire.uncertain = True
    await coordinator.tick()
    note(life, "new")
    clock[0] = "2026-10-06T00:00:15+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 1
    assert len(book.get("daily", item["id"])["occurrences"]) == 1
    assert store.list()[0]["status"] == "ambiguous"


async def test_capture_waits_for_organizing_then_uses_latest_record(rig, tmp_path):
    store, book, service, coordinator, wire, clock = rig
    captures = CaptureBook(LifeBook(store))
    item = book.create("daily", watch(), "watch")
    capture = captures.create("daily", CaptureDraft(record=LifeDraft(kind="note", title="拍写"), request_key="capture"))
    await coordinator.tick()
    clock[0] = "2026-10-05T00:00:15+00:00"
    await coordinator.tick()
    assert not wire.runs
    job = captures.claim()
    captures.state(job, "failed", error="验收用：没有材料")
    clock[0] = "2026-10-05T00:00:30+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 1


async def test_api_life_change_roundtrip_and_time_schedule_compatibility(tmp_path, clock):
    app = create_app(Settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        client.headers["X-Wearing-Token"] = (await client.get("/api/bootstrap")).json()["token"]
        response = await client.post("/api/schedules", json={"schedule": watch().model_dump(), "request_key": "watch"})
        assert response.status_code == 201
        item = response.json()
        assert item["next_run"] is None and item["schedule"]["changes"]["record_kinds"] == ["note"]
        # Existing time rules still dispatch after adding the event tables/schema.
        before = spec().model_dump(exclude={"changes"})
        time_item = app.state.schedules.create("daily", spec(), "old-format")
        with app.state.store.connection() as db:
            db.execute("UPDATE personal_schedules SET original_spec=? WHERE id=?", (json.dumps(before), time_item["id"]))
        assert app.state.schedules.create("daily", spec(), "old-format")["id"] == time_item["id"]
        result = await client.patch(f"/api/schedules/{item['id']}", json={"revision": 1, "action": "edit", "schedule": spec().model_dump()})
        assert result.status_code == 200 and result.json()["next_run"]
    await app.state.service.hermes.close()
