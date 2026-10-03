import json

import httpx
import pytest

from wearing.config import Settings
from wearing.hermes import HermesClient
from wearing.service import TaskError, TaskService
from wearing.store import Store


class HermesStub:
    """Wire-contract fixture only; does not stand in for a live-device acceptance."""

    def __init__(self):
        self.calls = []
        self.run_status = "running"
        self.fail_create = False
        self.fail_poll = False
        self.approval = {"request_id":"approval-1", "command":"touch example.txt"}
        self.session_id = "canonical-hermes-session"
        self.phone_tools = []

    async def __call__(self, request):
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body, dict(request.headers)))
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={"features":{"run_approval":True}, "wearing":{"phone_tools": self.phone_tools}})
        if request.method == "POST" and request.url.path == "/v1/runs":
            if self.fail_create:
                raise httpx.ReadTimeout("response lost after server accepted", request=request)
            return httpx.Response(202, json={"run_id":"run_1", "status":"started"})
        if request.url.path.endswith("/stop"):
            return httpx.Response(200, json={"status":"stopping"})
        if request.url.path.endswith("/approval"):
            return httpx.Response(200, json={"resolved":1})
        if self.fail_poll:
            raise httpx.ConnectError("temporary offline", request=request)
        return httpx.Response(200, json={"run_id":"run_1", "status":self.run_status, "output":"The file is ready.", "approval":self.approval,
                                        "session_id":self.session_id, "usage":{"input_tokens":12, "output_tokens":4}})


@pytest.fixture
async def rig(tmp_path):
    stub = HermesStub()
    client = HermesClient(Settings(tmp_path, hermes_key="test-key"), httpx.MockTransport(stub))
    store = Store(tmp_path / "test.sqlite3")
    service = TaskService(store, client)
    yield service, stub, store
    await client.close()


async def test_completed_requires_separate_verification(rig):
    service, stub, store = rig
    task = store.create("Make a file", "computer")
    await service.start(task["id"])
    stub.run_status = "completed"
    result = await service.refresh(task["id"])
    assert result["status"] == "completed_unverified"
    assert result["usage"]["input_tokens"] == 12
    assert result["verified_at"] is None
    verified = await service.verify(task["id"], "Opened and checked the file")
    assert verified["status"] == "verified"
    assert store.events(task["id"])[-1]["kind"] == "verified_by_user"


async def test_stop_request_does_not_report_stopped(rig):
    service, stub, store = rig
    task = store.create("Long operation", "computer")
    await service.start(task["id"])
    assert (await service.stop(task["id"]))["status"] == "stopping"
    stub.run_status = "stopping"
    assert (await service.refresh(task["id"]))["status"] == "stopping"
    stub.run_status = "cancelled"
    assert (await service.refresh(task["id"]))["status"] == "stopped"


async def test_uncertain_create_is_never_automatically_resubmitted(rig):
    service, stub, store = rig
    stub.fail_create = True
    task = store.create("External operation", "computer")
    result = await service.start(task["id"])
    assert result["status"] == "ambiguous"
    await service.tick()
    service.recover_startup()
    await service.tick()
    with pytest.raises(TaskError):
        await service.start(task["id"])
    posts = [call for call in stub.calls if call[:2] == ("POST", "/v1/runs")]
    assert len(posts) == 1
    assert posts[0][3]["idempotency-key"].startswith("wearing-")


async def test_poll_reconnect_preserves_remote_run(rig):
    service, stub, store = rig
    task = store.create("Remember run", "computer")
    await service.start(task["id"])
    stub.fail_poll = True
    assert (await service.refresh(task["id"]))["status"] == "connection_lost"
    service.recover_startup()
    stub.fail_poll = False
    stub.run_status = "completed"
    assert (await service.refresh(task["id"]))["status"] == "completed_unverified"
    assert len([c for c in stub.calls if c[:2] == ("POST", "/v1/runs")]) == 1


async def test_approval_is_bound_to_current_request(rig):
    service, stub, store = rig
    task = store.create("Needs approval", "computer")
    await service.start(task["id"])
    stub.run_status = "waiting_for_approval"
    await service.refresh(task["id"])
    with pytest.raises(TaskError):
        await service.approve(task["id"], "old-request", "once")
    await service.approve(task["id"], "approval-1", "once")
    calls = [c for c in stub.calls if c[1].endswith("/approval")]
    assert calls[0][2] == {"request_id":"approval-1", "choice":"once"}


async def test_one_run_at_a_time_and_no_phone_fallback(rig):
    service, stub, store = rig
    phone = store.create("Phone action", "phone")
    with pytest.raises(TaskError):
        await service.start(phone["id"])
    task = store.create("Computer action", "computer")
    await service.start(task["id"])
    other = store.create("Second computer action", "computer")
    with pytest.raises(TaskError):
        await service.start(other["id"])
    assert len([c for c in stub.calls if c[:2] == ("POST", "/v1/runs")]) == 1


async def test_phone_task_requires_discovered_tools_and_still_needs_verification(rig):
    service, stub, store = rig
    stub.phone_tools = ["mcp_wearing_phone_mobile_list_elements_on_screen"]
    task = store.create("Read the phone screen", "phone")
    await service.start(task["id"])
    stub.run_status = "completed"
    assert (await service.refresh(task["id"]))["status"] == "completed_unverified"
    sandbox = store.create("Sandbox action", "sandbox")
    with pytest.raises(TaskError, match="沙盒"):
        await service.start(sandbox["id"])


async def test_malformed_remote_status_is_visible_not_a_poll_crash(rig):
    service, stub, store = rig
    task = store.create("Check protocol", "computer")
    await service.start(task["id"])
    stub.run_status = ["not-a-valid-state"]
    assert (await service.refresh(task["id"]))["status"] == "ambiguous"


async def test_manual_resolution_is_not_verified_success(rig):
    service, stub, store = rig
    stub.fail_create = True
    task = store.create("Unknown outcome", "computer")
    await service.start(task["id"])
    result = await service.resolve(task["id"], "Checked Hermes and stopped the original work")
    assert result["status"] == "closed_by_user"
    assert result["verified_at"] is None


async def test_restart_reopens_database_and_queries_original_run(rig):
    service, stub, store = rig
    task = store.create("Continue after restart", "computer")
    await service.start(task["id"])
    reopened = Store(store.path)
    restarted = TaskService(reopened, service.hermes)
    restarted.recover_startup()
    assert reopened.get(task["id"])["status"] == "connection_lost"
    await restarted.tick()
    assert reopened.get(task["id"])["run_id"] == "run_1"
    assert reopened.get(task["id"])["status"] == "running"
    assert len([call for call in stub.calls if call[0:2] == ("POST", "/v1/runs")]) == 1


async def test_unchanged_poll_preserves_visible_detail_and_malformed_approval(rig):
    service, stub, store = rig
    task = store.create("Poll without changing focus", "computer")
    await service.start(task["id"])
    first = await service.refresh(task["id"])
    second = await service.refresh(task["id"])
    assert first["updated_at"] == second["updated_at"]
    stub.run_status = "waiting_for_approval"
    stub.approval = ["unexpected"]
    result = await service.refresh(task["id"])
    assert result["status"] == "waiting_for_approval"
    assert result["approval"] is None
    with pytest.raises(TaskError):
        await service.approve(task["id"], "approval-1", "once")


async def test_conversation_follows_canonical_session_across_restart_and_pending_messages(rig):
    service, stub, store = rig
    first = store.create_message("我想和你聊聊")
    await service.start(first["id"])
    pending = store.create_message("接着刚刚说的")
    with pytest.raises(TaskError):
        await service.start(pending["id"])
    stub.run_status = "completed"
    await service.refresh(first["id"])
    reopened = Store(store.path)
    restarted = TaskService(reopened, service.hermes)
    restarted.recover_startup()
    await restarted.start(pending["id"])
    posts = [call for call in stub.calls if call[:2] == ("POST", "/v1/runs")]
    assert len(posts) == 2
    assert posts[1][2]["session_id"] == stub.session_id
    assert posts[1][2]["input"] == "接着刚刚说的"
    assert [m["content"] for m in reopened.conversation()] == ["我想和你聊聊", "接着刚刚说的"]
    assert reopened.create_message("明天还想继续聊")["session_id"] == stub.session_id


async def test_offline_messages_cannot_skip_earlier_unsent_context(rig):
    service, stub, store = rig
    first = store.create_message("先说的背景")
    second = store.create_message("依赖刚刚的背景")
    with pytest.raises(TaskError, match="较早"):
        await service.start(second["id"])
    assert not any(c[:2] == ("POST", "/v1/runs") for c in stub.calls)
    await service.start(first["id"])
    stub.run_status = "completed"
    await service.refresh(first["id"])
    await service.start(second["id"])
