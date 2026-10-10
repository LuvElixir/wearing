"""Root-owned Core resource promises, shared by device and Core admission.

The host reads its own durable reservations; callers cannot supply an archive or
success flag. A stopped or not-yet-created Core retains its complete promise.
No release, restore, deletion, tenant registration or user operation is exposed.
"""

CORE_RESERVATIONS_SOURCE = r'''
import hashlib,json,os,re,stat,subprocess
from pathlib import Path

def core_reservations(vms,root='/var/lib/pajio-core-provisioning',node='pve01'):
    def require(ok):
        if not ok:raise ValueError('core_reservation_evidence_invalid')
    def read(path):
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd)
            require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o600 and st.st_size<=65536)
            raw=os.read(fd,65537);require(len(raw)<=65536);return raw
        finally:os.close(fd)
    def directory(path):
        st=path.lstat();require(stat.S_ISDIR(st.st_mode) and st.st_uid==0 and stat.S_IMODE(st.st_mode)==0o700)
    require(node=='pve01')
    base=Path(root)
    if not base.exists() and not base.is_symlink():return []
    directory(base);result=[];tenants=set();requests=set();ids=set()
    observed={row['vmid']:row for row in vms};require(len(observed)==len(vms))
    for folder in sorted(base.iterdir()):
        require(re.fullmatch(r'[1-9][0-9]{2,8}',folder.name) is not None);directory(folder)
        # An interrupted prepare directory is not silently free capacity.
        value=json.loads(read(folder/'reservation.json'))
        require(set(value)=={'version','node','vmid','tenant_id','request_id','vcpus','memory_mib','disk_mib','image_sha256'})
        require(type(value['version']) is int and value['version']==1 and value['node']==node)
        require(type(value['vmid']) is int and value['vmid']==int(folder.name))
        require(isinstance(value['tenant_id'],str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}',value['tenant_id']) is not None)
        require(isinstance(value['request_id'],str) and re.fullmatch(r'[a-f0-9]{32}',value['request_id']) is not None)
        require(isinstance(value['image_sha256'],str) and re.fullmatch(r'[a-f0-9]{64}',value['image_sha256']) is not None)
        for key,minimum,maximum in [('vcpus',1,16),('memory_mib',1024,32768),('disk_mib',16384,1048576)]:
            require(type(value[key]) is int and minimum<=value[key]<=maximum)
        require(value['tenant_id'] not in tenants and value['request_id'] not in requests and value['vmid'] not in ids)
        tenants.add(value['tenant_id']);requests.add(value['request_id']);ids.add(value['vmid'])
        row=observed.get(value['vmid'])
        if row is not None:
            require(not row.get('template') and row.get('owner') is None)
            answer=subprocess.run(['pvesh','get','/nodes/pve01/qemu/'+str(value['vmid'])+'/config','--output-format','json'],capture_output=True,text=True,timeout=30)
            require(answer.returncode==0 and len(answer.stdout)<=131072)
            config=json.loads(answer.stdout)
            description=json.loads(config.get('description',''))
            require(description=={'pajio_core_provisioning':value} and not config.get('template'))
        result.append({'vmid':value['vmid'],'vcpus':max(value['vcpus'],row['vcpus']) if row else value['vcpus'],
                       'memory_mib':max(value['memory_mib'],row['memory_mib']) if row else value['memory_mib'],
                       'disk_mib':max(value['disk_mib'],row['disk_mib']) if row else value['disk_mib']})
    return result
'''
