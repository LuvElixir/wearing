import json
import socket
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import ValidationError

from wearing.app import create_app
from wearing.artifacts import ArtifactBook
from wearing.briefing_api import BriefingBook, BriefingError, CreateBriefing
from wearing.briefing_preferences import BriefingPreferences, PreferenceError, SavePreferences
from wearing.config import Settings
from wearing.life import LifeBook, LifeDraft
from wearing.store import Store


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *_: pytest.fail('no external calls allowed'))


def setup(tmp_path):
    store = Store(tmp_path / 'state.sqlite3')
    return store, BriefingBook(store, ArtifactBook(store))


def save(revision=0, key='preferences-save-one', **values):
    return SavePreferences(revision=revision, request_key=key, **values)


def draft(key='briefing-request-one', **values):
    return CreateBriefing(date='2026-10-08', timezone='Asia/Shanghai', request_key=key, **values)


def test_defaults_identity_and_durable_idempotent_cas(tmp_path):
    store, book = setup(tmp_path)
    other = store.save_identity('Other synthetic', '', 'CN')['id']
    assert book.preferences.get('daily')['sources'] == ['event', 'task', 'note', 'files']
    body = save(interests=['设计'], priorities='下周上线', sources=['note', 'event'], max_items=2)
    first = book.preferences.save('daily', body)
    assert first['revision'] == 1 and first['sources'] == ['event', 'note']
    assert BriefingPreferences(Store(store.path)).save('daily', body) == first
    assert book.preferences.get(other)['revision'] == 0
    with pytest.raises(PreferenceError):
        book.preferences.save('daily', save(key='preferences-stale-two'))
    with pytest.raises(PreferenceError):
        book.preferences.save('daily', save(interests=['different']))
    assert book.preferences.save(other, body)['identity_id'] == other


def test_concurrent_updates_admit_one_version_only(tmp_path):
    _, book = setup(tmp_path)
    def update(index):
        try: return book.preferences.save('daily', save(key=f'parallel-save-{index:03}', priorities=str(index)))['revision']
        except PreferenceError: return 'conflict'
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(update, range(4)))
    assert results.count(1) == 1 and results.count('conflict') == 3


@pytest.mark.parametrize('patch', [{'revision': True}, {'revision': '0'}, {'interests': [' ']}, {'interests': ['a', ' a']}, {'interests': ['x'] * 9}, {'sources': []}, {'sources': ['mail']}, {'sources': ['note', 'note']}, {'max_items': 4}, {'identity_id': 'other'}, {'priorities': 'x' * 1001}])
def test_input_bounds_and_no_client_owner(patch):
    with pytest.raises(ValidationError): SavePreferences.model_validate({**save().model_dump(), **patch})


def test_generation_snapshots_current_preferences_and_does_not_read_unselected_files(tmp_path, monkeypatch):
    store, book = setup(tmp_path)
    LifeBook(store).create('daily', LifeDraft(kind='note', title='Selected synthetic note'), 'note-one')
    book.preferences.save('daily', save(sources=['note'], interests=['设计'], priorities='上线计划', max_items=1))
    monkeypatch.setattr('wearing.briefing_api.list_files', lambda *_args, **_kwargs: pytest.fail('unselected files read'))
    row = book.reserve('daily', draft(preferences_revision=1))
    assert [item['id'] for item in json.loads(row['sources'])] == ['note']
    assert json.loads(row['preferences'])['priorities'] == '上线计划'
    assert '首屏最多 1 项' in row['prompt'] and '上线计划' in row['prompt']
    assert '未选来源不要主动读取' in row['prompt'] and not store.list()
    book.preferences.save('daily', save(revision=1, key='preferences-save-two', priorities='Later priorities'))
    # Same-key replay is still the exact original intent, even after changing preferences.
    assert book.reserve('daily', draft(preferences_revision=1)) == row
    assert book.get('daily', row['id'])['preferences']['priorities'] == '上线计划'
    with pytest.raises(BriefingError, match='偏好已更新'):
        book.reserve('daily', draft(key='new-stale-generation', preferences_revision=1))
    with pytest.raises(BriefingError, match='上一版'):
        book.reserve('daily', draft(key='new-current-generation', preferences_revision=2))


def test_old_daily_table_and_old_request_replay_are_preserved(tmp_path):
    store, book = setup(tmp_path)
    row = book.reserve('daily', draft())
    with store.connection() as db:
        db.execute('ALTER TABLE daily_briefings DROP COLUMN preferences')
    upgraded = BriefingBook(Store(store.path), book.artifacts)
    assert upgraded.get('daily', row['id'])['preferences'] is None
    assert upgraded.reserve('daily', draft())['id'] == row['id']
    assert upgraded.preferences.get('daily')['revision'] == 0


async def test_new_version_after_completion_uses_new_preferences(tmp_path):
    from test_briefings import NoNetworkHermes
    from wearing.service import TaskService

    store, book = setup(tmp_path)
    hermes = NoNetworkHermes()
    service = TaskService(store, hermes)
    first = await book.create('daily', draft(preferences_revision=0), service)
    store.update(first['task_id'], status='completed_unverified', output='Synthetic text only')
    book.preferences.save('daily', save(sources=['note'], priorities='New synthetic priority', max_items=2))
    second = await book.create('daily', draft(key='new-preferences-generation', base_version=1, preferences_revision=1), service)
    assert second['version'] == 2 and second['preferences']['revision'] == 1
    assert [source['id'] for source in second['sources']] == ['note']
    assert second['task_id'] != first['task_id'] and len(hermes.starts) == 2
    assert 'New synthetic priority' in hermes.starts[1][0]['input']
    assert book.get('daily', first['id'])['preferences']['revision'] == 0


def test_partial_source_failure_preserves_success_and_never_leaks_error(tmp_path, monkeypatch):
    _, book = setup(tmp_path)
    LifeBook(book.store).create('daily', LifeDraft(kind='note', title='Synthetic usable note'), 'note-one')
    def failed(*_args, **_kwargs): raise OSError('/private/SECRET/path')
    monkeypatch.setattr('wearing.briefing_api.list_files', failed)
    result = book.settings('daily')
    states = {item['id']: item['state'] for item in result['available_sources']}
    assert states['note'] == 'available' and states['files'] == 'failed' and states['feishu'] == 'unavailable'
    assert 'SECRET' not in json.dumps(result) and all('references' not in source for source in result['available_sources'])


def test_feishu_authorization_is_local_ledger_only_and_not_read_success(tmp_path):
    _, book = setup(tmp_path)
    snapshot = {'state': 'connected', 'revocation_pending': False, 'capabilities': [
        {'id': 'documents', 'requested': True, 'authorized': True},
        {'id': 'calendar', 'requested': False, 'authorized': True}], 'access_token': 'NEVER-EXPOSE'}
    book.connection_reader = lambda _: snapshot
    book.preferences.save('daily', save(sources=['feishu']))
    row = book.reserve('daily', draft())
    source = json.loads(row['sources'])[0]
    assert source['state'] == 'authorized' and source['count'] is None and source['features'] == ['documents']
    assert 'NEVER-EXPOSE' not in row['prompt'] and '不代表已读到内容' in row['prompt']
    snapshot['revocation_pending'] = True
    assert book.sources('daily', ['feishu'])[0]['state'] == 'not_connected'
    snapshot['state'] = 'expired'
    assert book.sources('daily', ['feishu'])[0]['features'] == []


async def test_real_routes_csrf_static_order_identity_and_read_only_settings(tmp_path):
    app = create_app(Settings(tmp_path), engine_autostart=False, local_devices=False)
    try:
        store = app.state.store
        other = store.save_identity('Other synthetic', '', 'CN')['id']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://testserver') as http:
            path = '/api/briefings/preferences'
            state = (await http.get(path)).json()
            assert state['preferences']['revision'] == 0 and not store.list()
            assert (await http.post(path, json=save().model_dump())).status_code == 403
            token = (await http.get('/api/bootstrap')).json()['token']
            headers = {'X-Wearing-Token': token}
            response = await http.post(path, json=save(priorities='Only this identity').model_dump(), headers=headers)
            assert response.status_code == 200 and response.json()['revision'] == 1
            assert (await http.get(path, headers={'X-Wearing-Identity': other})).json()['preferences']['priorities'] == ''
            assert (await http.post(path, json=save().model_dump(), headers={**headers, 'Origin': 'null'})).status_code == 403
            assert (await http.post(path, json={**save().model_dump(), 'identity_id': other}, headers=headers)).status_code == 422
            assert not store.list()
    finally:
        await app.state.service.hermes.close()
