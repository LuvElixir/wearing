"""Result choice is an explicit durable message, not arbitrary HTML tool access."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import ValidationError

from wearing.artifact_choices import ArtifactChoices, ChoiceRequest
from wearing.artifacts import ArtifactDraft, ArtifactError
from wearing.app import create_app
from wearing.config import Settings
from wearing.goals import GoalBook, GoalCoordinator
from wearing.hermes import HermesClient
from wearing.service import TaskService
from wearing.store import Store
from test_artifacts import setup
from test_goals import GoalWire


def rig(tmp_path):
    store = Store(tmp_path / "fixture.sqlite3")
    book, task, draft = setup(store)
    draft = ArtifactDraft.model_validate({**draft.model_dump(), "choices": [
        {"id": "compare", "label": "继续比较", "instruction": "按总价和时间比较这两份测试方案。"},
        {"id": "short", "label": "整理成一页", "instruction": "压缩成一页可阅读的摘要。"},
    ]})
    item = book.publish("daily", draft, "fixture-publish")
    store.update(task["id"], status="completed_unverified")
    return store, book, ArtifactChoices(book), task, draft, item


def request(**patch):
    return ChoiceRequest(request_key="fixture-choice-request001", choice_id="compare", artifact_revision=1, selection_revision=0, **patch)


def test_choice_transaction_restart_parallel_idempotency_and_context(tmp_path):
    store, book, choices, task, _, item = rig(tmp_path)
    assert choices.state("daily", item["id"])["revision"] == 0
    with ThreadPoolExecutor(max_workers=5) as pool:
        receipts = list(pool.map(lambda _: choices.select("daily", item["id"], request()), range(8)))
    assert len({x["task_id"] for x in receipts}) == 1
    receipt = receipts[0]
    assert receipt["source_task_id"] == task["id"] and receipt["queue_state"] == "queued"
    child = store.get(receipt["task_id"])
    assert item["id"] in child["prompt"] and task["id"] in child["prompt"]
    assert "总价和时间" in child["prompt"] and "不代表付款" in child["prompt"]
    assert child["session_id"] != task["session_id"] and child["status"] == "draft"  # Fresh local owner never inherits unowned engine history.
    assert len(store.conversation()) == 2
    assert item["id"] not in store.conversation()[-1]["content"]
    assert "继续比较" in child["title"] and task["id"] not in child["title"]
    reopened = ArtifactChoices(type(book)(Store(store.path)))
    assert reopened.state("daily", item["id"])["selection"] == receipt
    assert reopened.select("daily", item["id"], request()) == receipt


def test_newer_version_blocks_fresh_selection_but_retry_finds_original_receipt(tmp_path):
    store, book, choices, task, draft, item = rig(tmp_path)
    receipt = choices.select("daily", item["id"], request())
    store.update(task["id"], status="running")
    newer = book.publish("daily", draft.model_copy(update={"previous_id": item["id"]}), "next-version")
    assert choices.select("daily", item["id"], request()) == receipt
    with pytest.raises(ArtifactError, match="新版本"):
        choices.select("daily", item["id"], request().model_copy(update={"request_key": "different-request-key"}))
    assert choices.state("daily", item["id"])["newer_id"] == newer["id"]


def test_unknown_choice_conflict_stale_state_active_source_and_active_followup(tmp_path):
    store, _, choices, task, _, item = rig(tmp_path)
    for patch in ({"choice_id": "execute-shell"}, {"selection_revision": 1}, {"artifact_revision": 2}):
        with pytest.raises(ArtifactError):
            choices.select("daily", item["id"], request().model_copy(update=patch))
    store.update(task["id"], status="ambiguous")
    with pytest.raises(ArtifactError, match="原任务"):
        choices.select("daily", item["id"], request())
    store.update(task["id"], status="completed_unverified")
    receipt = choices.select("daily", item["id"], request())
    with pytest.raises(ArtifactError, match="提交编号"):
        choices.select("daily", item["id"], request().model_copy(update={"choice_id": "short"}))
    fresh = request().model_copy(update={"request_key": "next-choice-request", "selection_revision": 1})
    with pytest.raises(ArtifactError, match="上一项选择"):
        choices.select("daily", item["id"], fresh)
    store.update(receipt["task_id"], status="stopped")
    assert choices.select("daily", item["id"], fresh)["revision"] == 2


def test_identity_and_account_scope_cannot_disclose_another_choice(tmp_path):
    store, _, choices, _, _, item = rig(tmp_path)
    other = store.save_identity("other")["id"]
    for method in (lambda: choices.state(other, item["id"]), lambda: choices.select(other, item["id"], request())):
        with pytest.raises(ArtifactError) as error:
            method()
        assert error.value.status == 404
    a = choices.select("daily", item["id"], request(), "a" * 64)
    assert choices.state("daily", item["id"], "b" * 64)["selection"] is None
    b = choices.select("daily", item["id"], request(), "b" * 64)
    assert a["task_id"] != b["task_id"]
    with pytest.raises(ArtifactError) as error:
        choices.state("daily", item["id"], "untrusted")
    assert error.value.status == 401


def test_sql_failure_rolls_back_message_queue_and_selection(tmp_path):
    store, _, choices, _, _, item = rig(tmp_path)
    with store.connection() as db:
        db.execute("CREATE TRIGGER reject_fixture BEFORE INSERT ON artifact_selections BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        choices.select("daily", item["id"], request())
    assert len(store.conversation()) == 1
    assert choices.state("daily", item["id"])["selection"] is None
    assert store.next_queued_message() is None


async def test_selection_dispatches_existing_coordinator_once_without_external_effect(tmp_path):
    store, _, choices, _, _, item = rig(tmp_path)
    receipt = choices.select("daily", item["id"], request())
    wire = GoalWire()
    client = HermesClient(Settings(tmp_path, hermes_key="fixture"), httpx.MockTransport(wire))
    service = TaskService(store, client)
    coordinator = GoalCoordinator(GoalBook(store), service)
    try:
        await coordinator.tick()
        await coordinator.tick()
        assert len(wire.runs) == 1 and item["id"] in wire.runs[0]["input"]
        assert choices.select("daily", item["id"], request())["queue_state"] == "dispatched"
        assert choices.state("daily", item["id"])["selection"]["task_id"] == receipt["task_id"]
    finally:
        await client.close()


def test_strict_choice_schema_and_tool_definitions(tmp_path):
    from wearing.artifact_tools import TOOLS
    import jsonschema
    schema = next(t.inputSchema for t in TOOLS if t.name == "artifact_publish")
    base = {"artifact": {"path": "x.html", "title": "title", "summary": "summary", "choices": [
        {"id": "ok", "label": "ok", "instruction": "continue"}]}, "request_key": "key"}
    jsonschema.validate(base, schema)
    for patch in ({"artifact_revision": True}, {"selection_revision": "0"}, {"choice_id": "../x"}, {"request_key": "short"}, {"command": "shell"}):
        with pytest.raises(ValidationError):
            ChoiceRequest.model_validate({**request().model_dump(), **patch})
    with pytest.raises(ValidationError):
        ArtifactDraft.model_validate({**base["artifact"], "choices": base["artifact"]["choices"] * 2})


async def test_api_csrf_no_html_bridge_exact_identity_and_receipt(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    from wearing.cloud.worker import TenantBoundary
    app.add_middleware(TenantBoundary, tenant_id='fixture', gateway_key='fixture-key')
    book, task, draft = setup(app.state.store)
    draft = ArtifactDraft.model_validate({**draft.model_dump(), "choices": [{"id": "compare", "label": "比较", "instruction": "继续比较。"}]})
    item = book.publish("daily", draft, "request")
    app.state.store.update(task["id"], status="completed_unverified")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", headers={'Authorization': 'Bearer fixture-key', 'X-Wearing-Tenant': 'fixture', 'X-Pajio-Storage-Scope': 'a' * 64}) as http:
        url = f'/api/artifacts/{item["id"]}/choices'
        assert (await http.post(url, json=request().model_dump())).status_code == 403
        token = (await http.get('/api/bootstrap')).json()['token']
        headers = {'X-Wearing-Token': token}
        result = await http.post(url, json=request().model_dump(), headers=headers)
        assert result.status_code == 201 and result.json()['source_task_id'] == task['id']
        assert (await http.get(url)).json()['selection']['task_id'] == result.json()['task_id']
        assert (await http.post(url, json=request().model_dump(), headers={**headers, 'Origin': 'null'})).status_code == 403
    await app.state.service.hermes.close()
