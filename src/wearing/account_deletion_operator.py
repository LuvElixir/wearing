"""Production deletion bridge. Explicit operator registry, no inferred ownership.

The journal contains no provider secrets. ControlStore is the source of the
accepted user request. Registered assets and tenant control receipts are pinned
to that request before any external action. Nothing runs on module import.
"""
import json
import re
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update

from .account_deletion import CODES, DeletionError, Receipt, digest, encoded, identifier
from .cloud.account_deletion_control import AccountDeletionControl
from .cloud.control import deletion_requests, members, ownership, routes, sessions, tenants, users
from .cloud.instance import read_private
from .cloud.mobile_auth import session_storage_scope


ASSET_FIELDS = {'tenant_id', 'instance_id', 'owner_user_id', 'account_id', 'region', 'cvm_id',
                'system_disk_id', 'disk_ids', 'snapshot_ids', 'exclusive', 'complete',
                'indexes_on_disks', 'backups_only_snapshots', 'other_resources',
                'worker_upstream', 'operator_credential_ref'}


def checked_asset(value):
    if not isinstance(value, dict) or set(value) != ASSET_FIELDS: raise DeletionError('incomplete_registry')
    for k in ('tenant_id', 'instance_id', 'owner_user_id'): identifier(value[k])
    for k, pattern in [('account_id', r'[0-9]{1,32}'), ('region', r'[a-z][a-z0-9-]{1,62}'),
                       ('cvm_id', r'ins-[a-z0-9]{8,32}'), ('system_disk_id', r'disk-[a-z0-9]{8,32}'),
                       ('operator_credential_ref', r'[A-Za-z0-9_-]{1,80}\.key')]:
        if not isinstance(value[k], str) or not re.fullmatch(pattern, value[k]): raise DeletionError('incomplete_registry')
    for k, prefix in [('disk_ids', 'disk-'), ('snapshot_ids', 'snap-')]:
        ids = value[k]
        if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(i, str) or not re.fullmatch(prefix+r'[a-z0-9]{8,32}', i) for i in ids) or len(ids) != len(set(ids)):
            raise DeletionError('incomplete_registry')
    if not value['disk_ids'] or value['system_disk_id'] not in value['disk_ids']: raise DeletionError('incomplete_registry')
    if any(value[k] is not True for k in ('exclusive', 'complete', 'indexes_on_disks', 'backups_only_snapshots')) or value['other_resources'] != []:
        raise DeletionError('incomplete_registry')
    url = urlparse(value['worker_upstream'])
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in ('', '/')): raise DeletionError('incomplete_registry')
    return json.loads(encoded(value))


class OperatorRegistry:
    def __init__(self, jobs):
        if jobs.mode != 'operator': raise DeletionError('adapter_mismatch')
        self.jobs = jobs
        with jobs.tx() as db:
            db.execute('CREATE TABLE IF NOT EXISTS deletion_assets (tenant TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS deletion_bindings (control_id TEXT PRIMARY KEY,job_id TEXT UNIQUE NOT NULL,value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS deletion_operator_proofs (id TEXT PRIMARY KEY,value TEXT NOT NULL)')

    def register(self, value):
        asset = checked_asset(value)
        with self.jobs.tx() as db:
            old = db.execute('SELECT value FROM deletion_assets WHERE tenant=?', (asset['tenant_id'],)).fetchone()
            if old and json.loads(old[0]) == asset: return asset
            if old: raise DeletionError('ownership_changed')  # No overwrite of pinned assets.
            for row in db.execute('SELECT value FROM deletion_assets'):
                other = json.loads(row[0])
                if other['instance_id'] == asset['instance_id']: raise DeletionError('ownership_changed')
                if other['account_id'] == asset['account_id'] and other['region'] == asset['region']:
                    if (other['cvm_id'] == asset['cvm_id'] or set(other['disk_ids']) & set(asset['disk_ids'])
                            or set(other['snapshot_ids']) & set(asset['snapshot_ids'])): raise DeletionError('ownership_changed')
            db.execute('INSERT INTO deletion_assets VALUES(?,?)', (asset['tenant_id'], encoded(asset)))
        return asset

    def asset(self, tenant):
        with self.jobs.tx() as db:
            row = db.execute('SELECT value FROM deletion_assets WHERE tenant=?', (tenant,)).fetchone()
        if not row: raise DeletionError('incomplete_registry')
        return checked_asset(json.loads(row[0]))

    def proof(self, key, value=None):
        with self.jobs.tx() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO deletion_operator_proofs VALUES(?,?)', (key, encoded(value)))
            row = db.execute('SELECT value FROM deletion_operator_proofs WHERE id=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None


class TenantDeletionClient:
    """Private operator endpoint, never the business gateway credential."""
    def __init__(self, credential_root, *, transport=None):
        self.root = credential_root
        self.transport = transport

    def execute(self, asset, request):
        key = read_private(self.root / asset['operator_credential_ref']).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{64}', key): raise DeletionError('adapter_unconfigured')
        url = asset['worker_upstream'].rstrip('/') + '/internal/account-deletion'
        headers = {'Authorization': 'Bearer ' + key}
        try:
            with httpx.Client(timeout=25, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                response = client.post(url, json=request, headers=headers)
                if response.status_code != 200: raise ValueError()
                posted = response.json()
                # Separate readback is required; a POST receipt alone is not proof.
                response = client.get(url, params={k: request[k] for k in ('job_id', 'plan_revision', 'phase', 'operation_id')}, headers=headers)
                if response.status_code != 200: raise ValueError()
                value = response.json()
                if value != posted or value.get('request') != request: raise ValueError()
                if value.get('state') != 'done': raise DeletionError(value.get('code') if value.get('code') in CODES else 'provider_unavailable')
                if not re.fullmatch(r'[a-f0-9]{64}', value.get('evidence', '')): raise ValueError()
                return value
        except (httpx.HTTPError, ValueError):
            raise DeletionError('provider_unavailable') from None


class ProductionDeletionAdapter:
    mode = 'operator'

    def __init__(self, control, jobs, registry, provider_for, tenant_client):
        if not control.operator or jobs.mode != 'operator': raise DeletionError('operator_required', 403)
        self.control, self.jobs, self.registry = control, jobs, registry
        self.provider_for, self.tenant_client = provider_for, tenant_client

    def prepare(self, control_id):
        try:
            return self._prepare(control_id)
        except DeletionError as error:
            with self.control.transaction(mutating=True) as db:
                db.execute(update(deletion_requests).where(deletion_requests.c.id == control_id,
                    deletion_requests.c.state.in_(['frozen', 'waiting'])).values(state='waiting',
                    code=error.code if error.code in CODES else 'ownership_changed', updated_at=int(self.jobs.clock())))
            raise

    def _prepare(self, control_id):
        """Import only a real accepted request, never a new operator-invented user request."""
        with self.control.transaction() as db:
            row = db.execute(select(deletion_requests).where(deletion_requests.c.id == control_id)).mappings().first()
            if not row: raise DeletionError('job_not_found', 404)
            plan, user = json.loads(row['plan_json']), row['user_id']
            state = row['state']
        if state == 'awaiting_operator': AccountDeletionControl(self.control).freeze(control_id)
        with self.control.transaction() as db:
            registrations, assets = [], {}
            for t in plan['tenants']:
                r = db.execute(select(ownership).where(ownership.c.tenant_id == t['tenant_id'])).mappings().one()
                people = sorted(db.scalars(select(members.c.user_id).where(members.c.tenant_id == t['tenant_id'])))
                registrations.append(dict(tenant_id=t['tenant_id'], classification=r['classification'], owner_user_id=r['owner_user_id'], member_ids=people, instance_id=r['instance_id']))
                if t['action'] == 'erase_private':
                    a = self.registry.asset(t['tenant_id'])
                    route = db.execute(select(routes).where(routes.c.tenant_id == t['tenant_id'])).mappings().first()
                    if (a['owner_user_id'] != user or a['instance_id'] != t['instance_id'] or not route
                            or a['worker_upstream'].rstrip('/') != route['upstream'].rstrip('/')): raise DeletionError('ownership_changed')
                    assets[t['tenant_id']] = a
                else:
                    # Per-user token ownership in shared tenants is not yet registered.
                    # Stop before external work; never freeze or erase another member.
                    raise DeletionError('incomplete_registry')
        # Registry entries unrelated to the accepted request may never silently
        # expand a journal job (even if they name this user).
        accepted = {t['tenant_id'] for t in plan['tenants']}
        with self.jobs.tx() as db:
            for r in db.execute('SELECT id,members FROM tenants'):
                if user in json.loads(r['members']) and r['id'] not in accepted: raise DeletionError('ownership_changed')
        for r in registrations:
            try: current = self.jobs.registration(r['tenant_id'])
            except DeletionError as error:
                if error.code != 'tenant_not_registered': raise
                current = None
            if current:
                if {k: current[k] for k in r} != r: raise DeletionError('ownership_changed')
            else:
                self.jobs.register(r['tenant_id'], r['classification'], r['member_ids'], owner_user_id=r['owner_user_id'], instance_id=r['instance_id'])
        journal_plan = self.jobs.preview(user)
        job = self.jobs.request(user, control_id, journal_plan['revision'])
        binding = {'control_id': control_id, 'user_id': user, 'control_revision': row['plan_revision'],
                   'journal_revision': job['plan_revision'], 'tenants': plan['tenants'], 'assets': assets}
        with self.jobs.tx() as db:
            old = db.execute('SELECT job_id,value FROM deletion_bindings WHERE control_id=?', (control_id,)).fetchone()
            if old and (old['job_id'] != job['id'] or json.loads(old['value']) != binding): raise DeletionError('ownership_changed')
            if not old: db.execute('INSERT INTO deletion_bindings VALUES(?,?,?)', (control_id, job['id'], encoded(binding)))
        self._frozen(binding)
        return job

    def _frozen(self, binding):
        with self.control.transaction() as db:
            if db.scalar(select(users.c.deletion_state).where(users.c.id == binding['user_id'])) != 'frozen': raise DeletionError('ownership_changed')
            if db.scalar(select(sessions.c.id_hash).where(sessions.c.user_id == binding['user_id'])): raise DeletionError('ownership_changed')
            request = db.execute(select(deletion_requests).where(deletion_requests.c.id == binding['control_id'])).mappings().one()
            if request['plan_revision'] != binding['control_revision'] or request['state'] not in ('frozen', 'waiting', 'completed'): raise DeletionError('ownership_changed')
            for t in binding['tenants']:
                people = list(db.execute(select(members.c.user_id, members.c.active).where(members.c.tenant_id == t['tenant_id'])))
                r = db.execute(select(ownership).where(ownership.c.tenant_id == t['tenant_id'])).mappings().one()
                if (people != [(binding['user_id'], False)] or r['owner_user_id'] != binding['user_id'] or r['classification'] != 'private'
                        or r['instance_id'] != t['instance_id'] or db.scalar(select(tenants.c.deletion_state).where(tenants.c.id == t['tenant_id'])) != 'frozen'):
                    raise DeletionError('ownership_changed')

    def _binding(self, op):
        with self.jobs.tx() as db:
            row = db.execute('SELECT value FROM deletion_bindings WHERE job_id=?', (op.job_id,)).fetchone()
        if not row: raise DeletionError('adapter_mismatch')
        b = json.loads(row[0])
        if b['user_id'] != op.user_id or b['journal_revision'] != op.plan_revision: raise DeletionError('adapter_mismatch')
        self._frozen(b)
        for t, asset in b['assets'].items():
            if self.registry.asset(t) != asset: raise DeletionError('ownership_changed')
        return b

    def execute(self, op):
        try:
            b = self._binding(op)
            if op.phase == 'freeze_account': proof = {'control_id': b['control_id'], 'frozen': True}
            elif op.phase == 'revoke_user_devices':
                proofs = []
                for tenant, asset in b['assets'].items():
                    request = {'job_id': b['control_id'], 'plan_revision': b['control_revision'],
                               'operation_id': digest([op.operation_id, tenant, 'freeze']),
                               'tenant_id': tenant, 'instance_id': asset['instance_id'], 'phase': 'freeze_tenant',
                               'owner_scope': session_storage_scope(op.user_id, tenant)}
                    # Tenant freeze also revokes connector/native/push access, even
                    # when a later unsupported upstream token revoke must wait.
                    proofs.append(self.tenant_client.execute(asset, request))
                proof = {'control_id': b['control_id'], 'business_sessions': 0, 'tenant_device_fences': proofs}
            elif op.phase == 'finalize_account':
                status = self.jobs.status(op.job_id)
                if any(s['state'] != 'succeeded' for s in status['steps'] if s['phase'] != 'finalize_account'):
                    raise DeletionError('adapter_mismatch')
                proof = {'journal_id': op.job_id, 'steps': [{k: s[k] for k in ('phase', 'tenant_id', 'evidence')} for s in status['steps'] if s['phase'] != 'finalize_account']}
                # Minimal immutable identity tombstone remains to deny re-enrollment;
                # tenant content/volumes/backups are gone, not claimed anonymized SQL.
                self.registry.proof(op.operation_id, proof)
                with self.control.transaction(mutating=True) as db:
                    db.execute(update(deletion_requests).where(deletion_requests.c.id == b['control_id']).values(state='completed', code='verified', updated_at=int(self.jobs.clock())))
            else:
                asset = b['assets'].get(op.tenant_id)
                if not asset or asset['instance_id'] != op.instance_id: raise DeletionError('adapter_mismatch')
                if op.phase in {'freeze_tenant', 'revoke_credentials', 'revoke_devices', 'drain_actions'}:
                    payload = {'job_id': b['control_id'], 'plan_revision': b['control_revision'], 'operation_id': op.operation_id,
                               'tenant_id': op.tenant_id, 'instance_id': op.instance_id, 'phase': op.phase,
                               'owner_scope': session_storage_scope(op.user_id, op.tenant_id)}
                    proof = self.tenant_client.execute(asset, payload)
                elif op.phase in {'stop_instance', 'erase_primary', 'erase_indexes', 'erase_backups', 'finalize_tenant'}:
                    proof = self.provider_for(asset).run(op, asset)
                else: raise DeletionError('adapter_mismatch')
            self.registry.proof(op.operation_id, proof)
            return Receipt(op.operation_id, 'done', evidence=digest(proof))
        except DeletionError as error:
            return Receipt(op.operation_id, 'retry', code=error.code if error.code in CODES else 'adapter_failed')

    def resume(self, job_id, *, max_steps=50):
        result = self.jobs.run(job_id, self, max_steps=max_steps)
        with self.jobs.tx() as db:
            binding = db.execute('SELECT value FROM deletion_bindings WHERE job_id=?', (job_id,)).fetchone()
        if binding and result['state'] != 'completed':
            b = json.loads(binding[0])
            with self.control.transaction(mutating=True) as db:
                db.execute(update(deletion_requests).where(deletion_requests.c.id == b['control_id'], deletion_requests.c.state != 'completed').values(state='waiting', code=result['code'] or 'instance_busy', updated_at=int(self.jobs.clock())))
        return result
