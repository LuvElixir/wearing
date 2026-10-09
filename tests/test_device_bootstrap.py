import base64
import importlib.util
import json
from pathlib import Path

import pytest

from wearing.cloud.device_bootstrap import BootstrapSpec, BootstrapBook, render, write_bundle, validate_delivery
from wearing.cloud.device_bootstrap_ssh import STAGE_REMOTE
from wearing.cloud.device_provisioning import Owner, ProvisionError, fingerprint
from test_device_provisioning import setup, reserve, spec

KEY='ssh-ed25519 '+base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+b'x'*32).decode()


def settings(**changes):
    return BootstrapSpec.model_validate({'node':'pve01','network':{'subnet':'10.78.1.0/30','tenant_ipv4':'10.77.101.2','turn_ipv4':'134.175.112.118'},
        'operator_ssh_public_key':KEY,'artifact_sha256':'a'*64,**changes})


def owner(item=None):
    item=item or spec()
    return Owner(tenant_id=item.tenant_id,identity_id=item.identity_id,resource_id=item.resource_id,request_id=item.request_id,
                 request_sha256=fingerprint(item.model_dump()),nonce='e'*64,kind=item.kind,vcpus=item.vcpus,memory_mib=item.memory_mib,disk_mib=item.disk_mib)


def network_module():
    path=Path(__file__).resolve().parents[1]/'deploy/on-prem/render-device-network.py'
    definition=importlib.util.spec_from_file_location('synthetic_device_network',path)
    module=importlib.util.module_from_spec(definition);definition.loader.exec_module(module);return module


def test_cloud_init_has_fresh_owner_os_identity_and_no_reused_credentials(tmp_path):
    result=render(spec(),owner(),settings())
    assert result==render(spec(),owner(),settings())
    user=json.loads(result['files']['user-data'].split('\n',1)[1])
    assert user['ssh_deletekeys'] and user['disable_root'] and not user['ssh_pwauth']
    assert user['users'][0]['lock_passwd'] and user['users'][0]['name']=='pajio-admin'
    assert user['users'][0]['ssh_authorized_keys']==[KEY]
    assert not {'password','chpasswd','token','pair_code'} & user.keys()
    assert 'OPENAI_API_KEY' not in json.dumps(result)
    another=spec(request_id='b'*32,tenant_id='tenant_b',resource_id='computer_b',vmid=1201)
    assert render(another,owner(another),settings())['manifest']['instance_id']!=result['manifest']['instance_id']
    write_bundle(tmp_path/'bundle',result)
    assert all(not p.stat().st_mode&0o077 for p in (tmp_path/'bundle').iterdir())
    with pytest.raises(ProvisionError,match='bootstrap_output_must_be_empty'): write_bundle(tmp_path/'bundle',result)


def test_fresh_guests_include_real_native_runtime_dependencies():
    from wearing.mobile import resource_id
    linux=json.loads(render(spec(),owner(),settings())['files']['user-data'].split('\n',1)[1])
    assert 'imagemagick' in linux['packages'] # Agent capture uses import, independently of mss/WebRTC.
    phone=spec(kind='android',resource_id=resource_id('127.0.0.1:21200'))
    android=json.loads(render(phone,owner(phone),settings())['files']['user-data'].split('\n',1)[1])
    assert 'libatomic1' in android['packages'] # Required by the pinned Node 26 binary.
    assert 'linux-modules-extra-generic' not in android['packages'] # Not a valid Noble package.


@pytest.mark.parametrize('value',['-----BEGIN PRIVATE KEY-----','ssh-ed25519 AAAA','command="oops" '+KEY,KEY+'\n'+KEY])
def test_credentials_and_ssh_options_cannot_enter_bootstrap(value):
    with pytest.raises(ValueError): settings(operator_ssh_public_key=value)


@pytest.mark.parametrize('changes',[{'subnet':'192.168.1.0/30'},{'subnet':'10.78.1.0/24'},{'subnet':'10.78.1.1/30'},
                                   {'turn_ipv4':'127.0.0.1'},{'uplink':'vmbr0; echo fail'}])
def test_invalid_networks_fail_closed(changes):
    n=settings().network.model_dump();n.update(changes)
    with pytest.raises(ValueError): settings(network=n)


def test_network_fragments_have_anti_spoof_cross_tenant_host_and_ipv6_denials():
    module=network_module();bundle=render(spec(),owner(),settings());lease=json.loads(bundle['files']['network-lease.json'])
    rules=module.rules([lease])
    assert 'ip saddr != 10.78.1.2 drop' in rules and 'meta nfproto ipv6 drop' in rules
    assert 'ip daddr @nonpublic drop' in rules and 'provisioned_input iifname "pj1200"' in rules
    assert 'ip saddr 10.77.101.2 tcp dport 9443 accept' in rules
    assert 'ip daddr 10.77.101.2 tcp dport 8444 accept' in rules
    assert 'tcp dport 22 accept' not in rules and 'flush ruleset' not in rules
    assert module.rules([]).strip()==''
    with pytest.raises(ValueError,match='duplicate_network_scope'):module.rules([lease,lease])
    lease['uplink']='vmbr0\nflush ruleset'
    with pytest.raises(ValueError):module.rules([lease])


def test_parent_hooks_and_persistence_preserve_guard_order():
    root=Path(__file__).resolve().parents[1]/'deploy/on-prem'
    source=(root/'lab-network.nft').read_text()
    forward=source.split('chain guest_forward {',1)[1].split('table ip',1)[0]
    assert forward.index('ip saddr != 10.77.104.2') < forward.index('jump provisioned_forward') < forward.index('ip daddr @nonpublic')
    host=source.split('chain host_input {',1)[1].split('chain guest_forward',1)[0]
    assert 'jump provisioned_input' in host and 'jump provisioned_forward' not in host
    apply=(root/'apply-lab-network.sh').read_text()
    assert apply.index('pajio-render-device-network.py') < apply.index('nft --check') < apply.index('nft --file')
    assert 'flock -n 9' in apply


def test_stopped_stage_uses_original_owner_and_artifact_binding_after_timeout(setup):
    book,provider=setup;sha=reserve(book,provider);book.apply(spec().request_id,provider,plan_sha256=sha)
    b=BootstrapBook(book);plan=b.plan(spec().request_id,settings(),provider);calls=[]
    def stage(item,o,config,bundle):
        calls.append(config)
        return {'network_staged':True,'started':False,'bundle_sha256':bundle['bundle_sha256'],
                'config_sha256':provider.inspect_vm(item.vmid).config_sha256}
    provider.stage_network=stage
    result=b.stage_network(spec().request_id,settings(),provider,reviewed_sha256=plan['bundle_sha256'])
    assert result['state']=='network_staged' and not result['product_ready'] and not result['started']
    with pytest.raises(ProvisionError,match='bootstrap_plan_changed'):
        b.stage_network(spec().request_id,settings(),provider,reviewed_sha256='0'*64)
    assert len(calls)==1
    compile(STAGE_REMOTE,'<exact-network-stage>','exec')
    assert "['qm','start'" not in STAGE_REMOTE and "['ifup',bridge]" in STAGE_REMOTE


def test_partial_or_wrong_scope_evidence_never_means_delivered():
    o=owner();partial={'owner_sha256':fingerprint(o.model_dump()),'native_ready':True}
    result=validate_delivery(o,partial)
    assert not result['product_ready'] and 'paired_scope_matches' in result['pending']
    with pytest.raises(ProvisionError,match='delivery_owner_changed'):validate_delivery(o,{})
