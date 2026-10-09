import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from wearing.notifications import NotificationConfig, NotificationService, NotificationError
from wearing.quiet_hours import quiet_until, validate_quiet_hours
from wearing.store import Store

PROJECT = '12345678-abcd-1234-abcd-123456789abc'
INSTALL = 'synthetic-phone-001'
TOKEN = 'ExpoPushToken[syntheticToken12345]'
def stamp(value): return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()
def policy(start=1320, end=480, zone='Asia/Shanghai'):
    return dict(enabled=True, start_minute=start, end_minute=end, timezone=zone)


def test_overnight_boundary_and_daytime_window():
    p = policy()
    assert quiet_until(p, stamp('2026-10-08T13:59:59')) is None
    assert quiet_until(p, stamp('2026-10-08T14:00:00')) == stamp('2026-10-09T00:00:00')
    assert quiet_until(p, stamp('2026-10-09T00:00:00')) is None
    assert quiet_until(policy(720, 780, 'UTC'), stamp('2026-10-08T12:15:30')) == stamp('2026-10-08T13:00:00')
    assert quiet_until({**p, 'enabled': False}, stamp('2026-10-08T14:00:00')) is None


def test_dst_missing_and_repeated_hours_follow_actual_local_clock():
    # Spring 02:30 never occurs: first allowed instant is 03:00 local.
    assert quiet_until(policy(60, 150, 'America/New_York'), stamp('2026-03-08T06:20:00')) == stamp('2026-03-08T07:00:00')
    # Autumn 01:00 repeats, both occurrences remain inside 00:30–02:30.
    assert quiet_until(policy(30, 150, 'America/New_York'), stamp('2026-11-01T04:45:00')) == stamp('2026-11-01T07:30:00')


@pytest.mark.parametrize('values', [(True,0,0,'UTC'),(True,False,10,'UTC'),(True,0,1440,'UTC'),(True,0,1,'../UTC'),(True,0,1,'Missing/Zone'),(1,0,1,'UTC')])
def test_invalid_policy_rejected(values):
    with pytest.raises(ValueError): validate_quiet_hours(*values)


@pytest.fixture
async def env(tmp_path):
    now = [stamp('2026-10-08T15:00:00')]
    calls = []
    def request(req):
        calls.append(req)
        return httpx.Response(200, json={'data': {'status':'ok', 'id':f'ticket-{len(calls)}'}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(request))
    store = Store(tmp_path / 'quiet.db')
    service = NotificationService(store, config=NotificationConfig(True,PROJECT), client=client, clock=lambda:now[0])
    yield service, store, now, calls
    await client.aclose()


def complete(store):
    task = store.create('synthetic quiet-hours task','hermes')
    store.update(task['id'], status='completed_unverified', output='synthetic result')
    return task['id']


async def test_quiet_defer_restart_release_and_other_installation_not_starved(env):
    s, store, now, calls = env
    s.register('daily',INSTALL,TOKEN,PROJECT,'ios')
    s.register('daily',INSTALL+'other','ExpoPushToken[syntheticOther123]',PROJECT,'ios')
    saved = s.update_preferences('daily',INSTALL,0,True,1320,480,'Asia/Shanghai')
    assert saved['revision'] == 1
    task = complete(store)
    await s.tick()
    assert len(calls) == 1 and TOKEN not in calls[0].content.decode()
    with store.connection() as db:
        row = dict(db.execute('SELECT * FROM notification_outbox WHERE installation_id=?',(INSTALL,)).fetchone())
    assert row['state'] == 'pending' and row['attempts'] == 0 and row['error_code'] == 'QuietHours'
    restarted = NotificationService(store, config=s.config,client=s.client,clock=s.clock)
    assert restarted.preferences('daily',INSTALL) == saved
    now[0] = stamp('2026-10-09T00:00:00')
    assert await restarted.send_one()
    assert len(calls) == 2 and calls[-1].content.decode().count(task) == 1
    assert not await restarted.send_one()


async def test_changed_window_rechecks_pending_without_touching_uncertain_deliveries(env):
    s, store, now, calls = env
    s.register('daily',INSTALL,TOKEN,PROJECT,'ios')
    s.update_preferences('daily',INSTALL,0,True,1320,480,'Asia/Shanghai')
    complete(store); await s.tick(); assert calls == []
    with pytest.raises(NotificationError) as error: s.update_preferences('daily',INSTALL,0,False,1320,480,'UTC')
    assert error.value.status == 409
    s.update_preferences('daily',INSTALL,1,False,1320,480,'Asia/Shanghai')
    assert await s.send_one() and len(calls) == 1
    s.update_preferences('daily',INSTALL,2,True,1320,480,'Asia/Shanghai')
    assert not await s.send_one() and len(calls) == 1
    work = store.save_identity('Work')['id']
    assert s.preferences(work,INSTALL)['revision'] == 0


async def test_superseded_or_disabled_held_notification_never_sends(env):
    s, store, now, calls = env
    s.register('daily',INSTALL,TOKEN,PROJECT,'ios')
    s.update_preferences('daily',INSTALL,0,True,1320,480,'Asia/Shanghai')
    task = complete(store); await s.tick()
    store.update(task,status='verified')
    now[0] = stamp('2026-10-09T00:00:00'); await s.tick()
    assert calls == []
    now[0] = stamp('2026-10-09T15:00:00'); complete(store); await s.tick()
    s.disable('daily',INSTALL)
    now[0] = stamp('2026-10-10T00:00:00'); await s.tick()
    assert calls == []


async def test_http_policy_requires_csrf_and_scopes_revision(tmp_path):
    from wearing.app import create_app
    from wearing.config import Settings
    app = create_app(Settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        body = dict(installation_id=INSTALL,revision=0,**policy())
        assert (await client.post('/api/notifications/preferences',json=body)).status_code == 403
        boot = (await client.get('/api/bootstrap')).json()
        headers = {'X-Wearing-Token':boot['token'],'X-Wearing-Identity':'daily'}
        assert (await client.post('/api/notifications/preferences',json=body,headers=headers)).json()['revision'] == 1
        assert (await client.post('/api/notifications/preferences',json=body,headers=headers)).status_code == 409
        assert (await client.post('/api/notifications/preferences',json={**body,'revision':1,'timezone':'bad'},headers=headers)).status_code == 400
        assert (await client.post('/api/notifications/preferences',json={**body,'identity_id':'other'},headers=headers)).status_code == 422
    await app.state.service.hermes.close()
