"""Only synthetic phone sessions and data; no actual OS or network calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import pytest
from wearing.native_actions import NativeActions, NativeActionError
from wearing.store import Store

PHONE, SECRET, SESSION = 'a' * 32, 'b' * 64, 'c' * 32
POLICY = {'calendars': [{'id': 'cal', 'title': '测试日历', 'writable': True}],
          'reminders': [{'id': 'rem', 'title': '测试提醒', 'writable': True}],
          'calendar_create': True, 'reminder_create': True, 'location': True}


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    stamp = [datetime(2026, 10, 8, tzinfo=timezone.utc)]
    book = NativeActions(store, lambda: stamp[0])
    device = book.configure('daily', PHONE, SECRET, 0, True, POLICY)
    book.connect('daily', PHONE, SECRET, 1, SESSION, sorted(['calendar.read', 'reminders.read', 'location.read', 'calendar.create', 'reminders.create']))
    task = store.create('合成操作', 'general')
    with store.connection() as db:
        db.execute("UPDATE tasks SET status='running',run_id='synthetic-run' WHERE id=?", (task['id'],))
    return book, stamp, task


def request(book, method='location.read', params=None, key='once'):
    return book.request('daily', PHONE, method, params or {}, key)


def claim(book, r, approve=True):
    return book.claim('daily', PHONE, SECRET, SESSION, r['id'], r['fingerprint'], approve)


def finish(book, r, status='succeeded', code='ok', data=None):
    return book.finish('daily', PHONE, SECRET, SESSION, r['id'], r['fingerprint'], {'status': status, 'code': code, 'data': data or {}})


def test_real_claim_receipt_replay_and_identity_isolation(env):
    book, _, _ = env
    r = request(book)
    assert r['state'] == 'queued'
    assert claim(book, r)['state'] == 'executing'
    result = finish(book, r, data={'latitude': 30, 'longitude': 120, 'accuracy': 25, 'timestamp': '2026-10-08T00:00:00Z'})
    assert result['state'] == 'succeeded'
    assert finish(book, r, data={'latitude': 30, 'longitude': 120, 'accuracy': 25, 'timestamp': '2026-10-08T00:00:00Z'}) == result
    assert request(book) == result
    other = book.store.save_identity('其他')['id']
    assert book.devices(other) == []
    with pytest.raises(NativeActionError):
        book.get(other, r['id'])
    assert SECRET not in json.dumps(result) and SECRET not in json.dumps(book.devices('daily'))


def test_read_is_discarded_after_foreground_ends(env):
    book, _, _ = env
    r = request(book)
    claim(book, r)
    book.disconnect('daily', PHONE, SECRET, SESSION)
    with pytest.raises(NativeActionError):
        finish(book, r, data={'latitude': 30})
    assert book.get('daily', r['id'])['result'] is None
    assert book.devices('daily')[0]['online'] is False


def test_write_has_phone_confirmation_no_replay_and_late_original_receipt(env):
    book, _, _ = env
    r = request(book, 'reminders.create', {'calendar_id': 'rem', 'title': '合成测试'})
    with pytest.raises(NativeActionError):
        finish(book, r)
    claim(book, r)
    with pytest.raises(NativeActionError):
        claim(book, r)
    book.disconnect('daily', PHONE, SECRET, SESSION)
    assert book.get('daily', r['id'])['state'] == 'unknown'
    book.connect('daily', PHONE, SECRET, 1, 'd' * 32, ['reminders.create'])
    with pytest.raises(NativeActionError):
        request(book, 'reminders.create', {'calendar_id': 'rem', 'title': '合成测试'}, 'another')
    assert finish(book, r, data={'id':'native-reminder','calendar_id':'rem','title':'合成测试','notes':'','due':None,'all_day':False,'completed':False,'marker':'pajio://native/'+r['id']})['state'] == 'succeeded'


def test_task_stop_cancels_unclaimed_and_expires_admitted_write(env):
    book, _, task = env
    r = request(book)
    with book.store.connection() as db:
        db.execute("UPDATE tasks SET status='cancelled' WHERE id=?", (task['id'],))
    assert book.get('daily', r['id'])['state'] == 'expired'
    with pytest.raises(NativeActionError):
        claim(book, r)


def test_clock_expiry_and_service_restart_keep_uncertainty(env):
    book, stamp, _ = env
    r = request(book, 'reminders.create', {'calendar_id': 'rem', 'title': '合成测试'})
    claim(book, r)
    stamp[0] += timedelta(seconds=61)
    restarted = NativeActions(Store(book.store.path), book.clock)
    assert restarted.get('daily', r['id'])['state'] == 'unknown'
    with pytest.raises(NativeActionError):
        restarted.connect('daily', PHONE, SECRET, 1, SESSION, ['reminders.create'])
    restarted.connect('daily', PHONE, SECRET, 1, 'e' * 32, ['reminders.create'])
    assert request(restarted, 'reminders.create', {'calendar_id': 'rem', 'title': '合成测试'})['state'] == 'unknown'


@pytest.mark.parametrize('method,params', [('calendar.read', {'calendar_ids':['other'], 'start':'2026-10-08T00:00:00Z', 'end':'2026-10-09T00:00:00Z'}), ('calendar.read', {'calendar_ids':['cal'], 'start':'2026-10-08', 'end':'2026-10-09'}), ('calendar.read', {'calendar_ids':['cal'], 'start':'2026-10-08T00:00:00Z', 'end':'2027-10-09T00:00:00Z'}), ('location.read', {'background': True}), ('reminders.create', {'calendar_id':'rem', 'title':'x', 'attendees':['someone']})])
def test_unselected_unbounded_and_extra_params_rejected(env, method, params):
    with pytest.raises(NativeActionError):
        request(env[0], method, params)


def test_policy_cas_permission_change_and_nonce_mismatch(env):
    book, _, _ = env
    r = request(book)
    with pytest.raises(NativeActionError):
        book.claim('daily', PHONE, 'f' * 64, SESSION, r['id'], r['fingerprint'], True)
    with pytest.raises(NativeActionError):
        request(book, 'location.read', {'bad': True})
    book.configure('daily', PHONE, SECRET, 1, False, POLICY)
    with pytest.raises(NativeActionError):
        claim(book, r)
    with pytest.raises(NativeActionError):
        book.configure('daily', PHONE, SECRET, 1, True, POLICY)
    assert book.get('daily', r['id'])['state'] == 'cancelled'


def test_concurrent_idempotent_submit_single_admission(env):
    book, _, _ = env
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: request(book), range(4)))
    assert len({r['id'] for r in rows}) == 1
    def attempt(_):
        try:
            return claim(book, rows[0])['state']
        except NativeActionError:
            return 'rejected'
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(attempt, range(4))) == ['executing','rejected','rejected','rejected']


def test_http_route_mutations_use_current_identity_not_body(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from wearing.native_actions_api import install_native_action_routes
    book, _, _ = env
    app = FastAPI()
    @app.middleware('http')
    async def scope(req, next):
        req.state.identity_id = 'daily'
        return await next(req)
    install_native_action_routes(app, book)
    client = TestClient(app)
    body = {'installation_id':PHONE,'secret':SECRET,'connection_id':SESSION}
    assert client.post('/api/native-actions/poll', json=body).status_code == 200
    assert client.post('/api/native-actions/poll', json={**body,'identity_id':'other'}).status_code == 422
    assert client.post('/api/native-actions/poll', json={**body,'secret':'wrong'}).status_code == 401
