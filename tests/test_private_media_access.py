"""Signaling authorization and races; synthetic SDP, no media/device claims."""
import json
from types import SimpleNamespace

import httpx
import pytest

from wearing.cloud.relay import RelayStore, ConnectionRequest, PairRequest, PollRequest, RelayError
from wearing.private_media_access import offer, transport


@pytest.fixture
def media(tmp_path):
    actor, token, resource = 'a' * 64, 'b' * 64, 'computer_media_test'
    config = tmp_path / 'media.json'
    store = RelayStore(tmp_path / 'relay', 'tenant_media', human_access_ready=True, media_config=config)
    spec = {'resource_id': resource, 'name': 'Test desktop', 'kind': 'computer', 'methods': ['computer.status']}
    bundle = store.pair_code('daily', [spec], [])
    store.pair(PairRequest(code=bundle['code'], token=token))
    connection = store.connect(token, ConnectionRequest())['connection_id']
    config.write_text(json.dumps({'version': 1, 'enabled': True,
        'hosts': {resource: {'identity_id': 'daily', 'connector_id': bundle['connector_id'],
                            'url': 'https://pinned.invalid:9443', 'token': 's' * 64,
                            'ca': '/test/ca', 'client_cert': '/test/cert', 'client_key': '/test/key'}},
        'turn': {'urls': ['turn:turn.invalid:3478?transport=udp'], 'secret': 't' * 64}}))
    config.chmod(0o600)
    def poll(acks=None):
        return store.poll(token, PollRequest(connection_id=connection, availability={resource: True},
                          human_access_ready=True, human_availability={resource: True}, human_acks=acks or {}))
    poll()
    state = store.request_human('daily', actor, resource, expected_generation=0, request_id='request_media')
    control = poll()['human_controls'][0]
    ack = {resource: {'session_id': state['session_id'], 'epoch': state['epoch'],
                     'revision': control['revision'], 'gateway_epoch': 7, 'state': 'human_private'}}
    return SimpleNamespace(store=store, actor=actor, token=token, rid=resource, state=state,
                           poll=poll, ack=ack, config=config, bundle=bundle)


def test_desktop_supported_but_media_waits_for_device_ack(media):
    assert media.state['supported'] is True
    with pytest.raises(RelayError, match='human_session_not_active'):
        transport(media.store, 'daily', media.actor, media.rid)
    media.poll(media.ack)
    result = transport(media.store, 'daily', media.actor, media.rid)
    assert result['gateway_epoch'] == 7 and result['epoch'] == media.state['epoch']
    assert result['ice_servers'][0]['username'].endswith(':' + media.state['session_id'])
    assert 't' * 64 not in json.dumps(result) and 's' * 64 not in json.dumps(result)
    assert 'pinned.invalid' not in json.dumps(result)


def test_other_owner_identity_revocation_and_bad_pin_cannot_get_media(media):
    media.poll(media.ack)
    for identity, actor in [('daily', 'c' * 64), ('other', media.actor)]:
        with pytest.raises(RelayError):
            transport(media.store, identity, actor, media.rid)
    conf = json.loads(media.config.read_text())
    conf['hosts'][media.rid]['connector_id'] = 'wrong_connector'
    media.config.write_text(json.dumps(conf))
    with pytest.raises(RelayError, match='private_gateway_unavailable'):
        transport(media.store, 'daily', media.actor, media.rid)
    media.store.revoke(media.bundle['connector_id'])
    with pytest.raises(RelayError):
        transport(media.store, 'daily', media.actor, media.rid)


async def test_offer_is_pinned_scope_and_credentials_are_not_returned(media):
    media.poll(media.ack)
    def host(request):
        assert str(request.url) == 'https://pinned.invalid:9443/v1/offer'
        body = json.loads(request.content)
        assert body['scope']['user_id'] == media.actor and body['scope']['resource_id'] == media.rid
        assert body['gateway_epoch'] == 7
        assert request.headers['authorization'] == 'Bearer ' + 's' * 64
        return httpx.Response(200, json={'type': 'answer', 'sdp': 'v=0\r\nsynthetic', 'gateway_epoch': 7,
                                       'token': 'must-not-return'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(host)) as client:
        result = await offer(media.store, 'daily', media.actor, media.rid,
                             session_id=media.state['session_id'], epoch=media.state['epoch'],
                             sdp='v=0\r\nsynthetic', type='offer', client=client)
    assert set(result) == {'type', 'sdp', 'gateway_epoch'}


async def test_close_during_offer_discards_answer_and_stale_epoch_never_contacts_host(media):
    media.poll(media.ack)
    seen = []
    def host(request):
        seen.append(request)
        media.store.close_human('daily', media.actor, media.rid,
                                session_id=media.state['session_id'], epoch=media.state['epoch'])
        return httpx.Response(200, json={'type': 'answer', 'sdp': 'v=0\r\nsynthetic', 'gateway_epoch': 7})
    async with httpx.AsyncClient(transport=httpx.MockTransport(host)) as client:
        values = dict(session_id=media.state['session_id'], epoch=media.state['epoch'],
                      sdp='v=0\r\nsynthetic', type='offer', client=client)
        with pytest.raises(RelayError):
            await offer(media.store, 'daily', media.actor, media.rid, **{**values, 'epoch': 99})
        assert not seen
        with pytest.raises(RelayError):
            await offer(media.store, 'daily', media.actor, media.rid, **values)
        assert len(seen) == 1
    assert media.store.human_status('daily', media.actor, media.rid)['state'] == 'paused'


@pytest.mark.parametrize('reply', [
    {'type': 'answer', 'sdp': 'v=0\r\nsynthetic', 'gateway_epoch': 8},
    {'type': 'answer', 'sdp': 'x' * 70000, 'gateway_epoch': 7},
    {'type': 'offer', 'sdp': 'v=0\r\nsynthetic', 'gateway_epoch': 7},
])
async def test_malformed_or_wrong_epoch_answer_rejected(media, reply):
    media.poll(media.ack)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply))) as client:
        with pytest.raises(RelayError):
            await offer(media.store, 'daily', media.actor, media.rid,
                        session_id=media.state['session_id'], epoch=media.state['epoch'],
                        sdp='v=0\r\nsynthetic', type='offer', client=client)
