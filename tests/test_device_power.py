import json
import subprocess

import pytest

from wearing.cloud.device_power import DevicePower
from wearing.cloud.device_power_ssh import NATIVE_REMOTE, TENANT_REMOTE, POWER_REMOTE, SSHPowerAdapter
from wearing.cloud.device_provisioning import ProvisionError
from test_device_provisioning import setup, reserve, spec

OP='c'*32


class Adapter:
    def __init__(self, provider):
        self.provider=provider;self.calls=[];self.boot='old';self.epoch=3;self.ack=True
        self.error=None;self.quiet=False;self.phase='ready'
    def inspect_vm(self, vmid): return self.provider.inspect_vm(vmid)
    def assert_ready(self,*a):
        if not self.ack: raise ProvisionError('wake_readiness_pending')
    def maintenance(self,action,*a):
        self.calls.append(action)
        if action=='assert_drained' and not self.ack: raise ProvisionError('maintenance_ack_pending')
        if action=='finish_wake' and not self.ack: raise ProvisionError('wake_readiness_pending')
        return {'phase':'frozen','acknowledged':self.ack}
    def native(self,action,*a):
        self.calls.append(action)
        if action=='quiesce': self.quiet=True
        if action=='quiesced' and not self.quiet: raise ProvisionError('native_quiesce_unconfirmed')
        return {'boot_id':self.boot,'gateway_epoch':self.epoch,'ready':True}
    def assert_wake_capacity(self,*a): pass
    def power(self,action,item,owner,sha):
        self.calls.append(action)
        old=self.provider.inspect_vm(item.vmid)
        self.provider.vms[self.provider.vms.index(old)]=old.model_copy(update={'state':'stopped' if action=='shutdown' else 'running'})
        if action=='start': self.boot='new'
        if self.error: raise self.error


def prepared(setup):
    book,provider=setup;sha=reserve(book,provider);book.apply(spec().request_id,provider,plan_sha256=sha)
    provider.vms[1]=provider.vms[1].model_copy(update={'state':'running'})
    return DevicePower(book),Adapter(provider)


def test_full_manual_sleep_wake_retains_reservation_and_requires_fresh_boot(setup):
    power,adapter=prepared(setup)
    assert power.sleep(spec().request_id,OP,adapter)['state']=='sleeping'
    assert adapter.calls==['health','begin','freeze','assert_drained','quiesce','quiesced','shutdown']
    assert power.sleep(spec().request_id,OP,adapter)['state']=='sleeping'
    assert adapter.calls.count('shutdown')==1
    assert power.wake(spec().request_id,OP,adapter)['state']=='ready'
    assert power.book.status(spec().request_id)['state']=='staged'
    assert power.status(spec().request_id)['resources_reserved']


def test_unknown_shutdown_reply_observes_state_and_never_replays(setup):
    power,adapter=prepared(setup);adapter.error=TimeoutError('hidden')
    with pytest.raises(ProvisionError,match='power_outcome_unknown'): power.sleep(spec().request_id,OP,adapter)
    assert power.status(spec().request_id)['state']=='shutdown_sent'
    adapter.error=None
    assert power.sleep(spec().request_id,OP,adapter)['state']=='sleeping'
    assert adapter.calls.count('shutdown')==1


def test_unknown_start_reply_observes_without_second_start(setup):
    power,adapter=prepared(setup);power.sleep(spec().request_id,OP,adapter)
    adapter.error=TimeoutError()
    with pytest.raises(ProvisionError): power.wake(spec().request_id,OP,adapter)
    adapter.error=None
    assert power.wake(spec().request_id,OP,adapter)['state']=='ready'
    assert adapter.calls.count('start')==1


def test_wrong_owner_never_quiesces_or_stops(setup):
    power,adapter=prepared(setup)
    v=adapter.provider.vms[1]
    adapter.provider.vms[1]=v.model_copy(update={'owner':v.owner.model_copy(update={'tenant_id':'other'})})
    with pytest.raises(ProvisionError,match='vm_owner_or_configuration_changed'): power.sleep(spec().request_id,OP,adapter)
    assert adapter.calls==[]


def test_ack_and_health_failure_keeps_gate_closed(setup):
    power,adapter=prepared(setup)
    power.sleep(spec().request_id,OP,adapter)
    adapter.ack=False
    with pytest.raises(ProvisionError,match='wake_readiness_pending'): power.wake(spec().request_id,OP,adapter)
    assert power.status(spec().request_id)['state']=='waking'
    adapter.ack=True
    assert power.wake(spec().request_id,OP,adapter)['state']=='ready'


def test_native_gateway_epoch_change_denies_wake_without_releasing_gate(setup):
    power,adapter=prepared(setup);power.sleep(spec().request_id,OP,adapter);adapter.epoch+=1
    with pytest.raises(ProvisionError,match='wake_native_generation_unconfirmed'): power.wake(spec().request_id,OP,adapter)
    assert 'wake' not in adapter.calls


def test_exact_ssh_sources_compile_and_are_fixed_allowlists(tmp_path):
    for source in [NATIVE_REMOTE,TENANT_REMOTE,POWER_REMOTE]: compile(source,'<remote>','exec')
    assert "'--forceStop','0'" in POWER_REMOTE and "['qm','stop'" not in POWER_REMOTE
    assert 'guard' not in NATIVE_REMOTE # native check is exact metadata + OS lock, no model input
    config=tmp_path/'ssh';config.touch();calls=[]
    def run(argv,**kw):
        calls.append((argv,kw));return subprocess.CompletedProcess(argv,0,'{"ready":true}','do not log me')
    a=SSHPowerAdapter(ssh_config=config,host='pve',node='pve01',sources={'tenants':{},'devices':{}},runner=run)
    with pytest.raises(ProvisionError,match='operator_apply_required'): a.power('shutdown',spec(),spec(),'0'*64)
    assert calls==[]
