import httpx

from test_gateway import ORIGIN, lab


async def test_public_information_is_anonymous_static_and_does_not_route_to_a_tenant(tmp_path):
    async with lab(tmp_path) as (_, _, _, _, workers, provider, app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
            for path in ('/privacy', '/support'):
                response = await client.get(path, params={'token': 'never-reflect-this'})
                assert response.status_code == 200
                assert 'ArchieLiew' in response.text
                assert 'tiancaimiaosan233@gmail.com' in response.text
                assert 'never-reflect-this' not in response.text
                assert '深圳市好运加载' not in response.text
                assert '<script' not in response.text
                assert 'set-cookie' not in response.headers
                assert response.headers['referrer-policy'] == 'no-referrer'
                assert "default-src 'none'" in response.headers['content-security-policy']
                head = await client.head(path)
                assert head.status_code == 200 and not head.content
            # The new public endpoints cannot turn an arbitrary tenant route public.
            assert (await client.get('/api/records')).status_code == 401
            assert provider.token_calls == 0
            assert not workers.requests
