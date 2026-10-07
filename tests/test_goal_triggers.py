"""Goal/event continuity with real SQLite and the existing synthetic run adapter."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from wearing.goals import GoalBook, GoalCoordinator
from wearing.life import LifeBook, LifeDraft
from wearing.life_proxy import dispatch
from wearing.schedules import ScheduleBook, ScheduleDraft, ScheduleError
from wearing.store import Store
from test_goals import report
from test_schedules import rig, clock


def watch(goal):
    return ScheduleDraft(title='旅行有新情况再继续', instruction='新记录与旅行有关时，读取最新内容，按原目标调整建议。',
                         kind='life_change', goal_id=goal['id'], changes={'record_kinds':['note','event'], 'debounce_seconds':15, 'cooldown_minutes':1})


def advance(clock, seconds=15):
    clock[0] = (datetime.fromisoformat(clock[0])+timedelta(seconds=seconds)).isoformat()


def linked(rig, monkeypatch, steps=3):
    store, book, service, coordinator, wire, clock = rig
    monkeypatch.setattr('wearing.goals.now', lambda: clock[0])
    goals = book.goals
    goal = goals.create('daily','找安静的假期去处','只研究，不下单','给出有依据的候选',steps)
    goal = goals.control(goal['id'],1,'resume')
    item = book.create('daily',watch(goal),'watch')
    service.context_provider = lambda t: goals.context(t)+book.context(t)
    service.start_guard = lambda t: (goals.guard(t),book.guard(t))
    return goals, goal, item, GoalCoordinator(goals,service)


def note(store, key='new', actor='user'):
    return LifeBook(store).create('daily',LifeDraft(kind='note',title=key,content='假期多了一天，想找适合步行的去处'),key,actor)


async def test_goal_wait_event_restart_shared_budget_and_single_feedback(rig, monkeypatch):
    store, book, service, coordinator, wire, clock = rig
    goals, goal, item, gc = linked(rig,monkeypatch)
    await gc.tick()
    assert len(wire.runs)==1
    assert '"wait_for_changes_available": true' in wire.runs[-1]['instructions']
    wire.status, wire.output='completed',report('已核对当前条件，等新情况', 'wait')
    await service.tick(); await gc.tick()
    assert goals.get(goal['id'])['status']=='waiting'
    assert goals.get(goal['id'])['next_wake'] is None
    record=note(store)
    await coordinator.tick(); advance(clock)
    reopened=ScheduleBook(Store(store.path))
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed=list(pool.map(lambda _: reopened.claim(item['id']),range(4)))
    assert sum(t is not None for t in claimed)==1
    task=next(t for t in claimed if t)
    assert goals.get(goal['id'])['used_steps']==2
    assert goals.step_for(task['id'])['goal_id']==goal['id']
    wire.status='running'
    await coordinator.tick(); await gc.tick()
    assert len(wire.runs)==2
    assert record['id'] in wire.runs[-1]['instructions']
    assert '已核对当前条件' in wire.runs[-1]['instructions']
    assert '只研究，不下单' in wire.runs[-1]['instructions']
    wire.status,wire.output='completed',report('已按多出的一天更新候选','wait')
    await service.tick(); await coordinator.tick(); await gc.tick()
    assert goals.get(goal['id'])['status']=='waiting'
    assert len(goals.detail(goal['id'])['steps'])==2
    assert len(goals.updates('daily')['items'])==2
    assert book.conversation('daily')==[]  # goal path owns the only delivery
    await coordinator.tick(); await gc.tick()
    assert len(wire.runs)==2


async def test_changes_during_running_step_are_retained_until_reconciled(rig,monkeypatch):
    store,book,service,coordinator,wire,clock=rig
    goals,goal,item,gc=linked(rig,monkeypatch)
    await gc.tick()
    note(store); await coordinator.tick(); advance(clock)
    assert book.claim(item['id']) is None
    wire.status,wire.output='completed',report('已有第一轮证据','wait')
    await service.tick(); await gc.tick()
    task=book.claim(item['id'])
    assert task and goals.get(goal['id'])['used_steps']==2


@pytest.mark.parametrize('state',['paused','cancelled','completed','needs_user','needs_review','limited'])
async def test_events_never_restart_non_running_goals(rig,monkeypatch,state):
    store,book,_,coordinator,wire,clock=rig
    goals,goal,item,_=linked(rig,monkeypatch)
    with store.connection() as db:
        db.execute('UPDATE personal_goals SET status=?,next_wake=NULL WHERE id=?',(state,goal['id']))
    note(store); await coordinator.tick(); advance(clock,90); await coordinator.tick()
    assert not wire.runs
    assert goals.get(goal['id'])['status']==state
    assert book.get('daily',item['id'])['next_run'] is None


async def test_pause_resume_and_revision_discard_old_changes(rig,monkeypatch):
    store,book,_,coordinator,wire,clock=rig
    goals,goal,item,gc=linked(rig,monkeypatch)
    note(store); await coordinator.tick()
    await gc.control(goal['id'],'daily',2,'pause')
    note(store,'during-pause')
    await gc.control(goal['id'],'daily',3,'resume')
    advance(clock,90); await coordinator.tick()
    assert not wire.runs
    assert book.get('daily',item['id'])['next_run'] is None
    # Resume may schedule its own goal round; a stale event must not do so.
    new=note(store,'after-resume'); await coordinator.tick(); advance(clock)
    task=book.claim(item['id'])
    assert task and goals.step_for(task['id'])['revision']==4
    context=book.context(task)
    assert new['id'] in context and 'during-pause' not in context


async def test_pause_after_claim_blocks_dispatch_and_preserves_receipt(rig,monkeypatch):
    store,book,service,coordinator,wire,clock=rig
    goals,goal,item,gc=linked(rig,monkeypatch)
    note(store); book.events.collect(clock[0]); advance(clock)
    task=book.claim(item['id'])
    await gc.control(goal['id'],'daily',2,'pause')
    await coordinator.tick(); await gc.tick()
    assert not wire.runs
    assert store.get(task['id'])['status']=='stopped'
    assert goals.get(goal['id'])['used_steps']==1  # never refund ambiguous work
    assert book.get('daily',item['id'])['status']=='active'
    # Resuming the goal must not require separately resuming its watcher.
    paused=goals.get(goal['id'])
    await gc.control(goal['id'],'daily',paused['revision'],'resume')
    note(store,'new-after-interruption'); book.events.collect(clock[0]); advance(clock,61)
    next_task=book.claim(item['id'])
    assert next_task and goals.get(goal['id'])['used_steps']==2


async def test_budget_background_origin_and_expired_event(rig,monkeypatch):
    store,book,_,coordinator,wire,clock=rig
    goals,goal,item,_=linked(rig,monkeypatch,steps=1)
    note(store,'automated',actor='agent'); await coordinator.tick()
    assert book.get('daily',item['id'])['next_run'] is None
    note(store); book.events.collect(clock[0]); advance(clock,3700)
    assert book.claim(item['id']) is None
    assert goals.get(goal['id'])['used_steps']==0
    assert book.get('daily',item['id'])['occurrences'][0]['status']=='skipped'
    with store.connection() as db: db.execute('UPDATE personal_goals SET used_steps=1 WHERE id=?',(goal['id'],))
    note(store,'limit'); await coordinator.tick(); advance(clock); await coordinator.tick()
    assert not wire.runs and goals.get(goal['id'])['used_steps']==1


async def test_goal_ownership_duplicates_and_background_cannot_expand_work(rig,monkeypatch):
    store,book,_,coordinator,wire,clock=rig
    goals,goal,item,gc=linked(rig,monkeypatch)
    other=store.save_identity('别的身份')['id']
    with pytest.raises(ScheduleError): book.create(other,watch(goal),'foreign')
    with pytest.raises(ScheduleError): book.create('daily',watch(goal),'duplicate')
    with pytest.raises(ValidationError): ScheduleDraft(title='invalid',instruction='invalid',kind='cron',cron='* * * * *',goal_id=goal['id'])
    assert dispatch(LifeBook(store),other,'goal_list',{})=={'items':[]}
    assert dispatch(LifeBook(store),'daily','goal_list',{})['items'][0]['id']==goal['id']
    await gc.tick()
    with pytest.raises(ScheduleError): dispatch(LifeBook(store),'daily','schedule_create',{'schedule':watch(goal).model_dump(),'request_key':'background'})
