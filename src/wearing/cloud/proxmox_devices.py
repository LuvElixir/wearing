"""Narrow operator SSH transport: inspect, full-clone stopped, prepare stopped.

No start/stop/delete operations. Host key checking uses the operator's existing
SSH config. Provider stderr/configuration and input text never enter diagnostics.
"""
import json
from pathlib import Path
import re
import shlex
import subprocess

from .device_provisioning import Inventory, ProvisionError, VM

# Runs only with the administrator's preconfigured SSH access. Inputs are JSON
# on stdin, not shell interpolation; pvesh/qm/lvs use fixed argument arrays.
REMOTE = r'''
import fcntl,hashlib,json,math,os,re,subprocess,sys,time
p=json.load(sys.stdin)
def fail(code):
    print(json.dumps({'error':code}));sys.exit(1)
def call(*args):
    r=subprocess.run(list(args),capture_output=True,text=True,timeout=45)
    if r.returncode:fail('proxmox_query_failed')
    return json.loads(r.stdout)
def digest(c):
    return hashlib.sha256(json.dumps({k:v for k,v in c.items() if k!='digest'},sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def config(vmid):
    return call('pvesh','get',f'/nodes/{p["node"]}/qemu/{vmid}/config','--output-format','json')
def mb_disk(c):
    total=0
    for key,value in c.items():
        if re.fullmatch(r'(?:scsi|sata|virtio|ide)\d+',key) and isinstance(value,str):
            if 'media=cdrom' in value or 'cloudinit' in value:continue
            m=re.search(r'(?:^|,)size=(\d+(?:\.\d+)?)([KMGT])(?:,|$)',value)
            if not m:fail('unsupported_disk_layout')
            total+=math.ceil(float(m[1])*{'K':1/1024,'M':1,'G':1024,'T':1048576}[m[2]])
    return total
def owner(c):
    try:return json.loads(c.get('description','')).get('pajio_provisioning')
    except (ValueError,AttributeError):return None
def vm(row):
    c=config(row['vmid']);o=owner(c)
    # Do not output descriptions, bootstrap keys, IPs or arbitrary config data.
    return {'vmid':row['vmid'],'state':row['status'],'vcpus':int(c.get('cores',1))*int(c.get('sockets',1)),
            'memory_mib':int(c.get('memory',512)),'disk_mib':mb_disk(c),'template':bool(c.get('template',False)),
            'locked':bool(c.get('lock')),'owner':o,'config_sha256':digest(c),
            'prepared':int(c.get('onboot',0))==0 and int(c.get('balloon',0))==0 and not any(re.fullmatch(r'(?:net|ipconfig)\d+',k) or k in ('sshkeys','cicustom','cipassword','ciuser','nameserver','searchdomain') for k in c)}
def inventory():
    status=call('pvesh','get',f'/nodes/{p["node"]}/status','--output-format','json')
    rows=call('pvesh','get','/cluster/resources','--type','vm','--output-format','json')
    rows=[r for r in rows if r['node']==p['node']]
    if any(r['type']!='qemu' for r in rows):fail('unsupported_container_inventory')
    storage=call('pvesh','get',f'/nodes/{p["node"]}/storage/{p["storage"]}/status','--output-format','json')
    if storage.get('type')!='lvmthin' or not storage.get('active') or not storage.get('enabled'):fail('unsupported_storage_inventory')
    config_storage=call('pvesh','get',f'/storage/{p["storage"]}','--output-format','json')
    if config_storage.get('vgname')!=p['vg'] or config_storage.get('thinpool')!=p['pool']:fail('storage_pool_mismatch')
    volumes=call('lvs','--reportformat','json','--units','b','--nosuffix','-o','vg_name,lv_name,lv_size,pool_lv')['report'][0]['lv']
    used=sum(math.ceil(float(v['lv_size'])/1048576) for v in volumes if v['vg_name']==p['vg'] and v['pool_lv']==p['pool'])
    return {'node':p['node'],'storage':p['storage'],'observed_at':time.time(),
            'physical_cores':int(status['cpuinfo']['cores'])*int(status['cpuinfo']['sockets']),
            'memory_mib':int(status['memory']['total'])//1048576,
            'available_memory_mib':int(status['memory']['available'])//1048576,
            'storage_mib':int(storage['total'])//1048576,'available_storage_mib':int(storage['avail'])//1048576,
            'committed_storage_mib':used,'vms':[vm(r) for r in rows]}
def checked_target(spec,expected):
    c=config(spec['vmid'])
    state=call('pvesh','get',f'/nodes/{p["node"]}/qemu/{spec["vmid"]}/status/current','--output-format','json')
    if owner(c)!=expected or c.get('template') or c.get('lock') or state.get('status')!='stopped':fail('vm_owner_or_state_conflict')
    return c
def run_change(argv):
    # No automatic retry after timeout: the operator ledger retains the attempt.
    r=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=300)
    if r.returncode:fail('proxmox_mutation_unconfirmed')
for key in ('node','storage','vg','pool'):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}',p.get(key,'')):fail('invalid_operator_target')
action=p.get('action')
if action=='inventory':print(json.dumps(inventory()));sys.exit()
if action not in ('clone_stopped','prepare_stopped'):fail('proxmox_action_not_allowed')
lock=os.open('/run/lock/pajio-device-provision.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:fail('host_provision_inflight')
spec,policy,expected=p['spec'],p['policy'],p['owner']
if action=='clone_stopped':
    inv=inventory();vms=inv['vms'];template=policy['templates'][spec['kind']]
    if any(v['vmid']==spec['vmid'] for v in vms):fail('vm_id_or_owner_conflict')
    source=next((v for v in vms if v['vmid']==template['vmid']),None)
    if not source or not source['template'] or source['state']!='stopped' or source['locked'] or source['owner'] or source['config_sha256']!=template['config_sha256'] or source['disk_mib']!=spec['disk_mib']:fail('reviewed_clean_template_required')
    # Final host-side fence serializes even separate operator processes. Known
    # staged devices count their promised memory/CPU, despite being powered off.
    memory=cpus=backup=0;slots={'linux':policy['external_linux_slots'],'android':policy['external_android_slots']}
    for item in vms:
        o=item['owner']
        if o:
            if o['request_id']==spec['request_id'] or o['resource_id']==spec['resource_id'] or (o['tenant_id'],o['kind'])==(spec['tenant_id'],spec['kind']):fail('device_binding_conflict')
            memory+=max(item['memory_mib'],o['memory_mib']);cpus+=max(item['vcpus'],o['vcpus']);backup+=o['disk_mib'];slots[o['kind']]+=1
        elif item['state']!='stopped' and not item['template']:
            memory+=item['memory_mib'];cpus+=item['vcpus']
    if memory+spec['memory_mib']+policy['host_memory_mib']>inv['memory_mib'] or cpus+spec['vcpus']+policy['host_cores']>inv['physical_cores']:fail('host_capacity_changed')
    slots[spec['kind']]+=1
    if any(slots[k]>policy[k+'_slots'] for k in slots):fail('host_capacity_changed')
    extra=spec['disk_mib']*2+4+backup
    if inv['committed_storage_mib']+extra>inv['storage_mib']*(100-policy['disk_free_percent'])//100:fail('host_capacity_changed')
    if inv['available_storage_mib']<extra+inv['storage_mib']*policy['disk_free_percent']//100 or inv['available_memory_mib']<spec['memory_mib']+policy['host_memory_mib']:fail('host_capacity_changed')
    source_config=config(template['vmid'])
    if int(source_config.get('onboot',0))!=0:fail('template_autostart_forbidden')
    # Ownership is part of qm's atomic clone creation, never attached afterward
    # to an unowned VMID. Existing VMIDs make qm clone fail rather than overwrite.
    run_change(['qm','clone',str(template['vmid']),str(spec['vmid']),'--full','1','--storage',p['storage'],
                '--name','pajio-device-'+spec['request_id'][:12],'--description',json.dumps({'pajio_provisioning':expected},separators=(',',':'))])
    checked_target(spec,expected)
else:
    c=checked_target(spec,expected)
    if digest(c)!=p['config_sha256']:fail('vm_configuration_changed')
    remove=[key for key in c if re.fullmatch(r'(?:net|ipconfig)\d+',key) or key in ('sshkeys','cicustom','cipassword','ciuser','nameserver','searchdomain')]
    argv=['qm','set',str(spec['vmid']),'--digest',c['digest'],'--memory',str(spec['memory_mib']),
          '--cores',str(spec['vcpus']),'--sockets','1','--balloon','0','--onboot','0']
    if remove:argv+=['--delete',','.join(sorted(remove))]
    run_change(argv);checked_target(spec,expected)
print(json.dumps({'ok':True,'started':False}))
'''


class ProxmoxDevices:
    def __init__(self, *, ssh_config, host, node, storage='local-lvm', vg='pve', pool='data',
                 allow_create=False, runner=subprocess.run):
        for value in (host, node, storage, vg, pool):
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}', value):
                raise ProvisionError('invalid_operator_target')
        self.config = Path(ssh_config).expanduser().resolve()
        if not self.config.is_file():
            raise ProvisionError('ssh_config_required')
        self.host = host
        self.params = {'node': node, 'storage': storage, 'vg': vg, 'pool': pool}
        self.allow_create, self.runner = allow_create, runner

    def _call(self, action, **body):
        if action not in {'inventory', 'clone_stopped', 'prepare_stopped'}:
            raise ProvisionError('proxmox_action_not_allowed')
        if action != 'inventory' and not self.allow_create:
            raise ProvisionError('operator_apply_required')
        argv = ['ssh', '-F', str(self.config), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ConnectTimeout=10', self.host, 'python3 -c ' + shlex.quote(REMOTE)]
        try:
            result = self.runner(argv, input=json.dumps({**self.params, 'action': action, **body}),
                                 capture_output=True, text=True, timeout=360 if action != 'inventory' else 60)
            if len(result.stdout) > 4 * 1024 * 1024:
                raise ValueError()
            data = json.loads(result.stdout)
            if result.returncode or data.get('error'):
                code = data.get('error')
                if not isinstance(code, str) or not re.fullmatch(r'[a-z_]{1,80}', code):
                    code = 'provider_outcome_unknown'
                raise ProvisionError(code)
            return data
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError) as error:
            if isinstance(error, ProvisionError):
                raise
            raise ProvisionError('provider_outcome_unknown') from None

    def inventory(self):
        try:
            return Inventory.model_validate(self._call('inventory'))
        except ValueError as error:
            if isinstance(error, ProvisionError):
                raise
            raise ProvisionError('invalid_provider_inventory') from None

    def inspect_vm(self, vmid):
        return next((vm for vm in self.inventory().vms if vm.vmid == vmid), None)

    def clone_stopped(self, spec, policy, owner):
        return self._call('clone_stopped', spec=spec.model_dump(), policy=policy.model_dump(), owner=owner.model_dump())

    def prepare_stopped(self, spec, policy, owner, config_sha256):
        return self._call('prepare_stopped', spec=spec.model_dump(), policy=policy.model_dump(),
                          owner=owner.model_dump(), config_sha256=config_sha256)
