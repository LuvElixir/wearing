"""Root-owned preclaim capacity for full bundles and isolated benchmark fixtures.

This is capacity evidence only. A reservation grants no account, membership,
remote-control, pairing or device ownership. Normal device creation still uses
fresh AccountProof admission and records the exact Owner at first claim.
"""

RESOURCE_RESERVATIONS_SOURCE = r'''
import hashlib,json,os,re,stat,subprocess,tempfile,time
from pathlib import Path

def resource_reservations(vms,root='/var/lib/pajio-resource-reservations',node='pve01',core_root='/var/lib/pajio-core-provisioning'):
    def require(ok):
        if not ok:raise ValueError('resource_reservation_evidence_invalid')
    def read(path):
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd);require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o600 and st.st_size<=131072)
            raw=os.read(fd,131073);require(len(raw)<=131072);return raw
        finally:os.close(fd)
    def directory(path):
        st=path.lstat();require(stat.S_ISDIR(st.st_mode) and st.st_uid==0 and stat.S_IMODE(st.st_mode)==0o700)
    def query(args):
        answer=subprocess.run(args,capture_output=True,text=True,timeout=30)
        require(answer.returncode==0 and len(answer.stdout)<=1048576);return json.loads(answer.stdout)
    def ident(value):return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{32}',value) is not None
    def digest(value):return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{64}',value) is not None
    require(node=='pve01');base=Path(root)
    if not base.exists() and not base.is_symlink():return []
    directory(base);observed={v['vmid']:v for v in vms};require(len(observed)==len(vms));result=[];ids=set();requests=set();tenants=set()
    for folder in sorted(base.iterdir()):
        require(ident(folder.name));directory(folder)
        raw=read(folder/'reservation.json');hashed=hashlib.sha256(raw).hexdigest();value=json.loads(raw)
        require(set(value)=={'version','reservation_id','node','purpose','tenant_id','created_at','expires_at','members'})
        require(type(value['version']) is int and value['version']==1 and value['reservation_id']==folder.name and value['node']==node)
        require(value['purpose'] in ('invitation','benchmark') and type(value['created_at']) is int and type(value['expires_at']) is int and 0<value['created_at']<value['expires_at'])
        tenant=value['tenant_id']
        require(tenant is None if value['purpose']=='benchmark' else isinstance(tenant,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',tenant) is not None)
        if tenant is not None:require(tenant not in tenants);tenants.add(tenant)
        members=value['members'];require(isinstance(members,list) and 1<=len(members)<=6)
        if value['purpose']=='invitation':require(sorted(m.get('kind','') for m in members)==['android','core','linux'])
        local=set();validated=[]
        for member in members:
            require(isinstance(member,dict) and set(member)=={'kind','vmid','request_id','vcpus','memory_mib','disk_mib','image_sha256','core_reservation_sha256'})
            require(member['kind'] in ('core','linux','android') and ident(member['request_id']) and digest(member['image_sha256']))
            require(type(member['vmid']) is int and 100<=member['vmid']<=999999999 and member['vmid'] not in ids and member['request_id'] not in requests)
            for key,lo,hi in [('vcpus',1,16),('memory_mib',1024,32768),('disk_mib',16384,1048576)]:require(type(member[key]) is int and lo<=member[key]<=hi)
            if member['kind']!='core':require(member['memory_mib']>=2048 and member['core_reservation_sha256'] is None)
            else:require(value['purpose']=='invitation' and digest(member['core_reservation_sha256']))
            ids.add(member['vmid']);requests.add(member['request_id']);local.add(member['vmid']);validated.append(member)
        released=folder/'released.json'
        if released.exists() or released.is_symlink():
            receipt=json.loads(read(released));require(set(receipt)=={'version','reservation_sha256','removed_vmids'} and type(receipt['version']) is int and receipt['version']==1 and receipt['reservation_sha256']==hashed and receipt['removed_vmids']==sorted(local))
            require(not local.intersection(observed))
            volumes=query(['pvesh','get','/nodes/'+node+'/storage/local-lvm/content','--output-format','json'])
            require(not any(v.get('vmid') in local for v in volumes))
            require(not any((Path(core_root)/str(v)/'reservation.json').exists() for v in local))
            continue
        # Expiration alone never frees compute; unknown/partial attempts still count.
        for member in validated:
            vmid=member['vmid'];row=observed.get(vmid);claim_path=folder/('claim-'+str(vmid)+'.json');claimed=None
            if claim_path.exists() or claim_path.is_symlink():
                require(value['purpose']=='invitation' and member['kind']!='core')
                claim=json.loads(read(claim_path));require(set(claim)=={'version','reservation_sha256','owner'} and type(claim['version']) is int and claim['version']==1 and claim['reservation_sha256']==hashed)
                claimed=claim['owner'];require(isinstance(claimed,dict) and set(claimed)=={'version','tenant_id','identity_id','resource_id','request_id','request_sha256','nonce','kind','vcpus','memory_mib','disk_mib'})
                require(type(claimed['version']) is int and claimed['version']==1 and claimed['tenant_id']==tenant and digest(claimed['request_sha256']) and digest(claimed['nonce']))
                require(all(isinstance(claimed[k],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',claimed[k]) for k in ('identity_id','resource_id')))
                require(all(claimed[k]==member[k] for k in ('request_id','kind','vcpus','memory_mib','disk_mib')))
            corepath=Path(core_root)/str(vmid)/'reservation.json'
            if member['kind']=='core' and (corepath.exists() or corepath.is_symlink()):
                directory(Path(core_root));directory(corepath.parent);core_raw=read(corepath);core=json.loads(core_raw)
                require(hashlib.sha256(core_raw).hexdigest()==member['core_reservation_sha256'] and core['tenant_id']==tenant and core['node']==node and core['vmid']==vmid and all(core[k]==member[k] for k in ('request_id','vcpus','memory_mib','disk_mib','image_sha256')))
            if row is not None:
                require(not row.get('template'))
                if row.get('owner') is not None:require(claimed is not None and row['owner']==claimed)
                else:
                    require(claimed is None)
                    config=query(['pvesh','get','/nodes/'+node+'/qemu/'+str(vmid)+'/config','--output-format','json']);description=json.loads(config.get('description',''))
                    if member['kind']=='core':require(corepath.exists() and description=={'pajio_core_provisioning':json.loads(read(corepath))})
                    else:require(value['purpose']=='benchmark' and description=={'pajio_benchmark':{'reservation_id':value['reservation_id'],'member':member}})
            result.append({'reservation_id':value['reservation_id'],'reservation_sha256':hashed,'purpose':value['purpose'],'tenant_id':tenant,
                           'vmid':vmid,'kind':member['kind'],'request_id':member['request_id'],'owner':claimed,'expires_at':value['expires_at'],
                           'vcpus':max(member['vcpus'],row['vcpus']) if row else member['vcpus'],
                           'memory_mib':max(member['memory_mib'],row['memory_mib']) if row else member['memory_mib'],
                           'disk_mib':max(member['disk_mib'],row['disk_mib']) if row else member['disk_mib']})
    return result

def bind_resource_claim(promise,owner,root='/var/lib/pajio-resource-reservations'):
    # Called only inside the normal host clone fence, after operator AccountProof
    # admission. A capacity record itself never authorizes this operation.
    if promise['purpose']!='invitation' or promise['kind']=='core' or any(owner[k]!=promise[k] for k in ('tenant_id','request_id','kind')) or any(owner[k]!=promise[k] for k in ('vcpus','memory_mib','disk_mib')):
        raise ValueError('preclaim_owner_conflict')
    folder=Path(root)/promise['reservation_id'];path=folder/('claim-'+str(promise['vmid'])+'.json')
    value={'version':1,'reservation_sha256':promise['reservation_sha256'],'owner':owner}
    if path.exists() or path.is_symlink():
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>131072:raise ValueError('preclaim_file_unsafe')
            if json.loads(os.read(fd,131073))!=value:raise ValueError('preclaim_owner_conflict')
        finally:os.close(fd)
        return
    if time.time()>=promise['expires_at']:raise ValueError('preclaim_expired')
    fd,tmp=tempfile.mkstemp(prefix='.claim-',dir=folder)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(value,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        os.link(tmp,path);parent=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
'''
