"""Outbound-only connector with a local write-ahead execution journal.

No listener, shell executor, ADB endpoint, model key or cloud-provider credential.
"""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import ssl
import stat
from urllib.parse import urlparse

import httpx
from filelock import FileLock
from pydantic import Field, field_validator

from ...cloud.commands import (Record, DeviceCommand, Scope, TaskAuthority, ResourceGrant,
                               ConnectionAuthority, LeaseAuthority, authorize_command)
from ...cloud.instance import read_private
from ...cloud.relay import ResourceSpec, MAX_BODY, encoded
from ...config import private_directory, write_private_json
from ...profile import write_private_text
from .daemon_state import desired


class PairBundle(Record):
    endpoint: str
    ca_pem: str = Field(max_length=16384)
    code: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    connector_id: str = Field(pattern=r'^connector_[a-f0-9]{32}$')
    tenant_id: str
    identity_id: str
    pairing_generation: int = Field(ge=1,le=1)
    policy_revision: int = Field(ge=1,strict=True)
    resources: list[ResourceSpec] = Field(min_length=1,max_length=32)

    @field_validator('endpoint')
    @classmethod
    def endpoint_https(cls, value):
        u = urlparse(value)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.path not in ('','/') or u.query or u.fragment:
            raise ValueError('Connector endpoint must be HTTPS without credentials or a path')
        return value.rstrip('/')


class Journal:
    def __init__(self, root):
        root = Path(root).absolute()
        if root.is_symlink():
            raise ValueError('unsafe_connector_directory')
        private_directory(root)
        self.root, self.path = root, root/'actions.sqlite3'
        if self.path.is_symlink():
            raise ValueError('unsafe_action_journal')
        with self.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, digest TEXT, state TEXT, result TEXT, connection TEXT, uploaded INTEGER DEFAULT 0)')
            if 'uploaded' not in {r[1] for r in db.execute('PRAGMA table_info(actions)')}:
                db.execute('ALTER TABLE actions ADD COLUMN uploaded INTEGER DEFAULT 0')
            db.execute('CREATE TABLE IF NOT EXISTS pauses(resource TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE IF NOT EXISTS remote_controls(resource TEXT PRIMARY KEY, generation INTEGER, paused INTEGER)')
        if os.name != 'nt': self.path.chmod(0o600)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path,timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally: db.close()

    def begin(self, command):
        digest = hashlib.sha256(encoded(command.model_dump(mode='json')).encode()).hexdigest()
        with self.tx() as db:
            row = db.execute('SELECT * FROM actions WHERE id=?',(command.command_id,)).fetchone()
            if row:
                if row['digest'] != digest: raise ValueError('command_id_collision')
                return False
            db.execute('INSERT INTO actions(id,digest,state,result,connection) VALUES (?,?,?,?,?)',(command.command_id,digest,'started',None,command.connection_id))
            return True

    def finish(self, command, state, result):
        payload = encoded(result) if result is not None else None
        if payload and len(payload.encode()) > MAX_BODY-8192:
            state, payload = 'unknown', None
        with self.tx() as db:
            db.execute('UPDATE actions SET state=?,result=? WHERE id=? AND state=\'started\'',(state,payload,command.command_id))

    def recover(self):
        with self.tx() as db:
            db.execute("UPDATE actions SET state='unknown' WHERE state='started'")

    def receipt(self, command_id):
        with self.tx() as db:
            row=db.execute('SELECT * FROM actions WHERE id=?',(command_id,)).fetchone()
            if not row: return None
            return {'command_id':command_id,'connection_id':row['connection'],
                    'state':'unknown' if row['state']=='started' else row['state'],
                    'result':json.loads(row['result']) if row['result'] else None}

    def paused(self, resource):
        with self.tx() as db:
            return (db.execute('SELECT 1 FROM pauses WHERE resource=?',(resource,)).fetchone() is not None
                    or db.execute('SELECT 1 FROM remote_controls WHERE resource=? AND paused=1',(resource,)).fetchone() is not None)

    def apply_controls(self, controls, resources):
        from ...cloud.commands import Identifier
        from pydantic import TypeAdapter
        if not isinstance(controls, list) or len(controls) > 32:
            raise ValueError('invalid_remote_controls')
        parsed = []
        for c in controls:
            resource = TypeAdapter(Identifier).validate_python(c['resource_id'])
            if (resource not in resources or type(c['generation']) is not int or c['generation'] < 1
                    or type(c['paused']) is not bool):
                raise ValueError('invalid_remote_controls')
            parsed.append((resource, c['generation'], int(c['paused'])))
        with self.tx() as db:
            for resource, generation, paused in parsed:
                old = db.execute('SELECT * FROM remote_controls WHERE resource=?',(resource,)).fetchone()
                if old and (generation < old['generation'] or (generation == old['generation'] and paused != old['paused'])):
                    raise ValueError('obsolete_remote_control')
                db.execute('INSERT OR REPLACE INTO remote_controls VALUES (?,?,?)',(resource,generation,paused))

    def control_acks(self):
        with self.tx() as db:
            return {r['resource']: r['generation'] for r in db.execute('SELECT * FROM remote_controls')}

    def pause(self, resource, enabled=True):
        with self.tx() as db:
            if enabled: db.execute('INSERT OR IGNORE INTO pauses VALUES (?)',(resource,))
            else: db.execute('DELETE FROM pauses WHERE resource=?',(resource,))

    def pending(self):
        with self.tx() as db:
            return [r[0] for r in db.execute('SELECT id FROM actions WHERE uploaded=0 AND state!=\'started\'')]

    def uploaded(self, command_id):
        with self.tx() as db:
            db.execute('UPDATE actions SET uploaded=1 WHERE id=?',(command_id,))


def client_for(config, root):
    ca=root/'cloud-ca.pem'
    if ca.is_symlink(): raise ValueError('unsafe_connector_certificate')
    write_private_text(ca,config['ca_pem'])
    return httpx.AsyncClient(base_url=config['endpoint'], verify=ssl.create_default_context(cafile=str(ca)),
                             timeout=15, follow_redirects=False, trust_env=False,
                             headers={'Authorization':'Bearer '+config['token']})


async def response(client,path,payload):
    # Refuse redirects and bound both JSON responses and screenshot transfer.
    async with client.stream('POST',path,json=payload) as r:
        data=bytearray()
        async for chunk in r.aiter_bytes():
            data.extend(chunk)
            if len(data)>MAX_BODY: raise ValueError('relay_response_too_large')
        if r.status_code != 200: raise httpx.HTTPStatusError('connector_request_rejected',request=r.request,response=r)
        return json.loads(data)


def read_bundle(path):
    """Privatize an owned browser download; runtime configs still use read_private."""
    path=Path(path)
    if path.is_symlink():raise ValueError('unsafe_downloaded_bundle')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'r',encoding='utf-8') as stream:
        metadata=os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size>65536:
            raise ValueError('unsafe_downloaded_bundle')
        if os.name!='nt':
            if metadata.st_uid!=os.getuid():raise ValueError('unsafe_downloaded_bundle')
            os.fchmod(stream.fileno(),0o600)
        return stream.read(65537)


async def pair(bundle_path, root, local_data):
    root=Path(root).absolute()
    journal=Journal(root)
    bundle=PairBundle.model_validate_json(read_bundle(bundle_path))
    path=root/'connector.json'
    with FileLock(root/'pair.lock',timeout=0):
        if path.exists():
            config=json.loads(read_private(path))
            if any(config.get(k)!=v for k,v in bundle.model_dump(mode='json').items()):
                raise ValueError('connector_already_has_different_pairing')
        else:
            config={**bundle.model_dump(mode='json'),'token':secrets.token_urlsafe(48),
                    'local_data':str(Path(local_data).resolve()),'connection_id':None}
            write_private_json(path,config)  # Persist before a request which may have an ambiguous response.
        async with client_for(config,root) as client:
            result=await response(client,'/v1/pair',{'code':config['code'],'token':config['token']})
        if any(result.get(k)!=config[k] for k in ('connector_id','tenant_id','identity_id')):
            raise ValueError('paired_scope_mismatch')
    return {'paired':True,'resources':len(config['resources'])}


class Connector:
    def __init__(self,root,adapter):
        self.root=Path(root).absolute()
        self.journal=Journal(self.root)
        self.config=json.loads(read_private(self.root/'connector.json'))
        PairBundle.model_validate({k:self.config[k] for k in PairBundle.model_fields})
        self.adapter=adapter
        self.connection=self.config.get('connection_id')
        self.human_acks = {}

    def pause_private_sessions(self):
        if hasattr(self.adapter, 'recover_human_access'):
            self.adapter.recover_human_access([r['resource_id'] for r in self.config['resources'] if r['kind'] in ('android','computer')])

    async def apply_human_controls(self, controls):
        """Authenticate scope from paired config before touching the host fence."""
        from ...device_gateway import GatewayScope
        if not isinstance(controls, list) or len(controls) > 32:
            raise ValueError('invalid_human_controls')
        for control in controls:
            if not isinstance(control, dict) or any(control.get(k) != self.config[k] for k in ('tenant_id','identity_id','connector_id')):
                raise ValueError('human_scope_not_paired')
            spec = next((r for r in self.config['resources'] if r['resource_id'] == control.get('resource_id')), None)
            if not spec or spec['kind'] not in ('android','computer') or control.get('action') not in ('takeover','pause','return'):
                raise ValueError('human_resource_not_paired')
            if not hasattr(self.adapter, 'apply_human_control'):
                raise ValueError('private_gateway_unavailable')
            scope = GatewayScope(**{k:control[k] for k in ('tenant_id','identity_id','user_id','connector_id','resource_id')})
            self.human_acks[scope.resource_id] = await self.adapter.apply_human_control(control, scope)

    async def execute(self,client,command):
        # Pinned local grant is a ceiling even if the remote authority is malformed.
        c=self.config
        spec=next((r for r in c['resources'] if r['resource_id']==command.resource_id),None)
        if not spec or command.connector_id!=c['connector_id'] or command.connection_id!=self.connection:
            raise ValueError('command_not_paired')
        if not self.journal.begin(command):
            old=self.journal.receipt(command.command_id)
            await response(client,'/v1/result',old)
            self.journal.uploaded(command.command_id)
            return
        state,result='unknown',None
        try:
            current=await response(client,'/v1/claim',{'connection_id':self.connection,'command_id':command.command_id})
            task=TaskAuthority.model_validate(current['task'])
            grant=ResourceGrant(scope=Scope(tenant_id=c['tenant_id'],identity_id=c['identity_id']),
                resource_id=spec['resource_id'],connector_id=c['connector_id'],pairing_generation=c['pairing_generation'],
                policy_revision=c['policy_revision'],methods=spec['methods'])
            remote_grant=ResourceGrant.model_validate(current['grant'])
            if remote_grant!=grant: raise ValueError('grant_not_paired')
            authorize_command(command,task=task,grant=grant,connection=ConnectionAuthority.model_validate(current['connection']),
                              lease=LeaseAuthority.model_validate(current['lease']),now=datetime.now(timezone.utc))
            if self.journal.paused(command.resource_id) or desired(self.root) == 'stopped':
                state='blocked'
            else:
                if command.method.startswith('files.'):
                    from ...device_files_native import execute_transfer
                    result=await asyncio.wait_for(execute_transfer(self.adapter,command,client,self.connection),timeout=45)
                elif command.method=='computer.input':
                    from ...desktop_input import DesktopApproval
                    approval=DesktopApproval.model_validate(current.get('input_approval'))
                    if not approval.permits(command):raise ValueError('desktop_approval_not_current')
                    result=await asyncio.wait_for(self.adapter.execute(command,approval=approval),timeout=45)
                else:
                    result=await asyncio.wait_for(self.adapter.execute(command),timeout=45)
                # Takeover while the native call ran discards observation contents.
                if self.journal.paused(command.resource_id):
                    state,result='unknown',None
                else: state='device_error' if result.get('isError') else 'completed'
        except asyncio.CancelledError:
            self.journal.finish(command,'unknown',None)
            raise
        except Exception:
            # A failed claim may mean the cloud committed it. Never admit that ID again.
            state,result='unknown',None
        self.journal.finish(command,state,result)
        await response(client,'/v1/result',self.journal.receipt(command.command_id))
        self.journal.uploaded(command.command_id)

    async def run(self,stop=None):
        try:
            return await self._run(stop)
        finally:
            self.pause_private_sessions()

    async def _run(self,stop=None):
        with FileLock(self.root/'runner.lock',timeout=0):
            from .permissions import update_permissions,require_settled
            require_settled(self.root)
            self.journal.recover()
            self.pause_private_sessions()
            delay=1
            async with client_for(self.config,self.root) as client:
                connected=bool(self.connection)
                def stopping():
                    return (stop is not None and stop.is_set()) or desired(self.root) == 'stopped'
                while not stopping():
                    try:
                        stage_path=self.root/'permission-update.json'
                        stage=json.loads(read_private(stage_path)) if stage_path.exists() else None
                        if stage and stage['state']=='pending':
                            bundle_path=self.root/'incoming-permission.json'
                            write_private_json(bundle_path,stage['bundle'])
                            try:await update_permissions(bundle_path,self.root,self.adapter,runner_owned=True)
                            except ValueError:
                                stage=json.loads(read_private(stage_path))
                                if stage['state']!='aborted':raise
                            self.config=json.loads(read_private(self.root/'connector.json'))
                            self.connection=self.config.get('connection_id');connected=False
                        if not connected:
                            previous=self.connection
                            result=await response(client,'/v1/connect',{'previous_connection_id':previous})
                            self.connection=result['connection_id']
                            self.config['connection_id']=self.connection
                            write_private_json(self.root/'connector.json',self.config)
                            connected=True
                        for pending in self.journal.pending():
                            await response(client,'/v1/result',self.journal.receipt(pending))
                            self.journal.uploaded(pending)
                        availability=await self.adapter.availability(self.config['resources'])
                        human_availability = {r['resource_id']:bool(availability.get(r['resource_id']))
                                              for r in self.config['resources'] if r['kind'] in ('android','computer')}
                        if hasattr(self.adapter,'human_availability'):
                            human_availability = await self.adapter.human_availability(self.config['resources'],availability)
                        availability={r:bool(ok and not self.journal.paused(r)) for r,ok in availability.items()}
                        value=await response(client,'/v1/poll',{'connection_id':self.connection,'availability':availability,
                                                             'control_acks':self.journal.control_acks(),'permission_delivery':True,
                                                             'human_access_ready':getattr(self.adapter,'human_access_ready',False) is True,
                                                             'human_availability':human_availability if getattr(self.adapter,'human_access_ready',False) is True else {},
                                                             'human_acks':self.human_acks})
                        self.human_acks = {}
                        self.journal.apply_controls(value.get('controls',[]),{r['resource_id'] for r in self.config['resources']})
                        await self.apply_human_controls(value.get('human_controls', []))
                        if value.get('permission_update'):
                            bundle_path=self.root/'incoming-permission.json'
                            write_private_json(bundle_path,value['permission_update'])
                            await update_permissions(bundle_path,self.root,self.adapter,runner_owned=True)
                            self.config=json.loads(read_private(self.root/'connector.json'))
                            self.connection=None;connected=False
                            continue
                        command=value.get('command')
                        if command and not stopping():
                            await self.execute(client,DeviceCommand.model_validate(command))
                        delay=1
                        write_private_json(self.root/'status.json',{'state':'connected','observed_at':datetime.now(timezone.utc).isoformat(),
                            'availability':availability,'paused':[r for r in availability if self.journal.paused(r)]})
                    except httpx.HTTPStatusError as error:
                        self.pause_private_sessions()
                        if error.response.status_code==401:
                            if not connected:
                                write_private_json(self.root/'status.json',{'state':'revoked_or_unpaired',
                                    'observed_at':datetime.now(timezone.utc).isoformat()})
                                return
                            connected=False
                        write_private_json(self.root/'status.json',{'state':'reconnecting','observed_at':datetime.now(timezone.utc).isoformat()})
                        delay=min(delay*2,15)
                    except (httpx.HTTPError,ValueError,OSError):
                        self.pause_private_sessions()
                        write_private_json(self.root/'status.json',{'state':'reconnecting','observed_at':datetime.now(timezone.utc).isoformat()})
                        delay=min(delay*2,15)
                    await asyncio.sleep(delay)
                if connected:
                    self.pause_private_sessions()
                    try:
                        await response(client,'/v1/disconnect',{'connection_id':self.connection})
                    except (httpx.HTTPError, ValueError, OSError):
                        pass
                write_private_json(self.root/'status.json',{'state':'stopped','observed_at':datetime.now(timezone.utc).isoformat()})
