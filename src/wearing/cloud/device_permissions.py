"""Two-sided, revision-fenced permission changes for an existing connector.

Creating/download a bundle does not grant anything. Only the paired device's
credential can commit it, after staging its matching local ceiling.
"""
import copy
import json
import secrets
from typing import Literal

from pydantic import Field, model_validator

from .commands import Record, Identifier
from .instance import read_private
from .relay import RelayError, encoded, fingerprint, utc
from .device_setup import DeviceOffer, tools_for
from ..connectors.remote.client import PairBundle
from ..connectors.remote.schemas import COMPUTER_METHODS
from ..device_files_io import FILE_METHODS


def canonical_resources(resources):
    return sorted([{**r, 'methods':sorted(r['methods'])} for r in resources],key=lambda r:r['resource_id'])


def grant_digest(connector):
    return fingerprint(encoded({'connector':connector['id'], 'identity':connector['identity'],
        'revision':connector['policy_revision'], 'resources':canonical_resources(json.loads(connector['resources']))}))


class ChangePermission(Record):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    resource_id: Identifier
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    mode: Literal['observe','input','files']
    file_access: bool | None = None
    delivery: Literal['manual','connector'] = 'manual'


class PermissionBundle(PairBundle):
    schema_version: int = Field(ge=1,le=1,strict=True)
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    from_revision: int = Field(ge=1,strict=True)
    expected_grant: str = Field(pattern=r'^[a-f0-9]{64}$')
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    expires_at: float

    @model_validator(mode='after')
    def scope(self):
        DeviceOffer(schema_version=1,resources=self.resources)
        if self.policy_revision != self.from_revision+1:
            raise ValueError('permission_revision_mismatch')
        if bundle_digest(self.model_dump(mode='json')) != self.digest:
            raise ValueError('permission_bundle_changed')
        return self


def bundle_digest(bundle):
    body={k:v for k,v in bundle.items() if k!='digest'}
    body['resources']=canonical_resources(body['resources'])
    return fingerprint(encoded(body))


class ApplyPermission(Record):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    code: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')


def require_idle(store,db,connector):
    store.expire(db)
    if db.execute("SELECT 1 FROM commands WHERE connector=? AND (state IN ('queued','executing') OR (state IN ('unknown','device_error') AND resolved=0))",(connector,)).fetchone():
        raise RelayError('permission_device_busy')
    if db.execute("SELECT 1 FROM desktop_proposals WHERE connector=? AND state='awaiting_user' AND expires>?",(connector,utc().timestamp())).fetchone():
        raise RelayError('permission_device_busy')


def create_permission(store,root,identity,request):
    destination=json.loads(read_private(root/'data/device-endpoint.json'))
    intent=fingerprint(encoded({'identity':identity,**request.model_dump(mode='json')}))
    with store.tx() as db:
        old=db.execute('SELECT * FROM permission_updates WHERE id=?',(request.request_id,)).fetchone()
        if old:
            if old['identity']!=identity or old['intent']!=intent:raise RelayError('permission_request_changed')
            if old['state']!='applied' and old['expires']<=utc().timestamp():raise RelayError('permission_expired')
            return json.loads(old['bundle'])
        match=[c for c in db.execute('SELECT * FROM connectors WHERE identity=? AND revoked=0',(identity,))
               if any(r['resource_id']==request.resource_id for r in json.loads(c['resources']))]
        if len(match)!=1:raise RelayError('resource_not_paired',404)
        c=match[0]
        if grant_digest(c)!=request.revision:raise RelayError('permission_changed')
        specs=copy.deepcopy(json.loads(c['resources']))
        resource=next(r for r in specs if r['resource_id']==request.resource_id)
        if request.mode == 'files':
            if request.file_access is None: raise RelayError('file_permission_choice_required')
            methods = set(resource['methods']) - set(FILE_METHODS)
        else:
            if resource['kind']!='computer':raise RelayError('permission_computer_only')
            methods=set(COMPUTER_METHODS) if request.mode=='input' else {'computer.observe','computer.status'}
        if request.file_access is True or (request.file_access is None and set(FILE_METHODS) <= set(resource['methods'])):
            methods.update(FILE_METHODS)
        if set(resource['methods'])==methods:raise RelayError('permission_unchanged')
        require_idle(store,db,c['id'])
        resource['methods']=sorted(methods)
        bundle={**destination,'code':secrets.token_urlsafe(32),'connector_id':c['id'],
            'tenant_id':store.tenant,'identity_id':identity,'pairing_generation':1,
            'policy_revision':c['policy_revision']+1,'resources':canonical_resources(specs),
            'schema_version':1,'request_id':request.request_id,'from_revision':c['policy_revision'],
            'expected_grant':grant_digest(c),'expires_at':utc().timestamp()+600}
        bundle['digest']=bundle_digest(bundle)
        PermissionBundle.model_validate(bundle)  # validate operator destination before persisting
        db.execute('INSERT INTO permission_updates(id,identity,connector,intent,bundle,expires,state,delivery) VALUES (?,?,?,?,?,?,?,?)',
            (request.request_id,identity,c['id'],intent,encoded(bundle),bundle['expires_at'],'pending',request.delivery))
        return bundle


def pending_delivery(store,db,connector):
    """Only deliver an explicitly requested automatic change to its original peer."""
    row=db.execute("SELECT * FROM permission_updates WHERE connector=? AND delivery='connector' AND state='pending' AND expires>? ORDER BY rowid DESC LIMIT 1",
        (connector['id'],utc().timestamp())).fetchone()
    if not row:return None
    bundle=json.loads(row['bundle'])
    if grant_digest(connector)!=bundle['expected_grant']:return None
    try:require_idle(store,db,connector['id'])
    except RelayError:return None
    return bundle


def read_permission(store,identity,request_id,download=False):
    with store.tx() as db:
        row=db.execute('SELECT * FROM permission_updates WHERE id=? AND identity=?',(request_id,identity)).fetchone()
        if not row:raise RelayError('permission_not_found',404)
        state=row['state']
        if state=='pending' and row['expires']<=utc().timestamp():state='expired'
        if download:
            if state!='pending':raise RelayError('permission_expired',409)
            return json.loads(row['bundle'])
        c=db.execute('SELECT * FROM connectors WHERE id=?',(row['connector'],)).fetchone()
        bundle=json.loads(row['bundle'])
        if state=='applied' and (not c or c['revoked'] or c['policy_revision']!=bundle['policy_revision']):state='superseded'
        online=bool(c and c['connection'] and (c['expires'] or 0)>utc().timestamp())
        return {'state':state,'policy_revision':bundle['policy_revision'],'connected':online}


def apply_permission(store,token,request,check_only=False):
    with store.tx() as db:
        c=store.auth(db,token)
        row=db.execute('SELECT * FROM permission_updates WHERE id=? AND connector=?',(request.request_id,c['id'])).fetchone()
        if not row:raise RelayError('permission_not_found',404)
        b=json.loads(row['bundle'])
        if not secrets.compare_digest(b['code'],request.code) or not secrets.compare_digest(b['digest'],request.digest):
            raise RelayError('permission_bundle_changed')
        result={'digest':b['digest'],'policy_revision':b['policy_revision'],'resources':b['resources']}
        if row['state']=='applied':
            if c['policy_revision']!=b['policy_revision'] or canonical_resources(json.loads(c['resources']))!=b['resources']:
                raise RelayError('permission_changed')
            return result  # ambiguous response recovery, including after the original expiry
        if c['policy_revision']!=b['from_revision'] or grant_digest(c)!=b['expected_grant']:
            raise RelayError('permission_changed')
        if row['expires']<=utc().timestamp() or row['state']=='expired':
            # Confirm the old cloud grant before a stopped device rolls back an
            # uncommitted stage. An applied change is handled above, never here.
            db.execute("UPDATE permission_updates SET state='expired' WHERE id=?",(request.request_id,))
            if check_only:
                return {'state':'expired','policy_revision':c['policy_revision'],
                    'resources':canonical_resources(json.loads(c['resources'])),'digest':b['expected_grant']}
            raise RelayError('permission_expired')
        require_idle(store,db,c['id'])
        if not check_only:
            db.execute('UPDATE connectors SET resources=?,tools=?,policy_revision=?,connection=NULL,previous=NULL,expires=NULL,availability=\'{}\' WHERE id=?',
                (encoded(b['resources']),encoded(tools_for(b['resources'])),b['policy_revision'],c['id']))
            for r in b['resources']:
                db.execute('UPDATE leases SET epoch=epoch+1 WHERE resource=?',(r['resource_id'],))
                db.execute('UPDATE controls SET ack=0,connection=NULL WHERE resource=?',(r['resource_id'],))
            db.execute("UPDATE permission_updates SET state='applied' WHERE id=?",(request.request_id,))
        return result
