"""Synthetic schedule contracts; these do not prove delivery/order/payment ability."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import httpx
import pytest
from pydantic import ValidationError
from wearing.app import create_app
from wearing.config import Settings
from wearing.hermes import HermesClient
from wearing.life import LifeBook
from wearing.life_proxy import dispatch
from wearing.schedules import ScheduleBook, ScheduleCoordinator, ScheduleDraft, ScheduleError, instant, next_time
from wearing.service import TaskService
from wearing.store import Store
from test_goals import GoalWire


@pytest.fixture
def clock(monkeypatch):
    value = ["2026-10-05T00:00:00+00:00"]
    monkeypatch.setattr("wearing.schedules.now", lambda: value[0])
    return value


def spec(**kwargs):
    return ScheduleDraft(title="定期查看测试记录", instruction="观察最新资料，只有变化时反馈，不操作外部账户。", kind="cron", cron="5 8 * * *", **kwargs)


@pytest.fixture
async def rig(tmp_path, clock):
    wire = GoalWire()
    client = HermesClient(Settings(tmp_path, hermes_key="test"), httpx.MockTransport(wire))
    store = Store(tmp_path / "test.sqlite3")
    book = ScheduleBook(store)
    service = TaskService(store, client)
    service.start_guard, service.context_provider = book.guard, book.context
    coordinator = ScheduleCoordinator(book, service)
    yield store, book, service, coordinator, wire, clock
    await client.close()


def test_calendar_timezones_dst_and_invalid_dates(clock):
    assert next_time(spec(), clock[0]) == "2026-10-05T00:05:00+00:00"
    ny = ScheduleDraft(title="早晨", instruction="读资料", kind="cron", cron="0 9 * * *", timezone="America/New_York")
    assert next_time(ny, "2026-03-07T15:00:00+00:00") == "2026-03-08T13:00:00+00:00"
    ny.cron = "30 2 * * *"
    assert next_time(ny, "2026-03-07T15:00:00+00:00") == "2026-03-09T06:30:00+00:00"
    ny.cron = "30 1 * * *"
    assert next_time(ny, "2026-11-01T05:30:01+00:00") == "2026-11-02T06:30:00+00:00"
    with pytest.raises(ScheduleError):
        next_time(ScheduleDraft(title="无效", instruction="无效时间", kind="cron", cron="0 0 31 2 *"), clock[0])


@pytest.mark.parametrize("data", [
    {"kind":"once", "at":"2026-10-06T09:00"}, {"kind":"cron", "cron":"* * * * * *"},
    {"kind":"cron", "cron":"bad"}, {"kind":"cron", "cron":"0 9 * * *", "timezone":"bad/zone"},
    {"kind":"cron", "cron":"0 9 * * *", "identity_id":"other"},
])
def test_validation(data):
    with pytest.raises(ValidationError):
        ScheduleDraft(title="test", instruction="test schedule", **data)


async def test_idempotent_concurrent_create_and_identity(rig):
    store, book, *_ = rig
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: book.create("daily", spec(), "same"), range(4)))
    assert len({r["id"] for r in results}) == 1
    item = results[0]
    other = store.save_identity("另一个身份")["id"]
    assert book.list(other) == []
    with pytest.raises(ScheduleError) as denied:
        book.get(other, item["id"])
    assert denied.value.status == 404
    changed = spec().model_copy(update={"title":"不同内容"})
    with pytest.raises(ScheduleError):
        book.create("daily", changed, "same")
    book.change("daily", item["id"], 1, "pause")
    assert book.create("daily", spec(), "same")["status"] == "paused"
    with pytest.raises(ScheduleError):
        book.change("daily", item["id"], 1, "resume")


async def test_due_claim_restart_silent_result_and_next_occurrence(rig):
    store, book, service, coordinator, wire, clock = rig
    item = book.create("daily", spec(), "one")
    await coordinator.tick()
    assert wire.runs == []
    clock[0] = "2026-10-05T00:05:00+00:00"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: book.claim(item["id"]), range(4)))
    assert sum(t is not None for t in results) == 1
    await coordinator.tick()
    assert len(wire.runs) == 1
    assert "scheduled_at" in wire.runs[0]["instructions"]
    reopened = ScheduleBook(Store(store.path))
    await ScheduleCoordinator(reopened, service).tick()
    assert len(wire.runs) == 1
    wire.status, wire.output = "completed", "[SILENT]"
    await service.tick()
    await coordinator.tick()
    assert book.conversation("daily") == []
    assert book.get("daily", item["id"])["occurrences"][0]["status"] == "silent"
    clock[0] = "2026-10-06T00:05:00+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 2
    assert wire.runs[0]["session_id"] != wire.runs[1]["session_id"]
    assert "[SILENT]" in wire.runs[1]["instructions"]


async def test_sleep_skips_missed_slots_without_backlog(rig):
    store, book, service, coordinator, wire, clock = rig
    item = book.create("daily", spec(), "one")
    clock[0] = "2026-10-09T10:00:00+00:00"
    await coordinator.tick()
    result = book.get("daily", item["id"])
    assert wire.runs == []
    assert result["next_run"] == "2026-10-10T00:05:00+00:00"
    assert len(result["occurrences"]) == 1
    assert result["occurrences"][0]["status"] == "skipped"


async def test_offline_retry_same_task_but_no_retry_uncertain_acceptance(rig):
    store, book, service, coordinator, wire, clock = rig
    item = book.create("daily", spec(), "one")
    clock[0] = "2026-10-05T00:05:00+00:00"
    wire.offline = True
    await coordinator.tick()
    task_id = store.list()[0]["id"]
    assert store.list()[0]["status"] == "draft"
    clock[0] = "2026-10-05T00:06:01+00:00"
    wire.offline, wire.uncertain = False, True
    await coordinator.tick()
    assert store.get(task_id)["status"] == "ambiguous"
    clock[0] = "2026-10-07T00:05:00+00:00"
    await coordinator.tick()
    assert len(wire.runs) == 1
    assert len(book.get("daily", item["id"])["occurrences"]) == 1


async def test_offline_reserved_work_expires(rig):
    store, book, service, coordinator, wire, clock = rig
    item = book.create("daily", spec(grace_minutes=15), "one")
    clock[0] = "2026-10-05T00:05:00+00:00"
    wire.offline = True
    await coordinator.tick()
    clock[0] = "2026-10-05T00:30:00+00:00"
    wire.offline = False
    await coordinator.tick()
    assert not wire.runs
    assert store.list()[0]["status"] == "stopped"
    assert book.get("daily", item["id"])["status"] == "paused"


async def test_pause_and_edit_do_not_change_or_duplicate_dispatched_work(rig):
    store, book, service, coordinator, wire, clock = rig
    item = book.create("daily", spec(), "one")
    clock[0] = "2026-10-05T00:05:00+00:00"
    await coordinator.tick()
    original = store.list()[0]
    paused = book.change("daily", item["id"], 1, "pause")
    assert store.get(original["id"])["status"] == "running"
    new = spec().model_copy(update={"title":"新安排", "instruction":"新的意图"})
    changed = book.change("daily", item["id"], paused["revision"], "edit", new)
    assert changed["status"] == "paused"
    wire.status, wire.output = "completed", "旧安排的真实返回"
    await service.tick()
    await coordinator.tick()
    assert book.get("daily", item["id"])["status"] == "paused"
    assert book.conversation("daily")[0]["content"] == item["schedule"]["title"]
    assert len(wire.runs) == 1


async def test_once_and_conversation_priority(rig):
    store, book, service, coordinator, wire, clock = rig
    item = book.create("daily", ScheduleDraft(title="一次", instruction="读测试资料", kind="once", at="2026-10-05T08:05:00+08:00"), "once")
    blocker = store.create("正在处理的测试任务", "computer")
    store.update(blocker["id"], status="running", run_id="fixture-running")
    message = (await service.submit_message("先处理用户消息", "daily"))["task"]
    store.update(blocker["id"], status="stopped")
    clock[0] = "2026-10-05T00:05:00+00:00"
    await coordinator.tick()
    assert not wire.runs
    await service.cancel_message(message["id"])
    await coordinator.tick()
    wire.status, wire.output = "completed", "有来源的测试结果"
    await service.tick()
    await coordinator.tick()
    assert book.get("daily", item["id"])["status"] == "finished"
    assert len(book.conversation("daily")) == 1
    await coordinator.tick()
    assert len(wire.runs) == 1


async def test_scheduled_agent_cannot_multiply_work_but_can_stop_own_schedule(rig):
    store, book, service, coordinator, wire, clock = rig
    item = book.create("daily", spec(), "one")
    clock[0] = "2026-10-05T00:05:00+00:00"
    await coordinator.tick()
    life = LifeBook(store)
    with pytest.raises(ScheduleError):
        dispatch(life, "daily", "schedule_create", {"schedule":spec().model_dump(), "request_key":"child"})
    with pytest.raises(ScheduleError):
        dispatch(life, "daily", "schedule_change", {"schedule_id":item["id"], "revision":1, "action":"edit", "schedule":spec().model_dump()})
    result = dispatch(life, "daily", "schedule_change", {"schedule_id":item["id"], "revision":1, "action":"pause"})
    assert result["status"] == "paused"
    assert len(book.list("daily")) == 1


async def test_api_and_agent_share_store_and_access_boundaries(tmp_path, clock):
    app = create_app(Settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        token = (await client.get("/api/bootstrap")).json()["token"]
        assert (await client.post("/api/schedules", json={"schedule": spec().model_dump(), "request_key":"api"})).status_code == 403
        client.headers["X-Wearing-Token"] = token
        response = await client.post("/api/schedules", json={"schedule": spec().model_dump(), "request_key":"api"})
        assert response.status_code == 201
        item = response.json()
        result = dispatch(LifeBook(app.state.store), "daily", "schedule_list", {})
        assert result["items"] == []  # No admitted task cannot borrow the local user's authority.
        # A real tool mutation belongs to an admitted user turn; invoking an
        # identity-bound MCP with no current turn must not borrow local authority.
        task, _ = app.state.store.accept_message('暂停这项安排', 'daily', 'owner-test-request', (), owner_scope='local')
        app.state.store.update(task['id'], status='running', run_id='synthetic-owner-run')
        assert dispatch(LifeBook(app.state.store), 'daily', 'schedule_list', {})['items'][0]['id'] == item['id']
        dispatch(LifeBook(app.state.store), "daily", "schedule_change", {"schedule_id":item["id"], "revision":1, "action":"pause"})
        assert (await client.get("/api/schedules")).json()["items"][0]["status"] == "paused"
        other = app.state.store.save_identity("另一个身份")["id"]
        client.headers["X-Wearing-Identity"] = other
        assert (await client.get(f"/api/schedules/{item['id']}")).status_code == 404
        assert (await client.patch(f"/api/schedules/{item['id']}", json={"revision":2,"action":"resume"})).status_code == 404
    await app.state.service.hermes.close()
