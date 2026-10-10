"""Preclaim has no account side effects and accepts only exact fresh host proof."""
import json
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from wearing.cloud.bundle_activation import ActivationError
from wearing.cloud.bundle_operator import BundleOperator, BundleReservation, HOST


def reservation():
    now=int(time.time())
    return dict(version=1,reservation_id='a'*32,node='pve01',purpose='invitation',tenant_id='tenant-fixture',
        created_at=now,expires_at=now+86400,members=[dict(kind=kind,vmid=1401+i,request_id=str(i+1)*32,
            vcpus=2 if kind=='android' else 1,memory_mib=2048 if kind=='core' else 4096,disk_mib=32768,
            image_sha256='b'*64,core_reservation_sha256='c'*64 if kind=='core' else None)
            for i,kind in enumerate(('core','linux','android'))])


@pytest.mark.parametrize('failure', ['stale', 'different_reservation', 'different_sha', 'failed_ssh'])
def test_operator_never_accepts_ambiguous_or_cross_bundle_receipt(failure):
    def runner(argv,**kwargs):
        import hashlib
        payload=json.loads(kwargs['input'])
        result=dict(reservation=payload['reservation'],reservation_sha256=hashlib.sha256(payload['reservation_raw'].encode()).hexdigest(),observed_at=time.time())
        if failure=='stale':result['observed_at']-=61
        if failure=='different_reservation':result['reservation']['tenant_id']='another-user'
        if failure=='different_sha':result['reservation_sha256']='0'*64
        return SimpleNamespace(returncode=1 if failure=='failed_ssh' else 0,stdout=json.dumps(result))
    operator=BundleOperator(ssh_config='/private/operator.conf',host='pajio-host',runner=runner)
    with pytest.raises(ActivationError,match='unconfirmed'):operator.reservation(reservation())


def test_inspection_is_read_only_and_create_requires_explicit_operator_action():
    import hashlib
    actions=[]
    def runner(argv,**kwargs):
        payload=json.loads(kwargs['input']);actions.append(payload['action'])
        assert 'StrictHostKeyChecking=yes' in argv and 'BatchMode=yes' in argv
        return SimpleNamespace(returncode=0,stdout=json.dumps(dict(reservation=payload['reservation'],
            reservation_sha256=hashlib.sha256(payload['reservation_raw'].encode()).hexdigest(),observed_at=time.time())))
    operator=BundleOperator(ssh_config='/private/operator.conf',host='pajio-host',runner=runner)
    assert operator.reservation(reservation())['reservation']['purpose']=='invitation'
    operator.reservation(reservation(),create=True)
    assert actions==['inspect','reserve']


@pytest.mark.parametrize('change', ['duplicate_vm','duplicate_request','missing_phone','core_proof_missing','underprovisioned_phone'])
def test_full_distinct_bundle_required_before_any_host_operation(change):
    data=reservation()
    if change=='duplicate_vm':data['members'][2]['vmid']=data['members'][1]['vmid']
    if change=='duplicate_request':data['members'][2]['request_id']=data['members'][1]['request_id']
    if change=='missing_phone':data['members'].pop()
    if change=='core_proof_missing':data['members'][0]['core_reservation_sha256']=None
    if change=='underprovisioned_phone':data['members'][2]['memory_mib']=1024
    calls=[]
    operator=BundleOperator(ssh_config='/private/operator.conf',host='pajio-host',runner=lambda *a,**k:calls.append(a))
    with pytest.raises(ValidationError):operator.reservation(data,create=True)
    assert calls==[]


@pytest.mark.parametrize('failure',['service_refused','different_plan','wrong_bundle','stale','nonfinite','malformed','ssh_failed'])
def test_invitation_requires_live_worker_receipt_bound_to_installed_plan(failure):
    value=BundleReservation.model_validate(reservation())
    plan=SimpleNamespace(bundle_id=value.reservation_id,tenant_id=value.tenant_id,
                         instance_id='primary-instance',host='pajio-host',reservation_sha256='c'*64)
    def runner(argv,**kwargs):
        assert argv[-2]=='controller'
        request=json.loads(kwargs['input'])
        assert request['bundle']['worker_plan_sha256']=='d'*64
        assert set(request['modules'])=={'bundle_activation.py','bundle_activation_pipeline.py','bundle_activation_worker.py'}
        result={'worker_ready':True,'worker_plan_sha256':'d'*64,'bundle_id':value.reservation_id,'observed_at':time.time()}
        if failure=='service_refused':result={'error':'bundle_worker_not_ready'}
        if failure=='different_plan':result['worker_plan_sha256']='e'*64
        if failure=='wrong_bundle':result['bundle_id']='f'*32
        if failure=='stale':result['observed_at']-=61
        if failure=='nonfinite':result['observed_at']=float('nan')
        return SimpleNamespace(returncode=1 if failure=='ssh_failed' else 0,
                               stdout='not JSON' if failure=='malformed' else json.dumps(result))
    operator=BundleOperator(ssh_config='/operator/config',host='pajio-host',worker_host='controller',runner=runner)
    with pytest.raises(ActivationError,match='bundle_worker_not_ready'):
        operator.worker_ready(plan,value,'d'*64)


def test_operator_cannot_issue_without_a_known_persistent_worker():
    operator=BundleOperator(ssh_config='/operator/config',host='pajio-host')
    with pytest.raises(ActivationError,match='bundle_worker_required'):
        operator.worker_ready(None,None,'d'*64)
