"""Join rendering/rate admission under the real, unprivileged PostgreSQL role."""
import json
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from starlette.requests import Request

from test_control_postgres import pg
from wearing.cloud.control import OIDCStateCache, digest, states
from wearing.cloud.join import JoinFlow


@pytest.fixture
def flow(pg):
    # Only this disposable QA global rate bucket is reset, not account data.
    with pg['operator_store'].transaction() as db:
        db.execute(delete(states).where(states.c.id_hash==digest('join-rate:global')))
    return JoinFlow(SimpleNamespace(issuer=pg['issuer'],public_origin='https://join.example'),
                    pg['web'],OIDCStateCache(pg['web']),None,None,None,lambda request:None)


def test_rate_uses_delete_insert_without_web_update_grant(pg,flow):
    binding=secrets.token_urlsafe(32)
    for _ in range(24):assert flow._limit(binding)
    assert not flow._limit(binding)
    with pg['web'].transaction(state_hash=digest('join-rate:'+binding)) as db:
        assert db.scalar(select(states.c.value))=='24'
    with pytest.raises(DBAPIError),pg['web'].transaction(state_hash=digest('join-rate:'+binding)) as db:
        db.execute(text("UPDATE wearing_control.wearing_oidc_states SET value='0'"))


def test_rate_concurrent_requests_admit_exactly_24(pg,flow):
    binding=secrets.token_urlsafe(32)
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(lambda _:flow._limit(binding),range(30)))==24


@pytest.mark.asyncio
async def test_render_holds_private_continuation_only_in_scoped_single_use_pg_state(pg,flow):
    request=Request({'type':'http','method':'GET','path':'/join','headers':[],'session':{}})
    context={'code_hash':'a'*64,'mobile':{'state':'synthetic-mobile-state','challenge':'synthetic-challenge'}}
    response=await flow.render(request,context)
    html=response.body.decode()
    ticket=re.search(r'name="ticket" value="([A-Za-z0-9_-]{43})"',html)[1]
    assert response.status_code==200
    assert all(value not in html for value in ('a'*64,'synthetic-mobile-state','synthetic-challenge'))
    assert set(request.session)=={'join_binding'}
    with pg['web'].transaction() as db:assert db.execute(select(states)).all()==[]
    with pg['web'].transaction(state_hash=digest('foreign-form')) as db:
        assert db.execute(select(states).where(states.c.id_hash==digest('join-form:'+ticket))).all()==[]
    stored=json.loads(await flow.cache.get('join-form:'+ticket))
    assert stored['code_hash']==context['code_hash'] and stored['mobile']==context['mobile']
    assert stored['binding']==digest(request.session['join_binding'])
    assert await flow.cache.get('join-form:'+ticket) is None
