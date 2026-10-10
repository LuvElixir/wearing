"""Host-authenticated retained archives, without deleting any owner/ledger row.

This module only validates root-owned host evidence. It cannot stop, release,
restore, delete, or transfer a VM. Operator retirement must first freeze access,
quiesce/drain the exact device, and preserve a verified backup. Ordinary stopped
VMs retain their complete CPU/RAM/slot promises.
"""

# The same verifier runs inside the provider's SSH inventory and final host lock.
# The caller cannot supply a receipt/path or assert that retirement succeeded.
RETENTION_SOURCE = r'''
import hashlib,json,os,re,stat
from pathlib import Path

def assert_group_restores_complete(vms,node,root='/var/lib/pajio-retained-vms'):
    """An interrupted legacy-Core restoration blocks every new admission.

    Execution owners resume their normal promises when their receipt is
    revoked. Legacy Core VMs have no such owner, so their group intent must
    remain a hard gate until the Core is actually running and durably ACKed.
    """
    base=Path(root)
    if not base.exists():return
    def require(ok):
        if not ok:raise ValueError('group_restore_capacity_unconfirmed')
    for directory in base.glob('*-restore'):
        for folder in (base,directory):
            st=folder.lstat()
            require(stat.S_ISDIR(st.st_mode) and st.st_uid==0 and stat.S_IMODE(st.st_mode)==0o700)
        journal=directory/'journal.json'
        # Creation of an empty private directory precedes capacity inspection;
        # all actual changes require a durable journal first.
        if not journal.exists():continue
        fd=os.open(journal,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd)
            require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o600 and st.st_size<=131072)
            raw=os.read(fd,131073);require(len(raw)<=131072);proof=json.loads(raw)
        finally:os.close(fd)
        require(type(proof.get('version')) is int and proof['version']==1 and proof.get('node')==node)
        require(isinstance(proof.get('operation'),str) and re.fullmatch('[a-f0-9]{32}',proof['operation']))
        require(isinstance(proof.get('manifest_sha256'),str) and re.fullmatch('[a-f0-9]{64}',proof['manifest_sha256']))
        require(proof.get('state')=='done' and proof.get('phase')=='core_running_devices_reserved')
        core=[v for v in vms if v['vmid']==proof.get('core_vmid')]
        require(len(core)==1 and type(proof.get('core_vmid')) is int and core[0]['state']=='running' and not core[0]['template'] and core[0]['owner'] is None)
        require(isinstance(proof.get('core_config_sha256'),str) and re.fullmatch('[a-f0-9]{64}',proof['core_config_sha256']) and core[0]['config_sha256']==proof['core_config_sha256'])

def retained_archive_sha(vmid,config,state,node,root='/var/lib/pajio-retained-vms'):
    try:
        owner=json.loads(config.get('description','')).get('pajio_provisioning')
    except (ValueError,AttributeError):owner=None
    if not owner:return None
    base=Path(root);directory=base/str(vmid)
    if not directory.exists():return None
    def require(ok):
        if not ok:raise ValueError('retained_archive_evidence_invalid')
    for folder in (base,directory):
        st=folder.lstat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid==0 and stat.S_IMODE(st.st_mode)==0o700)
    def read(name):
        fd=os.open(directory/name,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd)
            require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o600 and st.st_size<=131072)
            raw=os.read(fd,131073);require(len(raw)<=131072);return raw
        finally:os.close(fd)
    path=directory/'receipt.json'
    # No receipt means a merely stopped VM, including interrupted archiving.
    if not path.exists():return None
    raw=read('receipt.json');proof=json.loads(raw);backup_raw=read('backup-proof.json');backup=json.loads(backup_raw)
    digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    h=lambda value:hashlib.sha256(value).hexdigest()
    require(type(proof.get('version')) is int and proof['version']==1 and proof.get('kind')=='execution')
    require(type(proof.get('vmid')) is int and proof['vmid']==vmid and proof.get('node')==node)
    require(proof.get('owner_sha256')==digest(owner) and proof.get('compute_released') is True and proof.get('disks_retained') is True)
    require(state=='stopped' and int(config.get('onboot',0))==0 and config.get('lock')=='backup' and not config.get('template'))
    require(proof.get('locked_config_sha256')==digest({k:v for k,v in config.items() if k!='digest'}))
    require(proof.get('backup_proof_sha256')==h(backup_raw))
    require(all(isinstance(proof.get(k),str) and re.fullmatch(r'[a-f0-9]{64}',proof[k]) for k in ('membership_fence_sha256','maintenance_proof_sha256')))
    require(isinstance(proof.get('operation'),str) and re.fullmatch(r'[a-f0-9]{32}',proof['operation']))
    require(backup.get('version')==1 and type(backup.get('vmid')) is int and backup['vmid']==vmid and backup.get('operation')==proof['operation'])
    require(backup.get('zstd_verified') is True and backup.get('vma_verified') is True and backup.get('owner_sha256')==digest(owner))
    require(isinstance(backup.get('archive_sha256'),str) and re.fullmatch(r'[a-f0-9]{64}',backup['archive_sha256']))
    archive=directory/'retained.vma.zst';st=archive.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_nlink==1 and stat.S_IMODE(st.st_mode)==0o600)
    require(st.st_size==backup.get('archive_bytes') and st.st_mtime_ns==backup.get('archive_mtime_ns'))
    # Full bytes were verified at root's atomic archival commit. Ordinary
    # inventory verifies the immutable private artifact's identity, not a user
    # supplied success flag. Original VM disks remain allocated as well.
    return h(raw)
'''
