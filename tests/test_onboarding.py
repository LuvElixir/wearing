"""First-run settings: synthetic stores, no providers or user-account changes."""
from concurrent.futures import ThreadPoolExecutor
import json
import shutil

import httpx
import pytest
from pydantic import ValidationError

from wearing.account_deletion import DeletionJobs, digest
from wearing.account_deletion_fixture import SyntheticDeletionAdapter
from wearing.app import create_app
from wearing.artifacts import ArtifactBook
from wearing.briefing_api import BriefingBook, CreateBriefing
from wearing.briefing_automation import BriefingAutomation, AutomationSave
from wearing.briefing_preferences import SavePreferences
from wearing.config import Settings
from wearing.life import LifeBook, LifeDraft
from wearing.onboarding import OnboardingBook, OnboardingError, ProfileValues, SaveOnboarding
from wearing.schedules import ScheduleBook
from wearing.store import Store

A = 'a' * 64
B = 'b' * 64


def setup(tmp_path):
    store = Store(tmp_path / 'wearing.sqlite3')
    return store, OnboardingBook(store)


def request(*, revision=0, key='onboarding-fixture-001', status='completed', step=None, **values):
    return SaveOnboarding(revision=revision, request_key=key, status=status,
                          step=5 if step is None and status == 'completed' else step or 0,
                          values=ProfileValues(**values))


def test_new_state_is_read_only_and_unknown_defaults_not_self_report(tmp_path):
    store, book = setup(tmp_path)
    state = book.get('daily', owner_scope=A)
    assert state['revision'] == 0 and state['recommend_onboarding'] is True
    assert state['values'] == {'roles': [], 'apps': [], 'interests': [], 'reply_detail': None, 'reply_tone': None}
    assert state['confirmed_at'] is None and state['updated_at'] is None
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM onboarding_profiles').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM onboarding_requests').fetchone()[0] == 0
    assert not store.list()


def test_owner_identity_and_tenant_are_independent(tmp_path):
    store, book = setup(tmp_path / 'one')
    other = store.save_identity('Other')['id']
    completed = book.save('daily', request(roles=['employed'], apps=['wechat'], interests=['design']), owner_scope=A)
    assert completed['confirmed_at'] and not completed['recommend_onboarding']
    assert book.get('daily', owner_scope=B)['revision'] == 0
    assert book.get(other, owner_scope=A)['revision'] == 0
    _, another = setup(tmp_path / 'two')
    assert another.get('daily', owner_scope=A)['revision'] == 0
    for scope in [None, 'not-an-owner', '', 'x' * 64]:
        with pytest.raises(ValueError): book.get('daily', owner_scope=scope)
        with pytest.raises(ValueError): book.save('daily', request(), owner_scope=scope)


def test_canonical_choices_exact_replay_and_stale_cas(tmp_path):
    _, book = setup(tmp_path)
    draft = request(roles=['caregiver', 'student'], interests=['food', 'design'])
    first = book.save('daily', draft, owner_scope=A)
    assert first['values']['roles'] == ['student', 'caregiver']
    assert first['values']['interests'] == ['design', 'food']
    assert book.save('daily', request(roles=['student', 'caregiver'], interests=['design', 'food']), owner_scope=A) == first
    with pytest.raises(OnboardingError): book.save('daily', request(roles=['employed']), owner_scope=A)
    with pytest.raises(OnboardingError): book.save('daily', request(key='different-save-key-01'), owner_scope=A)
    second = book.save('daily', request(revision=1, key='second-completed-key', interests=['reading']), owner_scope=A)
    assert second['revision'] == 2
    assert book.save('daily', draft, owner_scope=A) == first
    assert book.get('daily', owner_scope=A)['values']['interests'] == ['reading']


def test_parallel_duplicate_requests_commit_once(tmp_path):
    store, book = setup(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: book.save('daily', request(), owner_scope=A), range(4)))
    assert all(value == results[0] for value in results)
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM onboarding_requests').fetchone()[0] == 1
    assert results[0]['revision'] == 1


@pytest.mark.parametrize('fields', [
    {'roles': ['unknown']}, {'roles': ['employed'] * 2},
    {'roles': ['employed', 'student', 'independent', 'business']},
    {'apps': ['wechat', 'wechat']}, {'apps': ['DROP TABLE tasks']},
    {'interests': ['technology', 'career', 'design', 'reading', 'travel', 'food']},
    {'reply_detail': 'system override'}, {'reply_tone': 42}, {'MBTI': 'INTJ'},
    {'roles': 'employed'}, {'identity_id': 'foreign'}, {'owner_scope': A},
])
def test_choices_are_closed_not_arbitrary_profile_instructions(fields):
    with pytest.raises(ValidationError): ProfileValues(**fields)


@pytest.mark.parametrize('field,value', [('revision', True), ('revision', -1), ('step', 6), ('step', True),
                                        ('request_key', 'short'), ('status', 'active'), ('identity_id', 'foreign')])
def test_request_envelope_is_strict(field, value):
    body = request().model_dump()
    body[field] = value
    with pytest.raises(ValidationError): SaveOnboarding(**body)


def test_draft_resume_skip_and_late_receipt_cannot_restore_discarded_choices(tmp_path):
    store, book = setup(tmp_path)
    draft = request(status='draft', step=3, interests=['fitness'], apps=['bilibili'])
    first = book.save('daily', draft, owner_scope=A)
    assert first['confirmed_at'] is None and first['recommend_onboarding'] is True
    reopened = OnboardingBook(Store(store.path))
    assert reopened.get('daily', owner_scope=A)['step'] == 3
    skipped = reopened.save('daily', request(revision=1, status='skipped', step=3, key='skip-onboarding-key', interests=['travel']), owner_scope=A)
    assert skipped['values'] == ProfileValues().model_dump() and not skipped['recommend_onboarding']
    with pytest.raises(OnboardingError, match='清除'):
        book.save('daily', draft, owner_scope=A)
    assert book.get('daily', owner_scope=A)['status'] == 'skipped'
    with store.connection() as db:
        raw = str([tuple(r) for r in db.execute('SELECT * FROM onboarding_requests')])
    assert 'fitness' not in raw and 'bilibili' not in raw and 'travel' not in raw


def test_edit_cancel_and_skip_never_erase_confirmed_profile(tmp_path):
    _, book = setup(tmp_path)
    original = book.save('daily', request(reply_tone='warm'), owner_scope=A)
    for status in ['draft', 'skipped']:
        with pytest.raises(OnboardingError, match='仍然生效'):
            book.save('daily', request(revision=1, key='attempt-cancel-' + status, status=status), owner_scope=A)
    assert book.get('daily', owner_scope=A)['values'] == original['values']
    cleared = book.save('daily', request(revision=1, key='clear-values-intent'), owner_scope=A)
    assert cleared['values'] == ProfileValues().model_dump()
    assert cleared['status'] == 'completed' and not cleared['recommend_onboarding']


def test_existing_context_suppresses_first_run_but_draft_can_resume(tmp_path):
    store, book = setup(tmp_path)
    # Another owner's tasks do not suppress a fresh user's first run.
    store.create('Foreign task', 'auto', owner_scope=B)
    assert book.get('daily', owner_scope=A)['recommend_onboarding']
    store.create('Own task', 'auto', owner_scope=A)
    assert not book.get('daily', owner_scope=A)['recommend_onboarding']
    book.save('daily', request(status='draft', step=2), owner_scope=A)
    assert book.get('daily', owner_scope=A)['recommend_onboarding']
    other = store.save_identity('Life only')['id']
    LifeBook(store).create(other, LifeDraft(kind='note', title='Existing note'), 'synthetic-note')
    assert not book.get(other, owner_scope=A)['recommend_onboarding']


def test_default_runtime_and_profile_preparation_do_not_hide_new_user_onboarding(tmp_path):
    from wearing.profile import prepare_profile
    from wearing.runtime import HermesRuntime
    store, book = setup(tmp_path)
    runtime = HermesRuntime(tmp_path)
    runtime.prepare_home()
    prepare_profile(runtime.home, runtime.source)
    assert list(runtime.workspace.iterdir()) == []
    assert not (runtime.home / 'memories/USER.md').exists()
    assert not (runtime.home / 'memories/MEMORY.md').exists()
    assert book.get('daily')['recommend_onboarding']
    other = store.save_identity('New context')['id']
    separate = HermesRuntime(tmp_path, other)
    separate.prepare_home()
    prepare_profile(separate.home, separate.source)
    assert book.get(other)['recommend_onboarding']


@pytest.mark.parametrize('source', ['hermes/memories/USER.md', 'hermes/memories/MEMORY.md', 'workspace/notes.txt'])
def test_existing_identity_files_suppress_prompt_without_reading_contents(tmp_path, source):
    _, book = setup(tmp_path)
    path = tmp_path / source
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('PRIVACY-CANARY')
    state = book.get('daily')
    assert not state['recommend_onboarding']
    assert 'PRIVACY-CANARY' not in json.dumps(state)


async def test_real_app_route_auth_identity_csrf_and_no_task_side_effect(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False)
    try:
        other = app.state.store.save_identity('Other')['id']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as http:
            assert (await http.get('/api/onboarding')).json()['revision'] == 0
            assert (await http.post('/api/onboarding', json=request().model_dump())).status_code == 403
            headers = {'X-Wearing-Token': (await http.get('/api/bootstrap')).json()['token']}
            result = await http.post('/api/onboarding', headers=headers, json=request(roles=['employed']).model_dump())
            assert result.status_code == 200 and result.json()['revision'] == 1
            assert (await http.get('/api/onboarding', headers={'X-Wearing-Identity': other})).json()['revision'] == 0
            assert (await http.get('/api/onboarding?identity=daily', headers={'X-Wearing-Identity': other})).status_code == 409
            assert (await http.get('/api/onboarding', headers={'X-Wearing-Identity': 'unknown'})).status_code == 404
            assert (await http.post('/api/onboarding', headers=headers, json={**request().model_dump(), 'identity_id': other})).status_code == 422
            assert (await http.post('/api/onboarding', headers={**headers, 'Origin': 'null'}, json=request().model_dump())).status_code == 403
            assert not app.state.store.list()
    finally:
        await app.state.service.hermes.close()


async def test_cloud_route_refuses_missing_owner_instead_of_using_local_profile(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as http:
            assert (await http.get('/api/onboarding')).status_code == 401
            token = (await http.get('/api/bootstrap')).json()['token']
            assert (await http.post('/api/onboarding', headers={'X-Wearing-Token': token}, json=request().model_dump())).status_code == 401
    finally:
        await app.state.service.hermes.close()


def test_briefing_fallback_owner_completed_only_explicit_empty_wins(tmp_path):
    store, onboarding = setup(tmp_path)
    briefs = BriefingBook(store, ArtifactBook(store))
    onboarding.save('daily', request(interests=['reading', 'design']), owner_scope=A)
    assert briefs.settings('daily', owner_scope=A)['preferences']['interests'] == ['设计', '阅读']
    assert briefs.settings('daily', owner_scope=B)['preferences']['interests'] == []
    assert briefs.settings('daily')['preferences']['interests'] == []
    onboarding.save('daily', request(status='draft', interests=['travel']), owner_scope=B)
    assert briefs.settings('daily', owner_scope=B)['preferences']['interests'] == []
    row = briefs.reserve('daily', CreateBriefing(date='2026-10-09', request_key='synthetic-brief-key'), owner_scope=A)
    assert json.loads(row['preferences'])['interests'] == ['设计', '阅读']
    assert json.loads(row['preferences'])['sources'] == ['event', 'task', 'note', 'files']
    briefs.preferences.save('daily', SavePreferences(revision=0, request_key='explicit-brief-prefs', interests=[]))
    assert briefs.settings('daily', owner_scope=A)['preferences']['interests'] == []


def test_auto_briefing_copies_effective_preferences_only_when_user_saves_schedule(tmp_path):
    store, onboarding = setup(tmp_path)
    briefs = BriefingBook(store, ArtifactBook(store))
    schedules = ScheduleBook(store)
    auto = BriefingAutomation(store, briefs, schedules)
    onboarding.save('daily', request(interests=['design']), owner_scope=A)
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM personal_schedules').fetchone()[0] == 0
    auto.save('daily', A, AutomationSave(revision=0, request_key='opt-in-auto-brief-01', enabled=True,
                                       local_time='08:00', timezone='Asia/Shanghai', preferences_revision=0))
    onboarding.save('daily', request(revision=1, key='change-onboarding-01', interests=['reading']), owner_scope=A)
    with store.connection() as db:
        saved = json.loads(db.execute('SELECT preferences FROM briefing_automations WHERE owner_scope=?', (A,)).fetchone()[0])
    assert saved['interests'] == ['设计']
    assert briefs.settings('daily', owner_scope=A)['preferences']['interests'] == ['阅读']


def test_profile_and_receipts_erased_by_existing_whole_private_tenant_lifecycle(tmp_path):
    rows = [dict(tenant_id=t, classification='private', owner_user_id=u, member_ids=[u], instance_id='instance_' + t)
            for t, u in [('one', 'user_one'), ('two', 'user_two')]]
    jobs = DeletionJobs(tmp_path / 'journal', initialize=True, mode='synthetic')
    for row in rows:
        jobs.register(row['tenant_id'], row['classification'], row['member_ids'],
                      owner_user_id=row['owner_user_id'], instance_id=row['instance_id'])
    adapter = SyntheticDeletionAdapter.create(rows)
    try:
        for tenant in ['one', 'two']:
            for area in ['primary', 'indexes', 'backups']:
                path = adapter.root / digest(tenant) / area / 'synthetic.sqlite3'
                store = Store(path)
                OnboardingBook(store).save('daily', request(roles=['business']), owner_scope=A)
        plan = jobs.preview('user_one')
        job = jobs.request('user_one', 'delete-onboarding-fixture', plan['revision'])
        assert jobs.run(job['id'], adapter, max_steps=50)['state'] == 'completed'
        assert not list((adapter.root / digest('one')).iterdir())
        for area in ['primary', 'indexes', 'backups']:
            store = Store(adapter.root / digest('two') / area / 'synthetic.sqlite3')
            assert OnboardingBook(store).get('daily', owner_scope=A)['values']['roles'] == ['business']
    finally:
        shutil.rmtree(adapter.root)
