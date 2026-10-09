"""Host renderer evidence: validate real files and atomic-apply failure path."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_device_bootstrap import settings, owner
from test_device_provisioning import spec
from wearing.cloud.device_bootstrap import render

ROOT=Path(__file__).resolve().parents[1]/'deploy/on-prem'

@pytest.fixture
def network():
    definition=importlib.util.spec_from_file_location('test_network_renderer',ROOT/'render-device-network.py')
    module=importlib.util.module_from_spec(definition);definition.loader.exec_module(module)
    return module

@pytest.fixture
def lease():
    return json.loads(render(spec(),owner(),settings())['files']['network-lease.json'])

@pytest.fixture
def files(tmp_path, monkeypatch, lease):
    directory=tmp_path/'leases';directory.mkdir(mode=0o700)
    path=directory/'1200.json';path.write_text(json.dumps(lease));path.chmod(0o600)
    original=Path.stat
    # CI/macOS files belong to the test user. Substitute uid only; all modes,
    # paths, symlinks, bytes and subprocess behavior below are real.
    def stat(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        if self==directory or directory in self.parents:
            data=list(result);data[4]=0;result=os.stat_result(data)
        return result
    monkeypatch.setattr(Path,'stat',stat)
    return directory,path

def query_for(lease,**changes):
    config={'description':json.dumps({'pajio_provisioning':lease['owner']}),'net0':'virtio=AA:BB:CC:DD:EE:FF,bridge=pj1200'}
    config.update(changes)
    def query(command,timeout):
        assert command==['pvesh','get','/nodes/pve01/qemu/1200/config','--output-format','json']
        assert timeout==10
        return json.dumps(config).encode()
    return query

def test_load_checks_actual_owner_and_bridge_before_rendering(network,lease,files):
    directory,_=files
    assert network.load(directory,query_for(lease))==[lease]
    for changes in ({'description':'{}'},{'template':1},{'net0':'virtio=AA,bridge=vmbr0'},{'net1':'virtio=BB,bridge=pj1200'}):
        with pytest.raises(ValueError):network.load(directory,query_for(lease,**changes))

def test_untrusted_permissions_symlinks_and_filenames_fail_closed(network,lease,files):
    directory,path=files
    directory.chmod(0o777)
    with pytest.raises(ValueError,match='unsafe_network_directory'):network.load(directory,query_for(lease))
    directory.chmod(0o700);path.chmod(0o644)
    with pytest.raises(ValueError,match='unsafe_network_lease'):network.load(directory,query_for(lease))
    path.chmod(0o600);other=directory/'1201.json';path.rename(other)
    with pytest.raises(ValueError,match='network_filename_changed'):network.load(directory,query_for(lease))
    other.rename(path);link=directory.parent/'link';link.symlink_to(directory,target_is_directory=True)
    with pytest.raises(ValueError,match='unsafe_network_directory'):network.load(link,query_for(lease))

@pytest.mark.parametrize('key',['vmid','subnet','resource_id','request_id'])
def test_each_global_unique_network_key_rejects_duplicate(network,lease,key):
    other=json.loads(json.dumps(lease));other['vmid']=1201;other['subnet']='10.78.1.4/30'
    other['owner']['resource_id']='computer_b';other['owner']['request_id']='b'*32
    if key in ('vmid','subnet'):other[key]=lease[key]
    else:other['owner'][key]=lease['owner'][key]
    with pytest.raises(ValueError,match='duplicate_network_scope'):network.rules([lease,other])

def test_only_paired_tenant_ports_precede_private_drop_and_default_deny(network,lease):
    value=network.rules([lease]);forward=[v for v in value.splitlines() if 'pv1200_forward ' in v]
    private=next(i for i,v in enumerate(forward) if 'ip daddr @nonpublic drop' in v)
    accepts=[v for v in forward[:private] if ' accept' in v]
    assert any('ip saddr 10.77.101.2 tcp dport 9443 accept' in v for v in accepts)
    assert any('ip daddr 10.77.101.2 tcp dport 8444 accept' in v for v in accepts)
    assert not any('tcp dport 22' in v or '8006' in v or '192.168.' in v for v in accepts)
    assert forward[-1].endswith(' drop')
    assert 'ip saddr != 10.78.1.2 drop' in value and 'ip daddr != 10.78.1.2 drop' in value
    assert 'meta nfproto ipv6 drop' in value and 'flush ruleset' not in value

def test_root_parse_failure_never_calls_nft_check_or_replacement(tmp_path):
    # Relocate only deployment paths so the real apply control flow can run
    # without modifying host /etc or requiring root in developer test runs.
    log=tmp_path/'nft.log';binary=tmp_path/'bin';binary.mkdir()
    nft=binary/'nft';nft.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$NFT_LOG"\nexit 0\n');nft.chmod(0o755)
    flock=binary/'flock';flock.write_text('#!/bin/sh\nexit 0\n');flock.chmod(0o755)
    rules=tmp_path/'rules';rules.write_text('table inet pajio_lab_guard {}\n')
    renderer=tmp_path/'renderer.py';renderer.write_text('raise SystemExit("bad ownership")\n')
    source=(ROOT/'apply-lab-network.sh').read_text().replace('/run/lock/pajio-device-network.lock',str(tmp_path/'lock')).replace('/etc/pajio/lab-network.nft',str(rules)).replace('/usr/local/libexec/pajio-render-device-network.py',str(renderer))
    process=subprocess.run(['sh'],input=source,text=True,capture_output=True,env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'NFT_LOG':str(log)})
    assert process.returncode!=0 and 'bad ownership' in process.stderr
    assert log.read_text().splitlines()==['list table inet pajio_lab_guard','list table ip pajio_lab_nat']
