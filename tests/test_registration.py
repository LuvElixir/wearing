"""Synthetic IdP/broker failure injection. Never uses customer passwords."""
import hashlib
import json
import os
from pathlib import Path
import threading
import socket
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor
import uuid

import httpx
import pytest
from filelock import Timeout

from test_invitations import ISSUER, invitation_lab, issue
from wearing.cloud.control import ControlStore, digest
from wearing.cloud.invitations import InvitationStore, InvitationError, code_hash
from wearing.cloud.registration import RegistrationBroker, RegistrationClient, RegistrationError, credentials
from wearing.cloud.registration import private_listener

PASSWORD='Synthetic-Password-42'
KEY='k'*64
URL='http://127.0.0.1:8080/realms/pajio/pajio-registration'


class Provider:
    def __init__(self, *, lose_first=False, conflict=None):
        self.calls=[]
        self.created=None
        self.lose_first=lose_first
        self.conflict=conflict
        self.override_subject=None

    def handle(self, request):
        payload=json.loads(request.content)
        action=request.url.path.rsplit('/',1)[-1]
        self.calls.append((action,set(payload)))
        assert request.headers['authorization']=='Bearer '+KEY
        if action=='create':
            assert payload['password']==PASSWORD
            if self.conflict:
                return httpx.Response(self.conflict[0],json={'code':self.conflict[1]})
            assert self.created is None, 'MUTATION WAS REPLAYED'
            self.created={'subject':'synthetic_subject','registration_id':payload['registration_id']}
            if self.lose_first:
                raise httpx.ReadTimeout('synthetic timeout')
        else:
            assert 'password' not in payload
            if self.created is None:
                return httpx.Response(404,json={'code':'not_found'})
        result=dict(self.created)
        if self.override_subject:result['subject']=self.override_subject
        return httpx.Response(200,json=result)


@pytest.fixture
def broker_lab(invitation_lab,tmp_path):
    ops,web,reg=invitation_lab
    code,_=issue(ops)
    provider=Provider()
    broker=RegistrationBroker(reg,tmp_path/'journal',issuer=ISSUER,provider_url=URL,provider_key=KEY,
                               transport=httpx.MockTransport(provider.handle))
    try:
        yield ops,web,code,provider,broker
    finally:
        broker.close()


def test_success_is_bound_not_membership_and_journal_contains_no_password(broker_lab):
    ops,web,code,provider,broker=broker_lab
    assert broker.register(code_hash(code),'alice',PASSWORD)=={'subject':'synthetic_subject'}
    assert broker.register(code_hash(code),'alice',PASSWORD)=={'subject':'synthetic_subject'}
    assert [a for a,_ in provider.calls]==['create','inspect']
    raw=''.join(p.read_text() for p in broker.root.glob('*.json'))
    for forbidden in (PASSWORD,KEY,code,'alice'):
        assert forbidden not in raw
    journal=json.loads(next(broker.root.glob('*.json')).read_text())
    assert journal['state']=='confirmed' and journal['subject']=='synthetic_subject'
    with pytest.raises(ValueError):web.login(ISSUER,'synthetic_subject')
    result=InvitationStore(web).redeem_hash(code_hash(code),issuer=ISSUER,subject='synthetic_subject')
    assert result['status']=='admitted'


def test_lost_create_response_retries_inspect_only_even_after_broker_restart(broker_lab):
    _,web,code,provider,broker=broker_lab
    provider.lose_first=True
    with pytest.raises(RegistrationError,match='registration_pending'):
        broker.register(code_hash(code),'alice',PASSWORD)
    assert provider.created is not None
    new_store=ControlStore(str(web.engine.url),registration=True)
    resumed=RegistrationBroker(new_store,broker.root,issuer=ISSUER,provider_url=URL,provider_key=KEY,
                               transport=httpx.MockTransport(provider.handle))
    try:
        assert resumed.register(code_hash(code),'alice',PASSWORD)=={'subject':'synthetic_subject'}
        assert [a for a,_ in provider.calls]==['create','inspect']
    finally:resumed.close()


def test_missing_journal_for_previously_reserved_intent_never_creates(broker_lab):
    _,_,code,provider,broker=broker_lab
    intent=uuid.uuid4().hex
    broker.invites.reserve_registration(code_hash(code),issuer=ISSUER,registration_id=intent,username_hash=digest('alice'))
    with pytest.raises(RegistrationError,match='registration_pending'):
        broker.register(code_hash(code),'alice',PASSWORD)
    assert [a for a,_ in provider.calls]==['inspect']
    assert json.loads((broker.root/(intent+'.json')).read_text())['state']=='inflight'
    with pytest.raises(RegistrationError):broker.register(code_hash(code),'alice',PASSWORD)
    assert [a for a,_ in provider.calls]==['inspect','inspect']


def test_fsync_failure_prevents_create_and_retry_is_inspect_only(broker_lab,monkeypatch):
    _,_,code,provider,broker=broker_lab
    with monkeypatch.context() as patch:
        patch.setattr(os,'fsync',lambda fd: (_ for _ in ()).throw(OSError('synthetic disk error')))
        with pytest.raises(RegistrationError,match='registration_pending'):
            broker.register(code_hash(code),'alice',PASSWORD)
    assert provider.calls==[]
    with pytest.raises(RegistrationError):broker.register(code_hash(code),'alice',PASSWORD)
    assert [a for a,_ in provider.calls]==['inspect']


def test_inflight_journal_is_synced_before_mutating_http(broker_lab,monkeypatch):
    _,_,code,provider,broker=broker_lab
    seen=[]
    original=os.fsync
    def fsync(fd):
        seen.append(os.fstat(fd).st_mode)
        return original(fd)
    original_handle=provider.handle
    def handle(request):
        assert len(seen)>=2  # file and containing directory
        assert json.loads(next(broker.root.glob('*.json')).read_text())['state']=='inflight'
        return original_handle(request)
    monkeypatch.setattr(os,'fsync',fsync)
    broker.wire.close();broker.wire=httpx.Client(transport=httpx.MockTransport(handle))
    broker.register(code_hash(code),'alice',PASSWORD)


@pytest.mark.parametrize('response',[(409,'username_unavailable'),(422,'password_policy')])
def test_only_definitive_precreate_rejection_releases_registration(broker_lab,response):
    _,_,code,provider,broker=broker_lab
    provider.conflict=response
    with pytest.raises(RegistrationError):broker.register(code_hash(code),'alice',PASSWORD)
    with pytest.raises(InvitationError):broker.invites.get_registration(code_hash(code),issuer=ISSUER)
    journal=json.loads(next(broker.root.glob('*.json')).read_text())
    assert journal['state']=='rejected'
    provider.conflict=None
    assert broker.register(code_hash(code),'bobx',PASSWORD)=={'subject':'synthetic_subject'}


@pytest.mark.parametrize('response',[(500,'username_unavailable'),(409,'different'),(502,'failed')])
def test_unknown_failure_never_releases_or_replays(broker_lab,response):
    _,_,code,provider,broker=broker_lab
    provider.conflict=response
    with pytest.raises(RegistrationError,match='registration_pending'):broker.register(code_hash(code),'alice',PASSWORD)
    original=broker.invites.get_registration(code_hash(code),issuer=ISSUER)
    with pytest.raises(RegistrationError):broker.register(code_hash(code),'alice',PASSWORD)
    assert original==broker.invites.get_registration(code_hash(code),issuer=ISSUER)
    assert [a for a,_ in provider.calls]==['create','inspect']


def test_changed_password_or_inspected_subject_fails_without_create_or_rebind(broker_lab):
    _,_,code,provider,broker=broker_lab
    broker.register(code_hash(code),'alice',PASSWORD)
    with pytest.raises(RegistrationError):broker.register(code_hash(code),'alice','Another-Password-42')
    assert len(provider.calls)==1
    provider.override_subject='wrong_subject'
    with pytest.raises(RegistrationError,match='registration_pending'):broker.register(code_hash(code),'alice',PASSWORD)
    assert broker.invites.get_registration(code_hash(code),issuer=ISSUER)['subject']=='synthetic_subject'


def test_same_code_parallel_requests_have_one_create(broker_lab):
    _,_,code,provider,broker=broker_lab
    entered,release=threading.Event(),threading.Event()
    original=provider.handle
    def handle(request):
        entered.set();assert release.wait(3)
        return original(request)
    broker.wire.close();broker.wire=httpx.Client(transport=httpx.MockTransport(handle))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(broker.register,code_hash(code),'alice',PASSWORD)
        assert entered.wait(3)
        with pytest.raises(RegistrationError,match='registration_pending'):
            broker.register(code_hash(code),'alice',PASSWORD)
        release.set()
        assert first.result()=={'subject':'synthetic_subject'}
    assert [a for a,_ in provider.calls]==['create']


def test_journal_symlink_or_malformed_never_creates(broker_lab,tmp_path):
    _,_,code,provider,broker=broker_lab
    intent=broker.invites.reserve_registration(code_hash(code),issuer=ISSUER,registration_id=uuid.uuid4().hex,
                                               username_hash=digest('alice'))
    target=tmp_path/'foreign';target.write_text('unchanged')
    path=broker.root/(intent['registration_id']+'.json');path.symlink_to(target)
    with pytest.raises(RegistrationError,match='registration_pending'):broker.register(code_hash(code),'alice',PASSWORD)
    assert provider.calls==[] and target.read_text()=='unchanged'
    path.unlink();path.write_text('{');path.chmod(0o600)
    with pytest.raises(RegistrationError,match='registration_pending'):broker.register(code_hash(code),'alice',PASSWORD)
    assert provider.calls==[]


@pytest.mark.parametrize('password',['short','x'*129,'abcdefghijk\n','abcdefghijk\ud800','abcdefghijk\u0080','abcdefghijk\u009f'])
def test_password_validation_is_non_echoing(password):
    with pytest.raises(RegistrationError) as error:credentials('alice',password)
    assert str(error.value)=='password_invalid'


def test_password_length_counts_unicode_codepoints():
    assert credentials('alice','🙂'*12)==('alice','🙂'*12)
    assert credentials('alice','🙂'*128)==('alice','🙂'*128)
    with pytest.raises(RegistrationError,match='password_invalid'):
        credentials('alice','🙂'*129)


@pytest.mark.asyncio
async def test_broker_body_boundary_preserves_413_without_calling_registration(tmp_path,monkeypatch):
    import wearing.cloud.registration as module
    config=tmp_path/'config.json';config.write_text('{}');config.chmod(0o600)
    class FakeBroker:
        def __init__(self,*args,**kwargs):pass
        def close(self):pass
        def register(self,*args):raise AssertionError('oversized body reached registration')
    monkeypatch.setattr(module,'read_private',lambda path: json.dumps({'database_url':'unused','journal_root':'unused',
        'issuer':'unused','provider_url':'unused','provider_key_file':'unused'}) if path==config else KEY)
    monkeypatch.setattr(module,'ControlStore',lambda *a,**kw:None)
    monkeypatch.setattr(module,'RegistrationBroker',FakeBroker)
    app=module.create_registration_app(config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://broker') as client:
        response=await client.post('/register',content=b'x'*4097)
        assert response.status_code==413 and response.json()['code']=='request_too_large'


@pytest.mark.asyncio
async def test_client_rejects_malformed_success_without_echo():
    client=RegistrationClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'subject':['bad']})))
    with pytest.raises(RegistrationError,match='registration_unavailable'):
        await client.register('a'*64,'alice',PASSWORD)


def test_committed_subject_with_lost_database_response_reconciles_inspect_only(broker_lab,monkeypatch):
    _,_,code,provider,broker=broker_lab
    original=broker.invites.bind_registration_subject
    def bind(*args,**kwargs):
        original(*args,**kwargs)
        raise OSError('synthetic response loss')
    with monkeypatch.context() as patch:
        patch.setattr(broker.invites,'bind_registration_subject',bind)
        with pytest.raises(RegistrationError,match='registration_pending'):
            broker.register(code_hash(code),'alice',PASSWORD)
    assert broker.register(code_hash(code),'alice',PASSWORD)=={'subject':'synthetic_subject'}
    assert [a for a,_ in provider.calls]==['create','inspect']


def test_broker_rejects_nonprivate_or_linked_root(invitation_lab,tmp_path):
    reg=invitation_lab[2]
    public=tmp_path/'public';public.mkdir(mode=0o755)
    with pytest.raises(ValueError):
        RegistrationBroker(reg,public,issuer=ISSUER,provider_url=URL,provider_key=KEY)
    assert public.stat().st_mode & 0o777 == 0o755
    linked=tmp_path/'linked';linked.symlink_to(public,target_is_directory=True)
    with pytest.raises(OSError):
        RegistrationBroker(reg,linked,issuer=ISSUER,provider_url=URL,provider_key=KEY)


@pytest.fixture
def socket_directory():
    # macOS AF_UNIX has a short pathname limit; pytest's default temp root is longer.
    with tempfile.TemporaryDirectory(prefix='pajio-uds-',dir='/tmp') as raw:
        path=Path(raw);path.chmod(0o750)
        yield path


def test_private_listener_is_0660_and_does_not_replace_active_socket(socket_directory):
    directory=socket_directory
    path=directory/'broker.sock'
    with private_listener(path):
        inode=path.stat().st_ino
        assert stat.S_IMODE(path.stat().st_mode)==0o660
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:client.connect(str(path))
        with pytest.raises(Timeout):
            with private_listener(path):raise AssertionError('replaced active listener')
        assert path.stat().st_ino==inode
    assert not path.exists()


def test_private_listener_reclaims_only_owned_stale_socket(socket_directory):
    directory=socket_directory
    path=directory/'broker.sock'
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as old:old.bind(str(path))
    with private_listener(path):assert path.exists()
    path.write_text('do not replace')
    with pytest.raises(ValueError,match='registration_socket_boundary'):
        with private_listener(path):raise AssertionError('replaced file')
    assert path.read_text()=='do not replace'


def test_private_listener_refuses_a_live_socket_without_its_lock(socket_directory):
    path=socket_directory/'broker.sock'
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as other:
        other.bind(str(path));other.listen(1)
        inode=path.stat().st_ino
        with pytest.raises(ValueError,match='registration_socket_in_use'):
            with private_listener(path):raise AssertionError('replaced other listener')
        assert path.stat().st_ino==inode
