import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError

from wearing.artifacts import ArtifactBook, ArtifactDraft
from wearing.briefing_api import BriefingBook, BriefingError, CreateBriefing, install_briefing_routes
from wearing.life import LifeBook, LifeDraft
from wearing.service import TaskService
from wearing.store import Store


class NoNetworkHermes:
    def __init__(self):
        self.starts = []
        self.available = True

    async def probe(self):
        return {'state': 'reachable' if self.available else 'unreachable', 'message': 'QA synthetic offline'}

    async def start(self, payload, key):
        self.starts.append((payload, key))
        return {'run_id': 'qa-run-' + str(len(self.starts))}


def setup(tmp_path):
    store = Store(tmp_path / 'briefing-test.sqlite3')
    artifacts = ArtifactBook(store)
    hermes = NoNetworkHermes()
    service = TaskService(store, hermes)
    return store, artifacts, hermes, service, BriefingBook(store, artifacts)


def draft(key='test-briefing-request-01', base=0, **values):
    return CreateBriefing(date='2026-10-07', timezone='Asia/Shanghai', request_key=key, base_version=base, **values)


@pytest.mark.parametrize('zone,local_stamp,local_day', [
    ('Asia/Shanghai', '2026-10-10T02:40:00+08:00', '2026-10-10'),
    ('America/Los_Angeles', '2026-10-09T11:40:00-07:00', '2026-10-09'),
])
@pytest.mark.parametrize('target', ['2026-10-08', '2026-10-10', '2026-10-12'])
def test_prompt_anchors_request_day_in_requested_timezone_and_keeps_target(tmp_path, monkeypatch, zone, local_stamp, local_day, target):
    monkeypatch.setattr('wearing.briefing_api.now', lambda: '2026-10-09T18:40:00+00:00')
    _, _, _, _, book = setup(tmp_path)
    request = CreateBriefing(date=target, timezone=zone, request_key='qa-date-anchor-request')
    row = book.reserve('daily', request)
    assert f'请求保存时刻：{local_stamp}' in row['prompt']
    assert f'按 {zone} 换算的请求当天：{local_day}' in row['prompt']
    assert f'本版目标日期：{target}' in row['prompt']
    assert '正文不使用今天、明天、昨天代替目标日期' in row['prompt']
    # A replay across midnight must retain the original intent and time context.
    monkeypatch.setattr('wearing.briefing_api.now', lambda: '2026-10-11T18:40:00+00:00')
    assert book.reserve('daily', request) == row


async def test_creation_uses_real_task_service_replay_and_no_duplicate_model_run(tmp_path):
    store, _, hermes, service, book = setup(tmp_path)
    results = await asyncio.gather(*(book.create('daily', draft(), service) for _ in range(4)))
    assert len({item['id'] for item in results}) == 1
    assert len(store.list()) == 1 and len(hermes.starts) == 1
    item = results[0]
    assert item['state'] == 'running' and item['artifacts'] == []
    assert item['task_id'] == store.list()[0]['id']
    assert 'artifact_publish' in hermes.starts[0][0]['input']
    # Reopen/restart uses the durable handoff; read-only requests never contact a model.
    reopened = BriefingBook(Store(store.path), ArtifactBook(Store(store.path)))
    assert reopened.list('daily', '2026-10-07', 'Asia/Shanghai')['items'][0]['id'] == item['id']
    assert (await reopened.create('daily', draft(), service))['task_id'] == item['task_id']
    assert len(hermes.starts) == 1


async def test_multiple_fresh_click_keys_coalesce_while_current_version_is_pending(tmp_path):
    store, _, hermes, service, book = setup(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda index: book.reserve('daily', draft(f'test-independent-click-{index}')), range(4)))
    assert len({row['id'] for row in rows}) == 1
    item = await book.create('daily', draft('test-independent-click-0'), service)
    store.update(item['task_id'], status='completed_unverified', output='QA only text')
    # An alias key also remains a durable replay after the task finishes.
    replay = await book.create('daily', draft('test-independent-click-3'), service)
    assert replay['id'] == item['id'] and replay['state'] == 'text_only'
    assert len(hermes.starts) == 1
    with pytest.raises(BriefingError, match='新版本'):
        await book.create('daily', draft('test-stale-new-version'), service)
    newer = await book.create('daily', draft('test-new-version-intent', base=1), service)
    assert newer['version'] == 2 and newer['task_id'] != item['task_id']
    assert len(hermes.starts) == 2


async def test_unlinked_reservation_and_saved_offline_task_recover_without_new_message(tmp_path):
    store, _, hermes, service, book = setup(tmp_path)
    reserved = book.reserve('daily', draft())
    assert book.get('daily', reserved['id'])['state'] == 'not_started' and not store.list()
    hermes.available = False
    first = await book.create('daily', draft(), service)
    assert first['state'] == 'not_started' and len(store.list()) == 1 and not hermes.starts
    hermes.available = True
    second = await book.create('daily', draft(), service)
    assert second['task_id'] == first['task_id'] and second['state'] == 'running'
    assert len(store.list()) == 1 and len(hermes.starts) == 1


async def test_message_handoff_recovers_if_request_was_saved_before_http_reply(tmp_path):
    store, _, hermes, service, book = setup(tmp_path)
    row = book.reserve('daily', draft())
    receipt = await service.submit_message(row['prompt'], 'daily', row['task_request_id'])
    recovered = await BriefingBook(store, book.artifacts).create('daily', draft(), service)
    assert recovered['task_id'] == receipt['task']['id'] and len(hermes.starts) == 1


async def test_other_work_queues_briefing_without_starting_another_run(tmp_path):
    store, _, hermes, service, book = setup(tmp_path)
    first = await service.submit_message('QA existing task', 'daily', 'qa-existing-message')
    item = await book.create('daily', draft(), service)
    assert item['state'] == 'queued' and item['delivery']['queued'] is True
    assert item['task_id'] != first['task']['id'] and len(hermes.starts) == 1


async def test_only_actual_published_artifacts_make_visual_result_and_keep_source_status_separate(tmp_path):
    store, artifacts, _, service, book = setup(tmp_path)
    life = LifeBook(store)
    life.create('daily', LifeDraft(kind='note', title='QA source one', content='真实合成资料'), 'qa-note-one')
    root = artifacts.workspace('daily'); root.mkdir(parents=True)
    (root / '资料.txt').write_text('QA source two')
    item = await book.create('daily', draft(), service)
    assert {source['id']: source['state'] for source in item['sources']} == {'event': 'empty', 'task': 'empty', 'note': 'available', 'files': 'available'}
    assert all('observed_at' in source for source in item['sources'])
    (root / 'brief.html').write_text('<!doctype html><html><body><h1>QA synthetic brief</h1></body></html>')
    artifact = artifacts.publish('daily', ArtifactDraft(path='brief.html', title='QA 简报', summary='QA 合成资料摘要', sources=['资料.txt'], limitations=['未读任何云端应用']), 'qa-visual-brief')
    store.update(item['task_id'], status='completed_unverified', output='QA 图文已保存')
    result = book.get('daily', item['id'])
    assert result['state'] == 'ready' and result['artifacts'][0]['id'] == artifact['id']
    assert result['artifacts'][0]['checks']['content'] == 'not_verified'
    assert artifacts.get('daily', artifact['id'], content=True)[1].startswith(b'<!doctype')
    # Later source changes do not mutate the saved input availability snapshot.
    life.create('daily', LifeDraft(kind='note', title='Later record'), 'qa-note-two')
    assert next(source for source in book.get('daily', item['id'])['sources'] if source['id'] == 'note')['count'] == 1


async def test_sources_exclude_only_unchanged_ledger_linked_briefings_and_preserve_real_progress(tmp_path):
    store, artifacts, _, service, book = setup(tmp_path)
    root = artifacts.workspace('daily'); root.mkdir(parents=True)
    first = await book.create('daily', draft(), service)
    raw = '<html><body>QA first briefing</body></html>'
    (root / 'brief.html').write_text(raw)
    brief_artifact = artifacts.publish('daily', ArtifactDraft(path='brief.html', title='First brief', summary='QA'), 'brief-output')
    store.update(first['task_id'], status='completed_unverified')
    # Exact same bytes in a user file are not the original published path.
    (root / 'user-copy.html').write_text(raw)
    normal = await service.submit_message('QA real research result', 'daily', 'non-briefing-task')
    (root / 'research.html').write_text('<html>QA research progress</html>')
    artifacts.publish('daily', ArtifactDraft(path='research.html', title='Research', summary='QA'), 'research-output')
    store.update(normal['task']['id'], status='completed_unverified')
    source = book.sources('daily', ['files'])[0]
    assert {item['path'] for item in source['references']} == {'user-copy.html', 'research.html'}
    assert source['count'] == 2
    second = book.reserve('daily', draft('second-briefing-generation', base=1))
    assert {item['path'] for item in json.loads(second['sources'])[-1]['references']} == {'user-copy.html', 'research.html'}
    assert '最多给 1 项有用的可选下一步' in second['prompt']
    assert '不要为缺少数据写长篇报告' in second['prompt']
    assert '不计入新增文件、来源覆盖或重要变化' in second['prompt']
    # Reusing a path for new content makes it eligible again.
    (root / 'brief.html').write_text('<html>QA new user content</html>')
    assert book.sources('daily', ['files'])[0]['count'] == 3
    (root / 'brief.html').write_text(raw)
    # Pre-migration results have no safe path provenance and stay visible.
    with store.connection() as db:
        db.execute('UPDATE artifacts SET source_path=NULL WHERE id=?', (brief_artifact['id'],))
    assert book.sources('daily', ['files'])[0]['count'] == 3
    assert '旧版可能未记原路径' in second['prompt']


async def test_briefing_source_filter_is_identity_and_account_scoped_and_supports_scheduler_link(tmp_path):
    store, artifacts, _, service, book = setup(tmp_path)
    owner = 'a' * 64
    first = await book.create('daily', draft(), service, owner_scope=owner)
    root = artifacts.workspace('daily'); root.mkdir(parents=True)
    raw = '<html>QA briefing</html>'; (root / 'same-name.html').write_text(raw)
    artifacts.publish('daily', ArtifactDraft(path='same-name.html', title='QA', summary='QA'), 'owner-brief')
    store.update(first['task_id'], status='completed_unverified')
    assert book.sources('daily', ['files'], owner_scope=owner)[0]['count'] == 0
    assert book.sources('daily', ['files'], owner_scope='b' * 64)[0]['count'] == 1
    # Scheduled briefs link a direct task instead of an HTTP handoff.
    with store.connection() as db:
        db.execute('UPDATE daily_briefings SET direct_task_id=? WHERE id=?', (first['task_id'], first['id']))
        db.execute('DELETE FROM message_handoffs WHERE task_id=?', (first['task_id'],))
    assert book.sources('daily', ['files'], owner_scope=owner)[0]['count'] == 0
    other = store.save_identity('Other QA')['id']; other_root = artifacts.workspace(other)
    other_root.mkdir(parents=True); (other_root / 'same-name.html').write_text(raw)
    assert book.sources(other, ['files'], owner_scope=owner)[0]['count'] == 1


async def test_excluded_briefings_do_not_consume_file_preview_slots(tmp_path):
    store, artifacts, _, service, book = setup(tmp_path)
    root = artifacts.workspace('daily'); root.mkdir(parents=True)
    first = await book.create('daily', draft(), service)
    (root / 'a-brief.html').write_text('<html>QA briefing</html>')
    artifacts.publish('daily', ArtifactDraft(path='a-brief.html', title='QA', summary='QA'), 'briefing-file')
    store.update(first['task_id'], status='completed_unverified')
    for number in range(30): (root / f'z-{number:02}.txt').write_text('QA')
    source = book.sources('daily', ['files'])[0]
    assert source['count'] == 30
    assert len(source['references']) == 30
    assert all(item['path'].startswith('z-') for item in source['references'])
    assert source['truncated'] is True  # The underlying bounded scan does not claim completeness.


async def test_replaced_symlink_is_not_followed_to_decide_briefing_exclusion(tmp_path, monkeypatch):
    store, artifacts, _, service, book = setup(tmp_path)
    root = artifacts.workspace('daily'); root.mkdir(parents=True)
    first = await book.create('daily', draft(), service)
    raw = '<html>QA briefing</html>'; path = root / 'brief.html'; path.write_text(raw)
    artifacts.publish('daily', ArtifactDraft(path='brief.html', title='QA', summary='QA'), 'briefing-file')
    store.update(first['task_id'], status='completed_unverified')
    # If followed, equal bytes would hide the file. A raced symlink must stay
    # uncertain instead; the later scoped tool must perform a fresh safe read.
    outside = tmp_path / 'outside.html'; outside.write_text(raw)
    from wearing.workspace import list_files
    def replaced(*args, **kwargs):
        listing = list_files(*args, **kwargs)
        path.unlink(); path.symlink_to(outside)
        return listing
    monkeypatch.setattr('wearing.briefing_api.list_files', replaced)
    assert book.sources('daily', ['files'])[0]['count'] == 1


async def test_failure_and_partial_text_are_never_called_finished_visuals(tmp_path):
    store, _, hermes, service, book = setup(tmp_path)
    item = await book.create('daily', draft(), service)
    for task_status, state in [('connection_lost', 'needs_attention'), ('ambiguous', 'needs_attention'), ('failed', 'failed'), ('stopped', 'stopped'), ('completed_unverified', 'text_only')]:
        store.update(item['task_id'], status=task_status, output='partial QA response')
        result = book.get('daily', item['id'])
        assert result['state'] == state and result['output'] == 'partial QA response' and result['artifacts'] == []
    assert len(hermes.starts) == 1


async def test_an_unreadable_source_is_recorded_as_failed_and_never_filled_with_content(tmp_path):
    _, artifacts, _, service, book = setup(tmp_path)
    outside = tmp_path / 'unrelated'; outside.mkdir()
    (outside / 'not-allowed.txt').write_text('NOT FOR THE BRIEFING')
    artifacts.workspace('daily').symlink_to(outside, target_is_directory=True)
    item = await book.create('daily', draft(), service)
    files = next(source for source in item['sources'] if source['id'] == 'files')
    assert files['state'] == 'failed' and files['count'] is None and files['references'] == []
    assert 'NOT FOR THE BRIEFING' not in json.dumps(item)


async def test_identity_isolation_and_request_key_content_guard(tmp_path):
    store, _, _, service, book = setup(tmp_path)
    item = await book.create('daily', draft(), service)
    other = store.save_identity('QA other identity', '', 'CN')['id']
    assert book.list(other, '2026-10-07', 'Asia/Shanghai')['items'] == []
    with pytest.raises(BriefingError) as caught:
        book.get(other, item['id'])
    assert caught.value.status == 404
    with pytest.raises(BriefingError, match='另一份'):
        book.reserve('daily', draft(base=1))
    other_item = await book.create(other, draft(), service)
    assert other_item['identity_id'] == other and other_item['id'] != item['id']


def test_invalid_dates_zones_versions_and_injected_owner_fail_validation():
    base = draft().model_dump()
    for changes in [{'date': '2026-02-30'}, {'timezone': 'unknown/timezone'}, {'base_version': 1.5}, {'identity_id': 'other'}, {'request_key': 'short'}]:
        with pytest.raises(ValidationError):
            CreateBriefing.model_validate({**base, **changes})


async def test_http_listing_is_read_only_and_returns_owned_contract(tmp_path):
    store, artifacts, hermes, service, _ = setup(tmp_path)
    app = FastAPI()
    @app.middleware('http')
    async def identity(request: Request, call_next):
        request.state.identity_id = request.headers.get('X-Wearing-Identity', 'daily')
        return await call_next(request)
    install_briefing_routes(app, store, service, artifacts)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://qa.test') as client:
        params = {'date': '2026-10-07', 'timezone': 'Asia/Shanghai'}
        assert (await client.get('/api/briefings', params=params)).json()['items'] == []
        assert not hermes.starts
        created = await client.post('/api/briefings', json=draft().model_dump())
        assert created.status_code == 201
        detail = await client.get('/api/briefings/' + created.json()['id'])
        assert detail.json()['task_id'] == created.json()['task_id']
        assert 'prompt' not in detail.json() and 'task_request_id' not in detail.json()
        assert (await client.get('/api/briefings', params={**params, 'timezone': 'bad/timezone'})).status_code == 422
        assert len(hermes.starts) == 1
