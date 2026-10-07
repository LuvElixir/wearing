"""Durable background feedback: receipt, identity, acknowledgement and recovery."""
import json
import sqlite3

import httpx
import pytest

from wearing.app import create_app
from wearing.config import Settings
from wearing.goals import GoalBook, GoalError
from wearing.store import Store


def finish(book, goal, decision="review", summary="阶段结果已整理，等你核对"):
    if goal["status"] == "paused":
        goal = book.control(goal["id"], goal["revision"], "resume")
    task = book.claim(goal["id"])
    book.store.update(task["id"], status="completed_unverified", output=json.dumps({
        "summary": summary, "evidence": [{"observation": "测试资料已整理", "source": "test fixture"}],
        "unknowns": [], "next_step": "讨论下一阶段", "decision": decision, "wait_seconds": 0,
    }, ensure_ascii=False))
    return task


@pytest.fixture
def book(tmp_path):
    return GoalBook(Store(tmp_path / "records.sqlite3"))


def goal(book, identity="daily", rounds=3):
    return book.create(identity, "整理一件长期的事", "仅使用测试资料", "能核对的阶段结果", rounds)


def test_feedback_commits_once_with_result_and_survives_restart(book):
    g = goal(book)
    task = finish(book, g)
    assert book.updates("daily")["unread"] == 0
    book.reconcile()
    update = book.updates("daily")["items"][0]
    assert update["task_id"] == task["id"]
    assert update["status"] == "needs_review"
    assert book.get(g["id"])["status"] == "needs_review"
    reopened = GoalBook(Store(book.store.path))
    reopened.reconcile()
    assert reopened.updates("daily") == book.updates("daily")
    assert reopened.updates("daily")["unread"] == 1


def test_feedback_failure_rolls_back_receipt_and_goal_then_recovers(book):
    g = goal(book)
    finish(book, g)
    with book.store.connection() as db:
        db.execute("""CREATE TRIGGER fixture_fail_feedback BEFORE INSERT ON goal_updates
            BEGIN SELECT RAISE(ABORT,'fixture crash'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        book.reconcile()
    assert book.detail(g["id"])["steps"][0]["processed"] == 0
    assert book.get(g["id"])["status"] == "active"
    with book.store.connection() as db:
        db.execute("DROP TRIGGER fixture_fail_feedback")
    book.reconcile()
    assert book.updates("daily")["unread"] == 1


def test_acknowledge_is_exact_idempotent_and_does_not_complete_goal(book):
    g1 = goal(book)
    finish(book, g1)
    book.reconcile()
    seen = book.updates("daily")["items"][0]["id"]
    g2 = goal(book)
    finish(book, g2)
    book.reconcile()  # Arrives after the browser read its earlier snapshot.
    result = book.acknowledge_updates("daily", [seen, seen])
    assert result["unread"] == 1
    assert result["items"][0]["goal_id"] == g2["id"]
    assert book.acknowledge_updates("daily", [seen]) == result
    assert book.get(g1["id"])["status"] == "needs_review"
    assert GoalBook(Store(book.store.path)).updates("daily") == result


def test_identity_scope_and_mixed_acknowledgement_roll_back(book):
    other = book.store.save_identity("出海", region="international")["id"]
    finish(book, goal(book))
    finish(book, goal(book, other))
    book.reconcile()
    daily = book.updates("daily")["items"][0]["id"]
    foreign = book.updates(other)["items"][0]["id"]
    with pytest.raises(GoalError):
        book.acknowledge_updates("daily", [daily, foreign])
    assert book.updates("daily")["unread"] == book.updates(other)["unread"] == 1


def test_old_revision_receipt_cannot_send_current_goal_feedback(book):
    g = goal(book)
    finish(book, g)
    current = book.get(g["id"])
    book.control(g["id"], current["revision"], "note", "现在按新的方向整理")
    book.reconcile()
    assert book.updates("daily")["unread"] == 0
    assert book.detail(g["id"])["steps"][0]["report"]


def test_failed_round_and_limit_also_return_feedback(book):
    g = book.control((g := goal(book))["id"], g["revision"], "resume")
    task = book.claim(g["id"])
    book.store.update(task["id"], status="failed", error="fixture failure")
    limited = goal(book, rounds=1)
    finish(book, limited, decision="continue")
    book.reconcile()
    assert {u["status"] for u in book.updates("daily")["items"]} == {"needs_user", "limited"}


def test_saved_feedback_includes_current_state_after_correction(book):
    g = goal(book)
    finish(book, g)
    book.reconcile()
    current = book.get(g["id"])
    book.control(g["id"], current["revision"], "note", "先按新的方向讨论")
    update = book.updates("daily")["items"][0]
    assert update["status"] == "needs_review"
    assert update["current_status"] == "paused"
    assert update["revision"] != update["current_revision"]


async def test_feedback_http_auth_identity_and_validation(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False)
    book = app.state.goals
    g = goal(book)
    finish(book, g)
    book.reconcile()
    other = book.store.save_identity("另一个身份")["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        token = (await client.get("/api/bootstrap")).json()["token"]
        data = (await client.get("/api/goal-updates")).json()
        uid = data["items"][0]["id"]
        assert (await client.get("/api/goal-updates", headers={"X-Wearing-Identity": other})).json()["unread"] == 0
        assert (await client.post("/api/goal-updates/seen", json={"ids": [uid]})).status_code == 403
        headers = {"X-Wearing-Token": token}
        for ids in ([], [True], ["1"], [0], list(range(1, 102))):
            assert (await client.post("/api/goal-updates/seen", json={"ids": ids}, headers=headers)).status_code == 422
        assert (await client.post("/api/goal-updates/seen", json={"ids": [uid]}, headers={**headers, "X-Wearing-Identity": other})).status_code == 409
        assert (await client.post("/api/goal-updates/seen", json={"ids": [uid]}, headers=headers)).json()["unread"] == 0
        assert book.get(g["id"])["status"] == "needs_review"
    await app.state.service.hermes.close()
