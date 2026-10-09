"""Explicit operator adoption of an already-paired VM, never a clone receipt."""
import json
import secrets
import sqlite3

from .device_provisioning import DeviceSpec, Owner, Policy, ProvisionError, encoded, fingerprint, inspect_capacity


class AdoptionBook:
    def __init__(self, book):
        self.book=book
        with book._tx() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS device_adoptions(
              request TEXT PRIMARY KEY, spec TEXT NOT NULL, policy TEXT NOT NULL,
              owner TEXT NOT NULL, account_scope TEXT NOT NULL, evidence TEXT NOT NULL,
              reviewed_sha256 TEXT NOT NULL, phase TEXT NOT NULL,
              provenance TEXT NOT NULL DEFAULT 'manual_adoption', updated REAL NOT NULL)''')

    def _row(self, request):
        with self.book._tx() as db:
            row=db.execute('SELECT * FROM device_adoptions WHERE request=?',(request,)).fetchone()
        if not row:raise ProvisionError('adoption_plan_required')
        return row

    def _capacity(self,spec,owner,policy,adapter):
        inventory=adapter.inventory();current=next((v for v in inventory.vms if v.vmid==spec.vmid),None)
        if (not current or current.owner not in (None,owner) or current.template or current.locked
                or (current.vcpus,current.memory_mib,current.disk_mib)!=(spec.vcpus,spec.memory_mib,spec.disk_mib)):
            raise ProvisionError('adoption_vm_conflict')
        with self.book._tx() as db:rows=self.book._rows(db)
        # This is an explicit plan simulation, not a claim of existing ownership.
        # Count the existing VM once and reserve a full recovery copy as usual.
        planned=inventory.model_copy(update={'vms':tuple(v.model_copy(update={'owner':owner}) if v.vmid==spec.vmid else v for v in inventory.vms)})
        value=inspect_capacity(spec,policy,planned,rows,now=self.book.clock())
        value['reasons']=[v for v in value['reasons'] if v!='reviewed_clean_template_required']
        value['admitted']=not value['reasons']
        return value

    @staticmethod
    def _valid(evidence,spec,owner,*,adopted=False):
        keys=('scope_matches','guest_matches_vm','paired_ready')
        if (any(evidence.get(k) is not True for k in keys) or evidence.get('vmid')!=spec.vmid
                or evidence.get('resource_id')!=spec.resource_id or not evidence.get('connector_id')
                or len(evidence.get('config_sha256',''))!=64 or len(evidence.get('machine_sha256',''))!=64
                or evidence.get('owner_sha256') not in (None,fingerprint(owner.model_dump()))
                or (adopted and evidence.get('owner_sha256')!=fingerprint(owner.model_dump()))):
            raise ProvisionError('adoption_evidence_unconfirmed')

    def plan(self,spec,policy,adapter):
        with self.book._guard():
            proof=self.book._account(spec)
            try:old=self._row(spec.request_id)
            except ProvisionError:old=None
            if old and (json.loads(old['spec'])!=spec.model_dump() or json.loads(old['policy'])!=policy.model_dump()
                        or json.loads(old['account_scope'])!=proof.scope()):raise ProvisionError('adoption_binding_changed')
            owner=Owner.model_validate_json(old['owner']) if old else Owner(
                tenant_id=spec.tenant_id,identity_id=spec.identity_id,resource_id=spec.resource_id,
                request_id=spec.request_id,request_sha256=fingerprint(spec.model_dump()),nonce=secrets.token_hex(32),
                kind=spec.kind,vcpus=spec.vcpus,memory_mib=spec.memory_mib,disk_mib=spec.disk_mib)
            evidence=adapter.adoption_probe(spec,owner);self._valid(evidence,spec,owner)
            capacity=self._capacity(spec,owner,policy,adapter)
            self.book._account(spec,proof.scope())
            reviewed=fingerprint({'spec':spec.model_dump(),'policy':policy.model_dump(),'owner':owner.model_dump(),
                                  'account_scope':proof.scope(),'evidence':evidence})
            if old and old['phase']!='planned':
                return self.status(spec.request_id)
            with self.book._tx() as db:
                if db.execute('SELECT 1 FROM devices WHERE request=?',(spec.request_id,)).fetchone():raise ProvisionError('adoption_request_already_registered')
                db.execute('INSERT OR REPLACE INTO device_adoptions VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (spec.request_id,encoded(spec.model_dump()),encoded(policy.model_dump()),encoded(owner.model_dump()),
                     encoded(proof.scope()),encoded(evidence),reviewed,'planned','manual_adoption',self.book.clock()))
            return {'request_id':spec.request_id,'provenance':'manual_adoption','reviewed_sha256':reviewed,
                    'admitted':capacity['admitted'],'reasons':capacity['reasons'],'demand':capacity['demand'],
                    'limits':capacity['limits'],'product_ready':False,'creates_resources':False}

    def status(self,request):
        row=self._row(request)
        return {'request_id':request,'provenance':row['provenance'],'state':row['phase'],
                'reviewed_sha256':row['reviewed_sha256'],'product_ready':False,'creates_resources':False}

    def apply(self,request,adapter,*,reviewed_sha256):
        with self.book._guard():
            row=self._row(request)
            if row['reviewed_sha256']!=reviewed_sha256:raise ProvisionError('adoption_plan_changed')
            spec,policy=DeviceSpec.model_validate_json(row['spec']),Policy.model_validate_json(row['policy'])
            owner=Owner.model_validate_json(row['owner']);scope=json.loads(row['account_scope']);before=json.loads(row['evidence'])
            self.book._account(spec,scope)
            current=adapter.adoption_probe(spec,owner);self._valid(current,spec,owner)
            if row['phase']=='adopted':
                self._valid(current,spec,owner,adopted=True)
                self.book._account(spec,scope)
                return self.status(request)
            if row['phase']=='planned' and current!=before:raise ProvisionError('adoption_evidence_changed')
            capacity=self._capacity(spec,owner,policy,adapter)
            if not capacity['admitted']:raise ProvisionError(','.join(capacity['reasons']))
            self.book._account(spec,scope)
            if row['phase']=='planned':
                with self.book._tx() as db:
                    try:
                        db.execute('INSERT INTO devices VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)',
                            (request,spec.tenant_id,spec.kind,spec.resource_id,spec.vmid,encoded(spec.model_dump()),
                             encoded(policy.model_dump()),reviewed_sha256,encoded(owner.model_dump()),'needs_operator',0,'manual_adoption_pending',self.book.clock()))
                        db.execute('INSERT INTO device_accounts VALUES (?,?)',(request,encoded(scope)))
                    except sqlite3.IntegrityError:raise ProvisionError('device_binding_conflict') from None
                    db.execute("UPDATE device_adoptions SET phase='applying',updated=? WHERE request=?",(self.book.clock(),request))
            # Adapter is a CAS/idempotent metadata-only operation. No power, net,
            # credential rotation, clone, configuration preparation or delete.
            adapter.adopt_existing(spec,owner,before)
            self.book._account(spec,scope)
            after=adapter.adoption_probe(spec,owner);self._valid(after,spec,owner,adopted=True)
            if after['machine_sha256']!=before['machine_sha256'] or after['connector_id']!=before['connector_id']:
                raise ProvisionError('adoption_guest_changed')
            self.book._account(spec,scope)
            with self.book._tx() as db:
                db.execute("UPDATE device_adoptions SET phase='adopted',updated=? WHERE request=?",(self.book.clock(),request))
                db.execute("UPDATE devices SET state='staged',code='manual_adoption',updated=? WHERE request=?",(self.book.clock(),request))
            return self.status(request)
