import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from wearing.app import create_app
from wearing.config import Settings
from wearing.confirmations import ConfirmationBook, MARKER, card_for, request_confirmation
from wearing.hermes import HermesClient, HermesError
from wearing.service import TaskError, TaskService
from wearing.store import Store
from test_lifecycle import HermesStub


CARD = {"title": "保存这份测试笔记？", "action": "在当前身份保存一条合成测试笔记。",
        "impact": "仅修改隔离测试数据，不访问设备或外部账号。", "confirm_label": "保存笔记"}


@pytest.mark.parametrize("action,expected", [("accept", "approved"), ("decline", "not_approved"), ("cancel", "not_approved")])
async def test_mcp_awaits_actual_decision(action, expected):
    seen = []
    async def elicit(message, schema):
        seen.append((message, schema))
        return SimpleNamespace(action=action)
    result = await request_confirmation(SimpleNamespace(session=SimpleNamespace(elicit_form=elicit)), CARD)
    assert result["decision"] == expected
    assert result["card_closed"] is True
    if expected == "not_approved":
        assert "不要催用户再次确认" in result["next"]
    assert result["action"] == CARD["action"]
    assert seen == [(MARKER + json.dumps(CARD, ensure_ascii=False), {"type": "object", "properties": {}})]


async def test_timeout_does_not_approve():
    async def elicit(*args):
        raise TimeoutError()
    result = await request_confirmation(SimpleNamespace(session=SimpleNamespace(elicit_form=elicit)), CARD)
    assert result["decision"] == "not_approved"


def test_incomplete_proposal_is_not_actionable():
    assert card_for({"command": MARKER + '{"title":"missing details"}'}) is None
    assert card_for({"command": MARKER + 'garbage'}) is None
    assert card_for({"command": "echo hello", "description": "Run a command"})["command"] == "echo hello"


@pytest.fixture
async def rig(tmp_path):
    stub = HermesStub()
    stub.approval = {"request_id": "decision-1", "command": MARKER + json.dumps(CARD)}
    client = HermesClient(Settings(tmp_path, hermes_key="test"), httpx.MockTransport(stub))
    store = Store(tmp_path / "wearing.sqlite3")
    service = TaskService(store, client)
    task = store.create_message("Synthetic confirmation acceptance")
    await service.start(task["id"])
    stub.run_status = "waiting_for_approval"
    task = await service.refresh(task["id"])
    yield stub, store, service, task
    await client.close()


async def test_confirm_receipt_survives_refresh_restart_and_duplicate(rig):
    stub, store, service, task = rig
    assert task["approval"]["card"] == CARD
    results = await asyncio.gather(service.approve(task["id"], "decision-1", "once"),
                                   service.approve(task["id"], "decision-1", "deny"), return_exceptions=True)
    assert sum(isinstance(r, TaskError) for r in results) == 1
    assert len([c for c in stub.calls if c[1].endswith("/approval")]) == 1
    # Even a stale remote status cannot re-enable the same question.
    stale = await service.refresh(task["id"])
    assert stale["approval"]["card_state"] == "answered"
    with pytest.raises(TaskError):
        await service.approve(task["id"], "decision-1", "once")
    rows = ConfirmationBook(Store(store.path)).for_identity("daily")[task["id"]]
    assert len(rows) == 1 and rows[0]["state"] == "answered" and rows[0]["choice"] == "once"
    other = store.save_identity("另一个身份")["id"]
    assert service.confirmations.for_identity(other) == {}


async def test_changed_request_invalidates_old_card(rig):
    stub, store, service, task = rig
    stub.approval = {**stub.approval, "request_id": "decision-2"}
    await service.refresh(task["id"])
    with pytest.raises(TaskError):
        await service.approve(task["id"], "decision-1", "once")
    rows = service.confirmations.for_identity("daily")[task["id"]]
    assert [r["state"] for r in rows] == ["expired", "pending"]
    await service.approve(task["id"], "decision-2", "deny")
    assert service.confirmations.for_identity("daily")[task["id"]][-1]["choice"] == "deny"


async def test_reusing_request_id_for_changed_action_is_rejected(rig):
    stub, store, service, task = rig
    stub.approval["command"] = MARKER + json.dumps({**CARD, "action": "换成另一件事情"})
    refreshed = await service.refresh(task["id"])
    assert refreshed["approval"]["card_invalid"] is True
    with pytest.raises(TaskError):
        await service.approve(task["id"], "decision-1", "once")
    assert not [c for c in stub.calls if c[1].endswith("/approval")]


async def test_lost_post_response_is_not_retried(rig):
    stub, store, service, task = rig
    calls = []
    async def lost(*args):
        calls.append(args)
        raise HermesError("receipt lost", uncertain=True)
    service.hermes.approve = lost
    with pytest.raises(TaskError):
        await service.approve(task["id"], "decision-1", "once")
    assert service.require(task["id"])["approval"]["card_state"] == "unknown"
    refreshed = await service.refresh(task["id"])
    assert refreshed["approval"]["card_state"] == "unknown"
    with pytest.raises(TaskError):
        await service.approve(task["id"], "decision-1", "once")
    assert len(calls) == 1


async def test_stop_expires_card(rig):
    stub, store, service, task = rig
    await service.stop(task["id"])
    assert service.confirmations.for_identity("daily")[task["id"]][0]["state"] == "expired"
    with pytest.raises(TaskError):
        await service.approve(task["id"], "decision-1", "once")


async def test_conversation_receipts_are_identity_scoped(rig, tmp_path):
    stub, store, service, task = rig
    await service.approve(task["id"], "decision-1", "deny")
    other = store.save_identity("其他身份")["id"]
    app = create_app(Settings(tmp_path), hermes=service.hermes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        boot = (await client.get("/api/bootstrap")).json()
        items = (await client.get("/api/conversation")).json()
        assert items[0]["turn"]["confirmations"][0]["choice"] == "deny"
        headers = {"X-Wearing-Identity": other, "X-Wearing-Token": boot["token"]}
        assert (await client.get("/api/conversation", headers=headers)).json() == []
        response = await client.post(f"/api/tasks/{task['id']}/approval", headers=headers,
                                     json={"request_id": "decision-1", "choice": "once"})
        assert response.status_code == 404
