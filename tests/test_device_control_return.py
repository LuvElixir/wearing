"""Real Core HTTP -> persistent relay: ordinary resume never releases a private pause."""
import httpx

from wearing.app import create_app
from wearing.cloud import relay
from wearing.cloud.relay import ResourceControl
from wearing.config import Settings
from test_device_access_relay_integration import ACTOR, RESOURCE, setup


async def test_private_paused_resume_is_refused_with_actionable_copy_and_no_mutation(tmp_path, monkeypatch):
    fixture = setup(tmp_path / 'fixture', ready=True)
    store = fixture.store
    human = store.request_human('daily', ACTOR, RESOURCE, expected_generation=0, request_id='test_private_resume')
    before = store.close_human('daily', ACTOR, RESOURCE, session_id=human['session_id'], epoch=human['epoch'])
    assert before['state'] == 'paused'
    app = create_app(Settings(tmp_path / 'core'), engine_autostart=False, local_devices=False)
    monkeypatch.setattr(relay, 'instance_relay', lambda _root: store)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
            response = await client.post('/api/devices/control', json={'resource_id': RESOURCE, 'paused': False,
                                                                        'expected_generation': before['control_generation']})
            assert response.status_code == 409
            assert '查看画面并明确交还' in response.json()['detail']
            assert 'human_session_requires_explicit_return' not in response.text
            assert store.human_status('daily', ACTOR, RESOURCE) == before
            assert store.inventory('daily')[0]['paused'] is True
    finally:
        await app.state.service.hermes.close()


async def test_ordinary_pause_still_resumes_through_existing_generation_gate(tmp_path, monkeypatch):
    fixture = setup(tmp_path / 'fixture', ready=True)
    store = fixture.store
    store.control('daily', ResourceControl(resource_id=RESOURCE, paused=True, expected_generation=0))
    app = create_app(Settings(tmp_path / 'core'), engine_autostart=False, local_devices=False)
    monkeypatch.setattr(relay, 'instance_relay', lambda _root: store)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            client.headers['X-Wearing-Token'] = (await client.get('/api/bootstrap')).json()['token']
            result = await client.post('/api/devices/control', json={'resource_id': RESOURCE, 'paused': False, 'expected_generation': 1})
            assert result.status_code == 200
            assert result.json() == {'resource_id': RESOURCE, 'paused': False, 'generation': 2}
            assert store.inventory('daily')[0]['control_pending'] is True
    finally:
        await app.state.service.hermes.close()
