from pathlib import Path
import re

import httpx
from starlette.applications import Starlette
from starlette.routing import Route

from wearing.cloud.auth_pages import ASSETS, auth_asset, page


def test_registration_markup_escapes_untrusted_values_and_keeps_nonce_policy():
    response = page('"<script>', stage='account', username='"><img src=x onerror=alert(1)>',
                    error='<svg onload=alert(1)>', issuer_origin='https://id.example')
    html = response.body.decode()
    assert '<svg onload=' not in html and '<img src=x' not in html
    assert '&lt;svg onload=' in html and '&quot;&gt;&lt;img' in html
    nonce = re.search(r'<style nonce="([^"]+)"', html)[1]
    assert f"script-src 'nonce-{nonce}'" in response.headers['content-security-policy']
    assert "default-src 'none'" in response.headers['content-security-policy']
    assert 'unsafe-inline' not in response.headers['content-security-policy']
    assert response.headers['cache-control'] == 'no-store'
    assert 'autocomplete="new-password"' in html and 'type="button" data-password-toggle' in html
    # Server policy counts Unicode code points; HTML length attributes count
    # UTF-16 code units and would truncate valid long non-BMP passphrases.
    password = re.search(r'<input id="password"[^>]+>', html)[0]
    assert 'minlength' not in password and 'maxlength' not in password


async def test_only_explicit_login_assets_are_public():
    app = Starlette(routes=[Route('/auth/art/{name:path}', auth_asset, methods=['GET','HEAD'])])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://pajio.example') as client:
        for path in ('auth.js',):
            response = await client.get('/auth/art/' + path)
            assert response.status_code == 200
            assert response.headers['x-content-type-options'] == 'nosniff'
        for path in ('bear-resting.png','bear-privacy.png','auth.css','../../gateway.json','%2E%2E%2Fgateway.json','/etc/passwd'):
            assert (await client.get('/auth/art/' + path)).status_code == 404


def test_idp_theme_reuses_assets_and_preserves_standard_authentication_templates():
    theme = Path(__file__).parents[1] / 'deploy/keycloak/pajio-theme/login'
    assert not list(theme.glob('*.ftl'))
    assert 'parent=keycloak.v2' in (theme/'theme.properties').read_text()
    for source, target in [('auth.css','css/pajio-base.css'),('auth.js','js/pajio.js')]:
        assert (ASSETS/source).read_bytes() == (theme/'resources'/target).read_bytes()
