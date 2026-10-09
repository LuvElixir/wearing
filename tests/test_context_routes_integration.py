"""Real create_app + private tenant boundaries; only synthetic relay inventory."""
import httpx
import pytest

from wearing.account_deletion import digest
from wearing.cloud.account_deletion_tenant import PATH
from wearing.cloud.instance import initialize_instance
from wearing.cloud.relay import RelayStore, PairRequest, ConnectionRequest, PollRequest
from wearing.cloud.worker import create_tenant_app
from wearing.profile import write_private_text

ORIGIN = 'https://fixture.invalid'
A, B, OPERATOR = 'a' * 64, 'b' * 64, 'x' * 64


@pytest.fixture
def tenant(tmp_path, monkeypatch):
    monkeypatch.setenv('PAJIO_TRIAL_LIMITS', '1')
    root = tmp_path / 'instance'
    instance = initialize_instance(root, 'tenant_context', ORIGIN)
    write_private_text(root / 'deletion-operator.key', OPERATOR)
    relay = RelayStore(root / 'data/device-relay', instance.tenant_id)
    bundle = relay.pair_code('daily', [{'resource_id': 'phone_test', 'name': 'Synthetic phone', 'kind': 'android',
                                      'methods': ['phone.mobile_list_elements_on_screen']}], [])
    relay.pair(PairRequest(code=bundle['code'], token='c' * 64))
    connection = relay.connect('c' * 64, ConnectionRequest())['connection_id']
    relay.poll('c' * 64, PollRequest(connection_id=connection, availability={'phone_test': True}))
    app = create_tenant_app(root, engine_autostart=False)
    headers = {'Authorization': 'Bearer ' + (root / 'gateway.key').read_text().strip(),
               'X-Wearing-Tenant': instance.tenant_id, 'X-Pajio-Storage-Scope': A}
    return root, instance, app, headers


async def test_real_context_routes_auth_csrf_identity_and_validation(tenant):
    _, _, app, headers = tenant
    paths = ['/api/chat-imports', '/api/devices/access/phone_test']
    body = {'expected_generation': 0, 'request_id': 'synthetic_request'}
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        for path in paths:
            assert (await client.get(path)).status_code == 401
            assert (await client.get(path, headers=headers | {'X-Wearing-Tenant': 'wrong'})).status_code == 403
            missing_owner = {k: v for k, v in headers.items() if k != 'X-Pajio-Storage-Scope'}
            assert (await client.get(path, headers=missing_owner)).status_code == 401
            assert (await client.get(path, headers=headers | {'X-Pajio-Storage-Scope': 'local'})).status_code == 401
            assert (await client.get(path, headers=headers | {'X-Wearing-Identity': 'unknown'})).status_code == 404
            assert (await client.get(path + '?identity=unknown', headers=headers | {'X-Wearing-Identity': 'daily'})).status_code == 409
        assert (await client.get(paths[1], headers=headers)).json()['supported'] is False
        token = (await client.get('/api/bootstrap', headers=headers)).json()['token']
        mutate = headers | {'X-Wearing-Token': token}
        for path in ['/api/chat-imports', paths[1] + '/request']:
            assert (await client.post(path, json=body, headers=headers)).status_code == 403
            assert (await client.post(path, json=body, headers=mutate | {'Origin': 'https://other.invalid'})).status_code == 403
        invalid = await client.post(paths[1] + '/request', json=body | {'password': 'SYNTHETIC-SECRET'}, headers=mutate)
        assert invalid.status_code == 422 and 'SYNTHETIC-SECRET' not in invalid.text
        assert (await client.post(paths[1] + '/request', json=body, headers=mutate)).status_code == 409
        raw = dict(request_key='synthetic-import-route', confirmed=True, platform='wechat', conversation_title='合成资料',
                   authors=['我'], self_author=None, source_sha256='d' * 64,
                   messages=[{'id': 'm1', 'author': '我', 'text': '合成检索词'}])
        saved = await client.post('/api/chat-imports', json=raw, headers=mutate)
        assert saved.status_code == 200, saved.text
        identifier = saved.json()['import_id']
        assert (await client.get('/api/chat-imports/' + identifier, headers=headers | {'X-Pajio-Storage-Scope': B})).status_code == 404
        assert (await client.get('/api/search?q=合成检索词&kind=chat_import', headers=headers)).json()['items'][0]['target']['import_id'] == identifier
        assert (await client.get('/api/search?q=合成检索词', headers=headers)).json()['items'] == []


async def test_freeze_blocks_every_new_device_route_and_chat_route(tenant):
    _, instance, app, headers = tenant
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        token = (await client.get('/api/bootstrap', headers=headers)).json()['token']
        response = await client.post(PATH, json={'job_id': 'a' * 32, 'plan_revision': 'b' * 64,
            'operation_id': digest(['freeze_tenant']), 'tenant_id': instance.tenant_id, 'instance_id': instance.instance_id,
            'phase': 'freeze_tenant', 'owner_scope': A}, headers={'Authorization': 'Bearer ' + OPERATOR})
        assert response.status_code == 200 and response.json()['state'] == 'done'
        for method, path in [('GET', '/api/devices/access/phone_test'), ('POST', '/api/devices/access/phone_test/request'),
                             ('POST', '/api/devices/access/phone_test/close'), ('POST', '/api/devices/access/phone_test/return'),
                             ('GET', '/api/chat-imports'), ('POST', '/api/chat-imports'),
                             ('GET', '/api/chat-imports/receipts/synthetic-import-route'), ('DELETE', '/api/chat-imports/chi_' + 'f' * 32)]:
            assert (await client.request(method, path, json={}, headers=headers | {'X-Wearing-Token': token})).status_code == 410
