"""Synthetic account provenance -> recurring task -> native queue integration.

No OS operation, customer account or cloud resource is read or modified.
"""
import asyncio
import sqlite3

import httpx
import pytest

from wearing import background_principals as principals
from wearing.app import create_app
from wearing.cloud.worker import TenantBoundary
from wearing.config import Settings
from wearing.goals import GoalBook, GoalError
from wearing.hermes import HermesClient
from wearing.life import LifeBook, LifeDraft
from wearing.life_proxy import dispatch
from wearing.native_actions import NativeActions, NativeActionError
from wearing.native_actions_tools import dispatch as native_dispatch
from wearing.schedules import ScheduleBook, ScheduleDraft, ScheduleError
from wearing.service import ACTIVE, TaskService
from wearing.store import Store
from test_goals import GoalWire, report

A, B = 'a'*64, 'b'*64
PHONE_A, PHONE_B, SECRET, CONNECTION = 'c'*32, 'd'*32, 'e'*64, 'f'*32
STAMP = '2026-10-08T00:00:00+00:00'
INTENT = dict(objective='核对系统日历', boundaries='只读取合成数据', success_criteria='收到核对结果', max_steps=3)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = [STAMP]
    monkeypatch.setattr('wearing.goals.now', lambda: clock[0])
    monkeypatch.setattr('wearing.schedules.now', lambda: clock[0])
    store = Store(tmp_path/'synthetic.sqlite3')
    schedules = ScheduleBook(store)
    return store, schedules.goals, schedules, clock


def user_turn(store, owner=A):
    task, _ = store.accept_message('请持续核对测试日历', 'daily', None, ACTIVE, owner_scope=owner)
    store.update(task['id'], status='running', run_id='synthetic-user-run-'+task['id'])
    return store.get(task['id'])


def principal(store, kind, source_id):
    with store.connection() as db:
        return principals.owner(db, kind, source_id)


def task_principal(store, task):
    with store.connection() as db:
        return principals.task_owner(db, task['id'], task['identity_id'])


def schedule(**patch):
    return ScheduleDraft(title='核对系统日历', instruction='只读取合成数据并返回核对结果', kind='cron', cron='5 * * * *', timezone='UTC', **patch)


def phone_book(store):
    book = NativeActions(store, require_task_owner=True)
    for phone, owner in ((PHONE_A, A), (PHONE_B, B)):
        book.configure('daily', phone, SECRET, 0, True, {'reminders':[{'id':'synthetic-list','title':'Synthetic list','writable':False}]}, owner_scope=owner)
        book.connect('daily', phone, SECRET, 1, CONNECTION, ['reminders.read'], owner_scope=owner)
    return book


async def assert_native_turn(store, task):
    wire = GoalWire()
    client = HermesClient(Settings(store.path.parent, hermes_key='synthetic'), httpx.MockTransport(wire))
    try:
        running = await TaskService(store, client).start(task['id'])
        assert running['status'] == 'running' and running['run_id'] == 'run-1'
        book = phone_book(store)
        found = await native_dispatch(store, 'daily', 'native_devices', {})
        assert [v['installation_id'] for v in found['items']] == [PHONE_A]
        with pytest.raises(NativeActionError):
            book.request('daily', PHONE_B, 'reminders.read', {'calendar_ids':['synthetic-list']}, 'foreign')
        pending = asyncio.create_task(native_dispatch(store, 'daily', 'native_request', {
            'installation_id':PHONE_A, 'method':'reminders.read', 'params':{'calendar_ids':['synthetic-list']}, 'request_key':'background-read'}))
        for _ in range(100):
            rows = book.history('daily', PHONE_A, SECRET, owner_scope=A)['items']
            if rows: break
            await asyncio.sleep(.001)
        assert rows and rows[0]['task_id'] == running['id'] and rows[0]['run_id'] == running['run_id']
        command = rows[0]
        book.claim('daily', PHONE_A, SECRET, CONNECTION, command['id'], command['fingerprint'], True, owner_scope=A)
        book.finish('daily', PHONE_A, SECRET, CONNECTION, command['id'], command['fingerprint'],
                    {'status':'succeeded','code':'ok','data':{'items':[],'returned':0,'has_more':False,'text_may_be_truncated':False}}, owner_scope=A)
        result = await asyncio.wait_for(pending, 2)
        assert result['state'] == 'succeeded'
        assert result['task_id'] == running['id'] and result['run_id'] == running['run_id']
        return running
    finally:
        await client.close()


async def test_mcp_goal_provenance_survives_restart_and_later_native_run(rig):
    store, goals, _, _ = rig
    source = user_turn(store)
    goal = dispatch(LifeBook(store), 'daily', 'goal_create', {'goal':{**INTENT,'start':True},'request_key':'goal-delegation'})
    assert principal(store, 'goal', goal['id']) == A
    assert goal['source_task_id'] == source['id']
    store.update(source['id'], status='completed_unverified')
    reopened = GoalBook(Store(store.path))
    task = reopened.claim(goal['id'])
    assert task_principal(store, task) == A
    running = await assert_native_turn(store, task)
    store.update(running['id'], status='completed_unverified', output=report())
    reopened.reconcile()
    with store.connection() as db:
        db.execute("UPDATE personal_goals SET next_wake=? WHERE id=?", (STAMP, goal['id']))
    next_task = GoalBook(Store(store.path)).claim(goal['id'])
    assert next_task['id'] != task['id'] and task_principal(store, next_task) == A


async def test_mcp_schedule_provenance_survives_restart_and_next_occurrence(rig):
    store, _, schedules, clock = rig
    source = user_turn(store)
    item = dispatch(LifeBook(store), 'daily', 'schedule_create', {'schedule':schedule().model_dump(),'request_key':'scheduled-read'})
    assert principal(store, 'schedule', item['id']) == A
    with store.connection() as db:
        assert db.execute("SELECT source_task_id FROM background_principals WHERE kind='schedule'").fetchone()[0] == source['id']
    store.update(source['id'], status='completed_unverified')
    clock[0] = '2026-10-08T00:05:00+00:00'
    reopened = ScheduleBook(Store(store.path))
    task = reopened.claim(item['id'])
    assert task_principal(store, task) == A
    running = await assert_native_turn(store, task)
    store.update(running['id'], status='completed_unverified', output='[SILENT]')
    reopened.reconcile()
    clock[0] = '2026-10-08T01:05:00+00:00'
    next_task = ScheduleBook(Store(store.path)).claim(item['id'])
    assert next_task['id'] != task['id'] and task_principal(store, next_task) == A


@pytest.mark.parametrize('kind', ['goal','schedule'])
def test_legacy_resume_does_not_adopt_current_account_or_phone(rig, kind):
    store, goals, schedules, clock = rig
    if kind == 'goal':
        item = goals.create('daily', **INTENT)
        goals.control(item['id'], 1, 'resume', owner_scope=A)
        task = goals.claim(item['id'])
    else:
        item = schedules.create('daily', schedule(), 'legacy')
        schedules.change('daily', item['id'], 1, 'pause', owner_scope=A)
        schedules.change('daily', item['id'], 2, 'resume', owner_scope=A)
        clock[0] = '2026-10-08T00:05:00+00:00'
        task = schedules.claim(item['id'])
    assert principal(store, kind, item['id']) is None and task_principal(store, task) is None
    store.update(task['id'], status='running', run_id='unowned-run')
    book = phone_book(store)
    with pytest.raises(NativeActionError): book.task_owner('daily')
    with pytest.raises(NativeActionError): book.request('daily', PHONE_A, 'reminders.read', {'calendar_ids':['synthetic-list']}, 'legacy-read')


def test_other_account_cannot_replay_edit_enable_or_message_owned_commitments(rig):
    store, goals, schedules, _ = rig
    goal = goals.create('daily', **INTENT, request_key='create-goal-123456', owner_scope=A)
    item = schedules.create('daily', schedule(), 'create-schedule', owner_scope=A)
    for owner in (B, None):
        with pytest.raises(GoalError): goals.create('daily', **INTENT, request_key='create-goal-123456', owner_scope=owner)
        with pytest.raises(GoalError): goals.control(goal['id'], 1, 'resume', owner_scope=owner)
        with pytest.raises(GoalError): goals.create_message(goal['id'], 'daily', '改成新目标', 'note', 1, owner_scope=owner)
        with pytest.raises(ScheduleError): schedules.create('daily', schedule(), 'create-schedule', owner_scope=owner)
        with pytest.raises(ScheduleError): schedules.change('daily', item['id'], 1, 'edit', schedule().model_copy(update={'instruction':'changed'}), owner_scope=owner)
        with pytest.raises(ScheduleError): schedules.change('daily', item['id'], 1, 'pause', owner_scope=owner)
    assert goals.get(goal['id'])['revision'] == schedules.get('daily', item['id'])['revision'] == 1
    message, _ = goals.create_message(goal['id'], 'daily', '继续讨论', owner_scope=A)
    assert task_principal(store, message) == A


def test_foreign_user_mcp_cannot_change_or_replay_owned_goal_and_schedule(rig):
    store, goals, schedules, _ = rig
    a = user_turn(store)
    goal = goals.delegate('daily', INTENT, 'tool-goal')
    item = dispatch(LifeBook(store), 'daily', 'schedule_create', {'schedule':schedule().model_dump(),'request_key':'tool-schedule'})
    store.update(a['id'], status='completed_unverified')
    user_turn(store, B)
    with pytest.raises(GoalError): goals.delegate('daily', INTENT, 'tool-goal')
    with pytest.raises(GoalError): goals.conversational_change('daily', {'goal_id':goal['id'],'revision':1,'action':'resume','request_key':'resume'})
    with pytest.raises(ScheduleError): dispatch(LifeBook(store), 'daily', 'schedule_create', {'schedule':schedule().model_dump(),'request_key':'tool-schedule'})
    with pytest.raises(ScheduleError): dispatch(LifeBook(store), 'daily', 'schedule_change', {'schedule_id':item['id'],'revision':1,'action':'pause'})


def test_source_task_must_still_be_current_at_commit_and_never_be_foreign(rig):
    store, goals, schedules, _ = rig
    source = user_turn(store)
    with pytest.raises(GoalError): goals.create('daily', **INTENT, source_task_id=source['id'], owner_scope=B)
    store.update(source['id'], status='completed_unverified')
    user_turn(store, B)
    with pytest.raises(ScheduleError): schedules.create('daily', schedule(), 'late-call', source_task_id=source['id'])
    assert not schedules.list('daily') and not goals.list('daily')


def test_linked_goal_schedule_requires_same_provenance_and_child_keeps_it(rig):
    store, goals, schedules, clock = rig
    goal = goals.create('daily', **INTENT, owner_scope=A)
    goals.control(goal['id'], 1, 'resume', owner_scope=A)
    watch = ScheduleDraft(title='记录变化时核对', instruction='核对新记录', kind='life_change', changes={'record_kinds':['note'],'debounce_seconds':15}, goal_id=goal['id'])
    for owner in (None, B):
        with pytest.raises(ScheduleError): schedules.create('daily', watch, 'foreign-watch', owner_scope=owner)
    item = schedules.create('daily', watch, 'own-watch', owner_scope=A)
    LifeBook(store).create('daily', LifeDraft(kind='note',title='合成变化'), 'change')
    schedules.events.collect(STAMP)
    clock[0] = '2026-10-08T00:00:16+00:00'
    task = schedules.claim(item['id'])
    assert task is not None and task_principal(store, task) == A
    assert goals.step_for(task['id'])['goal_id'] == goal['id']


def test_principal_write_failure_rolls_back_commitment_and_reserved_task(rig):
    store, goals, _, _ = rig
    with store.connection() as db:
        db.execute("CREATE TRIGGER reject_principal BEFORE INSERT ON background_principals BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError): goals.create('daily', **INTENT, owner_scope=A)
    assert not goals.list('daily')
    with store.connection() as db: db.execute('DROP TRIGGER reject_principal')
    goal = goals.create('daily', **INTENT, owner_scope=A)
    goals.control(goal['id'], 1, 'resume', owner_scope=A)
    with store.connection() as db:
        db.execute("CREATE TRIGGER reject_task_principal BEFORE INSERT ON task_principals BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError): goals.claim(goal['id'])
    assert not store.list() and goals.get(goal['id'])['used_steps'] == 0


async def test_actual_cloud_api_uses_gateway_owner_not_body_or_current_phone(tmp_path):
    app = create_app(Settings(tmp_path), local_devices=False, engine_autostart=False)
    app.add_middleware(TenantBoundary, tenant_id='synthetic', gateway_key='internal-fixture-key')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        headers={'Authorization':'Bearer internal-fixture-key','X-Wearing-Tenant':'synthetic','X-Pajio-Storage-Scope':A}) as client:
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        created = await client.post('/api/goals', json={**INTENT,'request_key':'api-goal-12345678'})
        assert created.status_code == 201
        goal = created.json()
        assert principal(app.state.store, 'goal', goal['id']) == A and 'owner_scope' not in created.text
        created = await client.post('/api/schedules', json={'schedule':schedule().model_dump(),'request_key':'api-schedule'})
        assert created.status_code == 201
        item = created.json()
        assert principal(app.state.store, 'schedule', item['id']) == A and 'owner_scope' not in created.text
        client.headers['X-Pajio-Storage-Scope'] = B
        assert (await client.post(f"/api/goals/{goal['id']}/control", json={'revision':1,'action':'resume'})).status_code == 409
        assert (await client.patch(f"/api/schedules/{item['id']}", json={'revision':1,'action':'pause'})).status_code == 409
        assert (await client.post('/api/conversation', json={'content':'借用另一账户目标','goal_id':goal['id']})).status_code == 409
        forged = await client.post('/api/goals', json={**INTENT,'owner_scope':A})
        assert forged.status_code == 201 and principal(app.state.store, 'goal', forged.json()['id']) == B
        assert (await client.post('/api/schedules', json={'schedule':schedule().model_dump(),'request_key':'forged','owner_scope':A})).status_code == 422
        del client.headers['X-Pajio-Storage-Scope']
        legacy = await client.post('/api/goals', json={**INTENT,'request_key':'preview-goal-123456'})
        assert legacy.status_code == 201 and principal(app.state.store, 'goal', legacy.json()['id']) is None
        legacy_schedule = await client.post('/api/schedules', json={'schedule':schedule().model_dump(),'request_key':'preview-schedule'})
        assert legacy_schedule.status_code == 201 and principal(app.state.store, 'schedule', legacy_schedule.json()['id']) is None
    await app.state.service.hermes.close()


async def test_cloud_constructor_without_boundary_never_assigns_local_authority(tmp_path):
    app = create_app(Settings(tmp_path), local_devices=False, engine_autostart=False)
    # Even if a future mount omits TenantBoundary, an untrusted header cannot
    # become a verified scope and the installer must not fall back to local.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver',
                                headers={'X-Pajio-Storage-Scope': A}) as client:
        client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
        created = await client.post('/api/schedules', json={'schedule':schedule().model_dump(),'request_key':'no-boundary'})
        assert created.status_code == 201
        assert principal(app.state.store, 'schedule', created.json()['id']) is None
        created = await client.post('/api/goals', json=INTENT)
        assert created.status_code == 201
        assert principal(app.state.store, 'goal', created.json()['id']) is None
    await app.state.service.hermes.close()


@pytest.mark.parametrize('kind', ['goal','schedule'])
def test_inherited_account_does_not_preserve_revoked_phone_grants(rig, kind):
    store, goals, schedules, clock = rig
    if kind == 'goal':
        item = goals.create('daily', **INTENT, owner_scope=A)
        goals.control(item['id'], 1, 'resume', owner_scope=A)
        task = goals.claim(item['id'])
    else:
        item = schedules.create('daily', schedule(), 'revoked-phone', owner_scope=A)
        clock[0] = '2026-10-08T00:05:00+00:00'
        task = schedules.claim(item['id'])
    store.update(task['id'], status='running', run_id='synthetic-run')
    book = phone_book(store)
    command = book.request('daily', PHONE_A, 'reminders.read', {'calendar_ids':['synthetic-list']}, 'before-revoke')
    book.configure('daily', PHONE_A, SECRET, 1, False, {}, owner_scope=A)
    assert task_principal(store, task) == A
    with pytest.raises(NativeActionError):
        book.claim('daily', PHONE_A, SECRET, CONNECTION, command['id'], command['fingerprint'], True, owner_scope=A)
    with pytest.raises(NativeActionError):
        book.request('daily', PHONE_A, 'reminders.read', {'calendar_ids':['synthetic-list']}, 'after-revoke')
    assert book.history('daily', PHONE_A, SECRET, owner_scope=A)['items'][0]['state'] == 'cancelled'


@pytest.mark.parametrize('kind', ['goal','schedule'])
def test_local_legacy_background_never_borrows_default_phone_authority(rig, kind):
    store, goals, schedules, clock = rig
    book = NativeActions(store)
    book.configure('daily', PHONE_A, SECRET, 0, True,
                   {'reminders':[{'id':'synthetic-list','title':'Synthetic list','writable':False}]})
    book.connect('daily', PHONE_A, SECRET, 1, CONNECTION, ['reminders.read'])
    if kind == 'goal':
        item = goals.create('daily', **INTENT)
        goals.control(item['id'], 1, 'resume', owner_scope='local')
        task = goals.claim(item['id'])
    else:
        item = schedules.create('daily', schedule(), 'legacy-local')
        clock[0] = '2026-10-08T00:05:00+00:00'
        task = schedules.claim(item['id'])
    store.update(task['id'], status='running', run_id='legacy-local-run')
    with pytest.raises(NativeActionError, match='重新建立委托'):
        book.task_owner('daily')
    with pytest.raises(NativeActionError):
        book.request('daily', PHONE_A, 'reminders.read', {'calendar_ids':['synthetic-list']}, 'must-not-borrow')
    store.update(task['id'], status='completed_unverified')
    # Ordinary historical local chat retains its existing compatibility, while
    # a newly and explicitly delegated local commitment can inherit 'local'.
    conversation = user_turn(store, None)
    assert book.task_owner('daily') == 'local'
    store.update(conversation['id'], status='completed_unverified')
    item = goals.create('daily', **INTENT, owner_scope='local')
    goals.control(item['id'], 1, 'resume', owner_scope='local')
    task = goals.claim(item['id'])
    store.update(task['id'], status='running', run_id='owned-local-run')
    assert book.task_owner('daily') == 'local'
