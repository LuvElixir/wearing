"""Durable, resource-scoped operator fence for safe device power maintenance.

This is not an HTTP endpoint. It preserves queued/executing work and only fences
new admission. Existing work must finish, and unresolved outcomes require review.
The ordinary connector control ACK remains necessary before shutting down.
"""
import json
import re


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS device_maintenance(
      resource TEXT PRIMARY KEY, identity TEXT NOT NULL, connector TEXT NOT NULL,
      operation TEXT NOT NULL, owner_sha256 TEXT NOT NULL, phase TEXT NOT NULL,
      generation INTEGER NOT NULL, updated REAL NOT NULL)''')


def guard(db, resource):
    initialize(db)
    row = db.execute('SELECT phase FROM device_maintenance WHERE resource=?', (resource,)).fetchone()
    if row and row['phase'] != 'awake':
        from .relay import RelayError
        raise RelayError('device_maintenance_waiting')


class DeviceMaintenance:
    def __init__(self, relay, *, operator=False):
        if not operator:
            raise ValueError('operator_required')
        self.relay = relay

    @staticmethod
    def _error(code):
        from .relay import RelayError
        raise RelayError(code)

    def _owned(self, db, identity, resource):
        from .device_access import owned
        return owned(db, identity, resource)[0]

    def _row(self, db, identity, resource, operation, owner_sha256):
        initialize(db)
        row = db.execute('SELECT * FROM device_maintenance WHERE resource=?', (resource,)).fetchone()
        c = self._owned(db, identity, resource)
        if (not row or row['identity'] != identity or row['connector'] != c['id']
                or row['operation'] != operation or row['owner_sha256'] != owner_sha256):
            self._error('maintenance_binding_changed')
        return row, c

    @staticmethod
    def _stamp():
        from .relay import utc
        return utc().timestamp()

    def _idle(self, db, resource):
        from .desktop_approval import expire_proposals
        expire_proposals(self.relay, db)
        # Never rewrite command states to manufacture idleness. This preserves
        # in-flight receipts and distinguishes unknown outcomes from completion.
        commands = db.execute("SELECT COUNT(*) FROM commands WHERE resource=? AND "
                              "(state IN ('queued','executing') OR (state IN ('unknown','device_error') AND resolved=0))",
                              (resource,)).fetchone()[0]
        human = db.execute("SELECT COUNT(*) FROM human_access WHERE resource=? AND state!='agent_ready'", (resource,)).fetchone()[0]
        proposals = db.execute("SELECT COUNT(*) FROM desktop_proposals WHERE resource=? AND state IN ('awaiting_user','approved') AND command IS NULL",
                               (resource,)).fetchone()[0]
        if commands or human or proposals:
            self._error('device_maintenance_busy')

    def begin(self, identity, resource, operation, owner_sha256):
        if not re.fullmatch('[a-f0-9]{32}', operation) or not re.fullmatch('[a-f0-9]{64}', owner_sha256):
            self._error('invalid_maintenance_operation')
        with self.relay.tx() as db:
            initialize(db)
            c = self._owned(db, identity, resource)
            old = db.execute('SELECT * FROM device_maintenance WHERE resource=?', (resource,)).fetchone()
            if old and old['phase'] != 'awake':
                self._row(db, identity, resource, operation, owner_sha256)
                return self._public(old)
            if old and old['operation'] == operation:
                self._row(db, identity, resource, operation, owner_sha256)
                return self._public(old)
            # Existing explicit pauses/private sessions belong to the user.
            # Maintenance cannot later restore them as agent-ready by accident.
            control = db.execute('SELECT * FROM controls WHERE resource=?', (resource,)).fetchone()
            if control and (control['paused'] or not self.relay.control_ready(db, resource, c['connection'])):
                self._error('device_not_agent_ready')
            self._idle(db, resource)
            generation = control['generation'] if control else 0
            db.execute('INSERT OR REPLACE INTO device_maintenance VALUES (?,?,?,?,?,?,?,?)',
                       (resource, identity, c['id'], operation, owner_sha256, 'freezing', generation, self._stamp()))
            return self._public(db.execute('SELECT * FROM device_maintenance WHERE resource=?', (resource,)).fetchone())

    def freeze(self, identity, resource, operation, owner_sha256):
        with self.relay.tx() as db:
            row, c = self._row(db, identity, resource, operation, owner_sha256)
            self._idle(db, resource)
            if row['phase'] not in ('freezing', 'frozen'):
                self._error('maintenance_phase_changed')
            if row['phase'] == 'freezing':
                control = db.execute('SELECT * FROM controls WHERE resource=?', (resource,)).fetchone()
                if ((control['generation'] if control else 0) != row['generation']
                        or (control and control['paused'])):
                    self._error('maintenance_control_changed')
                db.execute('INSERT OR REPLACE INTO controls(resource,generation,paused) VALUES (?,?,1)',
                           (resource, row['generation'] + 1))
                db.execute("UPDATE device_maintenance SET phase='frozen',generation=generation+1,updated=? WHERE resource=?",
                           (self._stamp(), resource))
            return self._status(db, identity, resource, operation, owner_sha256)

    def _status(self, db, identity, resource, operation, owner_sha256):
        row, c = self._row(db, identity, resource, operation, owner_sha256)
        control = db.execute('SELECT * FROM controls WHERE resource=?', (resource,)).fetchone()
        connected = bool(c['connection'] and (c['expires'] or 0) > self._stamp())
        ack = bool(control and control['generation'] == row['generation']
                   and control['ack'] == row['generation'] and control['connection'] == c['connection'])
        return {**self._public(row), 'connected': connected, 'acknowledged': ack,
                'agent_available': bool(json.loads(c['availability']).get(resource)),
                'human_available': bool(c['human_access_ready'] and json.loads(c['human_availability']).get(resource))}

    @staticmethod
    def _public(row):
        return {'resource_id': row['resource'], 'operation_id': row['operation'],
                'phase': row['phase'], 'generation': row['generation']}

    def status(self, identity, resource, operation, owner_sha256):
        with self.relay.tx() as db:
            return self._status(db, identity, resource, operation, owner_sha256)

    def assert_drained(self, identity, resource, operation, owner_sha256):
        with self.relay.tx() as db:
            value = self._status(db, identity, resource, operation, owner_sha256)
            self._idle(db, resource)
            if value['phase'] != 'frozen' or not value['connected'] or not value['acknowledged']:
                self._error('maintenance_ack_pending')
            return value

    def wake(self, identity, resource, operation, owner_sha256):
        """Called only after native health checks; normal admission stays fenced."""
        with self.relay.tx() as db:
            row, c = self._row(db, identity, resource, operation, owner_sha256)
            self._idle(db, resource)
            if row['phase'] == 'waking':
                return self._public(row)
            if row['phase'] != 'frozen':
                self._error('maintenance_phase_changed')
            control = db.execute('SELECT * FROM controls WHERE resource=?', (resource,)).fetchone()
            if not control or control['generation'] != row['generation'] or not control['paused']:
                self._error('maintenance_control_changed')
            db.execute('UPDATE controls SET generation=generation+1,paused=0,ack=0,connection=NULL WHERE resource=?', (resource,))
            db.execute("UPDATE device_maintenance SET phase='waking',generation=generation+1,updated=? WHERE resource=?", (self._stamp(), resource))
            return self._public(db.execute('SELECT * FROM device_maintenance WHERE resource=?', (resource,)).fetchone())

    def finish_wake(self, identity, resource, operation, owner_sha256):
        with self.relay.tx() as db:
            value = self._status(db, identity, resource, operation, owner_sha256)
            self._idle(db, resource)
            if value['phase'] not in ('waking', 'awake') or not all(value[k] for k in
                    ('connected', 'acknowledged', 'agent_available', 'human_available')):
                self._error('wake_readiness_pending')
            db.execute("UPDATE device_maintenance SET phase='awake',updated=? WHERE resource=?", (self._stamp(), resource))
            return {**value, 'phase': 'awake'}
