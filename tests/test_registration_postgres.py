from pathlib import Path
import uuid

import httpx
import pytest

from test_control_postgres import pg
from test_invitations_postgres import fresh
from test_registration import KEY,PASSWORD,URL,Provider
from wearing.cloud.control import ControlStore,ControlError
from wearing.cloud.invitations import InvitationStore,code_hash
from wearing.cloud.registration import RegistrationBroker,RegistrationError


def test_real_registration_role_recovers_unknown_create_without_admitting_until_oidc(pg,tmp_path):
    if 'registration' not in pg:
        pytest.skip('QA role must include the separate registration login')
    code,_,tenant=fresh(pg)
    reg=ControlStore(pg['registration'],registration=True)
    provider=Provider(lose_first=True)
    broker=RegistrationBroker(reg,tmp_path/'private',issuer=pg['issuer'],provider_url=URL,provider_key=KEY,
                               transport=httpx.MockTransport(provider.handle))
    try:
        with pytest.raises(RegistrationError,match='registration_pending'):
            broker.register(code_hash(code),'alice',PASSWORD)
        assert broker.register(code_hash(code),'alice',PASSWORD)=={'subject':'synthetic_subject'}
        assert [a for a,_ in provider.calls]==['create','inspect']
        with pytest.raises(ControlError):pg['web'].login(pg['issuer'],'synthetic_subject')
        result=InvitationStore(pg['web']).redeem_hash(code_hash(code),issuer=pg['issuer'],subject='synthetic_subject')
        assert result['tenant_id']==tenant
        session=pg['web'].session(pg['web'].login(pg['issuer'],'synthetic_subject'))
        assert pg['web'].private_owner_scope(session,pg['web'].route(session))
    finally:
        broker.close()
