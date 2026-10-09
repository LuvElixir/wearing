import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType, SimpleNamespace

import httpx
import pytest

from wearing.config import Settings
from wearing.app import create_app
from wearing.confirmations import request_confirmation, card_for
from wearing.confirmation_guard import ConfirmationGuard, install_confirmation_guard
from wearing.durable_confirmations import DurableConfirmations, ConfirmationError, MARKER, PREFIX
from wearing.hermes import HermesClient, HermesError
from wearing.life import LifeBook, LifeDraft
from wearing.life_proxy import dispatch
from wearing.service import TaskService, TaskError
from wearing.store import Store
from test_lifecycle import HermesStub

CARD = {"title": "更新这条测试笔记？", "action": "修改隔离测试身份里的合成笔记。", "impact": "只改变这条笔记的标题。", "confirm_label": "更新笔记"}


@pytest.fixture
def ledger(tmp_path):
    store = Store(tmp_path / "wearing.sqlite3")
    book = DurableConfirmations(store)
    original = store.create_message("修改测试笔记")
    original = store.update(original["id"], status="running", run_id="run_source")
    action = book.create("daily", CARD)
    return store, book, original, action


def recovery(ledger):
    store, book, original, action = ledger
    assert not book.finish_wait(action["id"])
    store.update(original["id"], status="completed_unverified", output="等待之后重新核对。")
    current = book.get("daily", action["id"])
    task_id, created = book.prepare_recovery("daily", action["id"], current["revision"], "recovery_request_01")
    assert created
    task = store.update(task_id, status="running", run_id="run_recovery")
    life = LifeBook(store)
    record = life.create("daily", LifeDraft(kind="note", title="原标题"), "record-one")
    guard = ConfirmationGuard(store, "daily")
    operation = {"tool": PREFIX + "life_change", "args": {"record_id": record["id"], "revision": record["revision"], "action": "edit", "patch": {"title": "新标题"}}}
    return store, book, task, life, record, guard, operation


def read_record(guard, task, life, record):
    return guard.execute(task, PREFIX + "life_records", {"record_id": record["id"]},
                         lambda args: dispatch(life, "daily", "life_records", args))


def approve_new(book, operation):
    proposal = book.create("daily", {**CARD, "operation": operation})
    assert book.finish_wait(proposal["id"], True)
    return proposal


async def test_timeout_persists_proposal_and_never_approves(ledger):
    store, book, original, action = ledger
    # Use a new run, so there is no second question in one unresolved run.
    book.finish_wait(action["id"], False)
    store.update(original["id"], status="completed_unverified")
    current = store.create_message("稍后回来确认")
    store.update(current["id"], status="running", run_id="run_timeout")
    messages = []
    async def elicit(message, schema):
        messages.append(message)
        raise TimeoutError
    result = await request_confirmation(SimpleNamespace(session=SimpleNamespace(elicit_form=elicit)), CARD,
                                        store=store, identity="daily")
    assert result["decision"] == "not_approved" and result["state"] == "needs_recheck"
    assert messages[0].startswith(MARKER)
    parsed = card_for({"command": messages[0]})
    assert parsed["action_id"] == result["action_id"]
    persisted = DurableConfirmations(Store(store.path)).get("daily", result["action_id"])
    assert persisted["state"] == "needs_recheck" and persisted["card"] == CARD
    called = []
    with pytest.raises(ConfirmationError):
        ConfirmationGuard(store, "daily").execute(store.get(current["id"]), "terminal", {"command": "do_it"}, lambda a: called.append(a))
    assert called == []


def test_recovery_create_is_atomic_across_process_style_connections_and_keys(ledger):
    store, book, original, action = ledger
    book.finish_wait(action["id"])
    store.update(original["id"], status="failed")
    revision = book.get("daily", action["id"])["revision"]
    def reserve(index):
        return DurableConfirmations(Store(store.path)).prepare_recovery("daily", action["id"], revision, f"request_recovery_{index}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert len({r[0] for r in results}) == 1 and sum(r[1] for r in results) == 1
    assert len(store.conversation()) == 2
    with pytest.raises(ConfirmationError):
        book.prepare_recovery("daily", action["id"], revision + 1, "request_recovery_0")
    other = store.save_identity("隔离")['id']
    with pytest.raises(ConfirmationError):
        book.prepare_recovery(other, action["id"], revision, "another_request_0")
    assert book.list(other) == []


@pytest.mark.parametrize("delivery", ["sending", "unknown"])
def test_lost_approval_delivery_becomes_recheck_only_after_terminal_run(ledger, delivery):
    store, book, original, action = ledger
    book.bind(original, action['id'], CARD, 'waiter-1')
    assert book.claim(original, action['id'], 'waiter-1')
    if delivery == 'unknown':
        book.delivery(action['id'], 'unknown')
    book.observe_task(original)
    assert book.get('daily', action['id'])['state'] == delivery
    assert not book.list('daily')[0]['can_resume']
    original = store.update(original['id'], status='failed')
    book.observe_task(original)
    current = book.get('daily', action['id'])
    assert current['state'] == 'needs_recheck'
    assert book.list('daily')[0]['can_resume']
    # A late waiter cannot grant permission after terminal reconciliation.
    assert not book.finish_wait(action['id'], True)
    task_id, created = book.prepare_recovery('daily', action['id'], current['revision'], 'retry_unknown_delivery')
    assert created and task_id != original['id']


def test_recovery_requires_actual_read_and_bound_revision(ledger):
    store, book, task, life, record, guard, operation = recovery(ledger)
    with pytest.raises(ConfirmationError, match="实际读取"):
        book.create("daily", {**CARD, "operation": operation})
    read_record(guard, task, life, record)
    life.update("daily", record["id"], 1, {"title": "用户刚修改了"})
    with pytest.raises(ConfirmationError, match="已经变化"):
        book.create("daily", {**CARD, "operation": operation})
    # Guessing the new revision without reading it is not enough.
    operation["args"]["revision"] = 2
    with pytest.raises(ConfirmationError, match="实际读取"):
        book.create("daily", {**CARD, "operation": operation})
    read_record(guard, task, life, record)
    assert book.create("daily", {**CARD, "operation": operation})["parent_id"]


@pytest.mark.parametrize("tool,args", [("terminal", {"command": "echo write"}),
    ("delegate_task", {"task": "skip restriction"}), ("browser_click", {"selector": "buy"}),
    (PREFIX + "life_create", {"record": {"title": "new"}}), ("mcp__other__life_records", {})])
def test_recovery_denies_every_unlisted_effect_capability(ledger, tool, args):
    store, book, task, life, record, guard, operation = recovery(ledger)
    with pytest.raises(ConfirmationError):
        guard.execute(task, tool, args, lambda _: pytest.fail("actual tool must not run"))
    with pytest.raises(ConfirmationError):
        book.create("daily", {**CARD, "operation": {"tool": tool, "args": args}})


def test_only_exact_newly_approved_operation_can_execute_once(ledger):
    store, book, task, life, record, guard, operation = recovery(ledger)
    read_record(guard, task, life, record)
    proposal = approve_new(book, operation)
    changed = {**operation["args"], "patch": {"title": "换成危险参数"}}
    with pytest.raises(ConfirmationError):
        guard.execute(task, operation["tool"], changed, lambda _: pytest.fail("changed call"))
    calls = []
    def change(args):
        calls.append(args)
        return dispatch(life, "daily", "life_change", args)
    def execute(_):
        try:
            return ConfirmationGuard(Store(store.path), "daily").execute(task, operation["tool"], operation["args"], change)
        except ConfirmationError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(execute, range(4)))
    assert sum(result is not None for result in results) == 1 and len(calls) == 1
    assert life.get("daily", record["id"])["title"] == "新标题"
    assert book.get("daily", proposal["id"])["state"] == "executed_unverified"


def test_user_change_after_new_approval_is_never_overwritten(ledger):
    store, book, task, life, record, guard, operation = recovery(ledger)
    read_record(guard, task, life, record)
    approve_new(book, operation)
    life.update("daily", record["id"], 1, {"title": "用户最新标题"})
    with pytest.raises(ConfirmationError):
        guard.execute(task, operation["tool"], operation["args"], lambda _: pytest.fail("stale write"))
    assert life.get("daily", record["id"])["title"] == "用户最新标题"


def test_unknown_execution_receipt_is_not_replayed_after_restart(ledger):
    store, book, task, life, record, guard, operation = recovery(ledger)
    read_record(guard, task, life, record)
    proposal = approve_new(book, operation)
    def lost(args):
        dispatch(life, "daily", "life_change", args)
        raise OSError("lost after commit")
    with pytest.raises(OSError):
        guard.execute(task, operation["tool"], operation["args"], lost)
    with pytest.raises(ConfirmationError):
        ConfirmationGuard(Store(store.path), "daily").execute(task, operation["tool"], operation["args"], lambda _: pytest.fail("duplicate"))
    assert book.get("daily", proposal["id"])["state"] == "execution_unknown"
    store.update(task["id"], status="failed")
    with pytest.raises(ConfirmationError):
        book.prepare_recovery("daily", proposal["id"], book.get("daily", proposal["id"])["revision"], "unknown_retry_key")


def test_unused_approved_permit_becomes_recheckable_after_interrupted_run(ledger):
    store, book, task, life, record, guard, operation = recovery(ledger)
    read_record(guard, task, life, record)
    proposal = approve_new(book, operation)
    task = store.update(task["id"], status="failed")
    book.observe_task(task)
    current = book.get("daily", proposal["id"])
    assert current["state"] == "needs_recheck"
    with pytest.raises(ConfirmationError):
        guard.execute(task, operation["tool"], operation["args"], lambda _: pytest.fail("old context"))
    next_task, created = book.prepare_recovery("daily", proposal["id"], current["revision"], "fresh_recovery_key")
    assert created and next_task != task["id"]


def test_interrupted_read_only_recovery_has_an_explicit_new_recheck_entry(ledger):
    store, book, task, life, record, guard, operation = recovery(ledger)
    task = store.update(task["id"], status="failed", error="engine restarted")
    book.observe_task(task)
    book.observe_task(task)  # refresh never creates duplicate recheck entries
    retry = [row for row in book.list("daily") if row['task_id'] == task['id']]
    assert len(retry) == 1 and retry[0]['can_resume']
    assert retry[0]['state'] == 'needs_recheck'
    next_task, created = book.prepare_recovery('daily', retry[0]['id'], retry[0]['revision'], 'retry_after_restart')
    assert created and next_task != task['id']
    # An old model thread cannot wake later and mutate during/after recovery.
    original = store.get(ledger[2]['id'])
    with pytest.raises(ConfirmationError):
        guard.execute(original, 'terminal', {}, lambda _: pytest.fail('retired execution'))


def test_real_dispatch_hook_checks_final_plugin_modified_arguments(ledger, monkeypatch):
    store, book, task, life, record, guard, operation = recovery(ledger)
    read_record(guard, task, life, record)
    approve_new(book, operation)
    executor = ModuleType("agent.tool_executor")
    def final_dispatch(agent, state, ref, *, execute, **kwargs):
        # Mirrors pinned Hermes plugin-modify position before final execute.
        ref.args = {**ref.args, "patch": {"title": "plugin swapped"}}
        return execute(ref.args)
    executor._dispatch_authorized_once = final_dispatch
    agent_module = ModuleType("agent")
    agent_module.tool_executor = executor
    approval_module = ModuleType("tools.approval_context")
    approval_module.get_current_session_key = lambda: "run_recovery"
    monkeypatch.setitem(sys.modules, "agent", agent_module)
    monkeypatch.setitem(sys.modules, "agent.tool_executor", executor)
    monkeypatch.setitem(sys.modules, "tools.approval_context", approval_module)
    monkeypatch.setenv("PAJIO_CONFIRMATION_DATA_DIR", str(store.path.parent))
    monkeypatch.setenv("PAJIO_CONFIRMATION_IDENTITY", "daily")
    assert install_confirmation_guard()
    assert install_confirmation_guard()  # no double wrapping
    state = SimpleNamespace(blocked=False)
    ref = SimpleNamespace(name=operation["tool"], args=operation["args"])
    value = executor._dispatch_authorized_once(None, state, ref, execute=lambda _: pytest.fail("modified mutation"))
    assert state.blocked and json.loads(value)["error"] == "confirmation_recheck_read_only"


class GuardedStub(HermesStub):
    guard = True
    starts = 0
    async def __call__(self, request):
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json={"features": {"run_approval": True}, "wearing": {"confirmation_guard": "durable-v1" if self.guard else None}})
        if request.method == "POST" and request.url.path == "/v1/runs":
            self.starts += 1
            self.calls.append(("POST", "/v1/runs", json.loads(request.content), {}))
            return httpx.Response(202, json={"run_id": f"run_{self.starts}", "status": "started"})
        return await super().__call__(request)


async def test_service_live_original_and_expired_resume_are_distinct_and_idempotent(tmp_path):
    stub = GuardedStub()
    client = HermesClient(Settings(tmp_path, hermes_key="test"), httpx.MockTransport(stub))
    store = Store(tmp_path / "wearing.sqlite3")
    service = TaskService(store, client)
    try:
        task = store.create_message("test")
        await service.start(task["id"])
        book = service.confirmations.durable
        proposal = book.create("daily", CARD)
        stub.run_status = "waiting_for_approval"
        stub.approval = {"request_id": "confirm-1", "command": MARKER + json.dumps({"action_id": proposal["id"], "card": CARD})}
        await service.refresh(task["id"])
        service.recover_startup()
        response = await service.resume_confirmation("daily", proposal["id"], 1, "request_initial_key")
        assert response["delivery"] == "live_confirmation" and stub.starts == 1
        book.finish_wait(proposal["id"])
        stub.run_status = "completed"
        await service.refresh(task["id"])
        current = book.get("daily", proposal["id"])
        responses = await asyncio.gather(*[service.resume_confirmation("daily", proposal["id"], current["revision"], "request_recover_key") for _ in range(3)])
        assert len({r["task"]["id"] for r in responses}) == 1 and stub.starts == 2
        assert all(r["authorized"] is False for r in responses)
    finally:
        await client.close()


async def test_unguarded_engine_cannot_start_recovery(ledger):
    store, book, original, action = ledger
    book.finish_wait(action["id"])
    store.update(original["id"], status="failed")
    stub = GuardedStub()
    stub.guard = False
    client = HermesClient(Settings(store.path.parent, hermes_key="test"), httpx.MockTransport(stub))
    try:
        service = TaskService(store, client)
        response = await service.resume_confirmation("daily", action["id"], book.get("daily", action["id"])["revision"], "unguarded_request_1")
        assert response["delivery"] == "saved" and "启用安全恢复" in response["reason"]
        assert stub.starts == 0
    finally:
        await client.close()


async def test_changed_remote_waiter_blocks_old_http_approval(ledger):
    store, book, task, action = ledger
    stub = GuardedStub()
    client = HermesClient(Settings(store.path.parent, hermes_key="test"), httpx.MockTransport(stub))
    try:
        service = TaskService(store, client)
        stub.run_status = "waiting_for_approval"
        stub.approval = {"request_id": "confirm-1", "command": MARKER + json.dumps({"action_id": action["id"], "card": CARD})}
        await service.refresh(task["id"])
        stub.approval = {**stub.approval, "request_id": "different"}
        with pytest.raises(TaskError, match="原确认"):
            await service.approve(task["id"], "confirm-1", "once")
        assert not [c for c in stub.calls if c[1].endswith('/approval')]
    finally:
        await client.close()


@pytest.mark.parametrize("answer,state", [("cancel", "needs_recheck"), ("decline", "denied"), ("accept", "approved")])
async def test_mcp_cancel_preserves_recovery_while_explicit_denial_closes(tmp_path, answer, state):
    store = Store(tmp_path / "wearing.sqlite3")
    task = store.create_message("测试确认")
    store.update(task["id"], status="running", run_id="run_test")
    async def elicit(*_): return SimpleNamespace(action=answer)
    result = await request_confirmation(SimpleNamespace(session=SimpleNamespace(elicit_form=elicit)), CARD, store=store, identity="daily")
    assert result["state"] == state
    assert (result["decision"] == "approved") is (answer == "accept")


async def test_confirmation_api_scopes_mutations_redacts_tasks_and_retries(tmp_path):
    stub = GuardedStub()
    hermes = HermesClient(Settings(tmp_path, hermes_key="test"), httpx.MockTransport(stub))
    app = create_app(Settings(tmp_path), hermes=hermes)
    store = app.state.store
    service = app.state.service
    task = store.create_message("API 合成提案")
    store.update(task["id"], status="running", run_id="source_api")
    book = service.confirmations.durable
    proposal = book.create("daily", CARD)
    book.finish_wait(proposal["id"])
    store.update(task["id"], status="completed_unverified")
    other = store.save_identity("其他账号")['id']
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            boot = (await client.get('/api/bootstrap')).json()
            headers = {'X-Wearing-Token': boot['token'], 'X-Wearing-Identity': 'daily'}
            listing = await client.get('/api/confirmations', headers=headers)
            assert listing.status_code == 200
            row = listing.json()['items'][0]
            assert row['can_resume'] and row['state'] == 'needs_recheck'
            body = {'revision': row['revision'], 'request_key': 'api_confirmation_01'}
            url = f"/api/confirmations/{proposal['id']}/resume"
            assert (await client.post(url, json=body)).status_code == 403
            foreign = {**headers, 'X-Wearing-Identity': other}
            assert (await client.get('/api/confirmations', headers=foreign)).json() == {'items': []}
            assert (await client.post(url, headers=foreign, json=body)).status_code == 404
            stale = await client.post(url, headers=headers, json={**body, 'revision': 999})
            assert stale.status_code == 409
            responses = [await client.post(url, headers=headers, json=body) for _ in range(2)]
            assert [r.status_code for r in responses] == [200, 200]
            values = [r.json() for r in responses]
            assert values[0]['task']['id'] == values[1]['task']['id'] and stub.starts == 1
            assert all(not value['authorized'] for value in values)
            for value in values:
                assert 'payload' not in value['task'] and 'idempotency_key' not in value['task']
    finally:
        await hermes.close()
