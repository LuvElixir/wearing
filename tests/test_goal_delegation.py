"""Natural-language handoff persists one bounded goal; fixtures are not model evidence."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import httpx
import pytest
from pydantic import ValidationError
from wearing.config import Settings
from wearing.goals import GoalBook, GoalCoordinator, GoalError
from wearing.hermes import HermesClient
from wearing.life import LifeBook
from wearing.life_proxy import dispatch
from wearing.service import TaskService
from wearing.store import Store
from test_goals import GoalWire, report


def proposal(**changes):
    return dict(objective='研究周末出行方案', boundaries='仅使用合成资料，不购买或预订',
                success_criteria='有来源的阶段结论供用户核对', max_steps=3, start=True, **changes)


@pytest.fixture
def rig(tmp_path):
    store=Store(tmp_path/'wearing.sqlite3');book=GoalBook(store)
    message=store.create_message('交给你持续研究，最多三轮，只用测试资料。')
    store.update(message['id'],status='running',run_id='conversation-run')
    return store,book,message


def test_delegation_commits_original_user_source_and_intent(rig):
    store,book,source=rig
    goal=dispatch(LifeBook(store),'daily','goal_create',{'goal':proposal(),'request_key':'first'})
    assert goal['status']=='active' and goal['used_steps']==0 and goal['max_steps']==3
    assert goal['source_task_id']==source['id'] and len(store.conversation())==1
    reopened=GoalBook(Store(store.path))
    assert reopened.get(goal['id'])==goal
    assert dispatch(LifeBook(store),'daily','goal_list',{'goal_id':goal['id']})['steps']==[]


def test_save_only_does_not_start_or_claim_work(rig):
    store,book,_=rig;spec=proposal();spec.pop('start')
    goal=book.delegate('daily',spec,'saved')
    assert goal['status']=='paused' and goal['next_wake'] is None and book.claim(goal['id']) is None


def test_replay_after_restart_or_pause_never_reactivates(rig):
    store,book,_=rig;goal=book.delegate('daily',proposal(),'retry')
    paused=book.control(goal['id'],1,'pause')
    assert GoalBook(Store(store.path)).delegate('daily',proposal(),'retry')==paused
    # Same turn, model accidentally chooses a new key: still one commitment.
    assert book.delegate('daily',proposal(),'changed-key')['id']==goal['id']
    assert len(book.list('daily'))==1
    with pytest.raises(GoalError,match='另一份约定'):
        book.delegate('daily',{**proposal(),'max_steps':4},'retry')
    assert book.get(goal['id'])==paused


def test_parallel_retries_are_atomic(rig):
    store,book,_=rig
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda n:book.delegate('daily',proposal(),'same'),range(8)))
    assert len({g['id'] for g in results})==1 and len(book.list('daily'))==1


def test_failed_receipt_rolls_back_goal(rig):
    store,book,_=rig
    with store.connection() as db:
        db.execute("CREATE TRIGGER refuse_receipt BEFORE INSERT ON goal_requests BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):book.delegate('daily',proposal(),'fail')
    assert book.list('daily')==[]


@pytest.mark.parametrize('status',['draft','stopping','stopped','waiting_for_approval','ambiguous','connection_lost','completed_unverified'])
def test_absent_or_uncertain_user_run_cannot_delegate(rig,status):
    store,book,source=rig;store.update(source['id'],status=status)
    with pytest.raises(GoalError):book.delegate('daily',proposal(),'no')
    assert book.list('daily')==[]


def test_foreign_identity_and_multiple_runs_cannot_delegate(rig):
    store,book,source=rig;other=store.save_identity('其他身份')['id']
    with pytest.raises(GoalError):book.delegate(other,proposal(),'foreign')
    second=store.create_message('另一条消息',other);store.update(second['id'],status='running')
    with pytest.raises(GoalError):book.delegate('daily',proposal(),'ambiguous')
    store.update(second['id'],status='stopped')
    goal=book.delegate('daily',proposal(),'allowed')
    with pytest.raises(GoalError):dispatch(LifeBook(store),other,'goal_list',{'goal_id':goal['id']})
    assert goal['source_task_id']==source['id']


@pytest.mark.parametrize('kind',['goal','schedule','goal_discussion'])
def test_background_or_existing_goal_discussion_cannot_multiply_work(rig,kind):
    store,book,source=rig;store.update(source['id'],status='completed_unverified')
    if kind=='goal':
        parent=book.create('daily','既有目标','只用测试资料','核对结果',3)
        book.control(parent['id'],1,'resume');task=book.claim(parent['id'])
    elif kind=='goal_discussion':
        parent=book.create('daily','既有目标','只用测试资料','核对结果',3)
        task,_=book.create_message(parent['id'],'daily','继续讨论这个目标')
    else:
        from wearing.schedules import ScheduleBook,ScheduleDraft
        schedules=ScheduleBook(store)
        schedule=schedules.create('daily',ScheduleDraft(title='后台测试',instruction='只用测试资料',kind='once',at='2035-01-01T00:00:00+00:00'),'s')
        task=store.create_message('synthetic anomalous schedule-message link')
        with store.connection() as db:
            db.execute("INSERT INTO schedule_occurrences(schedule_id,revision,due_at,spec,task_id,status,created_at) VALUES(?,1,?,?,?,'running',?)",(schedule['id'],'2035-01-01', '{}',task['id'],'2035-01-01'))
    store.update(task['id'],status='running')
    before=book.list('daily')
    with pytest.raises(GoalError):dispatch(LifeBook(store),'daily','goal_create',{'goal':proposal(),'request_key':'child'})
    assert book.list('daily')==before


@pytest.mark.parametrize('change',[{'start':'true'},{'max_steps':True},{'max_steps':1001},{'objective':' '},{'identity_id':'other'},{'source_task_id':'forged'}])
def test_tool_intent_is_strict_and_cannot_forge_provenance(rig,change):
    _,book,_=rig
    with pytest.raises(ValidationError):book.delegate('daily',{**proposal(),**change},'invalid')
    assert book.list('daily')==[]


async def test_handoff_waits_for_chat_then_delivers_once_through_existing_coordinator(rig):
    store,book,source=rig;wire=GoalWire();client=HermesClient(Settings(store.path.parent,hermes_key='fixture'),httpx.MockTransport(wire))
    service=TaskService(store,client);service.context_provider,service.start_guard=book.context,book.guard
    coordinator=GoalCoordinator(book,service)
    try:
        goal=book.delegate('daily',proposal(),'handoff')
        await coordinator.tick();assert not wire.runs
        store.update(source['id'],status='completed_unverified',output='已保存并安排推进')
        await coordinator.tick();assert len(wire.runs)==1
        assert 'source_conversation' in wire.runs[0]['instructions'] and source['prompt'] in wire.runs[0]['instructions']
        wire.status='completed';wire.output=report(decision='review')
        await service.tick();await coordinator.tick();await coordinator.tick()
        assert book.get(goal['id'])['status']=='needs_review'
        assert book.get(goal['id'])['used_steps']==1
        assert len(book.detail(goal['id'])['steps'])==1 and book.updates('daily')['unread']==1
        assert len(wire.runs)==1 and len(store.conversation())==1
    finally:await client.close()


def test_model_receives_only_kind_specific_fields_without_mutating_records(rig):
    store,_,_=rig;life=LifeBook(store)
    note=dispatch(life,'daily','life_create',{'record':{'kind':'note','title':'想法','content':'泉州两天'},'request_key':'note'})
    task=dispatch(life,'daily','life_create',{'record':{'kind':'task','title':'核对资料'},'request_key':'task'})
    event=dispatch(life,'daily','life_create',{'record':{'kind':'event','title':'查看方案','start_at':'2035-01-01T10:00:00+08:00','end_at':'2035-01-01T11:00:00+08:00'},'request_key':'event'})
    assert 'list_name' not in note and 'start_at' not in note and 'completed' not in note
    assert 'list_name' in task and 'completed' in task and 'start_at' not in task
    assert 'start_at' in event and 'list_name' not in event
    original=life.get('daily',note['id'])
    assert original['list_name']=='待办'  # Canonical client data stays compatible.
    detail=dispatch(life,'daily','life_records',{'record_id':note['id']})
    assert detail==note
    snapshot=dispatch(life,'daily','life_records',{})
    assert next(i for i in snapshot['items'] if i['id']==note['id'])==note
    changed=dispatch(life,'daily','life_change',{'record_id':note['id'],'revision':1,'action':'edit','patch':{'content':'泉州三天'}})
    assert changed['content']=='泉州三天' and changed['revision']==2 and 'list_name' not in changed
    assert life.get('daily',note['id'])['list_name']=='待办'
