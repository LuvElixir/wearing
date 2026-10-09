"""Explicit message admission and durable queue contracts; synthetic engine only."""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from wearing.activity import ActivityBook
from wearing.app import create_app
from wearing.config import Settings
from wearing.goals import GoalBook, GoalCoordinator
from wearing.hermes import HermesClient
from wearing.schedules import ScheduleBook, ScheduleCoordinator, ScheduleDraft
from wearing.service import ACTIVE, TaskError, TaskService
from wearing.store import MessageConflict, Store
from test_goals import GoalWire


@pytest.fixture
async def rig(tmp_path):
    wire = GoalWire()
    client = HermesClient(Settings(tmp_path, hermes_key="fixture"), httpx.MockTransport(wire))
    store = Store(tmp_path / "messages.sqlite3")
    book = GoalBook(store)
    service = TaskService(store, client)
    service.context_provider, service.start_guard = book.context, book.guard
    yield store, book, service, GoalCoordinator(book, service), wire
    await client.close()


def block(store, status="running", run_id="fixture-current"):
    original = store.create("仅用于占用测试执行位", "computer")
    return store.update(original["id"], status=status, run_id=run_id)


def request(index=1):
    return f"fixture-request-{index:04}"


async def test_busy_submission_is_queued_then_dispatches_exactly_once(rig):
    store, _, service, coordinator, wire = rig
    current = block(store)
    reply = await service.submit_message("忙完后整理测试资料", "daily", request())
    task = reply["task"]
    assert reply["delivery"] == "queued" and reply["queued"] and reply["queue_state"] == "queued"
    assert task["status"] == "draft" and not task["run_id"] and wire.runs == []
    snapshot = ActivityBook(store).snapshot()
    item = next(i for i in snapshot["items"] if i["task_id"] == task["id"])
    assert item["bucket"] == "waiting" and item["label"] == "已排队" and "尚未开始" in item["summary"]
    assert snapshot["counts"]["waiting"] == 1 and snapshot["counts"]["attention"] == 0
    await coordinator.tick()
    assert wire.runs == []
    store.update(current["id"], status="completed_unverified")
    await asyncio.gather(coordinator.tick(), coordinator.tick())
    assert len(wire.runs) == 1 and wire.runs[0]["input"] == task["prompt"]
    assert store.message_receipt(task["id"]) == {"queued": False, "queue_state": "dispatched", "blocked_reason": None}
    retry = await service.submit_message(task["prompt"], "daily", request())
    assert retry["task"]["id"] == task["id"] and retry["delivery"] == "submitted"
    assert len(store.conversation()) == len(wire.runs) == 1


async def test_free_offline_submission_is_saved_and_never_auto_admitted(rig):
    store, _, service, coordinator, wire = rig
    wire.offline = True
    reply = await service.submit_message("连接恢复后也先不要自动发送", "daily", request())
    assert reply["delivery"] == "saved" and not reply["queued"] and reply["queue_state"] is None
    wire.offline = False
    await coordinator.tick()
    duplicate = await service.submit_message(reply["task"]["prompt"], "daily", request())
    assert duplicate["task"]["id"] == reply["task"]["id"] and duplicate["delivery"] == "saved"
    assert wire.runs == []
    await service.start(reply["task"]["id"])
    assert len(wire.runs) == 1


async def test_accepted_queue_offline_keeps_receipt_and_backoff_without_claiming_execution(rig):
    store, _, service, coordinator, wire = rig
    current = block(store)
    reply = await service.submit_message("已接收的任务可以等待重连", "daily", request())
    store.update(current["id"], status="stopped")
    wire.offline = True
    await coordinator.tick()
    receipt = store.message_receipt(reply["task"]["id"])
    assert receipt["queued"] and receipt["queue_state"] == "blocked" and receipt["blocked_reason"]
    assert store.get(reply["task"]["id"])["status"] == "draft" and wire.runs == []
    wire.offline = False
    await coordinator.tick()
    assert wire.runs == []  # Retry delay is persisted, not a tight poll loop.
    with store.connection() as db:
        db.execute("UPDATE message_handoffs SET next_retry=NULL")
    await coordinator.tick()
    assert len(wire.runs) == 1


async def test_queue_and_request_receipt_survive_restart_without_duplicate_runs(rig):
    store, _, service, _, wire = rig
    current = block(store)
    reply = await service.submit_message("重启后接着这一次提交", "daily", request())
    reopened = Store(store.path)
    restarted = TaskService(reopened, service.hermes)
    restarted.recover_startup()
    coordinator = GoalCoordinator(GoalBook(reopened), restarted)
    await coordinator.tick()
    assert wire.runs == [] and reopened.get(current["id"])["status"] == "connection_lost"
    wire.status = "completed"
    await restarted.tick()
    await coordinator.tick()
    assert len(wire.runs) == 1
    duplicate = await restarted.submit_message(reply["task"]["prompt"], "daily", request())
    assert duplicate["task"]["id"] == reply["task"]["id"] and len(wire.runs) == 1


@pytest.mark.parametrize("status,run_id", [("ambiguous", None), ("connection_lost", "fixture-current"), ("starting", None)])
async def test_unknown_active_run_never_gets_auto_resolved_to_drain_queue(rig, status, run_id):
    store, _, service, coordinator, wire = rig
    current = block(store, status, run_id)
    await service.submit_message("请排队", "daily", request())
    await coordinator.tick()
    assert wire.runs == [] and store.get(current["id"])["status"] == status


async def test_uncertain_dispatch_blocks_further_queue_and_is_not_replayed(rig):
    store, _, service, coordinator, wire = rig
    current = block(store)
    first = await service.submit_message("第一条", "daily", request(1))
    second = await service.submit_message("第二条", "daily", request(2))
    store.update(current["id"], status="stopped")
    wire.uncertain = True
    await coordinator.tick()
    assert store.get(first["task"]["id"])["status"] == "ambiguous"
    wire.uncertain = False
    await coordinator.tick()
    duplicate = await service.submit_message("第一条", "daily", request(1))
    assert duplicate["task"]["status"] == "ambiguous" and len(wire.runs) == 1
    assert store.get(second["task"]["id"])["status"] == "draft"


async def test_identity_order_scope_and_idempotency_keys_are_independent(rig):
    store, _, service, coordinator, wire = rig
    other = store.save_identity("另一个生活场景")["id"]
    current = block(store)
    first = await service.submit_message("日常第一条", "daily", request())
    second = await service.submit_message("另一个身份第一条", other, request())
    third = await service.submit_message("日常第二条", "daily", request(2))
    assert first["task"]["id"] != second["task"]["id"]
    with pytest.raises(MessageConflict):
        await service.submit_message("不同内容不得复用请求", "daily", request())
    store.update(current["id"], status="stopped")
    await coordinator.tick()
    assert wire.runs[-1]["input"] == "日常第一条"
    store.update(first["task"]["id"], status="completed_unverified")
    await coordinator.tick()
    assert wire.runs[-1]["input"] == "另一个身份第一条"
    assert other in wire.runs[-1]["instructions"]
    assert first["task"]["session_id"] != second["task"]["session_id"]
    assert store.get(third["task"]["id"])["status"] == "draft"


async def test_one_identity_retry_delay_does_not_hide_another_identity_queue(rig):
    store, _, service, coordinator, wire = rig
    current = block(store)
    other = store.save_identity("另外一个身份")["id"]
    first = await service.submit_message("日常第一条", "daily", request())
    await service.submit_message("日常第二条", "daily", request(2))
    await service.submit_message("其他身份", other, request())
    store.defer_message(first["task"]["id"], "测试退避", "2099-01-01T00:00:00+00:00")
    store.update(current["id"], status="stopped")
    await coordinator.tick()
    assert len(wire.runs) == 1 and wire.runs[0]["input"] == "其他身份"


async def test_old_drafts_are_never_swept_into_queue_or_block_due_goals(rig):
    store, goals, service, coordinator, wire = rig
    legacy = store.create_message("以前留下的草稿，不是现在的委托")
    goal = goals.create("daily", "继续已委托的长期目标", "只读测试资料", "能核对结果", 3)
    goals.control(goal["id"], goal["revision"], "resume")
    await coordinator.tick()
    assert len(wire.runs) == 1 and legacy["prompt"] != wire.runs[0]["input"]
    assert store.get(legacy["id"])["status"] == "draft"
    assert not store.message_receipt(legacy["id"])["queued"]


async def test_due_schedule_is_not_blocked_by_legacy_draft(rig, monkeypatch):
    store, _, service, _, wire = rig
    legacy = store.create_message("历史草稿")
    book = ScheduleBook(store)
    clock = ["2026-01-01T00:00:00+00:00"]
    monkeypatch.setattr("wearing.schedules.now", lambda: clock[0])
    book.create("daily", ScheduleDraft(title="测试定时", instruction="只看测试资料", kind="once", at="2026-01-01T00:05:00+00:00"), "fixture-schedule")
    clock[0] = "2026-01-01T00:05:00+00:00"
    await ScheduleCoordinator(book, service).tick()
    assert len(wire.runs) == 1 and store.get(legacy["id"])["status"] == "draft"


async def test_queue_and_goals_take_turns_instead_of_starving_existing_goal(rig):
    store, goals, service, coordinator, wire = rig
    current = block(store)
    first = await service.submit_message("排队一", "daily", request(1))
    second = await service.submit_message("排队二", "daily", request(2))
    goal = goals.create("daily", "目标也要继续", "只读测试资料", "取得可核对进展", 3)
    goals.control(goal["id"], goal["revision"], "resume")
    store.update(current["id"], status="stopped")
    await coordinator.tick()
    assert wire.runs[-1]["input"] == "排队一"
    store.update(first["task"]["id"], status="completed_unverified")
    restarted = GoalCoordinator(GoalBook(Store(store.path)), service)
    await restarted.tick()
    assert len(wire.runs) == 2 and "wearing-goal-" in wire.runs[-1]["session_id"]
    assert store.get(second["task"]["id"])["status"] == "draft"
    step = goals.detail(goal["id"])["steps"][0]
    store.update(step["task_id"], status="completed_unverified", output=wire.output)
    await restarted.tick()
    assert len(wire.runs) == 3 and wire.runs[-1]["input"] == "排队二"


async def test_cancelled_queue_never_dispatches_or_reappears_on_http_retry(rig):
    store, _, service, coordinator, wire = rig
    current = block(store)
    reply = await service.submit_message("撤回这个测试动作", "daily", request())
    assert (await service.cancel_message(reply["task"]["id"]))["status"] == "stopped"
    duplicate = await service.submit_message("撤回这个测试动作", "daily", request())
    assert duplicate["queue_state"] == "cancelled" and duplicate["delivery"] == "saved" and not duplicate["queued"]
    item = next(i for i in ActivityBook(store).snapshot()["items"] if i["task_id"] == reply["task"]["id"])
    assert item["bucket"] == "results" and item["label"] == "已撤回" and "没有开始执行" in item["summary"]
    assert not item["unread"] and ActivityBook(store).snapshot()["unread"] == 0
    assert ActivityBook(Store(store.path)).snapshot()["unread"] == 0
    events = store.events(reply['task']['id'])
    assert (await service.cancel_message(reply['task']['id']))['status'] == 'stopped'
    assert store.events(reply['task']['id']) == events
    store.update(current["id"], status="stopped")
    await coordinator.tick()
    assert wire.runs == []


async def test_withdrawal_does_not_add_new_result_dot_but_stopped_and_failed_runs_still_do(rig):
    store, _, service, _, _ = rig
    current = block(store)
    first = await service.submit_message("第一条待撤回", "daily", request(1))
    second = await service.submit_message("第二条待撤回", "daily", request(2))
    activity = ActivityBook(store)
    for reply in (first, second):
        await service.cancel_message(reply["task"]["id"])
        assert activity.snapshot()["unread"] == 0
    store.update(current["id"], status="stopped")
    failed = store.create("已经尝试但失败的运行", "computer")
    store.update(failed["id"], status="failed", error="测试错误")
    snapshot = activity.snapshot()
    assert snapshot["unread"] == 2
    assert {item["task_id"] for item in snapshot["items"] if item["unread"]} == {current["id"], failed["id"]}
    assert snapshot["counts"]["results"] == 4


async def test_two_workers_retry_same_request_during_dispatch_only_once(rig):
    store, _, service, _, wire = rig
    second_worker = TaskService(Store(store.path), service.hermes)
    wire.start_entered, wire.start_release = asyncio.Event(), asyncio.Event()
    first = asyncio.create_task(service.submit_message("并发重复请求", "daily", request()))
    await wire.start_entered.wait()
    second = await second_worker.submit_message("并发重复请求", "daily", request())
    wire.start_release.set()
    first = await first
    assert first["task"]["id"] == second["task"]["id"]
    assert len(wire.runs) == len(store.conversation()) == 1


def test_parallel_receipt_reservation_is_atomic(tmp_path):
    store = Store(tmp_path / "parallel.sqlite3")
    block(store)
    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(lambda _: store.accept_message("同一次明确提交", "daily", request(), ACTIVE), range(12)))
    assert len({reply[0]["id"] for reply in replies}) == 1
    assert sum(created for _, created in replies) == 1
    assert len(store.conversation()) == 1


def test_receipt_storage_failure_rolls_back_message_and_event_together(tmp_path):
    store = Store(tmp_path / "rollback.sqlite3")
    with store.connection() as db:
        db.execute("""CREATE TRIGGER fixture_reject_handoff BEFORE INSERT ON message_handoffs
            BEGIN SELECT RAISE(ABORT,'fixture failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        store.accept_message("不得只保存半份回执", "daily", request(), ACTIVE)
    assert store.list() == store.conversation() == []
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0


async def test_two_workers_dispatch_same_queued_task_only_once(rig):
    store, _, service, _, wire = rig
    current = block(store)
    reply = await service.submit_message("两名worker不可重复交接", "daily", request())
    store.update(current["id"], status="stopped")
    second = TaskService(Store(store.path), service.hermes)
    original_probe = service.hermes.probe
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def delayed_probe():
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
        await release.wait()
        return await original_probe()

    service.hermes.probe = delayed_probe
    jobs = [asyncio.create_task(worker.dispatch_message()) for worker in (service, second)]
    await asyncio.wait_for(entered.wait(), 1)
    release.set()
    assert sum(await asyncio.gather(*jobs)) == 1
    assert len(wire.runs) == 1
    assert store.message_receipt(reply["task"]["id"])["queue_state"] == "dispatched"


async def test_cancel_during_another_worker_probe_wins_before_run_reservation(rig):
    store, _, service, _, wire = rig
    current = block(store)
    reply = await service.submit_message("交接前还可以撤回", "daily", request())
    store.update(current["id"], status="stopped")
    second = TaskService(Store(store.path), service.hermes)
    original_probe = service.hermes.probe
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_probe():
        entered.set()
        await release.wait()
        return await original_probe()

    service.hermes.probe = delayed_probe
    job = asyncio.create_task(service.dispatch_message())
    await asyncio.wait_for(entered.wait(), 1)
    await second.cancel_message(reply["task"]["id"])
    release.set()
    assert not await job and wire.runs == []
    assert store.message_receipt(reply["task"]["id"])["queue_state"] == "cancelled"


async def test_crash_after_reservation_never_requeues_unknown_dispatch(rig):
    store, _, service, _, wire = rig
    current = block(store)
    first = await service.submit_message("交接中断的任务", "daily", request(1))
    second = await service.submit_message("后面的任务", "daily", request(2))
    store.update(current["id"], status="stopped")
    assert store.reserve_start(first["task"]["id"], {"input": "fixture"}, "fixture-idempotency", ACTIVE)
    restarted_store = Store(store.path)
    restarted = TaskService(restarted_store, service.hermes)
    restarted.recover_startup()
    await GoalCoordinator(GoalBook(restarted_store), restarted).tick()
    assert wire.runs == []
    assert restarted_store.get(first["task"]["id"])["status"] == "ambiguous"
    assert restarted_store.get(second["task"]["id"])["status"] == "draft"
    assert restarted_store.message_receipt(first["task"]["id"])["queue_state"] == "dispatched"


async def test_dispatch_uses_the_queued_identity_client(rig):
    store, _, service, _, wire = rig
    other = store.save_identity("单独执行端")["id"]
    current = block(store)
    reply = await service.submit_message("交给这个身份的引擎", other, request())
    store.update(current["id"], status="stopped")
    selected = []

    async def resolve(identity):
        selected.append(identity)
        return service.hermes

    service.client_resolver = resolve
    assert await service.dispatch_message()
    assert selected == [other]
    assert store.get(reply["task"]["id"])["identity_id"] == other and len(wire.runs) == 1


async def test_api_receipts_validation_identity_and_cancel_superset(tmp_path):
    wire = GoalWire()
    settings = Settings(tmp_path, hermes_key="fixture")
    client = HermesClient(settings, httpx.MockTransport(wire))
    app = create_app(settings, hermes=client, engine_autostart=False, local_devices=False)
    from wearing.cloud.worker import TenantBoundary
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    store = app.state.store
    block(store)
    other = store.save_identity("另外一个身份")["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={'Authorization': 'Bearer fixture-key', 'X-Wearing-Tenant': 'fixture', 'X-Pajio-Storage-Scope': 'a' * 64}) as http:
        token = (await http.get("/api/bootstrap")).json()["token"]
        headers = {"X-Wearing-Token": token}
        body = {"content": "重复请求只保存一次", "request_id": request()}
        first = (await http.post("/api/conversation", json=body, headers=headers)).json()
        duplicate = (await http.post("/api/conversation", json=body, headers=headers)).json()
        assert first["delivery"] == duplicate["delivery"] == "queued"
        assert first["task"]["id"] == duplicate["task"]["id"]
        messages = (await http.get("/api/conversation")).json()
        assert len(messages) == 1 and messages[0]["queued"] and messages[0]["queue_state"] == "queued"
        assert (await http.post("/api/conversation", json={**body, "content": "另一条"}, headers=headers)).status_code == 409
        for invalid in (True, "short", "x" * 81, "x" * 16 + "/"):
            assert (await http.post("/api/conversation", json={**body, "request_id": invalid}, headers=headers)).status_code == 422
        for linked in ({"goal_id": "fixture"}, {"life_record_id": "fixture", "life_revision": 1}):
            assert (await http.post("/api/conversation", json={**body, **linked}, headers=headers)).status_code == 422
        old_client = await http.post("/api/conversation", json={"content": "旧客户端没有key也能排队"}, headers=headers)
        assert old_client.status_code == 201 and old_client.json()["queued"]
        url = f'/api/tasks/{first["task"]["id"]}/cancel-message'
        assert (await http.post(url, json={}, headers={**headers, "X-Wearing-Identity": other})).status_code == 404
        assert (await http.post(url, json={})).status_code == 403
        assert (await http.post(url, json={}, headers=headers)).json()["status"] == "stopped"
    assert wire.runs == []
    await client.close()
