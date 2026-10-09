"""Authenticated signaling to operator-pinned media hosts; never carries pixels/input.

The App receives short-lived TURN credentials, never the media host credential.
DeviceGateway on the host remains authoritative at offer, frame and input time.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import ssl
import time
from urllib.parse import urlparse

import httpx

from .cloud.instance import read_private
from .cloud.relay import RelayError
from .cloud import device_access


def configuration(store):
    path = getattr(store, 'media_config', None)
    if path is None:
        raise RelayError('private_gateway_unavailable', 409)
    try:
        value = json.loads(read_private(Path(path)))
        if value.get('version') != 1 or value.get('enabled') is not True:
            raise ValueError()
        if not isinstance(value.get('hosts'), dict) or not isinstance(value.get('turn'), dict):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError):
        raise RelayError('private_gateway_unavailable', 409) from None


def confirmed(store, identity, actor, resource, session_id=None, epoch=None):
    with store.tx() as db:
        connector, spec = device_access.owned(db, identity, resource)
        device_access.expire(db)
        row = db.execute('SELECT * FROM human_access WHERE resource=?', (resource,)).fetchone()
        if not row or row['actor'] != actor:
            raise RelayError('resource_not_paired', 404)
        state = device_access.public(store, db, connector, spec, row)
        if session_id is not None and (row['session'] != session_id or row['epoch'] != epoch):
            raise RelayError('human_session_changed', 409)
        if (not state['supported'] or state['state'] != 'human_private' or not state['device_confirmed']
                or not connector['connection'] or (connector['expires'] or 0) <= time.time()
                or not json.loads(connector['human_availability']).get(resource)):
            raise RelayError('human_session_not_active', 409)
        return state, {'tenant_id': store.tenant, 'identity_id': identity, 'user_id': actor,
                       'connector_id': connector['id'], 'resource_id': resource}


def host_for(config, scope):
    entry = config['hosts'].get(scope['resource_id'])
    try:
        if not isinstance(entry, dict) or any(entry.get(k) != scope[k] for k in ('identity_id', 'connector_id')):
            raise ValueError()
        url = urlparse(entry['url'])
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.path not in ('', '/') or url.query or url.fragment):
            raise ValueError()
        if not isinstance(entry['token'], str) or not 32 <= len(entry['token']) <= 256:
            raise ValueError()
        for key in ('ca', 'client_cert', 'client_key'):
            if not Path(entry[key]).is_absolute():
                raise ValueError()
        return entry
    except (KeyError, TypeError, ValueError):
        raise RelayError('private_gateway_unavailable', 409) from None


def ice_servers(config, state):
    try:
        turn = config['turn']
        urls, secret = turn['urls'], turn['secret']
        if (not isinstance(urls, list) or not 1 <= len(urls) <= 4
                or not all(isinstance(u, str) and u.startswith(('turn:', 'turns:')) and len(u) < 300 for u in urls)
                or not isinstance(secret, str) or len(secret) < 32):
            raise ValueError()
        # Absolute session deadline; reconnects cannot turn a short grant into a
        # permanent TURN credential. Host/input ownership may expire sooner.
        deadline = min(int(state['expires_at']), int(time.time()) + 600)
        if deadline <= time.time():
            raise ValueError()
        username = str(deadline) + ':' + state['session_id']
        password = base64.b64encode(hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
        return [{'urls': urls, 'username': username, 'credential': password}]
    except (KeyError, TypeError, ValueError):
        raise RelayError('private_gateway_unavailable', 409) from None


def transport(store, identity, actor, resource):
    state, scope = confirmed(store, identity, actor, resource)
    config = configuration(store)
    host_for(config, scope)
    return {'kind': 'webrtc', 'session_id': state['session_id'], 'epoch': state['epoch'],
            'gateway_epoch': state['gateway_epoch'], 'expires_at': state['expires_at'],
            'ice_servers': ice_servers(config, state)}


async def offer(store, identity, actor, resource, *, session_id, epoch, sdp, type, client=None):
    if type != 'offer' or not isinstance(sdp, str) or not sdp.startswith('v=0') or len(sdp) > 65536:
        raise RelayError('invalid_media_offer', 422)
    state, scope = confirmed(store, identity, actor, resource, session_id, epoch)
    config = configuration(store)
    entry = host_for(config, scope)
    body = {'scope': scope, 'session_id': session_id, 'epoch': epoch,
            'gateway_epoch': state['gateway_epoch'], 'sdp': sdp, 'type': type,
            'ice_servers': ice_servers(config, state)}
    owned_client = client is None
    try:
        if client is None:
            tls = ssl.create_default_context(cafile=entry['ca'])
            tls.load_cert_chain(entry['client_cert'], entry['client_key'])
            client = httpx.AsyncClient(verify=tls, trust_env=False, follow_redirects=False,
                                       timeout=httpx.Timeout(40, connect=5))
        async with client.stream('POST', entry['url'].rstrip('/') + '/v1/offer', json=body,
                                 headers={'Authorization': 'Bearer ' + entry['token']}) as response:
            if response.status_code != 200:
                raise RelayError('media_host_unavailable', 409)
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 131072:
                    raise RelayError('invalid_media_answer', 502)
        answer = json.loads(raw)
        if (not isinstance(answer, dict) or answer.get('type') != 'answer' or not isinstance(answer.get('sdp'), str)
                or not answer['sdp'].startswith('v=0') or len(answer['sdp']) > 65536
                or answer.get('gateway_epoch').__class__ is not int
                or answer.get('gateway_epoch') != state['gateway_epoch']):
            raise RelayError('invalid_media_answer', 502)
        current, _ = confirmed(store, identity, actor, resource, session_id, epoch)
        if current['gateway_epoch'] != state['gateway_epoch']:
            raise RelayError('human_session_changed', 409)
        return {'type': 'answer', 'sdp': answer['sdp'], 'gateway_epoch': answer['gateway_epoch']}
    except (httpx.HTTPError, OSError, ValueError, TypeError):
        raise RelayError('media_host_unavailable', 409) from None
    finally:
        if owned_client and client is not None:
            await client.aclose()
