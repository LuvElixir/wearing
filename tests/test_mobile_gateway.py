import base64
import hashlib
from urllib.parse import urlparse, parse_qs

import httpx
import pytest
from sqlalchemy import select, update
from wearing.cloud.control import states, sessions
from test_gateway import lab, login, ORIGIN

VERIFIER = 'v' * 64
STATE = 's' * 48
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b'=').decode()

async def authorize(client, provider, subject='alice'):
    response = await client.get('/auth/mobile/start', params={'challenge': CHALLENGE, 'state': STATE})
    assert response.status_code == 302
    response = await client.get('/auth/callback', params=provider.authorize(response.headers['location'], subject))
    assert response.status_code == 303
    url = urlparse(response.headers['location'])
    assert url.scheme == 'pajio' and url.netloc == 'auth'
    params = {k:v[0] for k,v in parse_qs(url.query).items()}
    assert set(params) == {'code', 'state'} and params['state'] == STATE
    return {**params, 'verifier': VERIFIER}

async def test_native_pkce_handoff_rejects_wrong_state_verifier_replay_and_tokens_never_in_redirect(tmp_path):
    async with lab(tmp_path) as (*_, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            body = await authorize(client, provider)
            assert (await client.get('/auth/session')).status_code == 401
            for wrong in ({**body,'verifier':'z'*64}, {**body,'state':'z'*48}):
                assert (await client.post('/auth/mobile/exchange', json=wrong)).status_code == 400
            response = await client.post('/auth/mobile/exchange', json=body)
            assert response.status_code == 200
            data = response.json()
            assert data['tenant_id'] == 'tenant_A' and len(data['access_token']) == 64
            assert 'private-' not in response.text
            assert (await client.post('/auth/mobile/exchange', json=body)).status_code == 400
            assert (await client.get('/auth/session')).status_code == 401
            client.headers['Authorization'] = 'Bearer ' + data['access_token']
            assert (await client.get('/auth/session')).json()['tenant_id'] == 'tenant_A'
            boot = (await client.get('/api/bootstrap')).json()
            assert (await client.post('/api/conversation', headers={'X-Wearing-Token':boot['token']}, json={'content':'native-only test'})).status_code == 201
            assert (await client.post('/api/conversation', headers={'X-Wearing-Token':boot['token'], 'Origin':'https://bad.example'},json={'content':'denied'})).status_code == 403
            assert (await client.post('/auth/tenant', json={'tenant_id':'tenant_B'})).status_code == 403
            assert (await client.post('/auth/logout')).json()['logged_out']
            assert (await client.get('/api/bootstrap')).status_code == 401

async def test_native_handoff_expiry_uninvited_and_cookie_cannot_rescue_bad_bearer(tmp_path):
    async with lab(tmp_path) as (_, _, _, control, _, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            assert (await client.get('/auth/mobile/start',params={'challenge':'bad','state':STATE})).status_code==422
            body=await authorize(client,provider)
            with control.engine.begin() as db: db.execute(update(states).values(expires=1))
            assert (await client.post('/auth/mobile/exchange',json=body)).status_code==400
            body=await authorize(client,provider,'uninvited')
            assert (await client.post('/auth/mobile/exchange',json=body)).status_code==403
            await login(client,provider)
            assert (await client.get('/api/bootstrap',headers={'Authorization':'Bearer bad'})).status_code==401
            assert (await client.get('/api/bootstrap',headers={'Authorization':'Bearer '+'z'*64})).status_code==401
            assert (await client.get('/api/bootstrap')).status_code==200

async def test_native_webview_cookie_and_membership_revoke_do_not_cross_tenants(tmp_path):
    async with lab(tmp_path) as (_, _, _, control, _, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            body=await authorize(client,provider)
            data=(await client.post('/auth/mobile/exchange',json=body)).json()
            response=await client.get('/',headers={'Authorization':'Bearer '+data['access_token']})
            assert response.status_code==200 and 'httponly' in response.headers['set-cookie']
            assert (await client.get('/auth/session')).json()['tenant_id']=='tenant_A'
            control.grant('https://identity.example','alice','tenant_A',active=False)
            assert (await client.get('/api/bootstrap',headers={'Authorization':'Bearer '+data['access_token']})).status_code==401
            assert (await client.get('/api/bootstrap')).status_code==401

async def test_native_handoff_single_winner_and_body_cap(tmp_path):
    import asyncio
    async with lab(tmp_path) as (*_, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            body=await authorize(client,provider)
            results=await asyncio.gather(*(client.post('/auth/mobile/exchange',json=body) for _ in range(4)))
            assert sorted(r.status_code for r in results)==[200,400,400,400]
            assert (await client.post('/auth/mobile/exchange',content=b'x'*2049)).status_code==413

async def test_gateway_replaces_client_notification_lease_with_verified_session_expiry(tmp_path):
    import time
    async with lab(tmp_path) as (_, _, _, _, workers, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            body=await authorize(client,provider)
            data=(await client.post('/auth/mobile/exchange',json=body)).json()
            client.headers['Authorization']='Bearer '+data['access_token']
            response=await client.get('/api/bootstrap',headers={'X-Pajio-Session-Expires':'999999999999'})
            assert response.status_code==200
            forwarded=workers.requests[-1].headers
            expiry=float(forwarded['x-pajio-session-expires'])
            assert time.time()<expiry<=time.time()+28800
            assert forwarded['x-wearing-tenant']=='tenant_A'
            assert forwarded['authorization']!='Bearer '+data['access_token']
            assert '999999999999' not in response.text

async def test_native_and_embedded_sessions_cannot_drift_to_another_tenant(tmp_path):
    async with lab(tmp_path) as (_, _, _, control, workers, provider, app):
        from test_gateway import ISSUER
        control.grant(ISSUER,'alice','tenant_B')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            body=await authorize(client,provider)
            session=(await client.post('/auth/mobile/exchange',json=body)).json()
            token=session['access_token']
            headers={'Authorization':'Bearer '+token,'X-Pajio-Expected-Tenant':'tenant_A'}
            assert (await client.get('/',headers=headers)).status_code==200
            assert (await client.post('/auth/tenant',headers=headers,json={'tenant_id':'tenant_B'})).status_code==403
            account=(await client.get('/auth/session')).json()
            assert (await client.post('/auth/tenant',headers={'Origin':ORIGIN,'X-Wearing-Csrf':account['csrf']},json={'tenant_id':'tenant_B'})).status_code==403
            # Even an operator-side mutation of this SID cannot send an old App
            # draft to a new tenant or return that tenant's private data.
            control.switch(token,'tenant_B')
            count=len(workers.requests)
            for path in ['/api/bootstrap','/api/conversation']:
                assert (await client.get(path,headers=headers)).status_code==401
            assert (await client.post('/api/conversation',headers=headers,json={'content':'must remain local'})).status_code==401
            assert (await client.get('/api/bootstrap')).status_code==401
            assert len(workers.requests)==count
