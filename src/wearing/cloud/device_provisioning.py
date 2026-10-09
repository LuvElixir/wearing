"""Operator-only device capacity ledger; no tenant endpoint, stop or delete action.

Reserves complete configured resources, never idle RSS. Provider operations create
only stopped devices; bootstrap, network, pairing and product readiness are separate.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Literal

from filelock import FileLock, Timeout
from pydantic import Field, model_validator

from .commands import Identifier, Record
from .device_admission import AccountProof, AdmissionError
from ..config import private_directory


class ProvisionError(ValueError):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class DeviceSpec(Record):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    tenant_id: Identifier
    identity_id: Identifier
    resource_id: Identifier
    kind: Literal['linux', 'android']
    vmid: int = Field(strict=True, ge=100, le=999999999)
    vcpus: int = Field(default=2, strict=True, ge=1, le=16)
    memory_mib: int = Field(default=4096, strict=True, ge=2048, le=32768)
    disk_mib: int = Field(default=32768, strict=True, ge=16384, le=1048576)


class Owner(Record):
    version: Literal[1] = 1
    tenant_id: Identifier
    identity_id: Identifier
    resource_id: Identifier
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    request_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    nonce: str = Field(pattern=r'^[a-f0-9]{64}$')
    kind: Literal['linux', 'android']
    vcpus: int = Field(strict=True, ge=1, le=16)
    memory_mib: int = Field(strict=True, ge=2048, le=32768)
    disk_mib: int = Field(strict=True, ge=16384, le=1048576)


class VM(Record):
    vmid: int = Field(strict=True, ge=100)
    state: Literal['running', 'stopped', 'paused']
    vcpus: int = Field(strict=True, ge=1)
    memory_mib: int = Field(strict=True, ge=1)
    disk_mib: int = Field(strict=True, ge=0)
    template: bool = False
    locked: bool = False
    owner: Owner | None = None
    config_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    prepared: bool = False


class Inventory(Record):
    node: Identifier
    storage: Identifier
    observed_at: float
    physical_cores: int = Field(strict=True, ge=1)
    memory_mib: int = Field(strict=True, ge=1)
    available_memory_mib: int = Field(strict=True, ge=0)
    storage_mib: int = Field(strict=True, ge=1)
    available_storage_mib: int = Field(strict=True, ge=0)
    committed_storage_mib: int = Field(strict=True, ge=0)
    vms: tuple[VM, ...]

    @model_validator(mode='after')
    def checked(self):
        owners = [vm.owner for vm in self.vms if vm.owner]
        if (not math.isfinite(self.observed_at)
                or len({vm.vmid for vm in self.vms}) != len(self.vms)
                or len({owner.resource_id for owner in owners}) != len(owners)
                or len({owner.request_id for owner in owners}) != len(owners)
                or self.available_memory_mib > self.memory_mib
                or self.available_storage_mib > self.storage_mib):
            raise ValueError('invalid_inventory')
        return self


class Template(Record):
    vmid: int = Field(strict=True, ge=100)
    config_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    clean_review_ref: Identifier
    disk_mib: int = Field(strict=True, ge=16384)


class Policy(Record):
    node: Identifier
    storage: Identifier
    templates: dict[Literal['linux', 'android'], Template]
    host_memory_mib: int = Field(default=6144, strict=True, ge=4096)
    host_cores: int = Field(default=2, strict=True, ge=1)
    disk_free_percent: int = Field(default=20, strict=True, ge=20, le=80)
    linux_slots: int = Field(default=1, strict=True, ge=0, le=100)
    android_slots: int = Field(default=1, strict=True, ge=0, le=100)
    # Existing devices deployed before this ledger need explicit operator slots;
    # arbitrary VM names never establish tenant ownership or a device kind.
    external_linux_slots: int = Field(default=0, strict=True, ge=0)
    external_android_slots: int = Field(default=0, strict=True, ge=0)
    reservation_seconds: int = Field(default=900, strict=True, ge=60, le=3600)


def inspect_capacity(spec, policy, inventory, reservations, *, now=None):
    """Pure, repeatable preview. Unknown/stale inventory fails closed."""
    now = time.time() if now is None else now
    if (not 0 <= now - inventory.observed_at <= 60
            or inventory.node != policy.node or inventory.storage != policy.storage):
        raise ProvisionError('inventory_stale_or_wrong_host')
    template = policy.templates.get(spec.kind)
    vms = {vm.vmid: vm for vm in inventory.vms}
    source = vms.get(template.vmid) if template else None
    reasons = []
    if (not template or not source or not source.template or source.state != 'stopped'
            or source.locked or source.owner or source.config_sha256 != template.config_sha256
            or source.disk_mib != template.disk_mib or spec.disk_mib != template.disk_mib):
        reasons.append('reviewed_clean_template_required')
    running = [v for v in inventory.vms if v.state != 'stopped' and not v.template]
    memory = sum(v.memory_mib for v in running)
    cpus = sum(v.vcpus for v in running)
    disk = inventory.committed_storage_mib
    extra_memory = extra_disk = 0
    slots = {'linux': policy.external_linux_slots, 'android': policy.external_android_slots}
    rows = list(reservations)
    known = {r['spec']['request_id'] for r in rows}
    for vm in inventory.vms:
        if vm.owner and vm.owner.request_id not in known:
            owner = vm.owner
            registered = DeviceSpec(request_id=owner.request_id, tenant_id=owner.tenant_id,
                                    identity_id=owner.identity_id, resource_id=owner.resource_id,
                                    kind=owner.kind, vmid=vm.vmid, vcpus=owner.vcpus,
                                    memory_mib=owner.memory_mib, disk_mib=owner.disk_mib)
            rows.append({'spec': registered.model_dump(), 'owner': owner.model_dump()})
            known.add(owner.request_id)
    # Host ownership survives local ledger loss. A new operator ledger must not
    # create a second binding for the same tenant/kind or reuse a resource ID.
    for row in rows:
        previous = DeviceSpec.model_validate(row['spec'])
        if previous.request_id == spec.request_id:
            if previous != spec:
                reasons.append('idempotency_request_changed')
        elif (previous.resource_id == spec.resource_id or previous.vmid == spec.vmid
              or (previous.tenant_id, previous.kind) == (spec.tenant_id, spec.kind)):
            reasons.append('device_binding_conflict')
    if not any(r['spec']['request_id'] == spec.request_id for r in rows):
        rows.append({'spec': spec.model_dump(), 'owner': None})
    for row in rows:
        item = DeviceSpec.model_validate(row['spec'])
        current = vms.get(item.vmid)
        expected = Owner.model_validate(row['owner']) if row.get('owner') else None
        if current and (expected is None or current.owner != expected):
            reasons.append('vm_id_or_owner_conflict')
            continue
        slots[item.kind] += 1
        if not current or current.state == 'stopped':
            allocated_memory = max(item.memory_mib, current.memory_mib if current else 0)
            memory += allocated_memory
            cpus += max(item.vcpus, current.vcpus if current else 0)
            extra_memory += allocated_memory
        else:
            # A running VM's allocation already entered the inventory totals.
            memory += max(0, item.memory_mib - current.memory_mib)
            cpus += max(0, item.vcpus - current.vcpus)
            extra_memory += max(0, item.memory_mib - current.memory_mib)
        # Every binding reserves one full recovery copy even if its VM exists.
        extra_disk += item.disk_mib
        if not current:
            # Include a 4 MiB cloud-init disk, not just the advertised OS size.
            extra_disk += item.disk_mib + 4
        elif current.disk_mib < item.disk_mib:
            extra_disk += item.disk_mib - current.disk_mib
    disk += extra_disk
    limits = {'memory_mib': max(0, inventory.memory_mib - policy.host_memory_mib),
              'vcpus': max(0, inventory.physical_cores - policy.host_cores),
              'disk_mib': inventory.storage_mib * (100 - policy.disk_free_percent) // 100,
              'linux_slots': policy.linux_slots, 'android_slots': policy.android_slots}
    demand = {'memory_mib': memory, 'vcpus': cpus, 'disk_mib': disk,
              'linux_slots': slots['linux'], 'android_slots': slots['android']}
    for key in demand:
        if demand[key] > limits[key]:
            reasons.append('capacity_' + key)
    if inventory.available_memory_mib < extra_memory + policy.host_memory_mib:
        reasons.append('host_memory_pressure')
    if inventory.available_storage_mib < extra_disk + inventory.storage_mib * policy.disk_free_percent // 100:
        reasons.append('storage_free_space_low')
    return {'admitted': not reasons, 'reasons': sorted(set(reasons)), 'demand': demand,
            'limits': limits, 'creates_resources': False, 'product_ready': False,
            'plan_sha256': fingerprint({'spec': spec.model_dump(), 'policy': policy.model_dump()}),
            'inventory_sha256': fingerprint(inventory.model_dump()),
            'observed_at': inventory.observed_at}


class ProvisionBook:
    """One private operator ledger for a host, shared by every creation worker.

    File locking covers provider IO as well as reservations. Lost clone responses
    are observed, never automatically replayed when the target is still absent.
    """
    def __init__(self, root, *, operator=False, clock=time.time, admission=None):
        if not operator:
            raise ProvisionError('operator_required')
        self.root = Path(root).expanduser().absolute()
        if self.root.is_symlink():
            raise ProvisionError('unsafe_operator_ledger')
        private_directory(self.root)
        if self.root.stat().st_uid != os.getuid():
            raise ProvisionError('unsafe_operator_ledger')
        self.path = self.root / 'devices.sqlite3'
        if self.path.is_symlink():
            raise ProvisionError('unsafe_operator_ledger')
        self.clock = clock
        self.admission = admission
        self.lock = FileLock(self.root / 'provision.lock', timeout=5)
        with self._tx() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS devices(
                request TEXT PRIMARY KEY, tenant TEXT NOT NULL, kind TEXT NOT NULL,
                resource TEXT NOT NULL UNIQUE, vmid INTEGER NOT NULL UNIQUE,
                spec TEXT NOT NULL, policy TEXT NOT NULL, plan TEXT NOT NULL,
                owner TEXT NOT NULL, state TEXT NOT NULL, expires REAL NOT NULL,
                attempted INTEGER NOT NULL DEFAULT 0, code TEXT NOT NULL DEFAULT '',
                updated REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS tenant_kind ON devices(tenant,kind)
                WHERE state NOT IN ('cancelled','expired');
                CREATE TABLE IF NOT EXISTS device_accounts(
                request TEXT PRIMARY KEY, scope TEXT NOT NULL);''')
        self.path.chmod(0o600)

    @contextmanager
    def _tx(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def _guard(self):
        try:
            with self.lock:
                yield
        except Timeout:
            raise ProvisionError('operator_action_inflight') from None

    def _rows(self, db):
        # Only an unattempted reservation can expire without provider inspection.
        db.execute("UPDATE devices SET state='expired',updated=? WHERE state='reserved' AND attempted=0 AND expires<=?",
                   (self.clock(), self.clock()))
        return [{'spec': json.loads(row['spec']), 'owner': json.loads(row['owner'])}
                for row in db.execute("SELECT spec,owner FROM devices WHERE state NOT IN ('cancelled','expired')")]

    def plan(self, spec, policy, adapter):
        with self._guard(), self._tx() as db:
            proof = self._account(spec)
            rows = self._rows(db)
            result = inspect_capacity(spec, policy, adapter.inventory(), rows, now=self.clock())
            self._account(spec, proof.scope())
            result['plan_sha256'] = self._plan_hash(spec, policy, proof)
            result['account_checked_at'] = proof.observed_at
            return result

    @staticmethod
    def _plan_hash(spec, policy, proof):
        return fingerprint({'spec': spec.model_dump(), 'policy': policy.model_dump(),
                            'account_scope': proof.scope()})

    def _account(self, spec, expected=None):
        if self.admission is None:
            raise ProvisionError('account_admission_required')
        try:
            proof = AccountProof.model_validate(self.admission.check(spec))
        except AdmissionError as error:
            raise ProvisionError(str(error)) from None
        except Exception:
            raise ProvisionError('account_evidence_unavailable') from None
        if (not math.isfinite(proof.observed_at) or not 0 <= self.clock() - proof.observed_at <= 60
                or proof.tenant_id != spec.tenant_id or proof.identity_id != spec.identity_id):
            raise ProvisionError('account_evidence_stale_or_wrong_scope')
        if expected is not None and proof.scope() != expected:
            raise ProvisionError('account_binding_changed')
        return proof

    def reserve(self, spec, policy, adapter, *, plan_sha256):
        with self._guard(), self._tx() as db:
            proof = self._account(spec)
            expected = self._plan_hash(spec, policy, proof)
            if expected != plan_sha256:
                raise ProvisionError('reviewed_plan_changed')
            rows = self._rows(db)
            old = db.execute('SELECT * FROM devices WHERE request=?', (spec.request_id,)).fetchone()
            if old:
                if old['plan'] != expected:
                    raise ProvisionError('idempotency_request_changed')
                if old['state'] in ('expired', 'cancelled'):
                    raise ProvisionError('reservation_expired_or_cancelled')
                binding = db.execute('SELECT scope FROM device_accounts WHERE request=?', (spec.request_id,)).fetchone()
                if not binding or json.loads(binding['scope']) != proof.scope():
                    raise ProvisionError('account_binding_changed')
                return self._public(old)
            result = inspect_capacity(spec, policy, adapter.inventory(), rows, now=self.clock())
            if not result['admitted']:
                raise ProvisionError(','.join(result['reasons']))
            self._account(spec, proof.scope())
            owner = Owner(tenant_id=spec.tenant_id, identity_id=spec.identity_id,
                          resource_id=spec.resource_id, request_id=spec.request_id,
                          request_sha256=fingerprint(spec.model_dump()), nonce=secrets.token_hex(32), kind=spec.kind,
                          vcpus=spec.vcpus, memory_mib=spec.memory_mib, disk_mib=spec.disk_mib)
            try:
                db.execute('INSERT INTO devices VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?)',
                           (spec.request_id, spec.tenant_id, spec.kind, spec.resource_id, spec.vmid,
                            encoded(spec.model_dump()), encoded(policy.model_dump()), expected,
                            encoded(owner.model_dump()), 'reserved', self.clock() + policy.reservation_seconds,
                            '', self.clock()))
            except sqlite3.IntegrityError:
                raise ProvisionError('device_binding_conflict') from None
            db.execute('INSERT INTO device_accounts VALUES (?,?)', (spec.request_id, encoded(proof.scope())))
            return self._public(db.execute('SELECT * FROM devices WHERE request=?', (spec.request_id,)).fetchone())

    @staticmethod
    def _public(row):
        return {'request_id': row['request'], 'tenant_id': row['tenant'], 'kind': row['kind'],
                'resource_id': row['resource'], 'vmid': row['vmid'], 'state': row['state'],
                'code': row['code'], 'plan_sha256': row['plan'], 'product_ready': False}

    def status(self, request_id):
        with self._tx() as db:
            row = db.execute('SELECT * FROM devices WHERE request=?', (request_id,)).fetchone()
            if not row:
                raise ProvisionError('request_not_found')
            return self._public(row)

    def _state(self, request_id, state, code=''):
        with self._tx() as db:
            db.execute('UPDATE devices SET state=?,code=?,updated=? WHERE request=?',
                       (state, code, self.clock(), request_id))

    def apply(self, request_id, adapter, *, plan_sha256):
        """Create/configure a stopped VM; never starts, stops, deletes or pairs it."""
        with self._guard():
            with self._tx() as db:
                # Legacy live devices carry explicit adoption provenance; the
                # clone/prepare path must never reset their existing environment.
                if (db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_adoptions'").fetchone()
                        and db.execute('SELECT 1 FROM device_adoptions WHERE request=?',(request_id,)).fetchone()):
                    raise ProvisionError('manual_adoption_cannot_clone_or_prepare')
                rows = self._rows(db)
                row = db.execute('SELECT * FROM devices WHERE request=?', (request_id,)).fetchone()
                if not row or row['plan'] != plan_sha256:
                    raise ProvisionError('reviewed_plan_changed')
                if row['state'] in ('expired', 'cancelled'):
                    raise ProvisionError('reservation_expired_or_cancelled')
                spec, policy = DeviceSpec.model_validate_json(row['spec']), Policy.model_validate_json(row['policy'])
                owner = Owner.model_validate_json(row['owner'])
                binding = db.execute('SELECT scope FROM device_accounts WHERE request=?', (request_id,)).fetchone()
            try:
                if not binding:
                    raise ProvisionError('account_binding_missing')
                account_scope = json.loads(binding['scope'])
                self._account(spec, account_scope)
                inventory = adapter.inventory()
                current = next((v for v in inventory.vms if v.vmid == spec.vmid), None)
                if current and (current.owner != owner or current.template or current.state != 'stopped' or current.locked):
                    raise ProvisionError('vm_owner_or_state_conflict')
                if row['attempted'] and not current:
                    raise ProvisionError('clone_outcome_unknown_no_replay')
                result = inspect_capacity(spec, policy, inventory, rows, now=self.clock())
                if not result['admitted']:
                    raise ProvisionError(','.join(result['reasons']))
                if row['state'] == 'staged':
                    if not current or not current.prepared or current.vcpus != spec.vcpus or current.memory_mib != spec.memory_mib or current.disk_mib != spec.disk_mib:
                        raise ProvisionError('staged_vm_changed')
                    self._account(spec, account_scope)
                    return self.status(request_id)
                if not current:
                    self._account(spec, account_scope)
                    with self._tx() as db:
                        db.execute("UPDATE devices SET state='cloning',attempted=1,updated=? WHERE request=?",
                                   (self.clock(), request_id))
                    adapter.clone_stopped(spec, policy, owner)
                    self._account(spec, account_scope)
                    current = adapter.inspect_vm(spec.vmid)
                if not current or current.owner != owner or current.state != 'stopped' or current.locked or current.template:
                    raise ProvisionError('clone_not_confirmed')
                if (current.prepared and current.vcpus == spec.vcpus
                        and current.memory_mib == spec.memory_mib and current.disk_mib == spec.disk_mib):
                    self._account(spec, account_scope)
                    self._state(request_id, 'staged')
                    return self.status(request_id)
                self._state(request_id, 'configuring')
                self._account(spec, account_scope)
                adapter.prepare_stopped(spec, policy, owner, current.config_sha256)
                self._account(spec, account_scope)
                current = adapter.inspect_vm(spec.vmid)
                if (not current or current.owner != owner or current.state != 'stopped' or current.locked
                        or not current.prepared or current.vcpus != spec.vcpus
                        or current.memory_mib != spec.memory_mib or current.disk_mib != spec.disk_mib):
                    raise ProvisionError('configuration_not_confirmed')
                self._account(spec, account_scope)
                self._state(request_id, 'staged')
                return self.status(request_id)
            except Exception as error:
                code = str(error) if isinstance(error, ProvisionError) else 'provider_outcome_unknown'
                self._state(request_id, 'needs_operator', code)
                raise ProvisionError(code) from None

    def cancel_unattempted(self, request_id, adapter):
        with self._guard(), self._tx() as db:
            row = db.execute('SELECT * FROM devices WHERE request=?', (request_id,)).fetchone()
            if not row or row['attempted'] or row['state'] not in ('reserved', 'needs_operator'):
                raise ProvisionError('reservation_cannot_cancel')
            if adapter.inspect_vm(row['vmid']) is not None:
                raise ProvisionError('vm_exists_no_automatic_release')
            db.execute("UPDATE devices SET state='cancelled',updated=? WHERE request=?", (self.clock(), request_id))
        return self.status(request_id)
