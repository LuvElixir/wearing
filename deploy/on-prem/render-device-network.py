#!/usr/bin/python3
"""Root-owned device leases -> fixed nft rules; no arbitrary rule text accepted."""
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess


def validate(leases):
    seen = {k: set() for k in ('vmid','subnet','resource_id','request_id')}
    for v in leases:
        if set(v) != {'version','vmid','node','owner','subnet','tenant_ipv4','turn_ipv4','uplink'} or v['version'] != 1:
            raise ValueError('invalid_network_lease')
        if type(v['vmid']) is not int or not 100 <= v['vmid'] <= 999999999:
            raise ValueError('invalid_network_lease')
        for key in ('node','uplink'):
            if not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,14}',v[key]): raise ValueError('invalid_network_lease')
        owner=v['owner']
        if not isinstance(owner,dict) or set(owner)!={'version','tenant_id','identity_id','resource_id','request_id','request_sha256','nonce','kind','vcpus','memory_mib','disk_mib'}:
            raise ValueError('invalid_network_owner')
        for key in ('tenant_id','identity_id','resource_id'):
            if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}',owner[key]): raise ValueError('invalid_network_owner')
        for key,length in [('request_id',32),('nonce',64),('request_sha256',64)]:
            if not re.fullmatch('[a-f0-9]{'+str(length)+'}',owner[key]):raise ValueError('invalid_network_owner')
        if owner['version']!=1 or owner['kind'] not in ('linux','android') or any(type(owner[k]) is not int or owner[k]<=0 for k in ('vcpus','memory_mib','disk_mib')):raise ValueError('invalid_network_owner')
        net=ipaddress.ip_network(v['subnet'],strict=True)
        tenant,turn=ipaddress.ip_address(v['tenant_ipv4']),ipaddress.ip_address(v['turn_ipv4'])
        if net.version!=4 or net.prefixlen!=30 or not net.subnet_of(ipaddress.ip_network('10.78.0.0/16')) or tenant.version!=4 or not tenant.is_private or tenant in net or turn.version!=4 or not turn.is_global:
            raise ValueError('invalid_network_scope')
        for key,value in [('vmid',v['vmid']),('subnet',str(net)),('resource_id',owner['resource_id']),('request_id',owner['request_id'])]:
            if value in seen[key]:raise ValueError('duplicate_network_scope')
            seen[key].add(value)
    return leases


def rules(leases):
    lines=[]
    for v in validate(leases):
        vid=v['vmid'];bridge='pj'+str(vid);guest=str(ipaddress.ip_network(v['subnet']).network_address+2)
        tenant,turn=v['tenant_ipv4'],v['turn_ipv4'];ci='pv'+str(vid)+'_input';cf='pv'+str(vid)+'_forward'
        for name in (ci,cf):lines.append(f'add chain inet pajio_lab_guard {name}')
        def rule(chain,body):lines.append(f'add rule inet pajio_lab_guard {chain} {body}')
        rule('provisioned_input',f'iifname "{bridge}" jump {ci}')
        rule(ci,'meta nfproto ipv6 drop');rule(ci,f'ip saddr != {guest} drop')
        rule(ci,'ct state established,related accept');rule(ci,'drop')
        rule('provisioned_forward',f'iifname "{bridge}" jump {cf}')
        rule('provisioned_forward',f'oifname "{bridge}" jump {cf}')
        rule(cf,'meta nfproto ipv6 drop')
        rule(cf,f'iifname "{bridge}" ip saddr != {guest} drop')
        rule(cf,f'oifname "{bridge}" ip daddr != {guest} drop')
        rule(cf,'ct state established,related accept')
        rule(cf,f'oifname "{bridge}" ip saddr {tenant} tcp dport 9443 accept')
        rule(cf,f'oifname "{bridge}" drop')
        rule(cf,f'ip daddr {tenant} tcp dport 8444 accept')
        rule(cf,f'ip daddr {turn} udp dport {{ 3478,49160-49200 }} accept')
        rule(cf,f'ip daddr {turn} tcp dport 3478 accept')
        rule(cf,'ip daddr @nonpublic drop')
        rule(cf,f'oifname "{v["uplink"]}" ip daddr {{ 223.5.5.5,1.1.1.1 }} udp dport 53 accept')
        rule(cf,f'oifname "{v["uplink"]}" ip daddr {{ 223.5.5.5,1.1.1.1 }} tcp dport 53 accept')
        rule(cf,f'oifname "{v["uplink"]}" tcp dport {{ 80,443 }} accept')
        rule(cf,f'oifname "{v["uplink"]}" udp dport 123 accept');rule(cf,'drop')
        lines.append(f'add rule ip pajio_lab_nat provisioned_nat ip saddr {guest} oifname "{v["uplink"]}" masquerade')
    return '\n'.join(lines)+'\n'


def load(root=Path('/etc/pajio/device-network'), query=subprocess.check_output):
    if not root.exists():return []
    if root.is_symlink() or root.stat().st_uid!=0 or root.stat().st_mode&0o022:raise ValueError('unsafe_network_directory')
    leases=[]
    for path in sorted(root.iterdir()):
        if not re.fullmatch(r'[0-9]+\.json',path.name) or path.is_symlink() or not path.is_file() or path.stat().st_uid!=0 or path.stat().st_mode&0o077 or path.stat().st_size>16384:
            raise ValueError('unsafe_network_lease')
        value=json.loads(path.read_text());validate([value])
        if path.stem!=str(value['vmid']):raise ValueError('network_filename_changed')
        config=json.loads(query(['pvesh','get',f'/nodes/{value["node"]}/qemu/{value["vmid"]}/config','--output-format','json'],timeout=10))
        if json.loads(config.get('description','{}')).get('pajio_provisioning')!=value['owner'] or config.get('template'):
            raise ValueError('network_vm_owner_changed')
        parts=dict(part.split('=',1) for part in config.get('net0','').split(',') if '=' in part)
        if parts.get('bridge')!='pj'+str(value['vmid']) or any(re.fullmatch(r'net[1-9][0-9]*',k) for k in config):
            raise ValueError('network_vm_bridge_changed')
        leases.append(value)
    return validate(leases)


if __name__=='__main__':
    try:
        if os.geteuid()!=0:raise ValueError('operator_required')
        print(rules(load()),end='')
    except Exception:
        raise SystemExit('Device network ownership verification failed; firewall was not replaced.')
