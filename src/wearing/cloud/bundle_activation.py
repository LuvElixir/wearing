"""Authenticated provisioning progress and fenced activation leases.

Progress contains no guest address, credential, provider ID or identity token.
Only the activation service may acquire a lease or publish delivery evidence.
"""
from __future__ import annotations

import json
import math
import re
import time

from sqlalchemy import select, text, update

from .control import ControlError


STATES = frozenset({'reserved', 'preparing', 'installing', 'pairing', 'ready', 'needs_review'})
MEMBER_STATES = frozenset({'pending', 'preparing', 'ready', 'needs_review'})
KINDS = ('core', 'linux', 'android')
STAGE_ORDER = ('reserved', 'preparing', 'installing', 'pairing', 'ready')
STEPS = frozenset(('planned', 'core', 'preparing', 'installing', 'pairing', 'complete', 'inspection', 'review')) | frozenset(
    kind + ':' + step for kind in ('linux', 'android')
    for step in ('reserve', 'clone', 'network', 'boot', 'runtime', 'pair', 'verify', 'startup'))


class ActivationError(ControlError):
    pass


def member_progress(value):
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, list):
        if len(value) != 3 or any(not isinstance(v, dict) for v in value) or len({v.get('kind') for v in value}) != 3:
            raise ActivationError('activation_progress_invalid')
        value = {v['kind']: {'state': v.get('state')} for v in value}
    if not isinstance(value, dict) or set(value) != set(KINDS):
        raise ActivationError('activation_progress_invalid')
    result = {}
    for kind in KINDS:
        item = value[kind]
        if not isinstance(item, dict) or item.get('state') not in MEMBER_STATES:
            raise ActivationError('activation_progress_invalid')
        result[kind] = {'state': item['state']}
    return result


def public_progress(value):
    if not value or value.get('state') not in STATES:
        raise ActivationError('provisioning_unavailable')
    members = member_progress(value.get('members', value.get('members_json')))
    if value['state'] == 'ready' and any(v['state'] != 'ready' for v in members.values()):
        raise ActivationError('activation_progress_invalid')
    reason = value.get('reason')
    if reason not in (None, 'provisioning_requires_review'):
        raise ActivationError('activation_progress_invalid')
    updated = value.get('updated_at')
    if type(updated) not in (int, float) or not math.isfinite(updated) or updated < 0:
        raise ActivationError('activation_progress_invalid')
    return {'state': value['state'], 'members': members, 'updated_at': int(updated),
            'reason': reason or None, 'retry_after': 5}


class ActivationStore:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock

    def _activation(self):
        if not getattr(self.store, 'activation', False):
            raise ActivationError('activation_role_required')

    @staticmethod
    def _identity(event_id, worker_id, generation):
        if (not isinstance(event_id, str) or not re.fullmatch('[a-f0-9]{32}', event_id)
                or not isinstance(worker_id, str) or not re.fullmatch('[a-f0-9]{32}', worker_id)
                or type(generation) is not int or generation < 1):
            raise ActivationError('activation_lease_invalid')

    def _pg(self, name, args, *, scope=None):
        allowed = {'bundle_activation_status', 'activation_claim', 'activation_heartbeat',
                   'activation_update', 'activation_release'}
        if name not in allowed:
            raise ActivationError('activation_function_invalid')
        placeholders = ','.join('CAST(:members AS jsonb)' if k == 'members' else ':' + k for k in args)
        with self.store.transaction(mutating=name != 'bundle_activation_status', **(scope or {})) as db:
            return db.scalar(text(f'SELECT wearing_control.{name}({placeholders})'), args)

    def _fresh(self, db, row):
        from .control import bundles, members, ownership, routes, digest
        owner = db.execute(select(ownership).where(ownership.c.tenant_id == row['tenant_id'])).mappings().first()
        people = sorted((r.user_id, bool(r.active)) for r in db.execute(
            select(members).where(members.c.tenant_id == row['tenant_id'])))
        route = db.scalar(select(routes.c.instance_id).where(routes.c.tenant_id == row['tenant_id']))
        bundle = db.execute(select(bundles).where(bundles.c.id == row['bundle_id'])).mappings().first()
        return bool(owner and bundle and owner['classification'] == 'private'
                    and owner['owner_user_id'] == row['user_id'] and owner['member_count'] == 1
                    and people == [(row['user_id'], True)]
                    and owner['revision'] == row['ownership_revision']
                    and owner['member_digest'] == row['member_digest']
                    and row['member_digest'] == digest(json.dumps(people, separators=(',', ':')))
                    and owner['instance_id'] == route == bundle['instance_id'] == row['instance_id']
                    and bundle['tenant_id'] == row['tenant_id']
                    and self.store.user_available(db, row['user_id'])
                    and self.store.tenant_editable(db, row['tenant_id']))

    def status(self, current):
        if self.store.postgres:
            value = self._pg('bundle_activation_status', {'tenant': current.tenant_id},
                             scope={'user_id': current.user_id, 'tenant_id': current.tenant_id})
        else:
            from .control import bundle_activations
            with self.store.transaction() as db:
                value = db.execute(select(bundle_activations).where(
                    bundle_activations.c.tenant_id == current.tenant_id,
                    bundle_activations.c.user_id == current.user_id)).mappings().first()
                if value is not None and not self._fresh(db, value):
                    value = None
        return public_progress(value)

    def claim(self, worker_id, lease_seconds=120):
        self._activation()
        self._identity('0' * 32, worker_id, 1)
        if type(lease_seconds) is not int or not 30 <= lease_seconds <= 300:
            raise ActivationError('activation_lease_invalid')
        if self.store.postgres:
            return self._pg('activation_claim', {'worker': worker_id, 'seconds': lease_seconds})
        from .control import bundles, bundle_activations
        now = int(self.clock())
        with self.store.transaction(mutating=True) as db:
            rows = db.execute(select(bundle_activations).where(
                bundle_activations.c.state.not_in(('ready', 'needs_review')),
                (bundle_activations.c.lease_until.is_(None)) | (bundle_activations.c.lease_until <= now))
                .order_by(bundle_activations.c.created_at, bundle_activations.c.id)).mappings().all()
            row = next((r for r in rows if self._fresh(db, r)), None)
            if row is None:
                return None
            changes = {'generation': row['generation'] + 1, 'lease_owner': worker_id,
                       'lease_until': now + lease_seconds, 'updated_at': now}
            db.execute(update(bundle_activations).where(bundle_activations.c.id == row['id']).values(**changes))
            bundle = db.execute(select(bundles).where(bundles.c.id == row['bundle_id'])).mappings().one()
            return {**dict(row), **changes, 'bundle': dict(bundle)}

    def _mutate(self, action, event_id, worker_id, generation, **changes):
        self._activation()
        self._identity(event_id, worker_id, generation)
        if self.store.postgres:
            return self._pg('activation_' + action, {'event': event_id, 'worker': worker_id,
                                                    'generation': generation, **changes})
        from .control import bundle_activations
        now = int(self.clock())
        with self.store.transaction(mutating=True) as db:
            row = db.execute(select(bundle_activations).where(bundle_activations.c.id == event_id,
                bundle_activations.c.lease_owner == worker_id, bundle_activations.c.generation == generation,
                bundle_activations.c.lease_until > now)).mappings().first()
            if row is None or not self._fresh(db, row):
                return None
            if action == 'heartbeat':
                values = {'lease_until': now + changes['seconds']}
            elif action == 'release':
                values = {'lease_until': None, 'lease_owner': None}
            else:
                if (row['state'] in ('ready', 'needs_review')
                        or changes['state'] != 'needs_review' and STAGE_ORDER.index(changes['state']) < STAGE_ORDER.index(row['state'])):
                    return None
                values = {k: v for k, v in changes.items() if k != 'members'}
                values['members_json'] = changes['members']
            values['updated_at'] = now
            db.execute(update(bundle_activations).where(bundle_activations.c.id == event_id).values(**values))
            return {**dict(row), **values}

    def heartbeat(self, event_id, worker_id, generation, lease_seconds=120):
        if type(lease_seconds) is not int or not 30 <= lease_seconds <= 300:
            raise ActivationError('activation_lease_invalid')
        return self._mutate('heartbeat', event_id, worker_id, generation, seconds=lease_seconds)

    def update(self, event_id, worker_id, generation, *, state, step, receipt_sha256, reason, members):
        progress = member_progress(members)
        if (state not in STATES or step not in STEPS
                or not re.fullmatch(r'[a-f0-9]{64}', receipt_sha256)
                or reason not in (None, 'provisioning_requires_review')
                or state == 'ready' and any(v['state'] != 'ready' for v in progress.values())):
            raise ActivationError('activation_progress_invalid')
        return self._mutate('update', event_id, worker_id, generation, state=state, step=step,
                            receipt_sha256=receipt_sha256, reason=reason,
                            members=json.dumps(progress, sort_keys=True, separators=(',', ':')))

    def release(self, event_id, worker_id, generation):
        return self._mutate('release', event_id, worker_id, generation)
