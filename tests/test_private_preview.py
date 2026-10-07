import json
from urllib.parse import urlparse, parse_qs

import httpx
import pytest

from wearing.cloud.instance import initialize_instance
from wearing.cloud.preview import create_preview_app

ORIGIN='http://127.0.0.1:18865'


class RawJSON(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"ok":true}'


async def login(client, root):
    access=parse_qs(urlparse(json.loads((root/'preview-access.json').read_text())['url']).fragment)['access'][0]
    return await client.post('/auth/local',json={'access':access},headers={'Origin':ORIGIN})


async def test_two_local_entries_keep_independent_sessions_on_the_same_hostname(tmp_path):
    a,b=tmp_path/'a',tmp_path/'b'
    second='http://127.0.0.1:18868'
    initialize_instance(a,'tenant_a',ORIGIN);initialize_instance(b,'tenant_b',second)
    def worker(_):return httpx.Response(200,stream=RawJSON())
    x=create_preview_app(a,'http://127.0.0.1:18866',worker_transport=httpx.MockTransport(worker))
    y=create_preview_app(b,'http://127.0.0.1:18867',worker_transport=httpx.MockTransport(worker))
    assert x.state.cookie_name!=y.state.cookie_name
    async with x.router.lifespan_context(x),y.router.lifespan_context(y),httpx.AsyncClient(transport=httpx.ASGITransport(app=x),base_url=ORIGIN) as c:
        assert (await login(c,a)).status_code==200
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=y),base_url=second,cookies=c.cookies) as d:
            assert (await d.get('/api/bootstrap')).status_code==401
            access=parse_qs(urlparse(json.loads((b/'preview-access.json').read_text())['url']).fragment)['access'][0]
            assert (await d.post('/auth/local',json={'access':access},headers={'Origin':second})).status_code==200
            c.cookies.update(d.cookies)
            assert (await c.get('/auth/session')).json()['tenant_id']=='tenant_a'
            assert (await d.get('/auth/session')).json()['tenant_id']=='tenant_b'


async def test_private_handoff_is_one_use_origin_bound_and_never_forwards_browser_credentials(tmp_path):
    root=tmp_path/'preview'
    initialize_instance(root,'tenant_test',ORIGIN)
    incoming=[]
    def worker(request):
        incoming.append(request)
        assert request.headers['Authorization']=='Bearer '+(root/'gateway.key').read_text().strip()
        assert request.headers['X-Wearing-Tenant']=='tenant_test'
        assert request.headers['Host']=='127.0.0.1:18865'
        assert 'cookie' not in request.headers
        return httpx.Response(200,stream=RawJSON(),headers={'Content-Type':'application/json','Set-Cookie':'must-not-cross=1','Content-Security-Policy':"default-src 'self'"})
    app=create_preview_app(root,'http://127.0.0.1:18866',worker_transport=httpx.MockTransport(worker))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as c:
        assert (await c.get('/api/bootstrap')).status_code==401
        assert (await c.get('/internal/runtime')).status_code==404
        assert (await c.get('/auth/entry.js')).status_code==200
        assert (await c.post('/auth/local',json={'access':'bad'},headers={'Origin':'https://foreign.example'})).status_code==403
        assert (await c.post('/auth/local',content='x'*257,headers={'Origin':ORIGIN})).status_code==400
        assert (await login(c,root)).status_code==200
        assert (await login(c,root)).status_code==401
        assert app.state.cookie_name in c.cookies
        assert (await c.get('/auth/session')).json()['mode']=='private_ssh_preview'
        r=await c.get('/api/bootstrap',headers={'Authorization':'Bearer browser-key','X-Wearing-Tenant':'tenant_other'})
        assert r.status_code==200 and 'set-cookie' not in r.headers
        assert r.headers['content-security-policy']=="default-src 'self'"
        assert (await c.post('/api/devices/control',json={})).status_code==403
        assert (await c.post('/api/devices/control',json={},headers={'Origin':ORIGIN,'X-Wearing-Token':'page-token'})).status_code==200
        assert incoming[-1].headers['X-Wearing-Token']=='page-token'
        assert (await c.get('/api/bootstrap',headers={'Host':'evil.example'})).status_code==400
        old_cookie=dict(c.cookies)
    restarted=create_preview_app(root,'http://127.0.0.1:18866',worker_transport=httpx.MockTransport(worker))
    async with restarted.router.lifespan_context(restarted), httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),base_url=ORIGIN,cookies=old_cookie) as c:
        assert (await c.get('/api/bootstrap')).status_code==401
        assert (await login(c,root)).status_code==200


@pytest.mark.parametrize('origin,upstream',[
    ('https://wearing.example','http://127.0.0.1:18866'),
    (ORIGIN,'https://external.example'),(ORIGIN,'http://127.0.0.1:18865'),
    (ORIGIN,'http://127.0.0.1:18866/path')])
def test_preview_refuses_public_listener_or_arbitrary_upstream(tmp_path,origin,upstream):
    root=tmp_path/'preview';initialize_instance(root,'tenant_test',origin)
    with pytest.raises(ValueError):create_preview_app(root,upstream)
