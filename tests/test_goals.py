"""Goal lifecycle contract tests. Fixtures are not real-world task evidence."""

import asyncio
import json

import httpx
import pytest

from wearing.app import create_app
from wearing.config import Settings
from wearing.goals import GoalBook, GoalCoordinator, GoalError, parse_report
from wearing.hermes import HermesClient
from wearing.service import TaskError, TaskService
from wearing.store import Store


def report(summary="已确认一个输入条件", decision="continue", **changes):
    return json.dumps({"summary": summary, "evidence": [{"observation": "输入条件来自测试样本", "source": "contract-test fixture"}],
                       "unknowns": ["下一项条件待验证"], "next_step": "检查下一项条件", "decision": decision,
                       "wait_seconds": 0, **changes}, ensure_ascii=False)


class GoalWire:
    def __init__(self):
        self.runs = []
        self.output = report()
        self.status = "running"
        self.offline = False
        self.uncertain = False
        self.stops = 0
        self.start_entered = None
        self.start_release = None

    async def __call__(self, request):
        if request.url.path.endswith("capabilities"):
            if self.offline:
                raise httpx.ConnectError("fixture offline", request=request)
            return httpx.Response(200, json={"features": {}})
        if request.method == "POST" and request.url.path.endswith("/runs"):
            self.runs.append(json.loads(request.content))
            if self.start_entered is not None:
                self.start_entered.set()
                await self.start_release.wait()
            if self.uncertain:
                raise httpx.ReadTimeout("fixture uncertain acceptance", request=request)
            return httpx.Response(202, json={"run_id": f"run-{len(self.runs)}"})
        if request.url.path.endswith("/stop"):
            self.stops += 1
            return httpx.Response(200, json={"status": "stopping"})
        return httpx.Response(200, json={"status": self.status, "output": self.output, "usage": {"input_tokens": 11, "output_tokens": 7}})


@pytest.fixture
async def rig(tmp_path):
    wire = GoalWire()
    settings = Settings(tmp_path, hermes_key="test-key")
    client = HermesClient(settings, httpx.MockTransport(wire))
    store = Store(tmp_path / "test.sqlite3")
    book = GoalBook(store)
    service = TaskService(store, client)
    service.context_provider, service.start_guard = book.context, book.guard
    coordinator = GoalCoordinator(book, service)
    yield store, book, service, coordinator, wire
    await client.close()


def create(book, identity="daily", max_steps=3):
    return book.create(identity, "验证一个路径还不确定的方向", "只处理测试资料", "有来源的阶段结论", max_steps)


async def activate(book, coordinator, goal):
    return await coordinator.control(goal["id"], goal["identity_id"], goal["revision"], "resume")


def due(store, goal):
    with store.connection() as db:
        db.execute("UPDATE personal_goals SET next_wake='2000-01-01T00:00:00+00:00' WHERE id=?", (goal["id"],))


async def test_goal_created_without_running_until_explicit_resume(rig):
    store, book, service, coordinator, wire = rig
    goal = create(book)
    await coordinator.tick()
    assert wire.runs == []
    await activate(book, coordinator, goal)
    await coordinator.tick()
    assert len(wire.runs) == 1
    assert book.get(goal["id"])["used_steps"] == 1
    assert "只处理测试资料" in wire.runs[0]["instructions"]
    assert '"current_round": 1' in wire.runs[0]["instructions"]
    assert '"previous_steps": []' in wire.runs[0]["instructions"]
    assert store.conversation() == []  # A wake is never forged as a user message.


async def test_background_continuation_stops_at_persistent_limit(rig):
    store, book, service, coordinator, wire = rig
    goal = create(book, max_steps=2)
    await activate(book, coordinator, goal)
    await coordinator.tick()
    wire.status = "completed"
    await service.tick()
    await coordinator.tick()
    assert book.get(goal["id"])["status"] == "active"
    assert len(wire.runs) == 1  # The next wake is delayed, not a busy loop.
    due(store, goal)
    await coordinator.tick()
    wire.output = report("第二项条件有新证据")
    await service.tick()
    await coordinator.tick()
    result = book.get(goal["id"])
    assert result["status"] == "limited"
    assert result["used_steps"] == 2
    await coordinator.tick()
    assert len(wire.runs) == 2
    assert '"current_round": 2' in wire.runs[1]["instructions"]
    assert "已确认一个输入条件" in wire.runs[1]["instructions"]
    with pytest.raises(GoalError, match="轮次"):
        await coordinator.control(goal["id"], "daily", result["revision"], "resume")
    result = await coordinator.control(goal["id"], "daily", result["revision"], "resume", add_steps=1)
    assert (result["used_steps"], result["max_steps"]) == (2, 3)


async def test_pause_cancels_future_work_but_waits_for_remote_stop(rig):
    store, book, service, coordinator, wire = rig
    goal = create(book)
    goal = await activate(book, coordinator, goal)
    await coordinator.tick()
    await coordinator.control(goal["id"], "daily", goal["revision"], "pause")
    task = store.list()[0]
    assert task["status"] == "stopping"
    assert wire.stops == 1
    wire.status = "completed"  # Late success cannot revive a paused goal.
    await service.tick()
    await coordinator.tick()
    assert book.get(goal["id"])["status"] == "paused"
    assert book.detail(goal["id"])["steps"][0]["report"]
    assert len(wire.runs) == 1


async def test_change_direction_invalidates_old_next_step_and_keeps_user_words(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    await coordinator.tick()
    await coordinator.control(goal["id"], "daily", goal["revision"], "note", "改成只考虑数字服务")
    wire.status = "completed"
    wire.output = report(next_step="继续采购实体货物")
    await service.tick()
    await coordinator.tick()
    assert len(wire.runs) == 2
    assert "采购实体货物" not in wire.runs[1]["input"]
    assert "改成只考虑数字服务" in wire.runs[1]["instructions"]
    assert wire.runs[1]["session_id"] != wire.runs[0]["session_id"]
    # The current revision is also supplied to a new ordinary chat/session.
    msg = store.create_message("我刚刚改了什么方向？")
    assert "改成只考虑数字服务" in book.context(msg)


async def test_restart_preserves_goal_and_queries_original_run_without_resend(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    await coordinator.tick()
    reopened = Store(store.path)
    newbook = GoalBook(reopened)
    newservice = TaskService(reopened, service.hermes)
    newservice.start_guard, newservice.context_provider = newbook.guard, newbook.context
    restarted = GoalCoordinator(newbook, newservice)
    newservice.recover_startup()
    await restarted.tick()
    assert len(wire.runs) == 1
    wire.status = "completed"
    await newservice.tick()
    await restarted.tick()
    assert newbook.get(goal["id"])["used_steps"] == 1
    assert newbook.detail(goal["id"])["steps"][0]["report"]


async def test_offline_before_send_reuses_reserved_step_after_backoff(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book, max_steps=1))
    wire.offline = True
    await coordinator.tick()
    assert wire.runs == []
    assert book.get(goal["id"])["used_steps"] == 1
    wire.offline = False
    await coordinator.tick()
    assert wire.runs == []
    due(store, goal)
    await coordinator.tick()
    assert len(wire.runs) == 1
    assert book.get(goal["id"])["used_steps"] == 1


async def test_uncertain_acceptance_never_replays_or_starts_next_step(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    wire.uncertain = True
    await coordinator.tick()
    await coordinator.tick()
    assert store.list()[0]["status"] == "ambiguous"
    assert len(wire.runs) == 1
    with pytest.raises(GoalError, match="原运行"):
        await coordinator.control(goal["id"], "daily", goal["revision"], "resume")


@pytest.mark.parametrize("output,status", [
    ("普通文字，没有可信的下一步结构", "needs_user"),
    (report(decision="review"), "needs_review"),
    (report(evidence=[]), "needs_user"),
    (report(decision="wait", wait_seconds=0), "needs_user"),
    (report(decision="wait", wait_seconds=3600), "waiting"),
    (report(decision="needs_user"), "needs_user"),
])
async def test_report_failure_and_model_completion_do_not_imply_verified_success(rig, output, status):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    await coordinator.tick()
    wire.status, wire.output = "completed", output
    await service.tick()
    await coordinator.tick()
    assert book.get(goal["id"])["status"] == status
    assert store.list()[0]["status"] == "completed_unverified"
    assert store.list()[0]["verified_at"] is None
    assert len(wire.runs) == 1


async def test_no_progress_stops_instead_of_looping(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    await coordinator.tick()
    wire.status = "completed"
    await service.tick()
    await coordinator.tick()
    due(store, goal)
    await coordinator.tick()
    await service.tick()
    await coordinator.tick()
    assert book.get(goal["id"])["status"] == "needs_user"
    assert "没有报告新的进展" in book.get(goal["id"])["reason"]


async def test_pending_human_message_preempts_background_goal(rig):
    store, book, service, coordinator, wire = rig
    await activate(book, coordinator, create(book))
    blocker = store.create("正在处理的测试任务", "computer")
    store.update(blocker["id"], status="running", run_id="fixture-running")
    response = await service.submit_message("先等等，我还有话说", "daily")
    assert response["delivery"] == "queued"
    store.update(blocker["id"], status="stopped")
    await coordinator.tick()
    assert len(wire.runs) == 1 and wire.runs[0]["input"] == "先等等，我还有话说"


async def test_duplicate_ticks_and_receipts_do_not_duplicate_steps(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    await asyncio.gather(coordinator.tick(), coordinator.tick(), coordinator.tick())
    assert len(wire.runs) == 1
    wire.status = "completed"
    await service.tick()
    book.reconcile()
    first = book.get(goal["id"])
    book.reconcile()
    assert book.get(goal["id"]) == first


async def test_manual_task_start_cannot_bypass_goal_pause(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    task = book.claim(goal["id"])
    book.control(goal["id"], goal["revision"], "pause")
    with pytest.raises(TaskError, match="暂停"):
        await service.start(task["id"])
    assert wire.runs == []


async def test_identity_scope_and_stale_revision(rig):
    store, book, service, coordinator, wire = rig
    other = store.save_identity("出海")
    goal = create(book)
    with pytest.raises(GoalError):
        book.detail(goal["id"], other["id"])
    assert book.context(store.create_message("hello", other["id"])) == ""
    await activate(book, coordinator, goal)
    with pytest.raises(GoalError, match="新变化"):
        await coordinator.control(goal["id"], "daily", goal["revision"], "cancel")


async def test_only_user_confirmation_completes_goal_and_cancellation_is_terminal(rig):
    store, book, service, coordinator, wire = rig
    goal = create(book)
    confirmed = await coordinator.control(goal["id"], "daily", goal["revision"], "complete", "已在外部核对目标结果")
    assert confirmed["status"] == "completed"
    assert book.detail(goal["id"])["notes"][-1]["kind"] == "verified_by_user"
    cancelled = create(book)
    cancelled = await coordinator.control(cancelled["id"], "daily", cancelled["revision"], "cancel")
    with pytest.raises(GoalError, match="已经结束"):
        await activate(book, coordinator, cancelled)


def test_report_schema_rejects_authority_changes_and_excessive_waits():
    assert parse_report(report(max_steps=999)) is None
    assert parse_report(report(wait_seconds=999999999)) is None
    assert parse_report(report(decision="complete")) is None


async def test_api_scoping_csrf_and_conversation_receipts(tmp_path):
    wire = GoalWire()
    settings = Settings(tmp_path, hermes_key="test-key")
    hermes = HermesClient(settings, httpx.MockTransport(wire))
    app = create_app(settings, hermes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        data = {"objective": "测试持续目标", "boundaries": "仅使用测试数据", "success_criteria": "有真实测试记录", "max_steps": 2}
        assert (await client.post("/api/goals", json=data)).status_code == 403
        client.headers["X-Wearing-Token"] = (await client.get("/api/bootstrap")).json()["token"]
        assert (await client.post("/api/goals", json={**data, "boundaries": " "})).status_code == 422
        assert (await client.post("/api/goals", json={**data, "max_steps": 1001})).status_code == 422
        goal = (await client.post("/api/goals", json=data)).json()
        other = app.state.store.save_identity("别的身份")
        for path in [f'/api/goals/{goal["id"]}', "/api/goals"]:
            response = await client.get(path, headers={"X-Wearing-Identity": other["id"]})
            assert "测试持续目标" not in response.text
        response = await client.post(f'/api/goals/{goal["id"]}/control', headers={"X-Wearing-Identity": other["id"]}, json={"revision": 1, "action": "resume"})
        assert response.status_code == 409
        response = await client.post(f'/api/goals/{goal["id"]}/control', json={"revision": 1, "action": "pause", "add_steps": 1})
        assert response.status_code == 422
        await client.post(f'/api/goals/{goal["id"]}/control', json={"revision": 1, "action": "resume"})
        await app.state.goal_coordinator.tick()
        wire.status, wire.output = "completed", report(decision="review")
        await app.state.service.tick()
        await app.state.goal_coordinator.tick()
        messages = (await client.get("/api/conversation")).json()
        assert messages[0]["kind"] == "goal_step"
        assert messages[0]["turn"]["output"].startswith("已确认一个输入条件")
        assert '"decision"' not in messages[0]["turn"]["output"]
        assert "payload" not in messages[0]["turn"]
        assert (await client.get("/api/conversation", headers={"X-Wearing-Identity": other["id"]})).json() == []
    await hermes.close()


async def test_separate_service_instances_cannot_double_dispatch_same_or_different_tasks(rig):
    store, book, service, coordinator, wire = rig
    second_service = TaskService(store, service.hermes)
    first = store.create('一个独立请求', 'computer')
    second = store.create('另一个独立请求', 'computer')
    results = await asyncio.gather(service.start(first['id']), second_service.start(second['id']), return_exceptions=True)
    assert len(wire.runs) == 1
    assert sum(isinstance(result, TaskError) for result in results) == 1
    with pytest.raises(TaskError):
        await second_service.start(first['id'])
    assert len(wire.runs) == 1


async def test_goal_discussion_is_linked_but_does_not_change_the_goal(rig):
    store, book, service, coordinator, wire = rig
    goal = create(book)
    task, returned = await coordinator.message(goal['id'], 'daily', '目前有哪些未知？')
    assert returned == goal
    assert book.detail(goal['id'])['notes'] == []
    assert book.message_for(task['id'])['mode'] == 'discuss'
    await service.start(task['id'])
    assert '这是讨论，没有修改' in wire.runs[0]['instructions']
    assert store.conversation()[0]['content'] == '目前有哪些未知？'


async def test_goal_correction_and_message_are_atomic_and_invalidate_old_work(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    await coordinator.tick()
    original = store.list()[0]
    task, revised = await coordinator.message(goal['id'], 'daily', '先不做实体商品，考虑数字服务。', 'note', goal['revision'])
    assert revised['revision'] == goal['revision'] + 1
    assert revised['used_steps'] == 1
    assert book.detail(goal['id'])['notes'][-1]['content'] == task['prompt']
    assert wire.stops == 1
    assert store.get(original['id'])['status'] == 'stopping'
    assert book.message_for(task['id'])['queued']
    assert len(store.conversation()) == 1
    with pytest.raises(GoalError, match='新变化'):
        await coordinator.message(goal['id'], 'daily', '过期的更改不能写入', 'note', goal['revision'])
    assert len(store.conversation()) == 1
    assert len(book.detail(goal['id'])['notes']) == 1
    # The correction and message are one transaction, including insert failure.
    real_insert = store.insert_message
    def broken_insert(*args):
        raise RuntimeError('fixture write failure')
    store.insert_message = broken_insert
    with pytest.raises(RuntimeError):
        await coordinator.message(goal['id'], 'daily', '本条应回滚', 'note', revised['revision'])
    store.insert_message = real_insert
    assert book.get(goal['id'])['revision'] == revised['revision']
    assert len(book.detail(goal['id'])['notes']) == 1


async def test_explicit_queued_reply_recovers_and_never_resends(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    await coordinator.tick()
    task, _ = await coordinator.message(goal['id'], 'daily', '这条请等当前步骤结束再回答。')
    assert book.message_for(task['id'])['queued'] == 1
    await coordinator.tick()
    assert len(wire.runs) == 1
    wire.status = 'completed'
    await service.tick()
    recovered = GoalCoordinator(GoalBook(store), service)
    await recovered.tick()
    assert len(wire.runs) == 2
    assert wire.runs[-1]['input'] == task['prompt']
    assert book.message_for(task['id'])['queued'] == 0
    await recovered.tick()
    assert len(wire.runs) == 2


async def test_goal_discussion_saved_offline_does_not_auto_send_after_connection(rig):
    store, book, service, coordinator, wire = rig
    goal = create(book)
    task, _ = await coordinator.message(goal['id'], 'daily', '离线消息先保留')
    wire.offline = True
    with pytest.raises(TaskError):
        await service.start(task['id'])
    wire.offline = False
    await coordinator.tick()
    assert wire.runs == []
    assert book.message_for(task['id'])['queued'] == 0


async def test_ended_goals_allow_discussion_but_not_correction_or_cross_identity(rig):
    store, book, service, coordinator, wire = rig
    goal = create(book)
    ended = await coordinator.control(goal['id'], 'daily', goal['revision'], 'cancel')
    task, _ = await coordinator.message(goal['id'], 'daily', '回顾当时的判断')
    assert book.get(goal['id']) == ended
    with pytest.raises(GoalError, match='结束'):
        await coordinator.message(goal['id'], 'daily', '旧目标不能复活', 'note', ended['revision'])
    other = store.save_identity('别的身份')
    with pytest.raises(GoalError):
        await coordinator.message(goal['id'], other['id'], '不能跨身份关联')
    assert len(store.conversation()) == 1


async def test_goal_message_api_scopes_revision_validation_and_cancel_queue(tmp_path):
    wire = GoalWire()
    settings = Settings(tmp_path, hermes_key='test-key')
    engine = HermesClient(settings, httpx.MockTransport(wire))
    app = create_app(settings, engine)
    # Replace managed runtime resolver with the protocol fixture for this test.
    app.state.service.client_resolver = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as c:
        token = (await c.get('/api/bootstrap')).json()['token']
        headers = {'X-Wearing-Token': token}
        g = (await c.post('/api/goals', headers=headers, json={'objective':'测试目标关联', 'boundaries':'测试资料', 'success_criteria':'可核对输入'})).json()
        bad = await c.post('/api/conversation', headers=headers, json={'content':'这是一条补充', 'goal_mode':'note'})
        assert bad.status_code == 422
        bad = await c.post('/api/conversation', headers=headers, json={'content':'目标更新缺少修订号', 'goal_id':g['id'], 'goal_mode':'note'})
        assert bad.status_code == 422
        await c.post(f"/api/goals/{g['id']}/control", headers=headers, json={'revision':g['revision'], 'action':'resume'})
        await app.state.goal_coordinator.tick()
        response = await c.post('/api/conversation', headers=headers, json={'content':'看看这件事如何继续', 'goal_id':g['id']})
        assert response.status_code == 201
        assert response.json()['delivery'] == 'queued'
        task_id = response.json()['task']['id']
        messages = (await c.get('/api/conversation')).json()
        linked = next(m for m in messages if m['task_id'] == task_id)
        assert linked['goal_mode'] == 'discuss'
        assert linked['goal_title'] == g['objective']
        other = app.state.store.save_identity('国外场景')
        cross = await c.post('/api/conversation', headers={**headers,'X-Wearing-Identity':other['id']}, json={'content':'不能跨身份', 'goal_id':g['id']})
        assert cross.status_code == 409
        forbidden = await c.post(f'/api/tasks/{task_id}/cancel-message', json={})
        assert forbidden.status_code == 403
        cancelled = await c.post(f'/api/tasks/{task_id}/cancel-message', headers=headers, json={})
        assert cancelled.status_code == 200
        assert cancelled.json()['status'] == 'stopped'
        assert app.state.goals.message_for(task_id)['queued'] == 0
        assert (await c.post(f'/api/tasks/{task_id}/cancel-message', headers=headers, json={})).status_code == 409
    await engine.close()


async def test_goal_conversion_keeps_source_conversation_in_execution_context(rig):
    store, book, service, coordinator, wire = rig
    source = store.create_message('我还没有具体路径，想先验证数字服务。')
    store.update(source['id'], status='completed_unverified', output='固定测试回复：先核对用户需求。')
    goal = book.create('daily', '验证数字服务方向', '只做测试研究', '给出阶段证据', 1, source['id'])
    await activate(book, coordinator, goal)
    await coordinator.tick()
    instructions = wire.runs[0]['instructions']
    assert 'source_conversation' in instructions
    assert source['prompt'] in instructions
    assert '固定测试回复：先核对用户需求。' in instructions
    assert 'completed_unverified' in instructions
    assert len(store.conversation('daily')) == 1  # No synthetic user message.
    other = store.save_identity('来源隔离测试')
    with pytest.raises(GoalError):
        book.create(other['id'], '不允许跨身份引用', '测试范围', '可核对', 1, source['id'])


async def test_correction_during_remote_submission_stops_the_late_old_run(rig):
    store, book, service, coordinator, wire = rig
    goal = await activate(book, coordinator, create(book))
    wire.start_entered, wire.start_release = asyncio.Event(), asyncio.Event()
    dispatch = asyncio.create_task(coordinator.tick())
    await wire.start_entered.wait()
    # The worker holds the coordinator lock during this POST. Direct book
    # correction reproduces a separate process/API transaction at that point.
    message, updated = book.create_message(goal['id'], 'daily', '新情况：改沿数字服务研究。', 'note', goal['revision'])
    assert updated['revision'] == goal['revision'] + 1
    assert book.message_for(message['id'])['queued'] == 1
    wire.start_release.set()
    await dispatch
    old = book.detail(goal['id'])['steps'][0]
    assert store.get(old['task_id'])['status'] == 'running'
    await coordinator.tick()
    assert wire.stops == 1
    assert store.get(old['task_id'])['status'] == 'stopping'
    await coordinator.tick()
    assert wire.stops == 1  # No repeated stop while awaiting confirmation.
    wire.status = 'cancelled'
    await service.tick()
    await coordinator.tick()
    assert len(wire.runs) == 2
    assert store.get(message['id'])['status'] == 'running'
    assert book.get(goal['id'])['revision'] == updated['revision']
