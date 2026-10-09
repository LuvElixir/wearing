import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from wearing.cloud.device_bootstrap_repair import (
    REPAIR_VALIDATION_SOURCE, GUEST_REPAIR_SOURCE, HOST_REPAIR_SOURCE, repair_bootstrap)
from wearing.cloud.device_provisioning import DeviceSpec, Owner, ProvisionError, fingerprint


def setup():
    ns = {}; exec(REPAIR_VALIDATION_SOURCE, ns)
    spec = DeviceSpec(request_id='a'*32, tenant_id='tenant_b', identity_id='daily',
        resource_id='phone_29459143d81e0ef58142', kind='android', vmid=1212)
    owner = Owner(**{k:getattr(spec,k) for k in ('tenant_id','identity_id','resource_id','request_id','kind','vcpus','memory_mib','disk_mib')},
        request_sha256=fingerprint(spec.model_dump()), nonce='b'*64)
    state = {'status':'error', 'stage':None, 'errors':[ns['_REPAIR_ERROR']],
        'recoverable_errors':{'WARNING':ns['_REPAIR_WARNING']},
        'modules-final':{'errors':[ns['_REPAIR_ERROR']], 'recoverable_errors':{'WARNING':ns['_REPAIR_WARNING']}}}
    state.update({stage:{'errors':[], 'recoverable_errors':{}} for stage in ('init-local','init','modules-config')})
    expected = {'version':1, 'owner_sha256':fingerprint(owner.model_dump()), 'artifact_sha256':'c'*64}
    observed = {'packages':{'adb':'1:34.0.4-1build3'}, 'module_path':'/lib/modules/6.8.0-142-generic/binder_linux.ko.zst', 'module_sha256':'d'*64}
    receipt = {'version':1, 'repair':'android_missing_exact_kernel_modules',
        'owner_sha256':expected['owner_sha256'], 'artifact_sha256':expected['artifact_sha256'],
        'machine_sha256':'e'*64, 'kernel':'6.8.0-142-generic',
        'cloud_error_sha256':fingerprint(state), **observed}
    return ns, spec, owner, state, expected, observed, receipt


def test_repair_only_known_single_cloud_init_error():
    ns,_,_,state,*_=setup()
    assert ns['_repair_cloud_allowed'](state)
    for stage in ('init-local','init','modules-config','modules-final'):
        bad=copy.deepcopy(state);bad[stage]['errors'].append('other error')
        assert not ns['_repair_cloud_allowed'](bad)
    for key in ('errors','recoverable_errors'):
        bad=copy.deepcopy(state);bad[key]=[] if key=='errors' else {}
        assert not ns['_repair_cloud_allowed'](bad)
    bad=copy.deepcopy(state);bad['status']='done'
    assert not ns['_repair_cloud_allowed'](bad)


def test_repair_receipt_requires_current_identity_kernel_artifact_and_packages():
    ns,_,owner,state,expected,observed,receipt=setup()
    check=ns['_repair_receipt_matches']
    args=(owner.model_dump(),expected,'e'*64,state,'6.8.0-142-generic',observed)
    assert check(receipt,*args)
    for key in ('owner_sha256','artifact_sha256','machine_sha256','kernel','cloud_error_sha256','module_sha256'):
        bad={**receipt,key:'changed'};assert not check(bad,*args)
    assert not check({**receipt,'packages':{}},*args)
    assert not check({**receipt,'version':True},*args)
    assert not check({**receipt,'uploaded_success':True},*args)
    newer={**observed,'packages':{'adb':'new-version'}}
    assert not check(receipt,*args[:-1],newer)


def test_verifier_reads_root_receipt_and_probes_every_time(monkeypatch):
    ns,_,owner,state,expected,observed,receipt=setup();seen=[]
    ns['_repair_private']=lambda p:receipt if p.endswith('/bootstrap-repair.json') else state
    ns['_repair_observe']=lambda k:(seen.append(k) or observed)
    monkeypatch.setattr(ns['platform'],'release',lambda:'6.8.0-142-generic')
    assert ns['verify_bootstrap_repair'](owner.model_dump(),expected,'e'*64,state)
    assert seen==['6.8.0-142-generic']
    ns['_repair_observe']=lambda k:(_ for _ in ()).throw(ValueError('missing package'))
    assert not ns['verify_bootstrap_repair'](owner.model_dump(),expected,'e'*64,state)


def test_reboot_timestamp_changes_preserve_evidence_but_new_errors_do_not(monkeypatch):
    ns,_,owner,original,expected,observed,receipt=setup()
    ns['_repair_private']=lambda p:receipt if p.endswith('/bootstrap-repair.json') else original
    ns['_repair_observe']=lambda k:observed
    monkeypatch.setattr(ns['platform'],'release',lambda:'6.8.0-142-generic')
    current=copy.deepcopy(original);current['last_update']='a later boot'
    current['modules-final']['finished']=900
    assert ns['verify_bootstrap_repair'](owner.model_dump(),expected,'e'*64,current)
    current['init']['errors'].append('another boot error')
    assert not ns['verify_bootstrap_repair'](owner.model_dump(),expected,'e'*64,current)


def test_repair_uses_fixed_authenticated_host_qga_and_no_status_rewrite(tmp_path):
    _,spec,owner,_,_,_,_=setup();calls=[]
    def runner(argv,**kwargs):
        calls.append((argv,kwargs));p=json.loads(kwargs['input'])
        return SimpleNamespace(returncode=0,stdout=json.dumps({'bootstrap_repair_verified':True,
            'cloud_init_ready':False,'raw_cloud_init_status':'error',**p['intent']}))
    result=repair_bootstrap(config=tmp_path/'ssh',host='pve',node='pve01',spec=spec,owner=owner,
        artifact_sha256='c'*64,runner=runner)
    assert result['cloud_init_ready'] is False
    assert 'StrictHostKeyChecking=yes' in calls[0][0]
    assert '_REPAIR_ERROR' not in calls[0][0][-1]
    assert owner.nonce not in calls[0][0][-1]
    assert json.loads(calls[0][1]['input'])['guest_source']==GUEST_REPAIR_SOURCE
    assert "['cloud-init','status','--format','json']" in GUEST_REPAIR_SOURCE
    assert "['cloud-init','clean'" not in GUEST_REPAIR_SOURCE
    assert 'status.json' not in GUEST_REPAIR_SOURCE
    assert "json.loads(c.get('description','{}')).get('pajio_provisioning')!=owner" in HOST_REPAIR_SOURCE
    compile(GUEST_REPAIR_SOURCE,'guest','exec');compile(HOST_REPAIR_SOURCE,'host','exec')


def test_scope_change_and_ambiguous_ssh_never_report_ready(tmp_path):
    _,spec,owner,_,_,_,_=setup()
    def runner(*a,**k):return SimpleNamespace(returncode=1,stdout='private details')
    with pytest.raises(ProvisionError,match='invalid_bootstrap_repair_scope'):
        repair_bootstrap(config=tmp_path/'ssh',host='pve',node='pve01',spec=spec,
            owner=owner.model_copy(update={'identity_id':'other'}),artifact_sha256='c'*64,runner=runner)
    with pytest.raises(ProvisionError,match='bootstrap_repair_outcome_unknown'):
        repair_bootstrap(config=tmp_path/'ssh',host='pve',node='pve01',spec=spec,owner=owner,
            artifact_sha256='c'*64,runner=runner)


def test_receipt_interrupted_serialization_does_not_publish_partial_json(tmp_path, monkeypatch):
    ns={};exec(GUEST_REPAIR_SOURCE,ns)
    destination=tmp_path/'receipt.json'
    def interrupted(value, stream, **kwargs):
        stream.write('{')
        raise OSError('simulated interrupted write')
    with monkeypatch.context() as patch:
        patch.setattr(ns['json'],'dump',interrupted)
        with pytest.raises(OSError,match='interrupted'):
            ns['_repair_write_once'](destination,{'version':1})
    assert not destination.exists()
    assert list(tmp_path.iterdir())==[]
    ns['_repair_write_once'](destination,{'version':1})
    assert json.loads(destination.read_text())=={'version':1}
    assert destination.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('same',[False,True])
def test_receipt_commit_never_overwrites_concurrent_evidence(tmp_path,monkeypatch,same):
    ns={};exec(GUEST_REPAIR_SOURCE,ns)
    destination=tmp_path/'receipt.json';value={'version':1}
    concurrent=value if same else {'version':2}
    ns['_repair_private']=lambda path:json.loads(Path(path).read_text())
    original_link=ns['os'].link
    def competing_link(source,target,**kwargs):
        # The other writer wins after our initial exists() probe.
        Path(target).write_text(json.dumps(concurrent))
        return original_link(source,target,**kwargs)
    monkeypatch.setattr(ns['os'],'link',competing_link)
    if same:ns['_repair_write_once'](destination,value)
    else:
        with pytest.raises(ValueError,match='receipt_changed'):
            ns['_repair_write_once'](destination,value)
    assert json.loads(destination.read_text())==concurrent
    assert list(tmp_path.iterdir())==[destination]
