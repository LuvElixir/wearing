"""Synthetic progress/read-receipt contracts; no real engine or user data."""

import json

import httpx
import pytest

from wearing.activity import ActivityBook, ActivityError, ActivityQueryError
from wearing.app import create_app
from wearing.config import Settings
from wearing.confirmations import ConfirmationBook, MARKER
from wearing.goals import GoalBook
from wearing.hermes import HermesClient
from wearing.schedules import ScheduleBook
from wearing.store import IdentityError, Store, now


@pytest.fixture
def book(tmp_path):
    return ActivityBook(Store(tmp_path / "activity.sqlite3"))


def task(book, status="completed_unverified", identity="daily", **fields):
    created = book.store.create("整理测试资料", "computer", identity)
    return book.store.update(created["id"], status=status, **fields)


def seen(item):
    return {"task_id": item["task_id"], "version": item["version"]}


def single(book):
    return book.snapshot()["items"][0]


@pytest.mark.parametrize("status,bucket,label", [
    ("draft", "attention", "尚未开始"),
    ("connection_lost", "attention", "连接待核对"),
    ("ambiguous", "attention", "运行待核对"),
    ("future_status", "attention", "状态待核对"),
    ("starting", "active", "正在交接"),
    ("running", "active", "正在推进"),
    ("stopping", "active", "正在停止"),
    ("failed", "results", "执行未完成"),
    ("stopped", "results", "已停止"),
    ("closed_by_user", "results", "已结案"),
    ("completed_unverified", "results", "结果已返回"),
    ("verified", "results", "已核对"),
])
def test_progress_semantics(book, status, bucket, label):
    original = task(book, status)
    item = single(book)
    assert (item["status"], item["bucket"], item["label"]) == (status, bucket, label)
    assert item["unread"] is (bucket == "results")
    assert len(item["version"]) == 64
    assert book.store.get(original["id"]) == original
    if status == "draft":
        assert "还没有" in item["summary"]
    if status == "completed_unverified":
        assert "尚待核对" in item["summary"]


def test_read_receipt_survives_store_reopen_and_is_idempotent(book):
    original = task(book, output="测试结果")
    item = single(book)
    result = book.acknowledge("daily", [seen(item), seen(item)])
    assert result["unread"] == 0
    with book.store.connection() as db:
        receipt = dict(db.execute("SELECT * FROM activity_reads").fetchone())
    reopened = ActivityBook(Store(book.store.path))
    assert reopened.snapshot()["unread"] == 0
    reopened.acknowledge("daily", [seen(item)])
    with book.store.connection() as db:
        assert dict(db.execute("SELECT * FROM activity_reads").fetchone()) == receipt
    assert reopened.store.get(original["id"]) == original


def test_stale_snapshot_does_not_hide_new_result_or_new_verification(book):
    original = task(book, output="第一版")
    first = single(book)
    book.store.update(original["id"], output="第二版")
    second = single(book)
    assert second["version"] != first["version"]
    assert book.acknowledge("daily", [seen(first)])["unread"] == 1
    assert book.acknowledge("daily", [seen(second)])["unread"] == 0
    book.store.update(original["id"], status="verified", verification_note="实际文件已打开核对")
    third = single(book)
    assert third["label"] == "已核对" and third["unread"]
    assert book.acknowledge("daily", [seen(second)])["unread"] == 1


def test_poll_metadata_never_creates_unread_but_actual_result_change_does(book):
    original = task(book, output="已有结果")
    item = single(book)
    book.acknowledge("daily", [seen(item)])
    book.store.update(original["id"], usage={"input_tokens": 800}, research={"poll": "later"})
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET updated_at='2099-01-01T00:00:00+00:00' WHERE id=?", (original["id"],))
    current = single(book)
    assert current["version"] == item["version"] and not current["unread"]
    book.store.update(original["id"], output="已有结果，还有一项新的发现")
    assert single(book)["unread"]


def test_active_streaming_progress_never_gets_an_unread_dot(book):
    original = task(book, "running", output="正在查看")
    book.store.update(original["id"], output="正在核对更多内容")
    assert book.snapshot()["unread"] == 0
    book.acknowledge("daily", [seen(single(book))])
    with book.store.connection() as db:
        assert db.execute("SELECT count(*) FROM activity_reads").fetchone()[0] == 0
    book.store.update(original["id"], status="completed_unverified")
    assert book.snapshot()["unread"] == 1


def test_active_snapshot_does_not_claim_live_engine_observation(book):
    original = task(book, "running")
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?", (original["id"],))
    snapshot = book.snapshot()
    item = snapshot["items"][0]
    assert item["summary"] == "上次记录：执行中。结果返回后会保留在这里。"
    assert item["updated_at"] == '2020-01-01T00:00:00+00:00'
    assert snapshot["checked_at"] > item["updated_at"]
    assert item["status"] == "running" and item["bucket"] == "active"


def test_identity_filter_and_mixed_foreign_batch_roll_back(book):
    other = book.store.save_identity("出海", region="international")["id"]
    own = task(book, output="日常内容")
    foreign = task(book, identity=other, output="另一个身份内容")
    item = single(book)
    assert {i["task_id"] for i in book.snapshot()["items"]} == {own["id"]}
    foreign_item = book.snapshot(other)["items"][0]
    with pytest.raises(ActivityError):
        book.acknowledge("daily", [seen(item), seen(foreign_item)])
    assert book.snapshot()["unread"] == book.snapshot(other)["unread"] == 1
    with pytest.raises(ActivityError):
        book.acknowledge("daily", [seen(item), {"task_id": "missing", "version": "0" * 64}])
    with pytest.raises(IdentityError):
        book.snapshot("not-an-identity")
    assert foreign["output"] not in json.dumps(book.snapshot(), ensure_ascii=False)


def waiting(book):
    confirmations = ConfirmationBook(book.store)
    original = task(book, "waiting_for_approval", run_id="run-fixture")
    approval = {"request_id": "request-1", "command": MARKER + json.dumps({
        "title": "确认测试动作", "action": "保存测试资料", "impact": "只更新隔离测试资料", "confirm_label": "确认"})}
    approval = confirmations.observe(original, approval)
    original = book.store.update(original["id"], approval=approval)
    return confirmations, original


def test_seeing_confirmation_does_not_decide_or_expire_it(book):
    confirmations, original = waiting(book)
    before = confirmations.for_identity("daily")
    item = single(book)
    assert (item["label"], item["bucket"], item["summary"]) == ("等你确认", "attention", "保存测试资料")
    assert book.acknowledge("daily", [seen(item)])["counts"]["attention"] == 1
    assert confirmations.for_identity("daily") == before
    assert book.store.get(original["id"]) == original


@pytest.mark.parametrize("state,label,bucket", [
    ("sending", "确认送达待核对", "attention"),
    ("unknown", "确认送达待核对", "attention"),
    ("expired", "确认已过期", "attention"),
    ("answered", "正在核对接续", "active"),
])
def test_confirmation_receipt_is_more_precise_than_stale_task_status(book, state, label, bucket):
    _, original = waiting(book)
    first = single(book)
    with book.store.connection() as db:
        db.execute("UPDATE confirmation_cards SET state=? WHERE task_id=?", (state, original["id"]))
    item = single(book)
    assert (item["label"], item["bucket"]) == (label, bucket)
    assert item["version"] != first["version"] and not item["unread"]


def test_old_answered_card_cannot_answer_a_new_request(book):
    _, original = waiting(book)
    with book.store.connection() as db:
        db.execute("UPDATE confirmation_cards SET state='answered' WHERE task_id=?", (original["id"],))
    book.store.update(original["id"], approval={"request_id": "request-new", "command": "fixture-action"})
    assert single(book)["label"] == "等你确认"


def test_goal_and_schedule_link_is_deduplicated_and_report_is_readable(book):
    goals = GoalBook(book.store)
    ScheduleBook(book.store)
    goal = goals.create("daily", "核对测试资料", "仅使用隔离资料", "得到可检查结果", 3)
    goal = goals.control(goal["id"], goal["revision"], "resume")
    original = goals.claim(goal["id"])
    report = {"summary": "资料已整理，实际效果尚未核对", "next_step": "核对来源和日期", "decision": "review"}
    book.store.update(original["id"], status="completed_unverified", output=json.dumps(report, ensure_ascii=False))
    stamp = now()
    with book.store.connection() as db:
        db.execute("""INSERT INTO personal_schedules(id,identity_id,spec,request_key,original_spec,created_at,updated_at)
            VALUES('fixture-schedule','daily','{}','fixture-key','{}',?,?)""", (stamp, stamp))
        db.execute("""INSERT INTO schedule_occurrences(schedule_id,revision,due_at,spec,task_id,status,created_at)
            VALUES('fixture-schedule',1,?,'{}',?,'completed',?)""", (stamp, original["id"], stamp))
    item = single(book)
    assert book.snapshot()["total"] == 1
    assert item["source"] == "goal" and item["goal_id"] == goal["id"]
    assert item["summary"] == "资料已整理，实际效果尚未核对 下一步：核对来源和日期"
    assert item["label"] == "结果已返回" and "{" not in item["summary"]
    book.acknowledge("daily", [seen(item)])
    goals.reconcile()  # Persisting the same parsed report must not create a new result version.
    assert single(book)["version"] == item["version"]
    assert book.snapshot()["unread"] == 0


def test_summary_is_bounded_and_does_not_dump_raw_json(book):
    original = task(book, output='{"unexpected":"raw-json-report"}')
    assert single(book)["summary"] == "结果已返回，打开查看详情。"
    book.store.update(original["id"], output="证据" * 1000)
    assert len(single(book)["summary"]) == 400
    assert single(book)["summary"].endswith("…")


def test_full_counts_and_old_unread_results_survive_the_twenty_item_window(book):
    old = task(book, output="很早但未读的结果")
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?", (old["id"],))
    for _ in range(24):
        created = task(book)
        item = next(i for i in book.snapshot()["items"] if i["task_id"] == created["id"])
        book.acknowledge("daily", [seen(item)])
    result = book.snapshot()
    assert (result["total"], result["unread"], result["has_more"], len(result["items"])) == (25, 1, True, 20)
    assert result["counts"] == {"attention": 0, "active": 0, "waiting": 0, "results": 25}
    assert result["items"][0]["task_id"] == old["id"]
    for _ in range(21):
        task(book, "draft")
    result = book.snapshot()
    assert result["total"] == 46 and result["unread"] == 1 and result["has_more"]
    assert result["counts"]["attention"] == 21
    assert all(i["bucket"] == "attention" for i in result["items"])


def test_pages_reach_complete_history_with_global_counts_and_identity_isolation(book):
    own = {task(book)["id"] for _ in range(48)}
    own.update(task(book, "draft")["id"] for _ in range(5))
    other = book.store.save_identity("另一空间")["id"]
    task(book, identity=other, output="不应出现在当前分页")
    first = book.snapshot(limit=17)
    page, collected = first, []
    while True:
        assert page["total"] == page["filtered_total"] == 53
        assert page["counts"] == {"attention": 5, "active": 0, "waiting": 0, "results": 48}
        assert page["unread"] == 48
        assert page["revision"] == first["revision"]
        assert page["has_more"] is (page["next_cursor"] is not None)
        collected.extend(item["task_id"] for item in page["items"])
        if not page["next_cursor"]:
            break
        page = book.snapshot(limit=17, cursor=page["next_cursor"])
    assert len(collected) == len(set(collected)) == 53
    assert set(collected) == own
    filtered = book.snapshot(limit=10, bucket="results")
    assert filtered["total"] == 53 and filtered["filtered_total"] == 48
    assert all(item["bucket"] == "results" for item in filtered["items"])
    assert book.snapshot(bucket="results", limit=10, cursor=filtered["next_cursor"])["items"]
    with pytest.raises(ActivityQueryError):
        book.snapshot(other, cursor=first["next_cursor"])
    with pytest.raises(ActivityQueryError):
        book.snapshot(bucket="attention", cursor=filtered["next_cursor"])


def test_page_cursor_rejects_changed_order_instead_of_silently_skipping(book):
    originals = [task(book) for _ in range(4)]
    page = book.snapshot(limit=2)
    assert page["next_cursor"]
    book.store.update(originals[0]["id"], status="running")
    with pytest.raises(ActivityError, match="列表已更新"):
        book.snapshot(limit=2, cursor=page["next_cursor"])
    fresh = book.snapshot(limit=2)
    task(book, "draft")
    with pytest.raises(ActivityError, match="列表已更新"):
        book.snapshot(limit=2, cursor=fresh["next_cursor"])


def test_return_revision_only_reports_semantic_progress_not_polling_or_read_receipts(book):
    original = task(book, output="已有回复")
    first = book.snapshot()
    baseline = first["revision"]
    assert first["changed_since"] is None
    assert book.snapshot(since=baseline)["changed_since"] is False
    book.acknowledge("daily", [seen(first["items"][0])])
    book.store.update(original["id"], usage={"input_tokens": 10})
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET updated_at='2099-01-01T00:00:00+00:00' WHERE id=?", (original["id"],))
    assert book.snapshot(since=baseline)["changed_since"] is False
    book.store.update(original["id"], output="回复有新内容")
    changed = book.snapshot(since=baseline)
    assert changed["changed_since"] is True and changed["unread"] == 1
    assert changed["items"][0]["status"] == "completed_unverified"
    assert changed["items"][0]["label"] == "结果已返回"
    assert book.store.get(original["id"])["status"] == "completed_unverified"


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 101}, {"limit": True}, {"bucket": "done"},
                                 {"cursor": "not a cursor"}, {"cursor": "e30"}, {"since": "old"}])
def test_invalid_activity_queries_are_rejected(book, query):
    with pytest.raises(ActivityQueryError):
        book.snapshot(**query)


async def test_http_auth_validation_identity_and_no_engine_behavior(tmp_path):
    calls = []

    async def engine(request):
        calls.append(request)
        raise AssertionError("Activity must not invoke the engine")

    settings = Settings(tmp_path)
    hermes = HermesClient(settings, httpx.MockTransport(engine))
    app = create_app(settings, hermes=hermes, engine_autostart=False, local_devices=False)
    from wearing.cloud.worker import TenantBoundary
    app.add_middleware(TenantBoundary, tenant_id="fixture", gateway_key="fixture-internal")
    book = app.state.activity
    original = task(book, output="已保留结果")
    draft = task(book, "draft")
    other = book.store.save_identity("另一个身份")["id"]
    with book.store.connection() as db:
        events = list(db.execute("SELECT * FROM events"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        client.headers.update({"Authorization": "Bearer fixture-internal", "X-Wearing-Tenant": "fixture",
                               "X-Pajio-Storage-Scope": "a" * 64})
        token = (await client.get("/api/bootstrap")).json()["token"]
        result = (await client.get("/api/activity")).json()
        assert result["total"] == sum(result["counts"].values()) == len(result["items"]) == 2
        assert result["unread"] == sum(i["unread"] for i in result["items"]) == 1
        page = (await client.get("/api/activity", params={"limit": 1})).json()
        last = (await client.get("/api/activity", params={"limit": 1, "cursor": page["next_cursor"]})).json()
        assert last["has_more"] is False and last["next_cursor"] is None
        assert last["total"] == last["filtered_total"] == 2 and len(last["items"]) == 1
        assert (await client.get("/api/activity", params={"since": result["revision"]})).json()["changed_since"] is False
        for query in ({"limit": 0}, {"limit": 101}, {"cursor": "bad"}, {"bucket": "done"}, {"since": "old"}):
            assert (await client.get("/api/activity", params=query)).status_code == 422
        assert (await client.get("/api/activity", params={"cursor": page["next_cursor"]},
                                 headers={"X-Wearing-Identity": other})).status_code == 422
        item = next(i for i in result["items"] if i["task_id"] == original["id"])
        body = {"items": [seen(item)]}
        assert (await client.post("/api/activity/seen", json=body)).status_code == 403
        headers = {"X-Wearing-Token": token}
        for invalid in ({"items": []}, {"items": [seen(item)] * 101}, {"items": [{"task_id": 3, "version": item["version"]}]},
                        {"items": [{"task_id": item["task_id"], "version": "old"}]}, {**body, "everything": True}):
            assert (await client.post("/api/activity/seen", json=invalid, headers=headers)).status_code == 422
        assert (await client.get("/api/activity", headers={"X-Wearing-Identity": other})).json()["total"] == 0
        assert (await client.post("/api/activity/seen", json=body,
                                 headers={**headers, "X-Wearing-Identity": other})).status_code == 409
        assert (await client.post("/api/activity/seen", json=body, headers=headers)).json()["unread"] == 0
        assert (await client.get("/api/activity", params={"cursor": page["next_cursor"]})).status_code == 409
    assert calls == []
    assert book.store.get(original["id"]) == original and book.store.get(draft["id"]) == draft
    with book.store.connection() as db:
        assert list(db.execute("SELECT * FROM events")) == events
    await hermes.close()
