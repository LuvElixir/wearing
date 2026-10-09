"""Independent source exclusion checks using temporary owner-scoped fixtures.

Hermes /v1/runs reloads the selected session history (and its compressed tip)
before starting an agent. Removing source_conversation from new instructions
therefore cannot sanitize a previously used standalone goal session.
"""
import json

import httpx
import pytest

from test_conversation_sources import sources, exclude  # noqa: F401
from test_session_recall_guard import A, case, admit  # noqa: F401
from test_goals import GoalWire, due, report
from wearing.config import Settings
from wearing.goals import GoalBook
from wearing.hermes import HermesClient
from wearing.service import ACTIVE, TaskService
from wearing.conversation_sources import SourceError
from wearing.session_recall_guard import RecallConfig, RecallGuard


@pytest.mark.parametrize('queued_before_exclusion', [False, True])
async def test_exclusion_never_resumes_a_goal_engine_history(sources, queued_before_exclusion):
    controls, (store, _, source, _, _, _) = sources
    goals = GoalBook(store)
    goal = goals.create('daily', 'Retained product objective', 'Synthetic scope',
                        'Synthetic evidence', 3, source['id'], owner_scope=A)
    goals.control(goal['id'], goal['revision'], 'resume', owner_scope=A)
    wire = GoalWire()

    async def transport(request):
        if request.url.path.endswith('capabilities'):
            return httpx.Response(200, json={'features': {}, 'wearing': {'session_recall_guard': 'sources-v1'}})
        return await wire(request)

    client = HermesClient(Settings(store.path.parent, hermes_key='fixture'), httpx.MockTransport(transport))
    service = TaskService(store, client)
    service.context_provider, service.start_guard = goals.context, goals.guard
    try:
        first = goals.claim(goal['id'])
        await service.start(first['id'])
        assert 'source_conversation' in wire.runs[0]['instructions']
        store.update(first['id'], status='completed_unverified', output=report('Retained report'))
        goals.reconcile()
        due(store, goal)
        second = goals.claim(goal['id']) if queued_before_exclusion else None
        exclude(controls, task=source['id'])
        second = second or goals.claim(goal['id'])
        await service.start(second['id'])
        assert 'source_conversation' not in wire.runs[1]['instructions']
        assert 'Retained product objective' in wire.runs[1]['instructions']
        assert 'Retained report' in wire.runs[1]['instructions']
        assert wire.runs[1]['session_id'] != wire.runs[0]['session_id'], (
            'Same goal revision must not reload its pre-exclusion raw/tool history')
    finally:
        await client.close()


async def test_new_generation_goal_can_recall_other_authorized_sources(sources):
    controls, (store, _, source, _, remaining, _) = sources
    goals = GoalBook(store)
    goal = goals.create('daily', 'Synthetic new goal', 'Fixture only', 'Evidence', 1,
                        source['id'], owner_scope=A)
    goals.control(goal['id'], goal['revision'], 'resume', owner_scope=A)
    exclude(controls, task=source['id'])
    task = goals.claim(goal['id'])
    wire = GoalWire()

    async def transport(request):
        if request.url.path.endswith('capabilities'):
            return httpx.Response(200, json={'features': {}, 'wearing': {'session_recall_guard': 'sources-v1'}})
        return await wire(request)

    client = HermesClient(Settings(store.path.parent, hermes_key='fixture'), httpx.MockTransport(transport))
    try:
        await TaskService(store, client).start(task['id'])
        task = store.get(task['id'])
        guard = RecallGuard(RecallConfig(store.path.parent, 'daily'), lambda: task['run_id'])
        result = json.loads(guard.search(current_session_id=task['session_id'], session_id=remaining['session_id']))
        assert result['success'], 'Trusted host goal session should retain access to unexcluded sources'
        assert not json.loads(guard.search(current_session_id=task['session_id'], session_id=source['session_id']))['success']
    finally:
        await client.close()


@pytest.mark.parametrize('status', sorted(ACTIVE))
def test_local_policy_cannot_change_while_legacy_unowned_run_is_unsettled(sources, status):
    controls, (store, _, _, _, _, _) = sources
    source = admit(store, 'explicit-local-source', 'local')
    # This is a supported pre-upgrade local task: local RecallGuard accepts its
    # absent principal, so it can already hold raw recalled local content.
    legacy = store.create('Synthetic legacy task', 'computer')
    store.update(legacy['id'], status=status)
    with pytest.raises(SourceError, match='停止'):
        exclude(controls, task=source['id'], owner='local')


def test_local_policy_never_resumes_a_queued_unowned_chat(sources):
    controls, (store, _, _, _, _, _) = sources
    source = admit(store, 'explicit-local-source', 'local')
    legacy = store.create_message('Synthetic pre-upgrade queued chat')
    exclude(controls, task=source['id'], owner='local')
    payload = {'session_id': legacy['session_id']}
    admitted = store.reserve_start(legacy['id'], payload, 'synthetic-legacy-resume', ACTIVE, source_generation=1)
    # Fail closed is acceptable; automatically inventing a cloud/local owner is
    # not. An admitted task must never revive the stale raw session context.
    assert not admitted or payload['session_id'] != legacy['session_id']
