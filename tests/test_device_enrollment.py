import hashlib
import json
from pathlib import Path
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID
import pytest

from wearing.cloud.device_bootstrap import BootstrapBook
from wearing.cloud.device_enrollment import (EnrollmentBook, EnrollmentSpec, SSHEnrollmentAdapter,
    android_serial, certificate_material, validate_scope, checked_stage_result)
from wearing.cloud.device_enrollment_remote import issued_pair, bound_connector, write_exact, render_guest_files
from wearing.cloud.device_provisioning import ProvisionError, fingerprint
from wearing.cloud.relay import RelayStore, PairRequest
from wearing.mobile import resource_id
from test_device_bootstrap import settings as bootstrap_settings, owner
from test_device_provisioning import setup, reserve, spec


def device(**changes):
    return spec(resource_id='computer_'+'1'*20,**changes)


def materials(item=None):
    item=item or device()
    return certificate_material(owner(item),'10.78.1.2')


def config(m=None,**changes):
    m=m or materials()
    return EnrollmentSpec(guest_ipv4='10.78.1.2',tenant_endpoint='https://10.77.101.2:8444',
        relay_ca_pem=m['ca_cert'],artifact_sha256='a'*64).model_copy(update=changes)


def inventory(item=None):
    item=item or device()
    return {'resources':[{'resource_id':item.resource_id,'name':'测试设备','kind':'computer',
                          'methods':['computer.status','computer.observe']}],
            'tools':[{'name':'computer','description':'device control','inputSchema':{'type':'object'}}]}


class Adapter:
    def __init__(self):self.calls=[];self.applied={};self.lost=None;self.ready=True;self.fail=False
    def scope_targets(self,item):return {'tenant':'fixed_tenant','guest':'fixed_guest'}
    def result(self,stage,item,o,m):
        value={'complete':True,'owner_sha256':fingerprint(o.model_dump()),'connector_id':m['connector_id']}
        if stage=='prepare':value['inventory']=inventory(item)
        return value
    def apply(self,stage,item,o,c,m,results):
        self.calls.append(stage)
        if self.fail:raise RuntimeError('sensitive injected remote error')
        value=self.result(stage,item,o,m);self.applied[stage]=value
        if self.lost==stage:raise TimeoutError('SSH response lost')
        return value
    def reconcile(self,stage,*args):return self.applied.get(stage)
    def inspect(self,item,o,c,m,results):
        return {'owner_sha256':fingerprint(o.model_dump()),'owner_matches':True,'bootstrap_matches':True,
            'paired_scope_matches':True,'agent_online':self.ready,'human_online':self.ready,'mtls_verified':self.ready}


def staged(setup):
    book,provider=setup;item=device();sha=reserve(book,provider,item)
    book.apply(item.request_id,provider,plan_sha256=sha)
    bootstrap=BootstrapBook(book);settings=bootstrap_settings()
    plan=bootstrap.plan(item.request_id,settings,provider)
    provider.stage_network=lambda i,o,c,b:{'network_staged':True,'started':False,
        'bundle_sha256':b['bundle_sha256'],'config_sha256':provider.inspect_vm(i.vmid).config_sha256}
    bootstrap.stage_network(item.request_id,settings,provider,reviewed_sha256=plan['bundle_sha256'])
    return book,item,EnrollmentBook(book),Adapter(),config()


def test_complete_only_enrollment_live_check_not_overall_product_ready(setup):
    book,item,enrollment,adapter,settings=staged(setup)
    plan=enrollment.plan(item.request_id,settings,adapter)
    result=enrollment.enroll(item.request_id,settings,adapter,reviewed_sha256=plan['plan_sha256'])
    assert result['enrollment_ready'] and not result['product_ready']
    assert adapter.calls==['prepare','issue','configure','bind','activate']
    adapter.ready=False
    assert not enrollment.enroll(item.request_id,settings,adapter,reviewed_sha256=plan['plan_sha256'])['enrollment_ready']
    assert len(adapter.calls)==5
    path=book.root/'enrollment'/item.request_id/'material.json'
    assert path.stat().st_mode&0o077==0
    assert not any(v in json.dumps(result) for k,v in json.loads(path.read_text()).items() if k.endswith(('token','key','code')))


def test_lost_reply_reconciles_authoritative_exact_step_without_reexecution(setup):
    book,item,enrollment,adapter,settings=staged(setup);adapter.lost='issue'
    plan=enrollment.plan(item.request_id,settings,adapter)
    with pytest.raises(ProvisionError,match='enrollment_outcome_unknown'):
        enrollment.enroll(item.request_id,settings,adapter,reviewed_sha256=plan['plan_sha256'])
    assert enrollment.inspect(item.request_id,adapter)['state']=='unknown'
    assert enrollment.enroll(item.request_id,settings,adapter,reviewed_sha256=plan['plan_sha256'])['enrollment_ready']
    assert adapter.calls.count('issue')==1


def test_unknown_partial_mutation_never_replays_or_emits_remote_exception(setup):
    book,item,enrollment,adapter,settings=staged(setup);adapter.fail=True
    plan=enrollment.plan(item.request_id,settings,adapter)
    for _ in range(2):
        with pytest.raises(ProvisionError,match='^enrollment_outcome_unknown$'):
            enrollment.enroll(item.request_id,settings,adapter,reviewed_sha256=plan['plan_sha256'])
    assert adapter.calls==['prepare']


def test_enrollment_rejects_changed_plan_bootstrap_and_material(setup):
    book,item,enrollment,adapter,settings=staged(setup)
    with pytest.raises(ProvisionError,match='enrollment_bootstrap_mismatch'):
        enrollment.plan(item.request_id,settings.model_copy(update={'tenant_endpoint':'https://10.77.102.2:8444'}),adapter)
    plan=enrollment.plan(item.request_id,settings,adapter)
    with pytest.raises(ProvisionError,match='enrollment_review_changed'):
        enrollment.enroll(item.request_id,settings,adapter,reviewed_sha256='f'*64)
    enrollment.enroll(item.request_id,settings,adapter,reviewed_sha256=plan['plan_sha256'])
    path=book.root/'enrollment'/item.request_id/'material.json'
    data=json.loads(path.read_text());data['host_token']='different';path.write_text(json.dumps(data))
    with pytest.raises(ProvisionError,match='enrollment_material_changed'):enrollment.inspect(item.request_id,adapter)


def test_each_step_rechecks_account_ownership(setup):
    book,item,enrollment,adapter,settings=staged(setup)
    plan=enrollment.plan(item.request_id,settings,adapter)
    apply=adapter.apply
    def revoked(*args):
        result=apply(*args)
        book.admission.check=lambda item: (_ for _ in ()).throw(ValueError('deleted'))
        return result
    adapter.apply=revoked
    with pytest.raises(ProvisionError,match='account_evidence_unavailable'):
        enrollment.enroll(item.request_id,settings,adapter,reviewed_sha256=plan['plan_sha256'])
    assert adapter.calls==['prepare']


def test_fresh_android_devices_use_unique_ports_and_reject_overflow():
    for vmid in (100,1201,45535):
        item=spec(kind='android',vmid=vmid,resource_id=resource_id('127.0.0.1:'+str(20000+vmid)))
        validate_scope(item,owner(item));assert android_serial(item).endswith(str(20000+vmid))
    with pytest.raises(ProvisionError,match='invalid_android_device_port'):android_serial(spec(kind='android',vmid=45536))
    item=spec(kind='android',resource_id=resource_id('127.0.0.1:5555'))
    with pytest.raises(ProvisionError,match='enrollment_android_resource_mismatch'):validate_scope(item,owner(item))


def test_per_device_ca_leaf_scope_and_no_retained_ca_signing_key():
    a,b=materials(),materials();assert a['ca_cert']!=b['ca_cert']
    assert 'ca_key' not in a
    ca=x509.load_pem_x509_certificate(a['ca_cert'].encode())
    server=x509.load_pem_x509_certificate(a['server_cert'].encode())
    client=x509.load_pem_x509_certificate(a['client_cert'].encode())
    server.verify_directly_issued_by(ca);client.verify_directly_issued_by(ca)
    assert str(server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value[0].value)=='10.78.1.2'
    assert list(server.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)==[ExtendedKeyUsageOID.SERVER_AUTH]
    assert list(client.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)==[ExtendedKeyUsageOID.CLIENT_AUTH]
    assert server.public_key().public_numbers()==serialization.load_pem_private_key(a['server_key'].encode(),None).public_key().public_numbers()


def test_pair_issue_is_transactionally_idempotent_and_scope_bound(tmp_path):
    store=RelayStore(tmp_path/'relay','tenant_a');item=device();o=owner(item);m=materials()
    m['connector_token_sha256']=hashlib.sha256(m['connector_token'].encode()).hexdigest()
    results={'prepare':{'inventory':inventory(item)}}
    issued_pair(store,item,o,m,results,mutate=True)
    issued_pair(store,item,o,m,results,mutate=True)
    store.pair(PairRequest(code=m['pair_code'],token=m['connector_token']))
    assert bound_connector(store,item,m,results)['identity']=='daily'
    with pytest.raises(ProvisionError,match='enrollment_pairing_changed'):
        issued_pair(store,item,o.model_copy(update={'nonce':'0'*64}),m,results,mutate=True)
    with pytest.raises(ProvisionError,match='enrollment_pairing_unconfirmed'):
        bound_connector(store,item.model_copy(update={'identity_id':'work'}),m,results)
    second=device(request_id='b'*32);n=materials(second)
    with pytest.raises(ProvisionError,match='enrollment_resource_already_bound'):
        issued_pair(store,second,owner(second),n,results,mutate=True)


def test_expired_pair_stays_expired_and_cannot_rotate_under_same_request(tmp_path):
    store=RelayStore(tmp_path/'relay','tenant_a');item=device();o=owner(item);m=materials()
    m['connector_token_sha256']=hashlib.sha256(m['connector_token'].encode()).hexdigest()
    results={'prepare':{'inventory':inventory(item)}}
    issued_pair(store,item,o,m,results,mutate=True)
    with store.tx() as db:db.execute('UPDATE pairs SET expires=0')
    with pytest.raises(ProvisionError,match='enrollment_pairing_expired'):
        issued_pair(store,item,o,m,results,mutate=True)
    with store.tx() as db:assert db.execute('SELECT COUNT(*) FROM pairs').fetchone()[0]==1


def test_enrollment_requires_live_dynamic_relay_and_never_restarts_tenant(monkeypatch):
    import wearing.cloud.device_enrollment_remote as remote
    from wearing.cloud import relay
    monkeypatch.setattr(relay.RelayStore,'human_access_ready',property(lambda self:False),raising=False)
    monkeypatch.setattr(remote,'relay_process',lambda:('100',Path(relay.__file__).stat().st_mtime-20))
    with pytest.raises(ProvisionError,match='enrollment_live_relay_release_unconfirmed'):
        remote.verify_dynamic_relay()
    monkeypatch.setattr(remote,'relay_process',lambda:('101',Path(relay.__file__).stat().st_mtime+2))
    remote.verify_dynamic_relay()
    monkeypatch.setattr(relay.RelayStore,'human_access_ready',False)
    with pytest.raises(ProvisionError,match='enrollment_dynamic_relay_required'):
        remote.verify_dynamic_relay()
    import inspect
    assert 'restart' not in inspect.getsource(remote.tenant_action)


def test_reconcile_relay_reader_cannot_mutate_business_state(tmp_path):
    import sqlite3
    from wearing.config import write_private_json
    from wearing.cloud.device_enrollment_remote import ReadonlyRelay
    root=tmp_path/'instance';store=RelayStore(root/'data/device-relay','tenant_a')
    write_private_json(root/'private-media-access.json',{'version':1,'enabled':True,'hosts':{}})
    with store.tx() as db:
        db.execute("INSERT INTO commands(id,state,updated) VALUES('fixture','queued',0)")
    snapshot=ReadonlyRelay(root,'tenant_a')
    with snapshot.tx() as db:
        assert db.execute("SELECT state FROM commands WHERE id='fixture'").fetchone()[0]=='queued'
        with pytest.raises(sqlite3.OperationalError,match='readonly'):
            db.execute("DELETE FROM commands WHERE id='fixture'")
    with store.tx() as db:assert db.execute("SELECT state FROM commands WHERE id='fixture'").fetchone()[0]=='queued'


def test_stdin_transport_splits_keys_and_no_sensitive_error_surface(tmp_path):
    calls=[]
    def runner(argv,**kwargs):
        calls.append((argv,json.loads(kwargs['input'])))
        return subprocess.CompletedProcess(argv,1,stdout='not json',stderr='sensitive')
    adapter=SSHEnrollmentAdapter(config=tmp_path/'ssh-config',sources={'tenants':{'tenant_a':{
        'host':'tenant-a','python':'/opt/wearing/venv/bin/python','root':'/var/lib/wearing/instance','account':'wearing'}},
        'devices':{device().resource_id:{'host':'new-device'}}},allow_apply=True,runner=runner)
    item=device();m=materials();o=owner(item)
    for stage in ('configure','issue'):
        with pytest.raises(ProvisionError,match='^enrollment_outcome_unknown$'):
            adapter.apply(stage,item,o,config(m),m,{'prepare':{'inventory':inventory()}})
    guest,tenant=calls
    assert all(m['host_token'] not in ' '.join(argv) for argv,payload in calls)
    assert 'client_key' not in guest[1]['material'] and 'server_key' not in tenant[1]['material']
    assert 'connector_token' not in tenant[1]['material']
    assert 'StrictHostKeyChecking=yes' in guest[0] and 'BatchMode=yes' in guest[0]


def test_guest_templates_expose_only_mtls_offer_and_loopback_backend():
    from types import SimpleNamespace
    item=device();u=SimpleNamespace(pw_dir='/home/pajio-desktop',pw_uid=1001,pw_gid=1001,pw_name='pajio-desktop')
    files=render_guest_files(item,owner(item),config(),materials(),u)
    nginx=files['/etc/nginx/conf.d/pajio-private-media.conf'][0]
    assert 'ssl_verify_client on;' in nginx and 'limit_except POST' in nginx and 'location / { return 404; }' in nginx
    assert 'access_log off;' in nginx and 'error_log /dev/null crit;' in nginx


@pytest.mark.parametrize('kind',['linux','android'])
def test_generated_media_command_parses_real_cli_and_binds_only_loopback(monkeypatch,kind):
    import shlex
    import sys
    from types import SimpleNamespace
    from wearing import private_media
    item=device(kind=kind)
    u=SimpleNamespace(pw_dir='/home/pajio-desktop',pw_uid=1001,pw_gid=1001,pw_name='pajio-desktop')
    unit=render_guest_files(item,owner(item),config(),materials(),u)['/etc/systemd/system/pajio-private-media.service'][0]
    command=shlex.split(next(line.removeprefix('ExecStart=') for line in unit.splitlines() if line.startswith('ExecStart=')))
    assert command[:3]==['/opt/pajio-native/venv/bin/python','-m','wearing.private_media']
    observed=[]
    monkeypatch.setattr(sys,'argv',['wearing.private_media',*command[3:]])
    monkeypatch.setattr(private_media,'read_private',lambda path:'{}')
    monkeypatch.setattr(private_media,'create_app',lambda config:'test-app')
    monkeypatch.setitem(sys.modules,'uvicorn',SimpleNamespace(run=lambda app,**kwargs:observed.append((app,kwargs))))
    private_media.main()
    assert observed==[('test-app',{'host':'127.0.0.1','port':8792,'access_log':False,'log_level':'warning'})]


def test_install_once_never_follows_links_or_overwrites_changed_files(tmp_path):
    import os
    target=tmp_path/'private';write_exact(target,'first',uid=os.getuid(),gid=os.getgid())
    write_exact(target,'first',uid=os.getuid(),gid=os.getgid())
    with pytest.raises(ProvisionError,match='enrollment_existing_file_changed'):
        write_exact(target,'second',uid=os.getuid(),gid=os.getgid())
    link=tmp_path/'alias';link.symlink_to(target)
    with pytest.raises(ProvisionError,match='enrollment_file_unsafe'):
        write_exact(link,'first',uid=os.getuid(),gid=os.getgid())
