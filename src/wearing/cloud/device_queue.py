"""Durable operator FIFO, using ProvisionBook as the sole capacity allocator.

Waiting requests own no compute reservation. Promotion repeats live account and
host checks; a lost promotion reply is reconciled by the original request ID.
"""
import json
import sqlite3

from .device_provisioning import DeviceSpec, Policy, ProvisionError, encoded, fingerprint


class DeviceQueue:
    def __init__(self, book):
        self.book = book
        with book._tx() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS device_queue(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, request TEXT NOT NULL UNIQUE,
              tenant TEXT NOT NULL, kind TEXT NOT NULL, spec TEXT NOT NULL, policy TEXT NOT NULL,
              account_scope TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL,
              code TEXT NOT NULL, updated REAL NOT NULL);
              CREATE UNIQUE INDEX IF NOT EXISTS queue_tenant_kind ON device_queue(tenant,kind)
              WHERE state NOT IN ('cancelled','blocked');''')

    @staticmethod
    def _public(row):
        return {'request_id': row['request'], 'sequence': row['sequence'], 'state': row['state'],
                'code': row['code'], 'resources_reserved': row['state'] == 'reserved', 'product_ready': False}

    def enqueue(self, spec, policy):
        with self.book._guard(), self.book._tx() as db:
            proof = self.book._account(spec)
            digest = fingerprint({'spec': spec.model_dump(), 'policy': policy.model_dump(), 'scope': proof.scope()})
            old = db.execute('SELECT * FROM device_queue WHERE request=?', (spec.request_id,)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise ProvisionError('idempotency_request_changed')
                return self._public(old)
            bound = db.execute("SELECT request FROM devices WHERE tenant=? AND kind=? AND state NOT IN ('cancelled','expired')",
                               (spec.tenant_id, spec.kind)).fetchone()
            if bound:
                raise ProvisionError('device_binding_conflict')
            try:
                db.execute('INSERT INTO device_queue(request,tenant,kind,spec,policy,account_scope,digest,state,code,updated) VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (spec.request_id, spec.tenant_id, spec.kind, encoded(spec.model_dump()), encoded(policy.model_dump()),
                            encoded(proof.scope()), digest, 'queued', '', self.book.clock()))
            except sqlite3.IntegrityError:
                raise ProvisionError('device_binding_conflict') from None
            return self._public(db.execute('SELECT * FROM device_queue WHERE request=?', (spec.request_id,)).fetchone())

    def tick(self, adapter):
        # This is the same reentrant file lock used by ProvisionBook, not a
        # second allocator. No open SQLite transaction spans reserve().
        with self.book._guard():
            with self.book._tx() as db:
                row = db.execute("SELECT * FROM device_queue WHERE state IN ('queued','promoting') ORDER BY sequence LIMIT 1").fetchone()
            if not row:
                return {'state': 'empty', 'product_ready': False}
            spec, policy = DeviceSpec.model_validate_json(row['spec']), Policy.model_validate_json(row['policy'])
            try:
                self.book._account(spec, json.loads(row['account_scope']))
                # A previous process may have committed reserve before exiting.
                try:
                    result = self.book.status(spec.request_id)
                except ProvisionError as error:
                    if str(error) != 'request_not_found': raise
                    result = None
                if result:
                    if result['state'] in ('cancelled', 'expired'):
                        raise ProvisionError('reservation_expired_or_cancelled')
                    with self.book._tx() as db:
                        allocated = db.execute('SELECT spec,policy FROM devices WHERE request=?', (spec.request_id,)).fetchone()
                        scope = db.execute('SELECT scope FROM device_accounts WHERE request=?', (spec.request_id,)).fetchone()
                    if (not scope or json.loads(scope['scope']) != json.loads(row['account_scope'])
                            or json.loads(allocated['spec']) != spec.model_dump() or json.loads(allocated['policy']) != policy.model_dump()):
                        raise ProvisionError('idempotency_request_changed')
                else:
                    plan = self.book.plan(spec, policy, adapter)
                    if not plan['admitted']:
                        self._set(spec.request_id, 'queued', ','.join(plan['reasons']))
                        return self.status(spec.request_id)
                    self._set(spec.request_id, 'promoting')
                    self.book.reserve(spec, policy, adapter, plan_sha256=plan['plan_sha256'])
                self._set(spec.request_id, 'reserved')
            except Exception as error:
                code = str(error) if isinstance(error, ProvisionError) else 'promotion_outcome_unknown'
                # Unknown provider outcomes are retained for observation, while
                # account/ownership errors isolate this request from the queue.
                capacity = all(reason.startswith('capacity_') or reason in
                               ('host_memory_pressure','storage_free_space_low','host_capacity_changed')
                               for reason in code.split(','))
                retry = code in ('promotion_outcome_unknown', 'provider_outcome_unknown', 'account_evidence_unavailable')
                self._set(spec.request_id, 'queued' if capacity else 'promoting' if retry else 'blocked', code)
            return self.status(spec.request_id)

    def _set(self, request, state, code=''):
        with self.book._tx() as db:
            db.execute('UPDATE device_queue SET state=?,code=?,updated=? WHERE request=?', (state, code, self.book.clock(), request))

    def status(self, request):
        with self.book._tx() as db:
            row = db.execute('SELECT * FROM device_queue WHERE request=?', (request,)).fetchone()
            if not row: raise ProvisionError('queue_request_not_found')
            return self._public(row)

    def cancel(self, request):
        with self.book._guard(), self.book._tx() as db:
            row = db.execute('SELECT * FROM device_queue WHERE request=?', (request,)).fetchone()
            if (not row or row['state'] not in ('queued', 'blocked')
                    or db.execute('SELECT 1 FROM devices WHERE request=?', (request,)).fetchone()):
                raise ProvisionError('queue_cannot_cancel_reserved')
            db.execute("UPDATE device_queue SET state='cancelled',updated=? WHERE request=?", (self.book.clock(), request))
        return self.status(request)
