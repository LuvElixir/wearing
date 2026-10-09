import json
import pytest
from wearing.cloud.device_delivery import DeviceDelivery
from wearing.cloud.device_delivery_ssh import HOST,GUEST
from wearing.cloud.device_bootstrap import BootstrapBook
from wearing.cloud.device_provisioning import ProvisionError,fingerprint
from test_device_provisioning import setup,spec,reserve
from test_device_bootstrap import settings

@pytest.fixture
def delivery(setup):
    book,p=setup;sha=reserve(book,p);book.apply(spec().request_id,p,plan_sha256=sha)
    bootstrap=BootstrapBook(book);bundle=bootstrap.plan(spec().request_id,settings(),p)
    p.stage_network=lambda item,o,c,b:{'network_staged':True,'started':False,'bundle_sha256':b['bundle_sha256'],'config_sha256':p.inspect_vm(item.vmid).config_sha256}
    bootstrap.stage_network(spec().request_id,settings(),p,reviewed_sha256=bundle['bundle_sha256'])
    p.verify_staged_network=lambda *args:True;p.assert_wake_capacity=lambda *args:True
    def power(action,item,o,c):
        p.calls.append('start');v=p.inspect_vm(item.vmid);p.vms[p.vms.index(v)]=v.model_copy(update={'state':'running'})
    p.power=power
    p.attest=lambda item,o,b:{'owner_sha256':fingerprint(o.model_dump()),'cloud_init_ready':True,'machine_sha256':'a'*64,'ssh_host_key':'ssh-ed25519 fixture'}
    p.install_runtime=lambda *args:p.calls.append('install')
    p.runtime_status=lambda item,o,b,m:{'version':1,'owner_sha256':fingerprint(o.model_dump()),'artifact_sha256':b['manifest']['artifact_sha256']}
    return DeviceDelivery(book),book,p,bundle

def test_boot_install_has_single_start_and_verified_runtime(delivery):
    d,book,p,bundle=delivery;request=spec().request_id
    assert d.boot(request,p,reviewed_sha256=bundle['bundle_sha256'])['state']=='bootstrapped'
    assert d.boot(request,p,reviewed_sha256=bundle['bundle_sha256'])['state']=='bootstrapped'
    assert d.install_runtime(request,p)['state']=='runtime_installed'
    assert d.install_runtime(request,p)['state']=='runtime_installed'
    assert p.calls==['clone','prepare','start','install']
    assert not d.status(request)['product_ready']

def test_unknown_boot_is_observed_never_replayed(delivery):
    d,book,p,bundle=delivery;original=p.power
    def lost(*args):original(*args);raise TimeoutError()
    p.power=lost
    with pytest.raises(TimeoutError):d.boot(spec().request_id,p,reviewed_sha256=bundle['bundle_sha256'])
    assert d.status(spec().request_id)['state']=='boot_sent'
    assert d.boot(spec().request_id,p,reviewed_sha256=bundle['bundle_sha256'])['state']=='bootstrapped'
    assert p.calls.count('start')==1

def test_rebound_or_incomplete_guest_never_marks_ready(delivery):
    d,book,p,bundle=delivery;request=spec().request_id
    d.boot(request,p,reviewed_sha256=bundle['bundle_sha256'])
    original=p.attest
    p.attest=lambda *args:{**original(*args),'machine_sha256':'b'*64}
    with pytest.raises(ProvisionError,match='device_os_identity_changed'):d.install_runtime(request,p)
    assert 'install' not in p.calls

def test_partial_enrollment_stays_pending_and_browser_is_separate(delivery,monkeypatch):
    d,book,p,bundle=delivery;request=spec().request_id
    d.boot(request,p,reviewed_sha256=bundle['bundle_sha256']);d.install_runtime(request,p)
    from wearing.cloud.device_enrollment import EnrollmentBook
    monkeypatch.setattr(EnrollmentBook,'inspect',lambda self,*args:{'owner_matches':True,'bootstrap_matches':True,'paired_scope_matches':True,'agent_online':True,'human_online':True,'mtls_verified':True})
    p.delivery_evidence=lambda *args:{'network_isolated':True,'native_ready':False,'browser_ready':False,'browser_setup_state':'first_run_unverified'}
    result=d.verify(request,p,None)
    assert not result['product_ready'] and result['pending']==['native_ready']
    p.delivery_evidence=lambda *args:{'network_isolated':True,'native_ready':True,'browser_ready':False,'browser_setup_state':'first_run_unverified'}
    assert d.verify(request,p,None)['device_ready']
    assert not d.verify(request,p,None)['product_ready']
    assert d.status(request)['last_verified_ready'] and not d.status(request)['product_ready']
    p.delivery_evidence=lambda *args:{'network_isolated':False,'native_ready':True,'browser_ready':False}
    assert not d.verify(request,p,None)['product_ready']

def test_exact_remote_readiness_uses_qga_and_current_tcp_native_evidence():
    compile(HOST,'<delivery-host>','exec');compile(GUEST,'<delivery-guest>','exec')
    assert "'guest','exec'" in HOST and 'cloud-init' in HOST
    assert "connected(ip,port) is False" in GUEST and 'browser-ready.json' in GUEST
    assert 'v1/status' in GUEST and 'Authorization' in GUEST


def test_operator_ssh_trust_is_bound_to_qga_and_original_cloud_init_key(delivery,tmp_path):
    from pathlib import Path
    import subprocess
    from test_device_bootstrap import KEY
    d,book,p,bundle=delivery;request=spec().request_id
    original=p.attest
    p.attest=lambda *args:{**original(*args),'ssh_host_key':KEY}
    p.host='synthetic-hypervisor'
    d.boot(request,p,reviewed_sha256=bundle['bundle_sha256'])
    key=tmp_path/'operator-key';key.write_text('synthetic private placeholder');key.chmod(0o600)
    Path(str(key)+'.pub').write_text(KEY+'\n');base=tmp_path/'base-config';base.write_text('Host synthetic-hypervisor\n  HostName 127.0.0.1\n')
    result=d.bind_ssh(request,p,identity_file=key,base_config=base)
    config=Path(result['ssh_config']);known=config.with_suffix('.known_hosts')
    assert config.stat().st_mode&0o077==0 and known.stat().st_mode&0o077==0
    assert known.read_text().startswith('pajio-device-1200 '+KEY)
    assert d.bind_ssh(request,p,identity_file=key,base_config=base)==result
    parsed=subprocess.run(['ssh','-G','-F',str(config),result['guest_host']],text=True,capture_output=True)
    assert parsed.returncode==0 and 'hostname 10.78.1.2' in parsed.stdout and 'stricthostkeychecking true' in parsed.stdout
    included=subprocess.run(['ssh','-G','-F',str(config),'synthetic-hypervisor'],text=True,capture_output=True)
    assert included.returncode==0 and 'hostname 127.0.0.1' in included.stdout
    Path(str(key)+'.pub').write_text('ssh-ed25519 wrong')
    with pytest.raises(ProvisionError,match='bootstrap_ssh_identity_changed'):d.bind_ssh(request,p,identity_file=key,base_config=base)


def test_qga_management_proof_allows_docker_bridge_but_not_wrong_nic():
    import re
    definition=HOST.split('def management_matches(',1)[1].split("if v.get('owner_sha256')",1)[0]
    context={'re':re};exec('def management_matches('+definition,context)
    match=context['management_matches'];net='virtio=AA:BB:CC:DD:EE:FF,bridge=pj1212'
    interfaces=[{'mac':'aa:bb:cc:dd:ee:ff','addresses':['10.78.1.6']},{'mac':'02:42:00:00:00:01','addresses':['172.17.0.1']}]
    assert match(net,interfaces,'10.78.1.6')
    assert not match(net,interfaces,'172.17.0.1')
    assert not match('virtio=BB:BB:CC:DD:EE:FF',interfaces,'10.78.1.6')
    assert not match(net,interfaces+[interfaces[0]],'10.78.1.6')


def test_actual_qga_source_collects_mac_and_only_ipv4(monkeypatch,capsys):
    import ast,json,pathlib,subprocess
    from types import SimpleNamespace
    from wearing.cloud.device_delivery_ssh import HOST
    tree=ast.parse(HOST)
    source=next(n.value.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='source' for t in n.targets))
    documents={'/etc/pajio-native/bootstrap-expected.json':'{}','/etc/pajio-native/device-owner.json':'{"kind":"linux"}','/etc/machine-id':'1'*32,'/etc/ssh/ssh_host_ed25519_key.pub':'ssh-ed25519 synthetic'}
    monkeypatch.setattr(pathlib,'Path',lambda path:SimpleNamespace(read_text=lambda:documents[path]))
    monkeypatch.setattr(subprocess,'run',lambda *args,**kw:SimpleNamespace(stdout='{"status":"done","errors":[]}',returncode=0))
    def ip(args,**kwargs):
        assert args==['ip','-j','addr'] # -4 omits the MAC in real iproute2.
        return json.dumps([{'address':'bc:24:11:fb:72:7c','addr_info':[{'family':'inet','scope':'global','local':'10.78.1.2'},{'family':'inet6','scope':'global','local':'fd00::2'}]}])
    monkeypatch.setattr(subprocess,'check_output',ip)
    exec(compile(source,'<actual-qga-attestation>','exec'),{})
    observed=json.loads(capsys.readouterr().out)
    assert observed['interfaces']==[{'mac':'bc:24:11:fb:72:7c','addresses':['10.78.1.2']}]


def test_original_cloud_init_error_requires_independent_verified_repair(delivery):
    d,book,p,bundle=delivery;request=spec().request_id
    original=p.attest
    p.attest=lambda *args:{**original(*args),'cloud_init_ready':False,'raw_cloud_init_status':'error','bootstrap_repair_verified':False}
    with pytest.raises(ProvisionError,match='fresh_os_attestation_pending'):
        d.boot(request,p,reviewed_sha256=bundle['bundle_sha256'])
    p.attest=lambda *args:{**original(*args),'cloud_init_ready':False,'raw_cloud_init_status':'error','bootstrap_repair_verified':True}
    assert d.boot(request,p,reviewed_sha256=bundle['bundle_sha256'])['state']=='bootstrapped'
    evidence=json.loads(d._row(request)['evidence'])
    assert evidence['cloud_init_ready'] is False and evidence['raw_cloud_init_status']=='error'


def test_repair_readiness_is_rechecked_at_bind_install_and_verify(delivery,tmp_path):
    d,book,p,bundle=delivery;request=spec().request_id
    d.boot(request,p,reviewed_sha256=bundle['bundle_sha256']);d.install_runtime(request,p)
    original=p.attest
    p.attest=lambda *args:{**original(*args),'cloud_init_ready':False,'bootstrap_repair_verified':False}
    for operation in [lambda:d.bind_ssh(request,p,identity_file=tmp_path/'key',base_config=tmp_path/'config'),lambda:d.install_runtime(request,p),lambda:d.verify(request,p,None)]:
        with pytest.raises(ProvisionError,match='fresh_os_attestation_pending'):operation()


@pytest.mark.parametrize('lost_after_write',[True,False])
def test_autostart_updates_config_ledger_or_preserves_unknown_without_replay(delivery,lost_after_write):
    d,book,p,bundle=delivery;request=spec().request_id
    d.boot(request,p,reviewed_sha256=bundle['bundle_sha256'])
    with pytest.raises(ProvisionError,match='verified_device_required'):d.startup_plan(request,p)
    d._set(request,'ready')
    observed={'before_sha256':d._row(request)['config_sha256'],'after_sha256':'e'*64,'onboot':0};writes=[]
    p.startup_config=lambda *args:dict(observed)
    def change(item,owner,plan):
        writes.append(plan)
        if lost_after_write:observed.update(before_sha256=plan['after_sha256'],onboot=1)
        raise TimeoutError('synthetic reply lost')
    p.set_autostart=change
    plan=d.startup_plan(request,p)
    with pytest.raises(ProvisionError,match='startup_plan_changed'):d.finalize_startup(request,p,reviewed_sha256='f'*64)
    assert not writes
    with pytest.raises(TimeoutError):d.finalize_startup(request,p,reviewed_sha256=plan['plan_sha256'])
    if lost_after_write:
        result=d.finalize_startup(request,p,reviewed_sha256=plan['plan_sha256'])
        assert result['onboot'] and d._row(request)['config_sha256']=='e'*64
        assert d.finalize_startup(request,p,reviewed_sha256=plan['plan_sha256'])==result
    else:
        with pytest.raises(ProvisionError,match='startup_outcome_unknown_no_replay'):d.finalize_startup(request,p,reviewed_sha256=plan['plan_sha256'])
        assert d._row(request)['config_sha256']==plan['before_sha256']
    assert len(writes)==1


@pytest.mark.parametrize('config_uid,backend_ready',[(1234,True),(1234,False),(9999,True)])
@pytest.mark.parametrize('kind',['linux','android'])
def test_actual_delivery_guest_respects_dedicated_media_service_owner(tmp_path,monkeypatch,capsys,config_uid,backend_ready,kind):
    import hashlib,io,os,pathlib,pwd,socket,subprocess,sys,urllib.request
    from contextlib import nullcontext
    from types import SimpleNamespace
    from wearing.cloud.device_delivery_ssh import GUEST
    from wearing.cloud.device_provisioning import fingerprint
    owner={'kind':kind};machine='a'*32;artifact='b'*64
    payload={'action':'evidence','owner':owner,'owner_sha256':fingerprint(owner),'machine_sha256':hashlib.sha256(machine.encode()).hexdigest(),
             'artifact_sha256':artifact,'gateway_ipv4':'10.78.1.1','tenant_ipv4':'10.77.102.2','spec':{'resource_id':'computer_fixture','kind':kind}}
    files={'/etc/pajio-native/device-owner.json':json.dumps(owner),'/etc/machine-id':machine,
           '/etc/pajio-native/bootstrap-installed.json':json.dumps({'version':1,'owner_sha256':fingerprint(owner),'artifact_sha256':artifact}),
           '/etc/pajio/media-host.json':json.dumps({'token':'synthetic-public-fixture'})}
    for name,body in files.items():
        path=tmp_path/name.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body);path.chmod(0o600)
    original=pathlib.Path;rawstat=original.stat
    def stat(path,*args,**kwargs):
        values=list(rawstat(path,*args,**kwargs));values[4]=config_uid if path.name=='media-host.json' else 0;return os.stat_result(values)
    monkeypatch.setattr(original,'stat',stat)
    monkeypatch.setattr(pathlib,'Path',lambda value:tmp_path/str(value).lstrip('/'))
    monkeypatch.setattr(os,'geteuid',lambda:0)
    monkeypatch.setattr(pwd,'getpwnam',lambda name:SimpleNamespace(pw_uid=1234,pw_name=name,pw_dir='/home/'+name,pw_shell='/usr/sbin/nologin'))
    def probe(argv,**kwargs):
        assert argv[:3]==['runuser','-u','pajio-desktop' if kind=='linux' else 'pajio-phone']
        if kind=='linux':assert 'XAUTHORITY=/run/user/1234/pajio-x11/Xauthority' in argv and 'linux_computer_status' in argv[-1]
        else:
            assert 'NativeAdapter' in argv[-1] and 'phone.mobile_get_screen_size' in argv[-1]
            compile(argv[-1],'<exact-phone-probe>','exec')
        return SimpleNamespace(returncode=0,stdout=json.dumps({'ready':backend_ready}))
    monkeypatch.setattr(subprocess,'run',probe)
    def connect(target,**kwargs):
        if target==('10.77.102.2',8444):return nullcontext()
        raise TimeoutError()
    monkeypatch.setattr(socket,'create_connection',connect)
    monkeypatch.setattr(urllib.request,'urlopen',lambda *args,**kwargs:nullcontext(io.BytesIO(b'{"ready":true,"resources":["computer_fixture"]}')))
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(payload)))
    if config_uid==1234:
        exec(compile(GUEST,'<actual-delivery-guest>','exec'),{})
        proof=json.loads(capsys.readouterr().out);assert proof['native_ready']==backend_ready and proof['native_backend_ready']==backend_ready and proof['network_isolated']
    else:
        with pytest.raises(SystemExit):exec(compile(GUEST,'<actual-delivery-guest>','exec'),{})
        assert json.loads(capsys.readouterr().out)=={'error':'delivery_evidence_unavailable'}
