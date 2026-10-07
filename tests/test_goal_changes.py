"""User-directed changes preserve commitments and cannot be replayed as new work."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest
from pydantic import ValidationError
from wearing.goals import GoalBook, GoalError
from wearing.life import LifeBook
from wearing.life_proxy import dispatch
from wearing.store import Store


@pytest.fixture
def rig(tmp_path):
    store = Store(tmp_path / 'wearing.sqlite3')
    book = GoalBook(store)
    goal = book.create('daily', '泉州两天方案', '只看测试资料，未授权预订', '三个有来源的选项', 3)
    source = store.create_message('改为厦门三天，其他约定不变，先不要启动。')
    store.update(source['id'], status='running', run_id='user-run')
    return store, book, goal, source


def change(goal, **overrides):
    return dict(goal_id=goal['id'], revision=goal['revision'], action='revise',
                patch={'objective': '厦门三天方案'}, request_key='edit', **overrides)


def test_revise_preserves_scope_history_and_paused_state(rig):
    store, book, goal, source = rig
    book.control(goal['id'], 1, 'note', '用户补充：尽量人少')
    goal = book.get(goal['id'])
    result = dispatch(LifeBook(store), 'daily', 'goal_change', change(goal))
    assert result['id'] == goal['id'] and result['revision'] == 3
    assert result['objective'] == '厦门三天方案' and result['status'] == 'paused'
    assert result['boundaries'] == goal['boundaries'] and result['success_criteria'] == goal['success_criteria']
    assert result['max_steps'] == 3 and result['next_wake'] is None
    assert len(book.list('daily')) == 1 and len(book.detail(goal['id'])['notes']) == 1
    with store.connection() as db:
        assert db.execute('SELECT source_task_id FROM goal_changes').fetchone()[0] == source['id']
    assert GoalBook(Store(store.path)).conversational_change('daily', change(goal)) == result


def test_change_invalidates_pending_old_steps_and_report_cannot_revive(rig):
    store, book, goal, _ = rig
    goal = book.control(goal['id'], 1, 'resume')
    step = book.claim(goal['id'])
    with store.connection() as db:
        db.execute("UPDATE personal_goals SET next_step='去泉州' WHERE id=?", (goal['id'],))
    result = book.conversational_change('daily', change(goal))
    assert result['status'] == 'active' and result['next_step'] == ''
    assert result['used_steps'] == 1 and result['max_steps'] == 3
    assert store.get(step['id'])['status'] == 'stopped'
    book.reconcile()
    assert book.get(goal['id']) == result
    assert len(book.detail(goal['id'])['steps']) == 1


def test_resume_replay_never_adds_twice_or_undoes_later_pause(rig):
    store, book, goal, _ = rig
    args = dict(goal_id=goal['id'], revision=1, action='resume', add_steps=2, request_key='resume')
    result = book.conversational_change('daily', args)
    assert result['max_steps'] == 5 and result['status'] == 'active'
    paused = book.control(goal['id'], result['revision'], 'pause')
    assert book.conversational_change('daily', args) == paused
    assert book.conversational_change('daily', {**args, 'request_key': 'new-key'}) == paused
    with pytest.raises(GoalError, match='另一份调整'):
        book.conversational_change('daily', {**args, 'add_steps': 3})
    assert book.get(goal['id']) == paused


def test_stale_change_and_failed_receipt_leave_original_untouched(rig):
    store, book, goal, _ = rig
    with pytest.raises(GoalError, match='新变化'):
        book.conversational_change('daily', {**change(goal), 'revision': 2})
    with store.connection() as db:
        db.execute("CREATE TRIGGER refuse_change BEFORE INSERT ON goal_changes BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        book.conversational_change('daily', change(goal))
    assert book.get(goal['id']) == goal and book.detail(goal['id'])['notes'] == []


def test_parallel_changes_apply_once(rig):
    _, book, goal, _ = rig
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: book.conversational_change('daily', change(goal)), range(8)))
    assert {r['revision'] for r in results} == {2}


def test_foreign_identity_and_multiple_active_runs_rejected(rig):
    store, book, goal, _ = rig
    other = store.save_identity('其他身份')['id']
    with pytest.raises(GoalError):
        book.conversational_change(other, change(goal))
    other_goal = book.create(other, '另一目标', '范围不变', '核对结果')
    with pytest.raises(GoalError):
        book.conversational_change('daily', change(other_goal))
    task = store.create_message('另一个对话', other)
    store.update(task['id'], status='running')
    with pytest.raises(GoalError):
        book.conversational_change('daily', change(goal))
    assert book.get(goal['id']) == goal


@pytest.mark.parametrize('status', ['draft', 'waiting_for_approval', 'stopping', 'ambiguous', 'connection_lost', 'completed_unverified'])
def test_no_current_user_run_cannot_change(rig, status):
    store, book, goal, source = rig
    store.update(source['id'], status=status)
    with pytest.raises(GoalError):
        book.conversational_change('daily', change(goal))


@pytest.mark.parametrize('kind', ['goal', 'schedule'])
def test_background_cannot_rewrite_scope_or_grant_rounds(rig, kind):
    store, book, goal, source = rig
    with store.connection() as db:
        if kind == 'goal':
            db.execute("INSERT INTO goal_steps(task_id,goal_id,revision,created_at) VALUES(?,?,1,'fixture')", (source['id'], goal['id']))
        else:
            db.execute('CREATE TABLE schedule_occurrences(task_id TEXT)')
            db.execute('INSERT INTO schedule_occurrences VALUES(?)', (source['id'],))
    for args in [change(goal), dict(goal_id=goal['id'], revision=1, action='resume', add_steps=100, request_key='expand')]:
        with pytest.raises(GoalError, match='后台任务'):
            book.conversational_change('daily', args)
    assert book.get(goal['id']) == goal


def test_linked_discussion_can_only_change_its_original_goal(rig):
    store, book, goal, source = rig
    store.update(source['id'], status='completed_unverified')
    task, _ = book.create_message(goal['id'], 'daily', '改为厦门三天，先暂停')
    store.update(task['id'], status='running')
    other = book.create('daily', '另一目标', '仅查资料', '核对来源')
    with pytest.raises(GoalError, match='另一个目标'):
        book.conversational_change('daily', change(other))
    result = book.conversational_change('daily', change(goal))
    assert result['objective'] == '厦门三天方案'


@pytest.mark.parametrize('patch', [{'max_steps': 100}, {'identity_id': 'x'}, {'source_task_id': 'forged'}, {'objective': ' '}])
def test_patch_is_strict(rig, patch):
    _, book, goal, _ = rig
    with pytest.raises(ValidationError):
        book.conversational_change('daily', {**change(goal), 'patch': patch})


@pytest.mark.parametrize('args', [dict(action='complete', patch={}), dict(revision=True), dict(add_steps=True)])
def test_model_cannot_verify_completion_or_coerce_bounds(rig, args):
    _, book, goal, _ = rig
    with pytest.raises(ValidationError):
        book.conversational_change('daily', {**change(goal), **args})


@pytest.mark.parametrize('args', [dict(patch={}), dict(action='pause'), dict(action='note', patch={}), dict(add_steps=1)])
def test_mismatched_operation_rejected(rig, args):
    _, book, goal, _ = rig
    with pytest.raises(GoalError):
        book.conversational_change('daily', {**change(goal), **args})
