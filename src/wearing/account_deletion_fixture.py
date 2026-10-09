"""Actual filesystem erasure only inside newly-created synthetic /tmp fixtures.

This is NOT a control-plane/provider adapter and never pretends to stop a real
worker or revoke a provider grant. Synthetic stages carry explicit fixture mode.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import uuid

from filelock import FileLock

from .account_deletion import DeletionError, Operation, Receipt, digest, encoded, identifier


def _json_read(directory, name):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    with os.fdopen(fd,'rb') as file:
        info=os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024*1024:
            raise DeletionError('unsafe_storage')
        return json.loads(file.read(1024*1024+1))


def _json_write(directory, name, value):
    temporary='write_'+uuid.uuid4().hex
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
    try:
        with os.fdopen(fd,'wb') as file:
            file.write(encoded(value).encode());file.flush();os.fsync(file.fileno())
        os.replace(temporary,name,src_dir_fd=directory,dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:os.unlink(temporary,dir_fd=directory)
        except FileNotFoundError:pass


def _safe_tree(directory, device, depth=0, counter=None):
    counter=counter if counter is not None else [0]
    if depth > 16 or os.fstat(directory).st_dev != device:raise DeletionError('unsafe_storage')
    with os.scandir(directory) as entries:
        for entry in entries:
            counter[0]+=1
            if counter[0]>1000:raise DeletionError('unsafe_storage')
            info=entry.stat(follow_symlinks=False)
            if info.st_dev != device or stat.S_ISLNK(info.st_mode):raise DeletionError('unsafe_storage')
            if stat.S_ISDIR(info.st_mode):
                child=os.open(entry.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                try:_safe_tree(child,device,depth+1,counter)
                finally:os.close(child)
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:raise DeletionError('unsafe_storage')


def _erase(directory, name, device):
    try:child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
    except FileNotFoundError:return
    try:
        _safe_tree(child,device)
        with os.scandir(child) as entries:
            for entry in entries:
                info=entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):_erase(child,entry.name,device)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:os.unlink(entry.name,dir_fd=child)
                else:raise DeletionError('unsafe_storage')
        os.fsync(child)
    finally:os.close(child)
    os.rmdir(name,dir_fd=directory)
    os.fsync(directory)


class SyntheticDeletionAdapter:
    mode='synthetic'

    @classmethod
    def create(cls, registrations, *, clock=time.time):
        """Make our own empty temp root; never adopt an operator-supplied directory."""
        root=Path(tempfile.mkdtemp(prefix='pajio-delete-fixture-')).resolve()
        root.chmod(0o700)
        manifest={'schema':1,'mode':'synthetic','root_name':root.name,'nonce':uuid.uuid4().hex,
                  'tenants':{},'accounts':{},'effects':{}}
        for row in registrations:
            key=identifier(row['tenant_id'])
            if key in manifest['tenants']:raise DeletionError('duplicate_tenant')
            manifest['tenants'][key]={**row,'worker_running':True,'relay_running':True,'frozen':False,
                 'credentials_revoked':False,'devices_revoked':False,'inflight':False,'provider_unavailable':False,
                 'retained_until':None,'finalized':False}
            for user in row['member_ids']:
                manifest['accounts'].setdefault(identifier(user),{'frozen':False,'devices_revoked':False,'finalized':False})
            tenant=root/digest(key);tenant.mkdir(mode=0o700)
            for folder in ('primary','indexes','backups'):
                target=tenant/folder;target.mkdir(mode=0o700)
                (target/'synthetic.txt').write_text('Synthetic fixture only. '+key+' '+folder)
        fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:_json_write(fd,'fixture.json',manifest)
        finally:os.close(fd)
        return cls(root,clock=clock)

    def __init__(self, root, *, clock=time.time):
        raw=Path(root).absolute()
        allowed={Path(tempfile.gettempdir()).resolve(),Path('/tmp').resolve()}
        if raw.is_symlink() or raw.resolve().parent not in allowed or not raw.name.startswith('pajio-delete-fixture-'):
            raise DeletionError('unsafe_storage')
        self.root=raw.resolve();self.clock=clock
        info=self.root.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:raise DeletionError('unsafe_storage')
        self.fingerprint=(info.st_dev,info.st_ino)
        fd=self._open()
        try:self.nonce=_json_read(fd,'fixture.json')['nonce']
        finally:os.close(fd)

    def _open(self):
        fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if (info.st_dev,info.st_ino)!=self.fingerprint:raise DeletionError('unsafe_storage')
            value=_json_read(fd,'fixture.json')
            if value.get('schema')!=1 or value.get('mode')!='synthetic' or value.get('root_name')!=self.root.name:
                raise DeletionError('unsafe_storage')
            if hasattr(self,'nonce') and value.get('nonce')!=self.nonce:raise DeletionError('unsafe_storage')
            return fd
        except BaseException:os.close(fd);raise

    def snapshot(self):
        fd=self._open()
        try:return _json_read(fd,'fixture.json')
        finally:os.close(fd)

    def set_fixture_state(self, tenant_id, **changes):
        """Test fault injection; deliberately unavailable in the operator CLI."""
        if set(changes)-{'inflight','provider_unavailable','retained_until'}:raise DeletionError('invalid_fixture_state')
        with FileLock(self.root/'fixture.lock',timeout=0):
            fd=self._open()
            try:
                value=_json_read(fd,'fixture.json');value['tenants'][tenant_id].update(changes)
                _json_write(fd,'fixture.json',value)
            finally:os.close(fd)

    @staticmethod
    def _matches(value, operation):
        expected={r['tenant_id']:r for r in operation.scope}
        actual={key:r for key,r in value['tenants'].items() if operation.user_id in r['member_ids']}
        # Shared leave retains original membership evidence in this fixture's
        # registry and tracks detached users separately, matching production's
        # need for stable operation receipts after access is revoked.
        if set(expected)!=set(actual):return False
        keys=('classification','owner_user_id','member_ids','instance_id')
        return all(all(expected[k].get(field)==actual[k].get(field) for field in keys) for k in expected)

    def execute(self, operation: Operation):
        if operation.mode!='synthetic':return Receipt(operation.operation_id,'retry',code='adapter_mismatch')
        with FileLock(self.root/'fixture.lock',timeout=0):
            fd=self._open()
            try:
                value=_json_read(fd,'fixture.json')
                if not self._matches(value,operation):return Receipt(operation.operation_id,'retry',code='ownership_changed')
                old=value['effects'].get(operation.operation_id)
                if old:
                    if old['operation']!=digest(asdict(operation)):return Receipt(operation.operation_id,'retry',code='invalid_receipt')
                    return Receipt(operation.operation_id,'done',evidence=old['evidence'])
                account=value['accounts'][operation.user_id]
                tenant=value['tenants'].get(operation.tenant_id)
                phase=operation.phase
                if phase!='freeze_account' and not account['frozen']:
                    return Receipt(operation.operation_id,'retry',code='fixture_busy')
                if phase=='freeze_account':account['frozen']=True
                elif phase=='revoke_user_devices':account['devices_revoked']=True
                elif phase=='leave_shared':
                    if tenant['classification']!='shared' or tenant.get('owner_user_id')==operation.user_id:
                        return Receipt(operation.operation_id,'retry',code='ownership_changed')
                    tenant.setdefault('detached_users',[]).append(operation.user_id)
                elif phase=='finalize_account':
                    if not account['devices_revoked'] or any(
                        not value['tenants'][row['tenant_id']]['finalized'] if row['action']=='erase_private'
                        else operation.user_id not in value['tenants'][row['tenant_id']].get('detached_users',[])
                        for row in operation.scope
                    ):
                        return Receipt(operation.operation_id,'retry',code='fixture_busy')
                    account['finalized']=True
                else:
                    if (not tenant or tenant['classification']!='private' or tenant.get('owner_user_id')!=operation.user_id
                            or tenant['member_ids']!=[operation.user_id] or tenant.get('instance_id')!=operation.instance_id):
                        return Receipt(operation.operation_id,'retry',code='ownership_changed')
                    if phase=='freeze_tenant':tenant['frozen']=True
                    elif not tenant['frozen']:return Receipt(operation.operation_id,'retry',code='fixture_busy')
                    elif phase=='revoke_credentials':
                        if tenant['provider_unavailable']:return Receipt(operation.operation_id,'retry',code='provider_unavailable')
                        tenant['credentials_revoked']=True
                    elif phase=='revoke_devices':tenant['devices_revoked']=True
                    elif phase=='drain_actions':
                        if tenant['inflight']:return Receipt(operation.operation_id,'retry',code='instance_busy')
                    elif phase=='stop_instance':
                        if tenant['inflight'] or not tenant['credentials_revoked'] or not tenant['devices_revoked']:
                            return Receipt(operation.operation_id,'retry',code='instance_busy')
                        tenant['worker_running']=False;tenant['relay_running']=False
                    elif phase in {'erase_primary','erase_indexes','erase_backups'}:
                        if tenant['worker_running'] or tenant['relay_running'] or tenant['inflight']:
                            return Receipt(operation.operation_id,'retry',code='instance_busy')
                        if phase=='erase_backups' and tenant['retained_until'] and self.clock()<tenant['retained_until']:
                            return Receipt(operation.operation_id,'retained',code='backup_retained',retained_until=tenant['retained_until'])
                        directory=os.open(digest(operation.tenant_id),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                        try:_erase(directory,phase.removeprefix('erase_'),self.fingerprint[0])
                        finally:os.close(directory)
                    elif phase=='finalize_tenant':
                        if tenant['worker_running'] or tenant['relay_running'] or tenant['inflight']:
                            return Receipt(operation.operation_id,'retry',code='instance_busy')
                        directory=os.open(digest(operation.tenant_id),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                        try:
                            if os.listdir(directory):return Receipt(operation.operation_id,'retry',code='unsafe_storage')
                        finally:os.close(directory)
                        tenant['finalized']=True
                    else:return Receipt(operation.operation_id,'retry',code='invalid_receipt')
                evidence=digest(['synthetic-effect',self.nonce,asdict(operation)])
                value['effects'][operation.operation_id]={'operation':digest(asdict(operation)),'evidence':evidence}
                _json_write(fd,'fixture.json',value)
                return Receipt(operation.operation_id,'done',evidence=evidence)
            except (OSError,ValueError,KeyError,TypeError):
                return Receipt(operation.operation_id,'retry',code='unsafe_storage')
            finally:os.close(fd)
