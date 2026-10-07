"""Private per-tenant device outbox. No device ports are opened by this service.

Queued work may be delivered again; admitted work is never automatically replayed.
SQLite transactions fence reconnect/revocation/leases. Device execution also needs
its own durable journal and native local-driver ownership check.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import uuid

from fastapi import FastAPI, HTTPException, Request
from pydantic import Field, JsonValue

from .commands import (Record, Identifier, Method, Scope, DeviceCommand, TaskAuthority,
                       ResourceGrant, ConnectionAuthority, LeaseAuthority, authorize_command)
from .instance import load_instance, read_private
from ..config import private_directory
from ..profile import write_private_text

MAX_BODY = 8 * 1024 * 1024
CONNECTION_SECONDS = 90
COMMAND_SECONDS = 60
OBSERVATIONS = frozenset({'computer.status', 'computer.observe', 'phone.mobile_get_screen_size',
    'phone.mobile_list_apps', 'phone.mobile_list_elements_on_screen', 'phone.mobile_take_screenshot'})


def utc():
    return datetime.now(timezone.utc)


def ident(prefix):
    return prefix + '_' + uuid.uuid4().hex


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


class RelayError(ValueError):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


class ResourceSpec(Record):
    resource_id: Identifier
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern='^(android|computer)$')
    methods: frozenset[Method] = Field(min_length=1, max_length=32)


class PairRequest(Record):
    code: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{64}$')


class ConnectionRequest(Record):
    previous_connection_id: Identifier | None = None


class PollRequest(Record):
    connection_id: Identifier
    availability: dict[Identifier, bool] = Field(default_factory=dict, max_length=32)
    control_acks: dict[Identifier, int] = Field(default_factory=dict, max_length=32)
    permission_delivery: bool = Field(default=False,strict=True)


class ResourceControl(Record):
    resource_id: Identifier
    paused: bool = Field(strict=True)
    expected_generation: int = Field(ge=0, strict=True)


class DeviceReview(Record):
    command_id: Identifier
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    note: str = Field(min_length=5, max_length=2000)
    checked: bool = Field(strict=True)


class ClaimRequest(Record):
    connection_id: Identifier
    command_id: Identifier


class ResultRequest(ClaimRequest):
    state: str = Field(pattern='^(completed|device_error|blocked|unknown)$')
    result: dict[str, JsonValue] | None = None


class RelayStore:
    def __init__(self, root: Path, tenant_id: str):
        self.root, self.tenant = root.absolute(), tenant_id
        if self.root.is_symlink():
            raise RelayError('unsafe_relay_directory')
        private_directory(self.root)
        self.path = self.root / 'relay.sqlite3'
        if self.path.is_symlink():
            raise RelayError('unsafe_relay_database')
        with self.tx() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS meta(tenant TEXT PRIMARY KEY);
              CREATE TABLE IF NOT EXISTS pairs(code TEXT PRIMARY KEY, connector TEXT UNIQUE,
                identity TEXT, resources TEXT, tools TEXT, expires REAL, token TEXT);
              CREATE TABLE IF NOT EXISTS connectors(id TEXT PRIMARY KEY, identity TEXT, token TEXT UNIQUE,
                resources TEXT, tools TEXT, connection TEXT, previous TEXT, expires REAL,
                revoked INTEGER DEFAULT 0, availability TEXT DEFAULT '{}');
              CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, connector TEXT, resource TEXT,
                envelope TEXT, state TEXT, result TEXT, updated REAL, resolved INTEGER DEFAULT 0);
              CREATE TABLE IF NOT EXISTS leases(resource TEXT PRIMARY KEY, command TEXT, epoch INTEGER);
              CREATE TABLE IF NOT EXISTS controls(resource TEXT PRIMARY KEY, generation INTEGER,
                paused INTEGER, ack INTEGER DEFAULT 0, connection TEXT);
              CREATE TABLE IF NOT EXISTS device_reviews(command TEXT PRIMARY KEY, identity TEXT,
                revision TEXT, note TEXT, reviewed REAL, source TEXT);
              CREATE TABLE IF NOT EXISTS pairing_requests(id TEXT PRIMARY KEY, digest TEXT,
                bundle TEXT, expires REAL);
              CREATE TABLE IF NOT EXISTS desktop_proposals(id TEXT PRIMARY KEY, identity TEXT,
                resource TEXT, connector TEXT, connection TEXT, params TEXT, reason TEXT,
                expires REAL, state TEXT, command TEXT, decided REAL);
              CREATE TABLE IF NOT EXISTS desktop_run_waiters(proposal TEXT PRIMARY KEY, marker INTEGER UNIQUE,
                task TEXT, run TEXT, request TEXT, state TEXT NOT NULL, choice TEXT);
              CREATE INDEX IF NOT EXISTS commands_active ON commands(state,connector,updated);
            ''')
            db.execute('BEGIN IMMEDIATE')
            if 'resolved' not in {r[1] for r in db.execute('PRAGMA table_info(commands)')}:
                db.execute('ALTER TABLE commands ADD COLUMN resolved INTEGER DEFAULT 0')
            if 'policy_revision' not in {r[1] for r in db.execute('PRAGMA table_info(connectors)')}:
                db.execute('ALTER TABLE connectors ADD COLUMN policy_revision INTEGER NOT NULL DEFAULT 1')
            db.execute('CREATE TABLE IF NOT EXISTS permission_updates(id TEXT PRIMARY KEY, identity TEXT, connector TEXT, intent TEXT, bundle TEXT, expires REAL, state TEXT)')
            if 'delivery' not in {r[1] for r in db.execute('PRAGMA table_info(permission_updates)')}:
                db.execute("ALTER TABLE permission_updates ADD COLUMN delivery TEXT NOT NULL DEFAULT 'manual'")
            db.execute('CREATE TABLE IF NOT EXISTS desktop_task_grants(id TEXT PRIMARY KEY, identity TEXT, task TEXT, run TEXT, resource TEXT, connector TEXT, connection TEXT, policy INTEGER, generation INTEGER, app TEXT, expires REAL, remaining INTEGER, revoked INTEGER DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS desktop_proposal_grants(proposal TEXT PRIMARY KEY, grant_id TEXT)')
            if 'checkpoint' not in {r[1] for r in db.execute('PRAGMA table_info(desktop_proposals)')}:
                db.execute("ALTER TABLE desktop_proposals ADD COLUMN checkpoint TEXT NOT NULL DEFAULT 'commitment'")
            db.execute('CREATE INDEX IF NOT EXISTS commands_review ON commands(resource,state,resolved)')
            db.execute("UPDATE pairing_requests SET bundle='{}' WHERE expires<=?", (utc().timestamp(),))
            owners = [r[0] for r in db.execute('SELECT tenant FROM meta')]
            if owners and owners != [tenant_id]:
                raise RelayError('relay_owner_mismatch')
            db.execute('INSERT OR IGNORE INTO meta VALUES (?)', (tenant_id,))
        if os.name != 'nt':
            self.path.chmod(0o600)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def pair_code(self, identity, resources, tools):
        specs = [ResourceSpec.model_validate(r).model_dump(mode='json') for r in resources]
        if not 1 <= len(specs) <= 32 or len({r['resource_id'] for r in specs}) != len(specs):
            raise RelayError('invalid_resource_inventory')
        # These schemas are operator-approved from the local drivers, not supplied by a poll.
        if len(encoded(tools).encode()) > 65536 or not isinstance(tools, list):
            raise RelayError('invalid_tool_inventory')
        Scope(tenant_id=self.tenant, identity_id=identity)
        code, connector = secrets.token_urlsafe(32), ident('connector')
        with self.tx() as db:
            existing = {r['resource_id'] for c in db.execute('SELECT resources FROM connectors WHERE revoked=0')
                        for r in json.loads(c[0])}
            if existing.intersection(r['resource_id'] for r in specs):
                raise RelayError('resource_already_paired')
            db.execute('INSERT INTO pairs VALUES (?,?,?,?,?,?,NULL)',
                       (fingerprint(code), connector, identity, encoded(specs), encoded(tools), utc().timestamp()+600))
        return {'code': code, 'connector_id': connector, 'tenant_id': self.tenant, 'identity_id': identity,
                'pairing_generation': 1, 'policy_revision': 1, 'resources': specs}

    def pair(self, request: PairRequest):
        token_hash = fingerprint(request.token)
        with self.tx() as db:
            pair = db.execute('SELECT * FROM pairs WHERE code=?', (fingerprint(request.code),)).fetchone()
            if not pair or pair['expires'] <= utc().timestamp():
                raise RelayError('pairing_expired', 401)
            if pair['token']:
                if not secrets.compare_digest(pair['token'], token_hash):
                    raise RelayError('pairing_consumed', 401)
                c = db.execute('SELECT * FROM connectors WHERE id=?', (pair['connector'],)).fetchone()
                if not c or c['revoked']:
                    raise RelayError('connector_revoked', 401)
            else:
                # Two outstanding pairing codes cannot claim the same physical resource.
                existing = {r['resource_id'] for c in db.execute('SELECT resources FROM connectors WHERE revoked=0')
                            for r in json.loads(c[0])}
                if existing.intersection(r['resource_id'] for r in json.loads(pair['resources'])):
                    raise RelayError('resource_already_paired')
                db.execute('INSERT INTO connectors(id,identity,token,resources,tools) VALUES (?,?,?,?,?)',
                           (pair['connector'], pair['identity'], token_hash, pair['resources'], pair['tools']))
                db.execute('UPDATE pairs SET token=? WHERE code=?', (token_hash, pair['code']))
        return {'connector_id': pair['connector'], 'tenant_id': self.tenant, 'identity_id': pair['identity']}

    def auth(self, db, token):
        c = db.execute('SELECT * FROM connectors WHERE token=? AND revoked=0', (fingerprint(token),)).fetchone()
        if not c:
            raise RelayError('connector_not_authenticated', 401)
        return c

    def current(self, db, token, connection):
        c = self.auth(db, token)
        if not c['connection'] or c['connection'] != connection or (c['expires'] or 0) <= utc().timestamp():
            raise RelayError('connection_stale', 401)
        return c

    def connect(self, token, request: ConnectionRequest):
        with self.tx() as db:
            c = self.auth(db, token)
            now = utc().timestamp()
            # Retry after an ambiguous connect response recovers the SAME generation.
            if c['connection'] and c['previous'] == request.previous_connection_id and c['expires'] > now:
                return {'connection_id': c['connection']}
            if request.previous_connection_id != c['connection'] and not (
                    (c['expires'] or 0) <= now and request.previous_connection_id == c['previous']):
                raise RelayError('connection_stale')
            db.execute("UPDATE commands SET state='unknown',updated=? WHERE connector=? AND state IN ('queued','executing')",
                       (now, c['id']))
            connection = ident('connection')
            db.execute('UPDATE connectors SET connection=?,previous=?,expires=?,availability=\'{}\' WHERE id=?',
                       (connection, request.previous_connection_id, now+CONNECTION_SECONDS, c['id']))
        return {'connection_id': connection}

    def poll(self, token, request: PollRequest):
        with self.tx() as db:
            c = self.current(db, token, request.connection_id)
            resources = {r['resource_id'] for r in json.loads(c['resources'])}
            if not set(request.availability) <= resources:
                raise RelayError('resource_not_paired')
            if not set(request.control_acks) <= resources:
                raise RelayError('resource_not_paired')
            for resource, generation in request.control_acks.items():
                db.execute('UPDATE controls SET ack=?,connection=? WHERE resource=? AND generation=?',
                           (generation, c['connection'], resource, generation))
            now = utc().timestamp()
            db.execute('UPDATE connectors SET expires=?,availability=? WHERE id=?',
                       (now+CONNECTION_SECONDS, encoded(request.availability), c['id']))
            self.expire(db)
            row = db.execute("SELECT * FROM commands WHERE connector=? AND state='queued' ORDER BY updated LIMIT 1", (c['id'],)).fetchone()
            controls = [dict(resource_id=r['resource'], generation=r['generation'], paused=bool(r['paused']))
                        for r in db.execute('SELECT * FROM controls') if r['resource'] in resources]
            from .device_permissions import pending_delivery
            bundle=pending_delivery(store=self,db=db,connector=c) if request.permission_delivery else None
            return {'command': json.loads(row['envelope']) if row else None, 'controls': controls,
                    **({'permission_update':bundle} if bundle and not row else {})}

    def disconnect(self, token, request: PollRequest):
        """A graceful local stop blocks unadmitted work and expires this connection."""
        with self.tx() as db:
            c = self.auth(db, token)
            if c['connection'] != request.connection_id:
                raise RelayError('connection_stale', 401)
            db.execute("UPDATE commands SET state=CASE WHEN state='queued' THEN 'blocked' ELSE 'unknown' END,"
                       "result=NULL,updated=? WHERE connector=? AND state IN ('queued','executing')",
                       (utc().timestamp(), c['id']))
            db.execute("UPDATE connectors SET expires=0,availability='{}' WHERE id=?", (c['id'],))
            return {'disconnected':True}

    def control_ready(self, db, resource, connection):
        row = db.execute('SELECT * FROM controls WHERE resource=?', (resource,)).fetchone()
        return not row or (not row['paused'] and row['ack'] == row['generation'] and row['connection'] == connection)

    def control(self, identity, request: ResourceControl):
        """Fence new work immediately; device acknowledgement is reported separately."""
        with self.tx() as db:
            matches = [c for c in db.execute('SELECT * FROM connectors WHERE identity=? AND revoked=0', (identity,))
                       if any(r['resource_id'] == request.resource_id for r in json.loads(c['resources']))]
            if len(matches) != 1:
                raise RelayError('resource_not_paired', 404)
            old = db.execute('SELECT * FROM controls WHERE resource=?', (request.resource_id,)).fetchone()
            generation = old['generation'] if old else 0
            if request.expected_generation != generation:
                raise RelayError('control_changed')
            db.execute('INSERT OR REPLACE INTO controls(resource,generation,paused) VALUES (?,?,?)',
                       (request.resource_id, generation + 1, int(request.paused)))
            if request.paused:
                db.execute("UPDATE desktop_proposals SET state='cancelled' WHERE resource=? AND state='awaiting_user'",(request.resource_id,))
                db.execute("UPDATE commands SET state=CASE WHEN state='queued' THEN 'blocked' ELSE 'unknown' END,"
                           "result=NULL,updated=? WHERE resource=? AND state IN ('queued','executing')",
                           (utc().timestamp(), request.resource_id))
                db.execute('UPDATE leases SET epoch=epoch+1 WHERE resource=?', (request.resource_id,))
        return {'resource_id': request.resource_id, 'paused': request.paused, 'generation': generation + 1}

    def expire(self, db):
        now = utc()
        for row in db.execute("SELECT id,envelope FROM commands WHERE state IN ('queued','executing')").fetchall():
            if DeviceCommand.model_validate_json(row['envelope']).expires_at <= now:
                db.execute("UPDATE commands SET state='unknown',updated=? WHERE id=?", (now.timestamp(), row['id']))

    def authorities(self, c, command):
        resource = next((r for r in json.loads(c['resources']) if r['resource_id'] == command.resource_id), None)
        if not resource:
            raise RelayError('resource_not_paired')
        scope = Scope(tenant_id=self.tenant, identity_id=c['identity'])
        grant = ResourceGrant(scope=scope, resource_id=resource['resource_id'], connector_id=c['id'],
                              pairing_generation=1, policy_revision=c['policy_revision'], methods=resource['methods'], revoked=bool(c['revoked']))
        connection = ConnectionAuthority(tenant_id=self.tenant, connector_id=c['id'], connection_id=c['connection'],
                                         pairing_generation=1, capabilities={m for r in json.loads(c['resources']) for m in r['methods']},
                                         expires_at=datetime.fromtimestamp(c['expires'], timezone.utc), revoked=bool(c['revoked']))
        task = TaskAuthority(scope=scope, task_id=command.task_id)
        lease = LeaseAuthority(scope=scope, resource_id=command.resource_id, task_id=command.task_id,
                               connection_id=command.connection_id, epoch=command.lease_epoch, expires_at=command.expires_at)
        return dict(task=task, grant=grant, connection=connection, lease=lease)

    def enqueue(self, identity, resource, method, params):
        with self.tx() as db:
            return self._enqueue(db,identity,resource,method,params)

    def _enqueue(self, db, identity, resource, method, params, approval_id=None):
        self.expire(db)
        if method=='computer.input':
            from .desktop_approval import action_hash
            row=db.execute("SELECT * FROM desktop_proposals WHERE id=? AND state='approved' AND command IS NULL",(approval_id,)).fetchone()
            if (not row or row['identity']!=identity or row['resource']!=resource or row['expires']<=utc().timestamp()
                    or action_hash(json.loads(row['params']))!=action_hash(params)):
                raise RelayError('desktop_approval_required')
            params={**params,'approval_id':approval_id}
        matches = [(c,r) for c in db.execute('SELECT * FROM connectors WHERE revoked=0')
                   for r in json.loads(c['resources']) if r['resource_id'] == resource and c['identity'] == identity]
        if len(matches) != 1:
            raise RelayError('resource_not_paired')
        c, spec = matches[0]
        if not c['connection'] or (c['expires'] or 0) <= utc().timestamp():
            raise RelayError('connector_offline')
        if not json.loads(c['availability']).get(resource, False):
            raise RelayError('resource_offline_or_paused')
        if not self.control_ready(db, resource, c['connection']):
            raise RelayError('resource_paused_or_syncing')
        if method not in OBSERVATIONS and db.execute(
                "SELECT 1 FROM commands WHERE resource=? AND state IN ('unknown','device_error') AND resolved=0", (resource,)).fetchone():
            raise RelayError('previous_action_needs_review')
        lease = db.execute('SELECT * FROM leases WHERE resource=?', (resource,)).fetchone()
        if lease:
            old = db.execute('SELECT state FROM commands WHERE id=?', (lease['command'],)).fetchone()
            if old and old[0] in ('queued','executing'):
                raise RelayError('resource_busy')
        now = utc()
        task_id=ident('device_task')
        if approval_id:
            waiter=db.execute('SELECT task FROM desktop_run_waiters WHERE proposal=?',(approval_id,)).fetchone()
            if waiter and waiter['task']:task_id=waiter['task']
        command = DeviceCommand(protocol_version='1', command_id=ident('command'),
            scope=Scope(tenant_id=self.tenant, identity_id=identity), task_id=task_id,
            resource_id=resource, connector_id=c['id'], connection_id=c['connection'], pairing_generation=1,
            policy_revision=c['policy_revision'], lease_epoch=lease['epoch']+1 if lease else 1, method=method, params=params,
            created_at=now, expires_at=min(now+timedelta(seconds=COMMAND_SECONDS), datetime.fromtimestamp(c['expires'], timezone.utc)))
        authorize_command(command, **self.authorities(c, command), now=now)
        db.execute('INSERT INTO commands(id,connector,resource,envelope,state,result,updated) VALUES (?,?,?,?,?,?,?)',
                   (command.command_id, c['id'], resource, command.model_dump_json(), 'queued', None, now.timestamp()))
        db.execute('INSERT OR REPLACE INTO leases VALUES (?,?,?)', (resource, command.command_id, command.lease_epoch))
        return command

    def claim(self, token, request: ClaimRequest):
        with self.tx() as db:
            c = self.current(db, token, request.connection_id)
            self.expire(db)
            row = db.execute('SELECT * FROM commands WHERE id=? AND connector=?', (request.command_id, c['id'])).fetchone()
            if not row or row['state'] != 'queued':
                raise RelayError('command_not_queued')
            command = DeviceCommand.model_validate_json(row['envelope'])
            lease = db.execute('SELECT * FROM leases WHERE resource=?', (command.resource_id,)).fetchone()
            if not lease or lease['command'] != command.command_id or lease['epoch'] != command.lease_epoch:
                raise RelayError('lease_stale')
            authorities = self.authorities(c, command)
            authorize_command(command, **authorities, now=utc())
            if not json.loads(c['availability']).get(command.resource_id, False):
                raise RelayError('resource_offline_or_paused')
            if not self.control_ready(db, command.resource_id, c['connection']):
                raise RelayError('resource_paused_or_syncing')
            db.execute("UPDATE commands SET state='executing',updated=? WHERE id=?", (utc().timestamp(), command.command_id))
            result={k:v.model_dump(mode='json') for k,v in authorities.items()}
            if command.method=='computer.input':
                from .desktop_approval import authority
                result['input_approval']=authority(self,db,command).model_dump(mode='json')
            return result

    def result(self, token, request: ResultRequest):
        payload = encoded(request.result) if request.result is not None else None
        if payload and len(payload.encode()) > MAX_BODY-4096:
            raise RelayError('result_too_large', 413)
        with self.tx() as db:
            c = self.auth(db, token)
            row = db.execute('SELECT * FROM commands WHERE id=? AND connector=?', (request.command_id,c['id'])).fetchone()
            if not row:
                raise RelayError('command_not_found', 404)
            if row['resolved']:
                # A delayed upload cannot change a reviewed record or reveal discarded contents.
                return {'accepted': False, 'state': row['state']}
            # Idempotent receipt upload; never return another device's contents.
            if row['result']:
                if row['state'] == request.state and secrets.compare_digest(row['result'], payload or ''):
                    return {'accepted': True}
                raise RelayError('result_conflict')
            command = DeviceCommand.model_validate_json(row['envelope'])
            if request.connection_id != command.connection_id:
                raise RelayError('connection_stale')
            if (c['connection'] != command.connection_id or row['state'] != 'executing'
                    or utc() >= command.expires_at or (c['expires'] or 0) <= utc().timestamp()):
                db.execute("UPDATE commands SET state='unknown',result=NULL,updated=? WHERE id=?", (utc().timestamp(),row['id']))
                return {'accepted': False, 'state': 'unknown'}
            # Observations/input text are private tenant data; never logged.
            db.execute('UPDATE commands SET state=?,result=?,updated=? WHERE id=?',
                       (request.state, payload, utc().timestamp(), row['id']))
            return {'accepted': True}

    def read_result(self, command_id, identity):
        with self.tx() as db:
            self.expire(db)
            row = db.execute('SELECT * FROM commands WHERE id=?', (command_id,)).fetchone()
            if not row or DeviceCommand.model_validate_json(row['envelope']).scope.identity_id != identity:
                raise RelayError('command_not_found', 404)
            return {'command_id': command_id, 'state': row['state'],
                    'result': json.loads(row['result']) if row['result'] else None}

    def revoke(self, connector):
        with self.tx() as db:
            changed = db.execute('UPDATE connectors SET revoked=1,availability=\'{}\' WHERE id=?', (connector,)).rowcount
            if not changed:
                raise RelayError('connector_not_found', 404)
            db.execute("UPDATE commands SET state='unknown',result=NULL,updated=? WHERE connector=? AND state IN ('queued','executing')",
                       (utc().timestamp(), connector))

    def acknowledge(self, command_id):
        """Only an authenticated local operator may clear an uncertain action."""
        with self.tx() as db:
            changed = db.execute("UPDATE commands SET resolved=1 WHERE id=? AND state IN ('unknown','device_error')",(command_id,)).rowcount
            if not changed: raise RelayError('command_not_awaiting_review')
            row = db.execute('SELECT * FROM commands WHERE id=?', (command_id,)).fetchone()
            command = DeviceCommand.model_validate_json(row['envelope'])
            db.execute('INSERT OR IGNORE INTO device_reviews VALUES (?,?,?,?,?,?)',
                       (command_id, command.scope.identity_id, self.review_revision(row),
                        'Operator confirmed the device action outside the browser.', utc().timestamp(), 'operator'))

    @staticmethod
    def review_revision(row):
        return fingerprint(encoded([row['id'], row['envelope'], row['state'], row['updated'], row['resolved']]))

    def review_ready(self, db, row, command):
        c = db.execute('SELECT * FROM connectors WHERE id=?', (row['connector'],)).fetchone()
        deadline = max(command.expires_at.timestamp(), row['updated'])
        # The serial connector polls after finishing/uploading. A fresh post-deadline
        # heartbeat is required; an offline device cannot be declared quiescent here.
        return bool(c and not c['revoked'] and (c['expires'] or 0) > utc().timestamp()
                    and json.loads(c['availability']).get(row['resource'], False)
                    and c['expires'] - CONNECTION_SECONDS > deadline
                    and not db.execute("SELECT 1 FROM commands WHERE resource=? AND state IN ('queued','executing')",
                                       (row['resource'],)).fetchone())

    def reviews(self, identity):
        with self.tx() as db:
            self.expire(db)
            items = []
            for row in db.execute("SELECT * FROM commands WHERE state IN ('unknown','device_error') AND resolved=0 ORDER BY updated DESC"):
                command = DeviceCommand.model_validate_json(row['envelope'])
                if command.scope.identity_id != identity:
                    continue
                c = db.execute('SELECT * FROM connectors WHERE id=?', (row['connector'],)).fetchone()
                spec = next((r for r in json.loads(c['resources']) if r['resource_id']==row['resource']), {}) if c else {}
                items.append({'command_id':row['id'], 'resource_id':row['resource'], 'name':spec.get('name','设备'),
                              'method':command.method, 'state':row['state'], 'revision':self.review_revision(row),
                              'created_at':command.created_at.isoformat(), 'can_review':self.review_ready(db,row,command)})
            return items

    def review(self, identity, request: DeviceReview):
        if not request.checked or len(request.note.strip()) < 5:
            raise RelayError('device_review_required', 422)
        with self.tx() as db:
            self.expire(db)
            row = db.execute('SELECT * FROM commands WHERE id=?', (request.command_id,)).fetchone()
            if not row or DeviceCommand.model_validate_json(row['envelope']).scope.identity_id != identity:
                raise RelayError('command_not_found', 404)
            if row['resolved'] or self.review_revision(row) != request.revision:
                raise RelayError('review_changed')
            command = DeviceCommand.model_validate_json(row['envelope'])
            if row['state'] not in ('unknown','device_error') or not self.review_ready(db,row,command):
                raise RelayError('device_not_ready_for_review')
            db.execute('INSERT INTO device_reviews VALUES (?,?,?,?,?,?)',
                       (row['id'], identity, request.revision, request.note.strip(), utc().timestamp(), 'browser'))
            db.execute('UPDATE commands SET resolved=1 WHERE id=?', (row['id'],))
            return {'reviewed':True, 'replayed':False}

    def cancel(self, command_id, identity):
        """Fence work when its owning MCP call is cancelled; never undo device effects."""
        with self.tx() as db:
            row = db.execute('SELECT * FROM commands WHERE id=?',(command_id,)).fetchone()
            if not row or DeviceCommand.model_validate_json(row['envelope']).scope.identity_id != identity:
                raise RelayError('command_not_found',404)
            if row['state'] in ('queued','executing'):
                state = 'blocked' if row['state']=='queued' else 'unknown'
                db.execute('UPDATE commands SET state=?,result=NULL,updated=? WHERE id=?',(state,utc().timestamp(),command_id))
                db.execute('UPDATE leases SET epoch=epoch+1 WHERE command=?',(command_id,))

    def inventory(self, identity):
        with self.tx() as db:
            self.expire(db)
            value = []
            for c in db.execute('SELECT * FROM connectors WHERE identity=? AND revoked=0', (identity,)):
                online = bool(c['connection'] and (c['expires'] or 0) > utc().timestamp())
                for r in json.loads(c['resources']):
                    control = db.execute('SELECT * FROM controls WHERE resource=?', (r['resource_id'],)).fetchone()
                    pending = bool(control and (control['ack'] != control['generation'] or control['connection'] != c['connection']))
                    from .device_permissions import grant_digest
                    value.append({**r, 'connector_id':c['id'], 'connected':online,
                        'policy_revision':c['policy_revision'], 'permission_revision':grant_digest(c),
                        'needs_review':bool(db.execute("SELECT 1 FROM commands WHERE resource=? AND state IN ('unknown','device_error') AND resolved=0",(r['resource_id'],)).fetchone()),
                        'online':online and json.loads(c['availability']).get(r['resource_id'],False) and self.control_ready(db,r['resource_id'],c['connection']),
                        'paused':bool(control and control['paused']), 'control_generation':control['generation'] if control else 0,
                        'control_pending':pending,
                        'last_seen_at':datetime.fromtimestamp(c['expires']-CONNECTION_SECONDS,timezone.utc).isoformat() if c['expires'] else None})
            return value

    def schemas(self, identity):
        with self.tx() as db:
            return [t for c in db.execute('SELECT tools FROM connectors WHERE identity=? AND revoked=0', (identity,)) for t in json.loads(c[0])]


def instance_relay(root):
    instance = load_instance(root)
    return RelayStore(root / 'data/device-relay', instance.tenant_id)


def create_relay_app(root: Path):
    """Public surface is only pairing/connector transport. Operator routes are absent."""
    store = instance_relay(root)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.relay = store

    @app.middleware('http')
    async def boundary(request, call_next):
        from starlette.responses import JSONResponse
        if request.headers.get('origin') is not None:
            return JSONResponse({'detail':'browser_transport_not_allowed'},status_code=403)
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                return JSONResponse({'detail':'request_too_large'},status_code=413)
            chunks.append(chunk)
        request._body = b''.join(chunks)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(RelayError)
    async def rejected(request, error):
        from starlette.responses import JSONResponse
        return JSONResponse({'detail':error.code},status_code=error.status)

    from fastapi.exceptions import RequestValidationError
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        from starlette.responses import JSONResponse
        return JSONResponse({'detail':'invalid_connector_request'},status_code=422)

    def token(request):
        values = request.headers.getlist('authorization')
        if len(values) != 1 or not values[0].startswith('Bearer '):
            raise RelayError('connector_not_authenticated',401)
        value = values[0][7:]
        if len(value) != 64 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in value):
            raise RelayError('connector_not_authenticated',401)
        return value

    @app.post('/v1/pair')
    async def pair(value: PairRequest):
        return store.pair(value)

    @app.post('/v1/connect')
    async def connect(value: ConnectionRequest, request: Request):
        return store.connect(token(request),value)

    @app.post('/v1/poll')
    async def poll(value: PollRequest, request: Request):
        return store.poll(token(request),value)

    @app.post('/v1/disconnect')
    async def disconnect(value: PollRequest, request: Request):
        return store.disconnect(token(request),value)

    @app.post('/v1/claim')
    async def claim(value: ClaimRequest, request: Request):
        return store.claim(token(request),value)

    @app.post('/v1/result')
    async def result(value: ResultRequest, request: Request):
        return store.result(token(request),value)
    from .device_permissions import ApplyPermission, apply_permission
    @app.post('/v1/permissions/check')
    async def check_permissions(value: ApplyPermission, request: Request):
        return apply_permission(store,token(request),value,check_only=True)
    @app.post('/v1/permissions/apply')
    async def apply_permissions(value: ApplyPermission, request: Request):
        return apply_permission(store,token(request),value)
    return app
